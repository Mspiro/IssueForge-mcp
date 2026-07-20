"""
Unit tests for PatchApplier's already-applied detection.

Regression coverage for a real bug found testing MR !139 on #3392735:
apply_mr.py reported "[FAIL] Could not apply: Patch cannot be applied
cleanly with any strategy" for a patch whose changes were already present
in the working tree (from an earlier, interrupted session) — a forward
`git apply --check` fails identically for "already applied" and "genuinely
conflicting", so the tool couldn't tell them apart. See
project_issueforge_regression_gaps memory and session_report_3392735.md.
"""
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from services.patch_applier import PatchApplier


def _git(args, cwd):
    return subprocess.run(["git"] + args, cwd=cwd, capture_output=True, text=True)


def _init_repo_with_file(repo_dir, content):
    os.makedirs(repo_dir, exist_ok=True)
    _git(["init", "-q"], repo_dir)
    _git(["config", "user.email", "test@example.com"], repo_dir)
    _git(["config", "user.name", "Test"], repo_dir)
    with open(os.path.join(repo_dir, "file.txt"), "w") as f:
        f.write(content)
    _git(["add", "-A"], repo_dir)
    _git(["commit", "-q", "-m", "init"], repo_dir)


def _make_patch(repo_dir, patch_path, new_content):
    with open(os.path.join(repo_dir, "file.txt"), "w") as f:
        f.write(new_content)
    diff = _git(["diff"], repo_dir).stdout
    with open(patch_path, "w") as f:
        f.write(diff)
    # revert working copy back to the pre-patch state
    _git(["checkout", "--", "file.txt"], repo_dir)


class TestIsAlreadyApplied:
    def test_returns_true_when_patch_already_applied(self, tmp_path):
        repo = str(tmp_path / "repo")
        _init_repo_with_file(repo, "line1\nline2\nline3\n")
        patch_path = str(tmp_path / "change.patch")
        _make_patch(repo, patch_path, "line1\nline2-CHANGED\nline3\n")

        # Apply for real, so the tree now matches the patch's "after" state.
        _git(["apply", patch_path], repo)

        assert PatchApplier._is_already_applied(repo, patch_path) is True

    def test_returns_false_for_genuine_conflict(self, tmp_path):
        repo = str(tmp_path / "repo")
        _init_repo_with_file(repo, "line1\nline2\nline3\n")
        patch_path = str(tmp_path / "change.patch")
        _make_patch(repo, patch_path, "line1\nline2-CHANGED\nline3\n")

        # Diverge the tree with unrelated content instead of applying the patch.
        with open(os.path.join(repo, "file.txt"), "w") as f:
            f.write("totally different\nunrelated\n")
        _git(["add", "-A"], repo)
        _git(["commit", "-q", "-m", "unrelated change"], repo)

        assert PatchApplier._is_already_applied(repo, patch_path) is False


class TestApplyPatchFile:
    def test_reports_already_applied_as_success_not_failure(self, tmp_path):
        repo = str(tmp_path / "repo")
        _init_repo_with_file(repo, "line1\nline2\nline3\n")
        patch_path = str(tmp_path / "change.patch")
        _make_patch(repo, patch_path, "line1\nline2-CHANGED\nline3\n")
        _git(["apply", patch_path], repo)

        result = PatchApplier.apply_patch_file(repo, patch_path)
        assert result["success"] is True
        assert result["already_applied"] is True
        assert result["target_root"] == repo

    def test_genuine_conflict_still_reports_failure(self, tmp_path):
        repo = str(tmp_path / "repo")
        _init_repo_with_file(repo, "line1\nline2\nline3\n")
        patch_path = str(tmp_path / "change.patch")
        _make_patch(repo, patch_path, "line1\nline2-CHANGED\nline3\n")

        with open(os.path.join(repo, "file.txt"), "w") as f:
            f.write("totally different\nunrelated\n")
        _git(["add", "-A"], repo)
        _git(["commit", "-q", "-m", "unrelated change"], repo)

        result = PatchApplier.apply_patch_file(repo, patch_path)
        assert result["success"] is False
        assert "already_applied" not in result
