"""Unit tests for CommentSignalDetector."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from classifiers.comment_signal_detector import CommentSignalDetector


class TestKeywordSignals:
    def test_needs_work_detected(self):
        result = CommentSignalDetector.detect(["This patch needs work before RTBC."])
        assert "Patch requires revision" in result["comment_signals"]

    def test_no_signal_on_unrelated_text(self):
        result = CommentSignalDetector.detect(["Thanks for looking into this!"])
        assert result["comment_signals"] == []
        assert result["confidence"] == "low"

    def test_html_tags_do_not_break_keyword_matching(self):
        # clean_comment strips tags before matching; a keyword split across
        # tags (e.g. "test <b>failure</b>") should still be found once clean.
        result = CommentSignalDetector.detect(["<p>needs review</p>"])
        assert "Patch awaiting review" in result["comment_signals"]


class TestNaturalPhrasingSignals:
    """
    Regression coverage for a real miss: issue #3115759's most important
    comment — "Still huge +1 for this feature. Seems to have broken a few
    tests" — produced zero signal under the old literal-bigram matching
    ("test failure" / "failing test" only).
    """

    def test_broke_a_few_tests_detected(self):
        result = CommentSignalDetector.detect([
            "Still huge +1 for this feature. Seems to have broken a few tests"
        ])
        assert "Regression or failing test detected" in result["comment_signals"]

    def test_breaks_several_tests_detected(self):
        result = CommentSignalDetector.detect(["This breaks several tests in the suite."])
        assert "Regression or failing test detected" in result["comment_signals"]

    def test_tests_are_failing_detected(self):
        result = CommentSignalDetector.detect(["The tests are now failing after this change."])
        assert "Regression or failing test detected" in result["comment_signals"]

    def test_unrelated_use_of_broken_not_flagged(self):
        result = CommentSignalDetector.detect(["My local environment is broken somehow."])
        assert "Regression or failing test detected" not in result["comment_signals"]


class TestCommentSignalDetails:
    def test_details_carry_the_actual_snippet(self):
        result = CommentSignalDetector.detect([
            "Still huge +1 for this feature. Seems to have broken a few tests"
        ])
        details = result["comment_signal_details"]
        assert any(
            d["label"] == "Regression or failing test detected"
            and "broken a few tests" in d["snippet"]
            for d in details
        )

    def test_empty_input_returns_empty_details(self):
        result = CommentSignalDetector.detect([])
        assert result["comment_signal_details"] == []
