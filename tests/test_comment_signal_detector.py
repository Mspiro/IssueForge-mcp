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


class TestRelatedIssueDetection:
    """
    Regression coverage for issue #2915538: a comment favoring closing the
    issue in favor of #2913927 produced no signal at all under the old
    keyword-only detector, so a real redirect/duplicate discussion was
    silently invisible to Step 2's structured analysis.
    """

    def test_redirect_language_near_issue_ref_detected(self):
        comment = (
            "It turns out that the halite library makes it really easy to "
            "tell whether data has been base64-encoded or not ( #2913927: "
            "Option for base64 encode/decode of encrypted data ). The "
            "solution in that issue seems a lot cleaner than the one in "
            "this issue, so I favor closing this issue in favor of the "
            "other one."
        )
        result = CommentSignalDetector.detect([comment], current_issue_id="2915538")
        related = result["related_issues"]
        assert any(r["issue_id"] == "2913927" for r in related)

    def test_incidental_issue_reference_not_flagged(self):
        comment = "See #123456 for background on how this was originally discussed."
        result = CommentSignalDetector.detect([comment], current_issue_id="2915538")
        assert result["related_issues"] == []

    def test_self_reference_not_flagged_as_related(self):
        comment = "As noted in #2915538 above, favor closing this in favor of that."
        result = CommentSignalDetector.detect([comment], current_issue_id="2915538")
        assert result["related_issues"] == []

    def test_empty_input_returns_empty_related_issues(self):
        result = CommentSignalDetector.detect([])
        assert result["related_issues"] == []

    def test_current_issue_id_is_optional(self):
        # detect() must stay callable with the old one-argument signature —
        # existing callers (and this test file's other classes) don't pass
        # current_issue_id.
        result = CommentSignalDetector.detect(["Thanks for looking into this!"])
        assert result["related_issues"] == []


class TestEnvironmentSignalDetection:
    """
    Regression coverage for issue #3537777: a commenter tested the fix
    against Drupal CMS while the issue itself is filed under plain Drupal
    core — nothing in the pipeline surfaced that mismatch automatically
    before this. environment_signals is read-only, informational only: it
    must never change environment_plan, only flag something for the user
    to weigh before Step 3 provisions anything.
    """

    def test_git_clone_of_different_project_detected(self):
        comment = (
            "mkdir dftmedia\ncd dftmedia\n"
            "git clone https://git.drupalcode.org/project/drupal_cms.git\n"
            "cd drupal_cms\nddev config --database=mariadb:10.11\nddev start"
        )
        result = CommentSignalDetector.detect(
            [comment], current_project_name="drupal"
        )
        signals = result["environment_signals"]
        assert any(
            s["type"] == "different_project_cloned" and s["detail"] == "drupal_cms"
            for s in signals
        )

    def test_git_clone_of_same_project_not_flagged(self):
        comment = "git clone https://git.drupalcode.org/project/drupal_cms.git"
        result = CommentSignalDetector.detect(
            [comment], current_project_name="drupal_cms"
        )
        assert result["environment_signals"] == []

    def test_distribution_name_mentioned_without_clone_detected(self):
        comment = "Reproduce the fault on that new installation of Drupal CMS."
        result = CommentSignalDetector.detect([comment], current_project_name="drupal")
        signals = result["environment_signals"]
        assert any(s["type"] == "distribution_mentioned" for s in signals)

    def test_version_mentioned_near_action_verb_detected(self):
        comment = "I reproduced this on Drupal 10.3 with no issues."
        result = CommentSignalDetector.detect([comment])
        signals = result["environment_signals"]
        assert any(s["type"] == "version_mentioned" for s in signals)

    def test_unrelated_comment_produces_no_environment_signal(self):
        result = CommentSignalDetector.detect(["Thanks for looking into this!"])
        assert result["environment_signals"] == []

    def test_current_project_name_is_optional(self):
        # Must stay callable without current_project_name, same as
        # current_issue_id above.
        comment = "git clone https://git.drupalcode.org/project/drupal_cms.git"
        result = CommentSignalDetector.detect([comment])
        assert any(
            s["type"] == "different_project_cloned" for s in result["environment_signals"]
        )
