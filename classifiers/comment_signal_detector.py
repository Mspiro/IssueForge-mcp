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

    @staticmethod
    def detect(comment_bodies: List[str]) -> Dict:

        detected = set()

        for comment in comment_bodies:
            clean_comment = re.sub(r"<.*?>", "", comment)
            lower_comment = comment.lower()

            for keyword, signal in CommentSignalDetector.KEYWORD_SIGNALS.items():

                if keyword in lower_comment:
                    detected.add(signal)

        return {
            "comment_signals": list(detected),
            "confidence": "medium" if detected else "low"
        }