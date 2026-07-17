"""Unit tests for credential_manager — no filesystem or env mutations."""
import os
import sys
import pytest
from unittest.mock import patch, MagicMock
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import services.credential_manager as cm


class TestIsSetupComplete:
    def test_returns_true_when_both_set(self):
        with patch.dict(os.environ, {"GIT_USER_NAME": "Jane", "GIT_USER_EMAIL": "jane@x.com"}):
            assert cm.is_setup_complete() is True

    def test_returns_false_when_name_missing(self):
        env = {"GIT_USER_NAME": "", "GIT_USER_EMAIL": "jane@x.com"}
        with patch.dict(os.environ, env, clear=False):
            os.environ.pop("GIT_USER_NAME", None)
            assert cm.is_setup_complete() is False

    def test_returns_false_when_email_missing(self):
        env = {"GIT_USER_NAME": "Jane", "GIT_USER_EMAIL": ""}
        with patch.dict(os.environ, env):
            assert cm.is_setup_complete() is False

    def test_returns_false_when_both_missing(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("GIT_USER_NAME", None)
            os.environ.pop("GIT_USER_EMAIL", None)
            assert cm.is_setup_complete() is False


class TestGetCredentials:
    def test_returns_all_three_keys(self):
        env = {
            "GITLAB_TOKEN": "glpat-abc123",
            "GIT_USER_NAME": "Jane Smith",
            "GIT_USER_EMAIL": "jane@example.com",
        }
        with patch.dict(os.environ, env):
            creds = cm.get_credentials()
        assert creds["gitlab_token"] == "glpat-abc123"
        assert creds["git_name"] == "Jane Smith"
        assert creds["git_email"] == "jane@example.com"

    def test_returns_fallback_defaults_when_missing(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("GIT_USER_NAME", None)
            os.environ.pop("GIT_USER_EMAIL", None)
            os.environ.pop("GITLAB_TOKEN", None)
            os.environ.pop("DRUPAL_USERNAME", None)
            creds = cm.get_credentials()
        assert creds["git_name"] == "IssueForge User"
        assert creds["git_email"] == "issueforge@example.com"
        assert creds["gitlab_token"] == ""
        assert creds["drupal_username"] == ""

    def test_returns_drupal_username_when_set(self):
        # Regression coverage: drupal_username used to be hardcoded to "",
        # never actually read from the stored credential — the dashboard's
        # credit lookup needs the real www.drupal.org forum username, which
        # is a separate identity from the GitLab account above.
        with patch.dict(os.environ, {"DRUPAL_USERNAME": "sunlix"}):
            creds = cm.get_credentials()
        assert creds["drupal_username"] == "sunlix"

    def test_never_prompts(self):
        """get_credentials() must NEVER call input() or getpass()."""
        with patch("builtins.input", side_effect=AssertionError("should not prompt")):
            with patch("getpass.getpass", side_effect=AssertionError("should not prompt")):
                cm.get_credentials()


class TestRunInteractiveSetupForceReuse:
    """
    Regression coverage: `setup.py --force` used to treat a blank ("keep
    existing") answer at the GitLab token prompt as "no token entered" and
    abort the whole setup — before ever reaching the drupal.org username
    prompt further down. The on-screen "press Enter to keep" message told
    the user the opposite of what actually happened.
    """

    def test_blank_input_under_force_reuses_existing_token(self):
        with patch.dict(os.environ, {"GITLAB_TOKEN": "existing-token-1234"}), \
             patch.object(cm, "_prompt", side_effect=["", "sunlix"]), \
             patch.object(cm, "_validate_gitlab_token",
                          return_value=(True, {"username": "sunlix", "name": "S", "email": "s@x.com"})), \
             patch.object(cm, "_persist") as persist:
            cm.run_interactive_setup(force=True)

        # The reused token (not an empty string) must be what gets validated
        # and persisted — confirming the setup did NOT abort early.
        persisted_keys = [call.args[0] for call in persist.call_args_list]
        assert "GITLAB_TOKEN" in persisted_keys
        token_call = next(c for c in persist.call_args_list if c.args[0] == "GITLAB_TOKEN")
        assert token_call.args[1] == "existing-token-1234"

    def test_reaches_drupal_username_prompt_after_reusing_token(self):
        with patch.dict(os.environ, {"GITLAB_TOKEN": "existing-token-1234"}), \
             patch.object(cm, "_prompt", side_effect=["", "sunlix"]) as prompt, \
             patch.object(cm, "_validate_gitlab_token",
                          return_value=(True, {"username": "sunlix", "name": "S", "email": "s@x.com"})), \
             patch.object(cm, "_persist") as persist:
            cm.run_interactive_setup(force=True)

        # Second _prompt call is the drupal.org username prompt; it must
        # actually be reached (previously execution never got here).
        assert prompt.call_count == 2
        persisted_keys = [call.args[0] for call in persist.call_args_list]
        assert "DRUPAL_USERNAME" in persisted_keys

    def test_no_saved_token_still_requires_real_input(self):
        # Sanity check the fix didn't remove the "must enter something when
        # nothing is saved yet" behavior. Also clears DRUPAL_USERNAME so a
        # real value persisted by an earlier setup.py run on this machine
        # can't leak in and cause a spurious _persist call.
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("GITLAB_TOKEN", None)
            os.environ.pop("DRUPAL_USERNAME", None)
            with patch.object(cm, "_prompt", return_value=""), \
                 patch.object(cm, "_persist") as persist:
                cm.run_interactive_setup(force=True)
        persist.assert_not_called()


class TestPersist:
    def test_writes_to_credentials_file(self, tmp_path):
        creds_file = tmp_path / "credentials"
        with patch.object(cm, "CREDENTIALS_DIR", tmp_path), \
             patch.object(cm, "CREDENTIALS_FILE", creds_file):
            cm._persist("GIT_USER_NAME", "Test User")
        assert creds_file.exists()
        content = creds_file.read_text()
        assert "GIT_USER_NAME" in content
        assert "Test User" in content
