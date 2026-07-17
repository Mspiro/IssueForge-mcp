class PatchStatusClassifier:
    """
    Classifies patch lifecycle state based on comment signals.
    Returns STRING only (never dict).
    """

    # Keys must match the exact label strings CommentSignalDetector
    # produces (see KEYWORD_SIGNALS values there) — "Needs review" and
    # "Issue fixed" never matched anything real, so needs_review/fixed
    # were unreachable regardless of what comments said.
    SIGNAL_MAP = {
        "Patch requires revision": "needs_work",
        "Patch awaiting review": "needs_review",
        "Ready for community review": "rtbc",
        "Likely committed upstream": "fixed",
    }

    PRIORITY = [
        "needs_work",
        "needs_review",
        "rtbc",
        "fixed",
    ]

    @staticmethod
    def classify(comment_signals):

        detected = set()

        for signal in comment_signals:

            mapped = PatchStatusClassifier.SIGNAL_MAP.get(signal)

            if mapped:
                detected.add(mapped)

        for status in PatchStatusClassifier.PRIORITY:

            if status in detected:
                return status

        return "unknown"