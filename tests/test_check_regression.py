"""
Unit tests for check_regression.py's contrib repo-root detection.

Regression coverage for a real bug found testing MR !139 on #3392735:
check_regression.py always ran `git status` at the outer Drupal core
checkout, never the nested modules/contrib/<name> repo where contrib
changes actually live — so it silently reported "no matching test files"
even when real, tested changes existed. See project_issueforge_regression_gaps
memory and session_report_3392735.md for the full narrative.
"""
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "scripts"))

import check_regression


def _init_git_repo(path):
    os.makedirs(path, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)


class TestWorkRoot:
    def test_no_contrib_dir_returns_env_path(self, tmp_path):
        env_path = str(tmp_path)
        assert check_regression._work_root(env_path) == env_path

    def test_single_nested_contrib_repo_detected(self, tmp_path):
        env_path = str(tmp_path)
        nested = tmp_path / "modules" / "contrib" / "layout_paragraphs"
        _init_git_repo(str(nested))
        assert check_regression._work_root(env_path) == str(nested)

    def test_multiple_nested_repos_falls_back_to_env_path(self, tmp_path):
        env_path = str(tmp_path)
        _init_git_repo(str(tmp_path / "modules" / "contrib" / "module_a"))
        _init_git_repo(str(tmp_path / "modules" / "contrib" / "module_b"))
        assert check_regression._work_root(env_path) == env_path

    def test_contrib_dir_with_no_git_repos_falls_back_to_env_path(self, tmp_path):
        env_path = str(tmp_path)
        os.makedirs(tmp_path / "modules" / "contrib" / "not_a_repo", exist_ok=True)
        assert check_regression._work_root(env_path) == env_path


class TestReanchor:
    def test_same_root_returns_paths_unchanged(self, tmp_path):
        env_path = str(tmp_path)
        assert check_regression._reanchor(["core/foo.php"], env_path, env_path) == ["core/foo.php"]

    def test_nested_contrib_repo_paths_get_prefixed(self, tmp_path):
        env_path = str(tmp_path)
        work_root = str(tmp_path / "modules" / "contrib" / "layout_paragraphs")
        os.makedirs(work_root, exist_ok=True)
        result = check_regression._reanchor(
            ["src/LayoutParagraphsBuilder.php", "tests/src/Kernel/FooTest.php"],
            work_root, env_path,
        )
        assert result == [
            "modules/contrib/layout_paragraphs/src/LayoutParagraphsBuilder.php",
            "modules/contrib/layout_paragraphs/tests/src/Kernel/FooTest.php",
        ]
