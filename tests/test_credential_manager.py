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
            creds = cm.get_credentials()
        assert creds["git_name"] == "IssueForge User"
        assert creds["git_email"] == "issueforge@example.com"
        assert creds["gitlab_token"] == ""

    def test_never_prompts(self):
        """get_credentials() must NEVER call input() or getpass()."""
        with patch("builtins.input", side_effect=AssertionError("should not prompt")):
            with patch("getpass.getpass", side_effect=AssertionError("should not prompt")):
                cm.get_credentials()


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
