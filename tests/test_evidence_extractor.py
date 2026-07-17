"""Unit tests for EvidenceExtractor.

The contract under test: emit what exists, ranked, capped — never
synthesize. Extraction is structure-first (HTML blocks), regex-second
(ranking only), so a ranking misfire can include a less-useful block but
can never produce invented prose.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from services.evidence_extractor import (
    EvidenceExtractor,
    BLOCK_BUDGET,
    MAX_BLOCKS,
    MAX_CODE_REFS,
)


class TestExtractHtmlBlocks:
    def test_pulls_code_pre_and_blockquote(self):
        html = (
            "<p>Some prose.</p>"
            "<code>TypeError: x is null</code>"
            "<pre>stack line 1\nstack line 2</pre>"
            "<blockquote>quoted error</blockquote>"
        )
        blocks = EvidenceExtractor.extract_html_blocks(html)
        assert blocks == [
            "TypeError: x is null",
            "stack line 1\nstack line 2",
            "quoted error",
        ]

    def test_nested_pre_code_counts_once(self):
        html = "<pre><code>Fatal error: oops</code></pre>"
        blocks = EvidenceExtractor.extract_html_blocks(html)
        assert blocks == ["Fatal error: oops"]

    def test_prose_outside_blocks_is_ignored(self):
        # Structural pass must not leak prose — that's what keeps the
        # bundle small and non-hallucinatory.
        html = "<p>An Exception occurred somewhere, believe me.</p>"
        assert EvidenceExtractor.extract_html_blocks(html) == []

    def test_empty_and_malformed_html(self):
        assert EvidenceExtractor.extract_html_blocks("") == []
        assert EvidenceExtractor.extract_html_blocks("<pre>ok") in ([], ["ok"])


class TestRankBlocks:
    def test_php_exception_outranks_config_snippet(self):
        error = (
            "PHP Fatal error: Uncaught Drupal\\Core\\Database\\DatabaseException\n"
            "#0 /var/www/html/core/lib/Database.php(42): query()"
        )
        config = "dependencies:\n  - key:key\n  - encrypt:encrypt\n  - token"
        ranked = EvidenceExtractor.rank_blocks([config, error])
        assert ranked[0]["text"] == error
        assert ranked[0]["kind"] == "error"
        assert ranked[1]["kind"] == "code"

    def test_phpunit_failure_is_error_kind(self):
        block = (
            "1) Drupal\\Tests\\encrypt\\Unit\\EncryptServiceTest::testEncrypt\n"
            "Failed asserting that two strings are identical."
        )
        ranked = EvidenceExtractor.rank_blocks([block])
        assert ranked[0]["kind"] == "error"

    def test_budget_is_enforced_with_explicit_omission_note(self):
        # No silent caps: dropped blocks are announced.
        blocks = [f"Fatal error: number {i} " + "x" * 800 for i in range(8)]
        ranked = EvidenceExtractor.rank_blocks(blocks)
        emitted = [b for b in ranked if b["kind"] != "note"]
        assert len(emitted) <= MAX_BLOCKS
        assert sum(len(b["text"]) for b in emitted) <= BLOCK_BUDGET + 100
        assert any(b["kind"] == "note" and "omitted" in b["text"] for b in ranked)

    def test_single_giant_trace_cannot_crowd_out_everything(self):
        giant = "Fatal error: big\n" + "trace line\n" * 500
        small = "SQLSTATE[23000]: Integrity constraint violation"
        ranked = EvidenceExtractor.rank_blocks([giant, small])
        texts = [b["text"] for b in ranked]
        assert any("SQLSTATE" in t for t in texts)
        assert any("[block truncated]" in t for t in texts)

    def test_duplicate_blocks_are_deduped(self):
        block = "Fatal error: same thing"
        ranked = EvidenceExtractor.rank_blocks([block, block, block])
        assert len([b for b in ranked if b["kind"] != "note"]) == 1

    def test_tiny_inline_mentions_are_skipped(self):
        # `<code><button></code>` style inline mentions carry no evidence
        # and must not occupy ranked slots — but short ERROR blocks stay.
        ranked = EvidenceExtractor.rank_blocks(
            ["<button>", ".module.css", "SQLSTATE[23000] boom"]
        )
        texts = [b["text"] for b in ranked]
        assert texts == ["SQLSTATE[23000] boom"]


class TestExtractCodeRefs:
    def test_path_with_line_number(self):
        texts = ["<p>The bug is in core/lib/Drupal/Core/Form/FormBuilder.php line 432</p>"]
        refs = EvidenceExtractor.extract_code_refs(texts)
        assert "core/lib/Drupal/Core/Form/FormBuilder.php:432" in refs

    def test_bare_filename_without_line_is_skipped(self):
        # "composer.json" mentioned casually is too weak a signal.
        refs = EvidenceExtractor.extract_code_refs(["update composer.json please"])
        assert refs == []

    def test_bare_filename_with_line_is_kept(self):
        refs = EvidenceExtractor.extract_code_refs(["EncryptService.php on line 85"])
        assert refs == ["EncryptService.php:85"]

    def test_deduped_and_capped(self):
        texts = [f"src/File{i}.php line {i}" for i in range(20)]
        refs = EvidenceExtractor.extract_code_refs(texts)
        assert len(refs) == MAX_CODE_REFS

    def test_urls_are_not_code_refs(self):
        # Regression coverage: php.net documentation links matched the
        # file-path pattern ("functions.arguments.php") and polluted refs.
        texts = [
            "see https://www.php.net/manual/en/functions.arguments.php",
            "docs at api.drupal.org/api/drupal/core.api.php/group/hooks",
            "but src/Real/File.php line 10 is the actual bug",
        ]
        refs = EvidenceExtractor.extract_code_refs(texts)
        assert refs == ["src/Real/File.php:10"]


class TestDigestDiff:
    DIFF = (
        "diff --git a/src/EncryptService.php b/src/EncryptService.php\n"
        "--- a/src/EncryptService.php\n"
        "+++ b/src/EncryptService.php\n"
        "@@ -80,6 +80,11 @@ public function encrypt($text, $profile) {\n"
        " context line\n"
        "+      if ($profile->getBase64Encode()) {\n"
        "+        return base64_encode($encrypted);\n"
        "+      }\n"
        " context line\n"
    )

    def test_hunk_header_carries_function_context(self):
        digest = EvidenceExtractor.digest_diff(self.DIFF)
        assert digest["files"][0]["file"] == "src/EncryptService.php"
        header = digest["files"][0]["hunks"][0]["header"]
        assert "public function encrypt" in header

    def test_changed_lines_kept_context_dropped(self):
        digest = EvidenceExtractor.digest_diff(self.DIFF)
        changes = digest["files"][0]["hunks"][0]["changes"]
        assert all(c[:1] in "+-" for c in changes)
        assert not any("context line" in c for c in changes)

    def test_empty_diff_gives_none(self):
        assert EvidenceExtractor.digest_diff("") is None
        assert EvidenceExtractor.digest_diff("not a diff at all") is None

    def test_truncation_is_flagged(self):
        big = "".join(
            f"+++ b/file{i}.php\n@@ -1,1 +1,1 @@ fn{i}\n" + "+new line\n" * 20
            for i in range(30)
        )
        digest = EvidenceExtractor.digest_diff(big)
        assert digest["truncated"] is True


class TestGuidance:
    def test_bug_report_gets_root_cause_framing(self):
        g = EvidenceExtractor.guidance("Bug report")
        assert "root cause" in g.lower()
        assert "keyword guesses" in g

    def test_task_gets_scope_framing_not_bug_framing(self):
        # Regression coverage for the CSS-rename fiasco: a Task must never
        # be presented through root-cause framing.
        g = EvidenceExtractor.guidance("Task")
        assert "does NOT apply" in g
        assert "scope" in g.lower()

    def test_unknown_category_defaults_to_non_bug(self):
        assert "does NOT apply" in EvidenceExtractor.guidance("")


class TestBuild:
    def test_bundle_shape_for_bug_with_error(self):
        metadata = {
            "category": "Bug report",
            "problem_description_html":
                "<p>It crashes:</p><pre>Fatal error: Uncaught TypeError in "
                "src/EncryptService.php line 85</pre>",
        }
        comments = ["<code>SQLSTATE[42S02]: Base table not found</code>"]
        bundle = EvidenceExtractor.build(metadata, comments, self_diff())
        assert bundle["has_error_signal"] is True
        assert bundle["category"] == "Bug report"
        assert any("Fatal error" in b["text"] for b in bundle["error_blocks"])
        assert any("SQLSTATE" in b["text"] for b in bundle["error_blocks"])
        assert "src/EncryptService.php:85" in bundle["code_refs"]
        assert bundle["diff_digest"]["files"][0]["file"] == "src/EncryptService.php"

    def test_task_without_errors_degrades_honestly(self):
        # A rename task: no error blocks, no invented prose — just scope.
        metadata = {
            "category": "Task",
            "problem_description_html": "<p>Rename all the CSS files.</p>",
        }
        bundle = EvidenceExtractor.build(metadata, [], "")
        assert bundle["has_error_signal"] is False
        assert bundle["error_blocks"] == []
        assert bundle["diff_digest"] is None
        assert "does NOT apply" in bundle["guidance"]


def self_diff():
    return TestDigestDiff.DIFF
