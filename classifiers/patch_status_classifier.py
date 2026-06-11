class PatchStatusClassifier:
    """
    Classifies patch lifecycle state based on comment signals.
    Returns STRING only (never dict).
    """

    SIGNAL_MAP = {
        "Patch requires revision": "needs_work",
        "Needs review": "needs_review",
        "Ready for community review": "rtbc",
        "Issue fixed": "fixed",
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