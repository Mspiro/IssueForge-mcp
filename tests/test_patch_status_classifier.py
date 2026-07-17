"""Unit tests for PatchStatusClassifier."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from classifiers.patch_status_classifier import PatchStatusClassifier
from classifiers.comment_signal_detector import CommentSignalDetector


class TestClassify:
    def test_needs_work_takes_priority(self):
        signals = ["Patch requires revision", "Ready for community review"]
        assert PatchStatusClassifier.classify(signals) == "needs_work"

    def test_unknown_when_nothing_matches(self):
        assert PatchStatusClassifier.classify([]) == "unknown"
        assert PatchStatusClassifier.classify(["Some unrelated label"]) == "unknown"

    def test_needs_review_reachable(self):
        # Regression coverage: SIGNAL_MAP used to key on "Needs review",
        # a string CommentSignalDetector never actually produces (it emits
        # "Patch awaiting review"), so this status was unreachable.
        assert PatchStatusClassifier.classify(["Patch awaiting review"]) == "needs_review"

    def test_fixed_reachable(self):
        # Same bug, different key: SIGNAL_MAP had "Issue fixed", which
        # nothing produces; the real producer emits "Likely committed
        # upstream" for the "commit" keyword.
        assert PatchStatusClassifier.classify(["Likely committed upstream"]) == "fixed"

    def test_integrates_with_real_detector_output(self):
        # End-to-end: a real comment should flow through the detector's
        # actual output shape into a real, non-"unknown" status.
        detected = CommentSignalDetector.detect(["This is needs review status."])
        status = PatchStatusClassifier.classify(detected["comment_signals"])
        assert status == "needs_review"
