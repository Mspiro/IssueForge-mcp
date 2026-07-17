"""Unit tests for CodingStandardsChecker — no live DDEV calls."""
import os
import sys
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from services.coding_standards_checker import CodingStandardsChecker
from services.git_workspace_manager import GitWorkspaceManager


def _proc(returncode=0, stdout="", stderr=""):
    m = MagicMock()
    m.returncode = returncode
    m.stdout = stdout
    m.stderr = stderr
    return m


class TestLintable:
    def test_filters_to_php_like_extensions(self):
        files = [
            "src/EncryptService.php", "encrypt.module", "encrypt.install",
            "encrypt.info.yml", "templates/file-link.html.twig",
            "README.md", "js/thing.js",
        ]
        assert CodingStandardsChecker.lintable(files) == [
            "src/EncryptService.php", "encrypt.module", "encrypt.install",
        ]


class TestCheck:
    def test_no_lintable_files_passes_with_reason(self, tmp_path):
        result = CodingStandardsChecker.check(str(tmp_path), ["a.yml", "b.twig"])
        assert result["passed"] is True
        assert result["skipped_reason"]

    def test_missing_files_are_not_sent_to_phpcs(self, tmp_path):
        (tmp_path / "real.php").write_text("<?php\n")
        with patch("subprocess.run", return_value=_proc(0)) as run:
            result = CodingStandardsChecker.check(
                str(tmp_path), ["real.php", "gone.php"]
            )
        assert result["checked"] == ["real.php"]
        cmd = run.call_args[0][0]
        assert "gone.php" not in " ".join(cmd)

    def test_violations_reported_as_failure(self, tmp_path):
        (tmp_path / "bad.php").write_text("<?php\n")
        with patch("subprocess.run",
                   return_value=_proc(2, "FOUND 1 ERROR AFFECTING 1 LINE")):
            result = CodingStandardsChecker.check(str(tmp_path), ["bad.php"])
        assert result["passed"] is False
        assert "FOUND 1 ERROR" in result["output"]

    def test_missing_toolchain_does_not_block(self, tmp_path):
        # No core-dev install → report skipped, never block a contribution.
        (tmp_path / "a.php").write_text("<?php\n")
        with patch("subprocess.run", side_effect=FileNotFoundError("no ddev")):
            result = CodingStandardsChecker.check(str(tmp_path), ["a.php"])
        assert result["passed"] is True
        assert "unavailable" in result["skipped_reason"]

    def test_uses_core_standard_when_present(self, tmp_path):
        os.makedirs(tmp_path / "core")
        (tmp_path / "core" / "phpcs.xml.dist").write_text("<ruleset/>")
        (tmp_path / "a.php").write_text("<?php\n")
        with patch("subprocess.run", return_value=_proc(0)) as run:
            CodingStandardsChecker.check(str(tmp_path), ["a.php"])
        assert "core/phpcs.xml.dist" in " ".join(run.call_args[0][0])


class TestCheckAndFix:
    def test_clean_first_pass_skips_fixer(self, tmp_path):
        (tmp_path / "a.php").write_text("<?php\n")
        with patch("subprocess.run", return_value=_proc(0)) as run:
            result = CodingStandardsChecker.check_and_fix(str(tmp_path), ["a.php"])
        assert result["passed"] is True
        assert result["autofixed"] is False
        assert run.call_count == 1  # phpcs only, no phpcbf

    def test_autofix_then_recheck(self, tmp_path):
        # Regression coverage for the MR !12139 pipeline failure: one
        # phpcbf-fixable spacing error must be fixed and re-verified
        # locally instead of discovered by drupal.org CI after pushing.
        (tmp_path / "a.php").write_text("<?php\n")
        responses = [
            _proc(2, "FOUND 1 ERROR (fixable)"),   # phpcs: fail
            _proc(1, "A TOTAL OF 1 ERROR WERE FIXED"),  # phpcbf: fixed
            _proc(0, ""),                           # phpcs: clean
        ]
        with patch("subprocess.run", side_effect=responses):
            result = CodingStandardsChecker.check_and_fix(str(tmp_path), ["a.php"])
        assert result["passed"] is True
        assert result["autofixed"] is True

    def test_unfixable_violation_still_fails(self, tmp_path):
        (tmp_path / "a.php").write_text("<?php\n")
        responses = [
            _proc(2, "FOUND 2 ERRORS"),
            _proc(2, "FIXED 1 OF 2"),
            _proc(2, "FOUND 1 ERROR"),
        ]
        with patch("subprocess.run", side_effect=responses):
            result = CodingStandardsChecker.check_and_fix(str(tmp_path), ["a.php"])
        assert result["passed"] is False
        assert result["autofixed"] is True


class TestFilesPendingSubmission:
    def test_combines_uncommitted_and_unpushed(self, tmp_path):
        def fake_git(args, cwd, **kwargs):
            if args[:3] == ["diff", "--name-only", "HEAD"]:
                return _proc(0, "src/Unstaged.php\n")
            if args[:3] == ["diff", "--name-only", "--cached"]:
                return _proc(0, "src/Staged.php\n")
            if "rev-parse" in args:
                return _proc(0, "origin/branch\n")
            if "diff" in args:  # upstream..HEAD
                return _proc(0, "src/Committed.php\nsrc/Staged.php\n")
            return _proc(0)

        with patch.object(GitWorkspaceManager, "_git", side_effect=fake_git):
            files = GitWorkspaceManager.files_pending_submission(str(tmp_path))
        assert files == ["src/Committed.php", "src/Staged.php", "src/Unstaged.php"]

    def test_no_upstream_is_graceful(self, tmp_path):
        def fake_git(args, cwd, **kwargs):
            if "rev-parse" in args:
                return _proc(128, "", "no upstream")
            return _proc(0, "src/A.php\n")

        with patch.object(GitWorkspaceManager, "_git", side_effect=fake_git):
            files = GitWorkspaceManager.files_pending_submission(str(tmp_path))
        assert files == ["src/A.php"]
