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

    @staticmethod
    def detect(comment_bodies: List[str]) -> Dict:

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
            "confidence": "medium" if detected else "low"
        }

    @staticmethod
    def _snippet(text: str, start: int, match_len: int, window: int = 60) -> str:
        """A short, whitespace-collapsed excerpt around a match, for context."""
        lo = max(0, start - window // 2)
        hi = min(len(text), start + match_len + window // 2)
        return " ".join(text[lo:hi].split())