"""Unit tests for GitWorkspaceManager — no live git calls."""
import os
import sys
import subprocess
from unittest.mock import patch, MagicMock, call
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from services.git_workspace_manager import GitWorkspaceManager


class TestSetupIssueRemote:
    def _make_run(self, returncode=0, stdout=""):
        m = MagicMock()
        m.returncode = returncode
        m.stdout = stdout
        m.stderr = ""
        return m

    def test_adds_remote_and_returns_fork_url(self, tmp_path):
        responses = {
            "remote remove": self._make_run(0),
            "remote add": self._make_run(0),
            "fetch": self._make_run(0),
            "branch -r": self._make_run(0, "  issue/2692289-fix\n"),
        }

        def fake_git(args, cwd, **kwargs):
            key = " ".join(args[:2])
            for k, v in responses.items():
                if k in key:
                    return v
            return self._make_run(0)

        with patch.object(GitWorkspaceManager, "_git", side_effect=fake_git):
            result = GitWorkspaceManager.setup_issue_remote(
                str(tmp_path), "drupal", "2692289"
            )

        assert "git.drupalcode.org/issue/drupal-2692289" in result["remote_url"]
        assert result["fetched"] is True
        assert "2692289-fix" in result["remote_branches"]

    def test_graceful_when_fetch_fails(self, tmp_path):
        def fake_git(args, cwd, **kwargs):
            m = MagicMock()
            m.returncode = 1 if "fetch" in args else 0
            m.stdout = ""
            m.stderr = "Repository not found"
            return m

        with patch.object(GitWorkspaceManager, "_git", side_effect=fake_git):
            result = GitWorkspaceManager.setup_issue_remote(
                str(tmp_path), "drupal", "9999999"
            )

        assert result["fetched"] is False
        assert result["remote_branches"] == []
        assert result["warnings"]

    def test_fork_url_pattern(self, tmp_path):
        with patch.object(GitWorkspaceManager, "_git", return_value=MagicMock(returncode=0, stdout="", stderr="")):
            result = GitWorkspaceManager.setup_issue_remote(
                str(tmp_path), "paragraphs", "3401176"
            )
        assert result["remote_url"] == "https://git.drupalcode.org/issue/paragraphs-3401176.git"


class TestPushWithConfirmation:
    def _mock_git(self, responses: dict):
        """Return a _git side_effect that matches on args[0]."""
        def fake(args, cwd, **kwargs):
            m = MagicMock()
            m.returncode = 0
            m.stderr = ""
            for key, val in responses.items():
                if key in args:
                    m.stdout = val
                    return m
            m.stdout = ""
            return m
        return fake

    def test_cancels_when_user_types_n(self, tmp_path):
        fake = self._mock_git({
            "remote": "issue\norigin",
            "get-url": "https://git.drupalcode.org/issue/drupal-123.git",
            "--short": "M core/file.php",
            "--stat": " 1 file changed",
            "--oneline": "abc1234 previous commit",
        })
        with patch.object(GitWorkspaceManager, "_git", side_effect=fake), \
             patch("builtins.input", return_value="n"):
            result = GitWorkspaceManager.push_with_confirmation(str(tmp_path))
        assert result is False

    def test_cancels_when_final_answer_is_no(self, tmp_path):
        fake = self._mock_git({
            "remote": "origin",
            "get-url": "https://git.drupalcode.org/project/drupal.git",
            "--short": "",       # no uncommitted changes
            "--stat": " 1 file changed",
            "--oneline": "abc1234 some commit",
        })
        # No uncommitted changes → skips commit prompt, goes to push confirm
        with patch.object(GitWorkspaceManager, "_git", side_effect=fake), \
             patch("builtins.input", return_value="n"):
            result = GitWorkspaceManager.push_with_confirmation(str(tmp_path))
        assert result is False

    def test_never_pushes_without_yes(self, tmp_path):
        """Pressing Enter (empty string) must NOT push."""
        fake = self._mock_git({
            "remote": "origin",
            "get-url": "https://example.com/repo.git",
            "--short": "",
            "--stat": "",
            "--oneline": "",
        })
        with patch.object(GitWorkspaceManager, "_git", side_effect=fake), \
             patch("builtins.input", return_value=""):
            result = GitWorkspaceManager.push_with_confirmation(str(tmp_path))
        assert result is False

    def test_pushes_when_user_confirms_yes(self, tmp_path):
        call_log = []

        def fake(args, cwd, **kwargs):
            call_log.append(args[:])
            m = MagicMock()
            m.returncode = 0
            m.stdout = {
                "remote": "origin",
                "get-url": "https://git.drupalcode.org/project/drupal.git",
                "--short": "",
                "--stat": " 1 file changed",
                "--oneline": "abc commit",
            }.get(args[-1] if args else "", "")
            m.stderr = ""
            return m

        with patch.object(GitWorkspaceManager, "_git", side_effect=fake), \
             patch("builtins.input", return_value="y"):
            result = GitWorkspaceManager.push_with_confirmation(str(tmp_path))

        assert result is True
        push_calls = [c for c in call_log if "push" in c]
        assert push_calls, "git push was never called"


class TestWaitForFork:
    def test_returns_true_when_fork_appears(self, tmp_path):
        # ls-remote fails once then succeeds
        ls_remote_calls = [
            MagicMock(returncode=128),  # fork not ready
            MagicMock(returncode=0),    # fork ready
        ]

        def fake_run(args, **kwargs):
            if "ls-remote" in args:
                return ls_remote_calls.pop(0)
            return MagicMock(returncode=0)

        def fake_git(args, cwd, **kwargs):
            m = MagicMock()
            m.returncode = 0
            m.stdout = ""
            m.stderr = ""
            return m

        with patch("subprocess.run", side_effect=fake_run), \
             patch.object(GitWorkspaceManager, "_git", side_effect=fake_git), \
             patch("time.sleep"):
            result = GitWorkspaceManager.wait_for_fork(
                str(tmp_path), "drupal", "2692289", poll_interval=1, timeout=30
            )

        assert result is True

    def test_returns_false_on_timeout(self, tmp_path):
        def fake_run(args, **kwargs):
            return MagicMock(returncode=128)  # always fails

        with patch("subprocess.run", side_effect=fake_run), \
             patch("time.sleep"):
            result = GitWorkspaceManager.wait_for_fork(
                str(tmp_path), "drupal", "2692289", poll_interval=1, timeout=2
            )

        assert result is False
