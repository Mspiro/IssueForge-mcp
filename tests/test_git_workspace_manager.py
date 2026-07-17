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
            "branch -r": self._make_run(0, "  drupal-2692289/2692289-fix\n"),
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

    def test_remote_name_matches_drupal_org_instructions(self, tmp_path):
        # The issue page's "Get push access" block names the remote
        # "<project>-<issue_id>" — matching it lets users cross-check every
        # printed command against the page 1:1.
        recorded = []

        def fake_git(args, cwd, **kwargs):
            recorded.append(args)
            return self._make_run(0)

        with patch.object(GitWorkspaceManager, "_git", side_effect=fake_git):
            result = GitWorkspaceManager.setup_issue_remote(
                str(tmp_path), "encrypt", "2915538"
            )

        assert result["remote_name"] == "encrypt-2915538"
        assert ["remote", "add", "encrypt-2915538",
                "https://git.drupalcode.org/issue/encrypt-2915538.git"] in recorded
        # The legacy 'issue' remote from older environments is cleaned up.
        assert ["remote", "remove", "issue"] in recorded

    def test_push_url_uses_ssh_form(self, tmp_path):
        # Regression coverage: the remote used to be HTTPS-only. Anonymous
        # HTTPS can fetch a public fork but can never push, so every push
        # failed. The push URL must be the exact SSH form the issue page's
        # "Get push access" instructions show — host git.drupal.org.
        recorded = []

        def fake_git(args, cwd, **kwargs):
            recorded.append(args)
            return self._make_run(0)

        with patch.object(GitWorkspaceManager, "_git", side_effect=fake_git):
            result = GitWorkspaceManager.setup_issue_remote(
                str(tmp_path), "encrypt", "2915538"
            )

        assert result["push_url"] == "git@git.drupal.org:issue/encrypt-2915538.git"
        assert ["remote", "set-url", "--push", "encrypt-2915538",
                "git@git.drupal.org:issue/encrypt-2915538.git"] in recorded
        # Fetch URL stays anonymous HTTPS.
        assert result["remote_url"].startswith("https://")

    def test_find_issue_remote_by_url(self, tmp_path):
        # Detection is by URL, not name, so both canonical and legacy
        # ("issue") remote names from older environments are found.
        listing = (
            "origin\thttps://git.drupalcode.org/project/encrypt.git (fetch)\n"
            "origin\thttps://git.drupalcode.org/project/encrypt.git (push)\n"
            "encrypt-2915538\thttps://git.drupalcode.org/issue/encrypt-2915538.git (fetch)\n"
            "encrypt-2915538\tgit@git.drupal.org:issue/encrypt-2915538.git (push)\n"
        )
        with patch.object(
            GitWorkspaceManager, "_git",
            return_value=self._make_run(0, listing),
        ):
            assert GitWorkspaceManager.find_issue_remote(str(tmp_path)) == "encrypt-2915538"

    def test_find_issue_remote_none_when_absent(self, tmp_path):
        listing = "origin\thttps://git.drupalcode.org/project/drupal.git (fetch)\n"
        with patch.object(
            GitWorkspaceManager, "_git",
            return_value=self._make_run(0, listing),
        ):
            assert GitWorkspaceManager.find_issue_remote(str(tmp_path)) is None


class TestCheckoutMrBranch:
    """The drupal.org flow for updating an existing MR: work ON its branch.

    A locally created work branch has diverged history from the MR branch
    (same content, different commits), so pushing HEAD:<branch> from it is
    rejected — tracking the MR's own branch is the only correct path.
    """

    def _make_run(self, returncode=0, stdout="", stderr=""):
        m = MagicMock()
        m.returncode = returncode
        m.stdout = stdout
        m.stderr = stderr
        return m

    def test_creates_tracking_branch_like_issue_page_instructs(self, tmp_path):
        recorded = []

        def fake_git(args, cwd, **kwargs):
            recorded.append(args)
            if args[:2] == ["status", "--porcelain"]:
                return self._make_run(0, "")          # clean tree
            if args[:2] == ["rev-parse", "--verify"]:
                return self._make_run(1)              # no local branch yet
            return self._make_run(0)

        with patch.object(GitWorkspaceManager, "_git", side_effect=fake_git):
            result = GitWorkspaceManager.checkout_mr_branch(
                str(tmp_path), "encrypt-2915538", "base64"
            )

        assert result["success"] is True
        assert ["checkout", "-b", "base64", "--track",
                "encrypt-2915538/base64"] in recorded

    def test_reuses_existing_local_branch(self, tmp_path):
        recorded = []

        def fake_git(args, cwd, **kwargs):
            recorded.append(args)
            if args[:2] == ["status", "--porcelain"]:
                return self._make_run(0, "")
            return self._make_run(0)                  # branch exists

        with patch.object(GitWorkspaceManager, "_git", side_effect=fake_git):
            result = GitWorkspaceManager.checkout_mr_branch(
                str(tmp_path), "encrypt-2915538", "base64"
            )

        assert result["success"] is True
        assert ["checkout", "base64"] in recorded

    def test_refuses_dirty_working_tree(self, tmp_path):
        recorded = []

        def fake_git(args, cwd, **kwargs):
            recorded.append(args)
            if args[:2] == ["status", "--porcelain"]:
                return self._make_run(0, " M src/EncryptService.php\n")
            return self._make_run(0)

        with patch.object(GitWorkspaceManager, "_git", side_effect=fake_git):
            result = GitWorkspaceManager.checkout_mr_branch(
                str(tmp_path), "encrypt-2915538", "base64"
            )

        assert result["success"] is False
        assert "uncommitted changes" in result["message"]
        # Never attempts a checkout over a dirty tree.
        assert not any(a[0] == "checkout" for a in recorded)

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
