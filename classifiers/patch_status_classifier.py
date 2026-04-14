class PatchStatusClassifier:
    """
    Classify patch maturity level from comment signals.
    """

    STATUS_PRIORITY = [
        ("committed", "Likely committed upstream"),
        ("rtbc", "Ready for community review"),
        ("needs_review", "Patch awaiting review"),
        ("needs_work", "Patch requires revision"),
    ]

    @staticmethod
    def classify(comment_signals):

        for status, signal in PatchStatusClassifier.STATUS_PRIORITY:
            if signal in comment_signals:
                return status

        return "unknown"