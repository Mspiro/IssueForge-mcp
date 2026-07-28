from typing import List, Dict
import re


class CommentSignalDetector:
    """
    Detect useful engineering signals from issue comments.
    """

    KEYWORD_SIGNALS = {
        "needs work": "Patch requires revision",
        "needs review": "Patch awaiting review",
        "rtbc": "Ready for community review",
        "reroll": "Patch updated after feedback",
        "test failure": "Regression or failing test detected",
        "failing test": "Regression or failing test detected",
        "interdiff": "Patch comparison available",
        "reviewed": "Patch has reviewer feedback",
        "maintainer": "Maintainer involvement detected",
        "commit": "Likely committed upstream",
    }

    # Natural-language phrasings the literal KEYWORD_SIGNALS bigrams miss.
    # Real example that motivated this: a comment saying "Seems to have
    # broken a few tests" produced zero signal, because the only test-
    # breakage patterns were the exact substrings "test failure" /
    # "failing test" — commenters almost never write it that way.
    PATTERN_SIGNALS = [
        (re.compile(r"\b(broke|breaks|broken)\b(?:(?!\.).){0,40}\btests?\b", re.I),
         "Regression or failing test detected"),
        (re.compile(r"\btests?\b(?:(?!\.).){0,40}\b(fail|failing|failed)\b", re.I),
         "Regression or failing test detected"),
    ]

    # Drupal.org issue node IDs are 6-7 digit numbers referenced as "#NNNNNNN".
    # A bare reference isn't enough signal on its own — "see #123456 for
    # background" is common and unrelated — so this only fires when a
    # redirect/duplicate phrase appears within REF_WINDOW characters of the
    # reference, keeping precision high on the same or an adjacent sentence.
    ISSUE_REF_PATTERN = re.compile(r"#(\d{6,7})\b")
    REDIRECT_KEYWORDS = re.compile(
        r"\b(duplicate|supersed\w*|favor\w* closing|clos\w* (?:this|it) in favor|"
        r"close (?:this|it) (?:issue|one)|cleaner solution|same as|redirect\w*)\b",
        re.I,
    )
    REF_WINDOW = 200

    # Read-only heads-up only — never used to auto-change what gets
    # provisioned. A commenter testing against a different environment than
    # the issue's own project/version is exactly the kind of thing a human
    # should confirm before Step 3 provisions anything (see #3537777: a
    # commenter tested on Drupal CMS while the issue itself is filed under
    # plain Drupal core — nothing upstream of this would have caught that
    # automatically).

    # Someone pasting a `git clone .../project/<name>.git` command for a
    # DIFFERENT drupal.org project than the issue's own is unambiguous
    # evidence of a different test environment — no keyword guessing needed.
    GIT_CLONE_PROJECT_PATTERN = re.compile(
        r"git\s+clone\s+\S*drupalcode\.org/project/([a-zA-Z0-9_]+)(?:\.git)?",
        re.I,
    )

    # Known distributions mentioned by name, regardless of a git clone
    # command being present. Kept in sync by hand with
    # services/distribution_registry.py's KNOWN_DISTRIBUTIONS is unnecessary
    # here — this list is about recognizing prose mentions of well-known
    # distributions generally (including ones IssueForge can't provision
    # yet), not about what's provisionable.
    DISTRIBUTION_NAME_PATTERN = re.compile(
        r"\b(Drupal\s*CMS|Thunder|Varbase|Open\s*Social|Lightning)\b", re.I
    )

    # A specific core/PHP version mentioned near an action verb — e.g.
    # "reproduced on Drupal 10.3", "tested using PHP 8.2". Softer signal
    # than the two above (no comparison against the resolved plan happens
    # here), surfaced for a human to weigh, same as everything else in
    # this detector.
    ENV_VERSION_PATTERN = re.compile(
        r"\b(?:tested|reproduce[sd]?|reproducing|using|install(?:ed|ing)?|running)\b"
        r"(?:(?!\.).){0,40}?"
        r"\b(Drupal\s*\d{1,2}(?:\.\d+)?|PHP\s*\d\.\d)\b",
        re.I,
    )

    @staticmethod
    def _detect_environment_signals(
        comment_bodies: List[str], current_project_name: str = None
    ) -> List[Dict]:
        found = []
        seen_snippets = set()
        for comment in comment_bodies:
            clean_comment = re.sub(r"<.*?>", "", comment)

            for m in CommentSignalDetector.GIT_CLONE_PROJECT_PATTERN.finditer(clean_comment):
                cloned_project = m.group(1)
                if current_project_name and cloned_project == current_project_name:
                    continue
                snippet = CommentSignalDetector._snippet(
                    clean_comment, m.start(), m.end() - m.start(), window=100
                )
                if snippet in seen_snippets:
                    continue
                seen_snippets.add(snippet)
                found.append({
                    "type": "different_project_cloned",
                    "detail": cloned_project,
                    "snippet": snippet,
                })

            for m in CommentSignalDetector.DISTRIBUTION_NAME_PATTERN.finditer(clean_comment):
                snippet = CommentSignalDetector._snippet(
                    clean_comment, m.start(), m.end() - m.start()
                )
                if snippet in seen_snippets:
                    continue
                seen_snippets.add(snippet)
                found.append({
                    "type": "distribution_mentioned",
                    "detail": " ".join(m.group(1).split()),
                    "snippet": snippet,
                })

            for m in CommentSignalDetector.ENV_VERSION_PATTERN.finditer(clean_comment):
                snippet = CommentSignalDetector._snippet(
                    clean_comment, m.start(), m.end() - m.start(), window=100
                )
                if snippet in seen_snippets:
                    continue
                seen_snippets.add(snippet)
                found.append({
                    "type": "version_mentioned",
                    "detail": " ".join(m.group(1).split()),
                    "snippet": snippet,
                })

        return found

    @staticmethod
    def _detect_related_issues(comment_bodies: List[str], current_issue_id: str = None) -> List[Dict]:
        found = {}
        for comment in comment_bodies:
            clean_comment = re.sub(r"<.*?>", "", comment)
            for m in CommentSignalDetector.ISSUE_REF_PATTERN.finditer(clean_comment):
                issue_id = m.group(1)
                if current_issue_id and issue_id == str(current_issue_id):
                    continue
                lo = max(0, m.start() - CommentSignalDetector.REF_WINDOW)
                hi = min(len(clean_comment), m.end() + CommentSignalDetector.REF_WINDOW)
                window = clean_comment[lo:hi]
                if CommentSignalDetector.REDIRECT_KEYWORDS.search(window):
                    if issue_id not in found:
                        found[issue_id] = {
                            "issue_id": issue_id,
                            "snippet": " ".join(window.split()),
                        }
        return list(found.values())

    @staticmethod
    def detect(
        comment_bodies: List[str],
        current_issue_id: str = None,
        current_project_name: str = None,
    ) -> Dict:

        detected = set()
        # The specific claim behind each signal, not just its generic
        # bucket label — e.g. "Seems to have broken a few tests" rather
        # than just "Regression or failing test detected". Downstream
        # readers (the assistant summarizing RECENT_COMMENTS, or a future
        # structured-requirement-checklist step) need the actual sentence
        # to act on it; the bucket alone loses that.
        details = []

        for comment in comment_bodies:
            clean_comment = re.sub(r"<.*?>", "", comment)
            lower_comment = clean_comment.lower()

            for keyword, signal in CommentSignalDetector.KEYWORD_SIGNALS.items():
                idx = lower_comment.find(keyword)
                if idx != -1:
                    detected.add(signal)
                    details.append({
                        "label": signal,
                        "snippet": CommentSignalDetector._snippet(clean_comment, idx, len(keyword)),
                    })

            for pattern, signal in CommentSignalDetector.PATTERN_SIGNALS:
                m = pattern.search(clean_comment)
                if m:
                    detected.add(signal)
                    details.append({
                        "label": signal,
                        "snippet": CommentSignalDetector._snippet(clean_comment, m.start(), m.end() - m.start()),
                    })

        return {
            "comment_signals": list(detected),
            "comment_signal_details": details,
            "related_issues": CommentSignalDetector._detect_related_issues(
                comment_bodies, current_issue_id
            ),
            "environment_signals": CommentSignalDetector._detect_environment_signals(
                comment_bodies, current_project_name
            ),
            "confidence": "medium" if detected else "low"
        }

    @staticmethod
    def _snippet(text: str, start: int, match_len: int, window: int = 60) -> str:
        """A short, whitespace-collapsed excerpt around a match, for context."""
        lo = max(0, start - window // 2)
        hi = min(len(text), start + match_len + window // 2)
        return " ".join(text[lo:hi].split())