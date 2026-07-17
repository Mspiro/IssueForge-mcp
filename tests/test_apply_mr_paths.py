"""Unit tests for apply_mr's contrib-aware path handling.

Regression coverage for the nested-git-flow bug: for contrib issues the
patch lands in modules/contrib/<name> (its own git repo), so diff/status,
regression-check paths, and NEXT-STEPS git commands must all target that
nested repo — previously they all ran against the outer core clone, which
made the regression checker see zero changed files and report a false pass.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "scripts"))

from apply_mr import _to_env_relative, _changed_files_from_diff
from services.patch_applier import PatchApplier


class TestToEnvRelative:
    def test_core_repo_paths_unchanged(self):
        files = ["core/modules/system/src/Foo.php"]
        assert _to_env_relative(files, "/env", "/env") == files

    def test_contrib_paths_get_prefixed(self):
        files = ["src/EncryptService.php", "tests/src/Unit/EncryptServiceTest.php"]
        out = _to_env_relative(files, "/env", "/env/modules/contrib/encrypt")
        assert out == [
            "modules/contrib/encrypt/src/EncryptService.php",
            "modules/contrib/encrypt/tests/src/Unit/EncryptServiceTest.php",
        ]

    def test_prefixed_paths_match_regression_checker_heuristics(self):
        # The whole point of re-anchoring: RegressionChecker's contrib
        # pattern (modules/contrib/FOO/...) must recognize the results.
        from services.regression_checker import RegressionChecker
        out = _to_env_relative(
            ["tests/src/Kernel/Base64EncodeTest.php", "src/EncryptService.php"],
            "/env", "/env/modules/contrib/encrypt",
        )
        assert RegressionChecker.is_test_file(out[0])
        affected = RegressionChecker.extract_affected_modules(out)
        assert affected == [{
            "label": "encrypt",
            "module_dir": "modules/contrib/encrypt",
            "test_dir": "modules/contrib/encrypt/tests/src",
        }]


class TestChangedFilesFromDiff:
    def test_extracts_paths_from_unified_diff(self, tmp_path):
        # Used in --checkout mode, where the MR's changes are commits (not a
        # working-tree diff), so `git status` can't list them.
        diff = tmp_path / "mr.patch"
        diff.write_text(
            "diff --git a/src/EncryptService.php b/src/EncryptService.php\n"
            "--- a/src/EncryptService.php\n"
            "+++ b/src/EncryptService.php\n"
            "@@ -1 +1 @@\n"
            "diff --git a/tests/src/Kernel/Base64EncodeTest.php "
            "b/tests/src/Kernel/Base64EncodeTest.php\n"
            "--- /dev/null\n"
            "+++ b/tests/src/Kernel/Base64EncodeTest.php\n"
        )
        assert _changed_files_from_diff(str(diff)) == [
            "src/EncryptService.php",
            "tests/src/Kernel/Base64EncodeTest.php",
        ]

    def test_missing_file_gives_empty_list(self, tmp_path):
        assert _changed_files_from_diff(str(tmp_path / "nope.patch")) == []


class TestApplyPatchFileTargetRoot:
    def test_missing_patch_reports_failure(self, tmp_path):
        result = PatchApplier.apply_patch_file(str(tmp_path), str(tmp_path / "nope.diff"))
        assert result["success"] is False

    def test_target_root_present_on_unappliable_patch(self, tmp_path):
        # target_root must be reported even on failure so callers never
        # fall back to diffing the wrong repo.
        patch = tmp_path / "bad.diff"
        patch.write_text("+++ b/nonexistent/file.php\n@@ invalid @@\n")
        result = PatchApplier.apply_patch_file(str(tmp_path), str(patch))
        assert result["success"] is False
        assert "target_root" in result
