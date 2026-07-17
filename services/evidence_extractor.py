"""
Evidence extractor — assembles a small, high-signal evidence bundle from an
issue so the model driving the skill can determine the root cause in one
read, without re-fetching raw issue pages or full patches.

Design contract: emit what exists, ranked, capped — NEVER synthesize.

Extraction is structure-first, regex-second:
1. Structural pass — pull <code>/<pre>/<blockquote> blocks out of the
   issue's HTML. This is parsing, not pattern matching: it cannot "miss"
   an exotic error format because it does not interpret content.
2. Ranking pass — a small pattern set scores each block by error density
   (PHP exceptions, PHPUnit failures, Twig/JS/SQL/composer errors) only to
   decide WHICH blocks fit the byte budget, not what they mean.
3. Interpretation is left entirely to the model reading the output.

A ranking misfire therefore includes a less-useful block; it can never
produce invented prose — the failure mode the old keyword classifiers had.
"""

import re
from html import unescape
from html.parser import HTMLParser
from typing import Dict, List, Optional

# Byte budgets — explicit, with truncation flags (no silent caps).
BLOCK_BUDGET = 2500
DIFF_BUDGET = 2500
MAX_BLOCKS = 6
MAX_CODE_REFS = 10
MAX_CHANGED_LINES_PER_HUNK = 4
# Zero-score blocks shorter than this are inline mentions (`<button>`,
# `.module.css`), not evidence — they'd occupy ranked slots for nothing.
# Blocks that score as errors are kept at any length.
MIN_CODE_BLOCK_LEN = 30
MAX_HUNKS_PER_FILE = 3
MAX_DIFF_FILES = 10

_CAPTURE_TAGS = {"code", "pre", "blockquote"}

# Error-density signals, grouped by ecosystem. Weights favor signals that
# almost never appear outside genuine failure output.
_ERROR_PATTERNS = [
    (re.compile(r"Fatal error|Uncaught (?:\w+\\)*\w*(?:Exception|Error)", re.I), 3),
    (re.compile(r"\b(?:\w+\\)+\w*(?:Exception|Error)\b"), 3),      # namespaced FQCN
    (re.compile(r"#\d+ [/\w][^\n]*\.php\(\d+\)"), 3),              # PHP trace frame
    (re.compile(r"\.php(?: on line | line |:)(\d+)"), 2),
    (re.compile(r"Failed asserting|PHPUnit\\|Tests: \d+, Assertions: \d+"), 3),
    (re.compile(r"^\d+\) [A-Za-z\\]+::test\w+", re.M), 3),         # PHPUnit failure header
    (re.compile(r"Twig\\Error|\.html\.twig"), 2),
    (re.compile(r"\b(?:TypeError|ReferenceError)\b.*\n?.*at .+\.js:\d+"), 3),
    (re.compile(r"SQLSTATE\[\w+\]"), 3),
    (re.compile(r"Your requirements could not be resolved"), 3),
    (re.compile(r"\b(?:Warning|Notice|Deprecated)\b\s*:"), 1),
    (re.compile(r"AssertionError|assert\w* failed", re.I), 2),
]

_CODE_REF_PATTERN = re.compile(
    r"([A-Za-z0-9_][A-Za-z0-9_/.\-]*\.(?:php|module|inc|install|theme|twig|js|yml))"
    r"(?:\s*(?:on line|line|:)\s*(\d+))?"
)

# Issue categories where "root cause" framing applies.
_BUG_CATEGORIES = {"bug report", "bug"}


class _BlockCollector(HTMLParser):
    """Collect the text content of top-level <code>/<pre>/<blockquote> blocks."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.blocks: List[str] = []
        self._depth = 0
        self._buffer: List[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in _CAPTURE_TAGS:
            self._depth += 1
        elif self._depth and tag == "br":
            self._buffer.append("\n")

    def handle_endtag(self, tag):
        if tag in _CAPTURE_TAGS and self._depth:
            self._depth -= 1
            if self._depth == 0:
                text = "".join(self._buffer).strip()
                if text:
                    self.blocks.append(text)
                self._buffer = []

    def handle_data(self, data):
        if self._depth:
            self._buffer.append(data)


class EvidenceExtractor:

    @staticmethod
    def extract_html_blocks(html: str) -> List[str]:
        """Structural pass: all top-level code/pre/blockquote block texts."""
        if not html:
            return []
        collector = _BlockCollector()
        try:
            collector.feed(html)
            collector.close()
        except Exception:
            return collector.blocks
        return collector.blocks

    @staticmethod
    def score_block(text: str) -> int:
        return sum(
            weight for pattern, weight in _ERROR_PATTERNS if pattern.search(text)
        )

    @staticmethod
    def rank_blocks(blocks: List[str]) -> List[Dict]:
        """
        Order blocks by error density and fit them into BLOCK_BUDGET bytes.
        Zero-score blocks are still code (config, proposed fixes) and are
        kept at lower rank — included only if budget remains.
        """
        def _entry(text):
            score = EvidenceExtractor.score_block(text)
            return {"score": score,
                    "kind": "error" if score > 0 else "code",
                    "text": text}

        scored = sorted(
            (_entry(b) for b in blocks
             if EvidenceExtractor.score_block(b) > 0
             or len(b) >= MIN_CODE_BLOCK_LEN),
            key=lambda item: item["score"],
            reverse=True,
        )
        selected, used, dropped = [], 0, 0
        seen = set()
        for item in scored:
            key = item["text"][:120]
            if key in seen:
                continue
            seen.add(key)
            # Cap any single block at half the budget BEFORE the budget
            # check, so one giant trace is trimmed to fit rather than
            # dropped entirely — and can't crowd out everything else.
            text = item["text"]
            if len(text) > BLOCK_BUDGET // 2:
                text = text[: BLOCK_BUDGET // 2] + "\n… [block truncated]"
                item = {**item, "text": text}
            if len(selected) >= MAX_BLOCKS or used + len(text) > BLOCK_BUDGET:
                dropped += 1
                continue
            selected.append(item)
            used += len(text)
        return selected + ([{"kind": "note", "score": 0,
                             "text": f"[{dropped} more block(s) omitted for budget]"}]
                           if dropped else [])

    @staticmethod
    def extract_code_refs(texts: List[str]) -> List[str]:
        """File-path (+ optional line) references, deduped, capped."""
        refs = []
        seen = set()
        for text in texts:
            if not text:
                continue
            plain = unescape(re.sub(r"<[^>]+>", " ", text))
            for m in _CODE_REF_PATTERN.finditer(plain):
                path, line = m.group(1), m.group(2)
                # Skip bare filenames with no path AND no line number —
                # too weak a signal (e.g. casual mentions of "composer.json").
                if "/" not in path and not line:
                    continue
                # Skip URLs misread as file paths (php.net docs links etc.):
                # a leading segment that is a domain, or a URL scheme just
                # before the match.
                if re.match(r"(?:www\.|[\w.-]+\.(?:net|org|com|io|dev)/)", path):
                    continue
                if plain[max(0, m.start() - 8):m.start()].rstrip().endswith("//"):
                    continue
                ref = f"{path}:{line}" if line else path
                if ref not in seen:
                    seen.add(ref)
                    refs.append(ref)
                if len(refs) >= MAX_CODE_REFS:
                    return refs
        return refs

    @staticmethod
    def digest_diff(diff_text: str) -> Optional[Dict]:
        """
        Compress a unified diff to its skeleton: per-file hunk headers
        (which carry function context) plus a few changed lines per hunk.
        A fix diff is the previous fixer's root-cause hypothesis, compressed.
        """
        if not diff_text:
            return None
        files = []
        current = None
        hunk_changed = 0
        used = 0
        truncated = False

        for line in diff_text.splitlines():
            if used > DIFF_BUDGET:
                truncated = True
                break
            if line.startswith("+++ b/"):
                if len(files) >= MAX_DIFF_FILES:
                    truncated = True
                    break
                current = {"file": line[6:].split("\t")[0], "hunks": []}
                files.append(current)
            elif line.startswith("@@") and current is not None:
                if len(current["hunks"]) >= MAX_HUNKS_PER_FILE:
                    continue
                current["hunks"].append({"header": line, "changes": []})
                hunk_changed = 0
                used += len(line)
            elif (
                current is not None
                and current["hunks"]
                and line[:1] in ("+", "-")
                and not line.startswith(("+++", "---"))
            ):
                if hunk_changed < MAX_CHANGED_LINES_PER_HUNK:
                    current["hunks"][-1]["changes"].append(line[:160])
                    hunk_changed += 1
                    used += min(len(line), 160)
                else:
                    truncated = True

        if not files:
            return None
        return {"files": files, "truncated": truncated}

    @staticmethod
    def guidance(category: str) -> str:
        cat = (category or "").strip().lower()
        if cat in _BUG_CATEGORIES:
            return (
                "Category: Bug report. Derive the root cause YOURSELF from the "
                "evidence below (error blocks, code refs, diff digest) — "
                "heuristic_hints are keyword guesses, not conclusions. If the "
                "evidence is thin, say so and verify against the real code in "
                "the provisioned checkout before writing the repro script."
            )
        return (
            f"Category: {category or 'unknown'}. Root-cause framing does NOT "
            "apply — this is not a bug report. Read the evidence as the SCOPE "
            "of the proposed change instead, and frame verification as "
            "'confirm the change is still needed and applies cleanly'."
        )

    @staticmethod
    def build(
        metadata: Dict,
        comment_bodies: List[str],
        diff_text: str = "",
    ) -> Dict:
        """Assemble the full evidence bundle for the analysis context."""
        body_html = metadata.get("problem_description_html", "") or ""
        all_html = [body_html] + [c or "" for c in comment_bodies]

        blocks = []
        for html in all_html:
            blocks.extend(EvidenceExtractor.extract_html_blocks(html))

        ranked = EvidenceExtractor.rank_blocks(blocks)
        has_error_signal = any(b["kind"] == "error" for b in ranked)

        return {
            "guidance": EvidenceExtractor.guidance(metadata.get("category", "")),
            "category": metadata.get("category", ""),
            "error_blocks": ranked,
            "has_error_signal": has_error_signal,
            "code_refs": EvidenceExtractor.extract_code_refs(all_html),
            "diff_digest": EvidenceExtractor.digest_diff(diff_text),
        }
