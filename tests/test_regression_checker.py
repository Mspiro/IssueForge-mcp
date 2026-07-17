"""Unit tests for RegressionChecker — no live DDEV calls."""
import pytest
import sys, os
from unittest.mock import patch, MagicMock
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from services.regression_checker import RegressionChecker


class TestDiscoverTestFiles:
    def test_core_lib_pattern(self, tmp_path):
        # Create the test file on disk so discover_test_files finds it
        test_dir = tmp_path / "core" / "tests" / "Drupal" / "Tests" / "Core" / "Entity" / "Element"
        test_dir.mkdir(parents=True)
        (test_dir / "EntityAutocompleteTest.php").write_text("<?php")

        changed = ["core/lib/Drupal/Core/Entity/Element/EntityAutocomplete.php"]
        found = RegressionChecker.discover_test_files(str(tmp_path), changed)
        assert len(found) == 1
        assert "EntityAutocompleteTest.php" in found[0]

    def test_core_module_pattern(self, tmp_path):
        test_dir = tmp_path / "core" / "modules" / "field" / "tests" / "src" / "Unit"
        test_dir.mkdir(parents=True)
        (test_dir / "FieldItemListTest.php").write_text("<?php")

        changed = ["core/modules/field/src/FieldItemList.php"]
        found = RegressionChecker.discover_test_files(str(tmp_path), changed)
        assert len(found) == 1
        assert "FieldItemListTest.php" in found[0]

    def test_no_test_file_returns_empty(self, tmp_path):
        changed = ["core/lib/Drupal/Core/NoTestForThis.php"]
        found = RegressionChecker.discover_test_files(str(tmp_path), changed)
        assert found == []

    def test_empty_changed_files(self, tmp_path):
        assert RegressionChecker.discover_test_files(str(tmp_path), []) == []

    def test_self_matches_changed_test_file(self, tmp_path):
        # A patch that adds/modifies a test file directly (e.g. a new
        # FooTest.php shipped by an MR) must be run even though there's no
        # differently-named source file to heuristically map it from.
        test_dir = tmp_path / "core" / "modules" / "layout_builder" / "tests" / "src" / "Functional"
        test_dir.mkdir(parents=True)
        (test_dir / "LayoutBuilderNewFieldsTest.php").write_text("<?php")

        changed = ["core/modules/layout_builder/tests/src/Functional/LayoutBuilderNewFieldsTest.php"]
        found = RegressionChecker.discover_test_files(str(tmp_path), changed)
        assert found == ["core/modules/layout_builder/tests/src/Functional/LayoutBuilderNewFieldsTest.php"]

    def test_self_match_and_heuristic_combine_without_duplicates(self, tmp_path):
        src_test_dir = tmp_path / "core" / "modules" / "field" / "tests" / "src" / "Unit"
        src_test_dir.mkdir(parents=True)
        (src_test_dir / "FieldItemListTest.php").write_text("<?php")

        changed = [
            "core/modules/field/src/FieldItemList.php",
            "core/modules/field/tests/src/Unit/FieldItemListTest.php",
        ]
        found = RegressionChecker.discover_test_files(str(tmp_path), changed)
        assert found.count("core/modules/field/tests/src/Unit/FieldItemListTest.php") == 1


class TestExtractAffectedModules:
    def test_core_module_source_change_detected(self):
        changed = ["core/modules/layout_builder/src/Entity/LayoutBuilderEntityViewDisplay.php"]
        modules = RegressionChecker.extract_affected_modules(changed)
        assert modules == [{
            "label": "layout_builder",
            "module_dir": "core/modules/layout_builder",
            "test_dir": "core/modules/layout_builder/tests/src",
        }]

    def test_test_only_changes_do_not_trigger_sweep(self):
        changed = ["core/modules/layout_builder/tests/src/Functional/LayoutBuilderTest.php"]
        assert RegressionChecker.extract_affected_modules(changed) == []

    def test_contrib_module_source_change_detected(self):
        changed = ["modules/contrib/paragraphs/src/Entity/Paragraph.php"]
        modules = RegressionChecker.extract_affected_modules(changed)
        assert modules[0]["label"] == "paragraphs"

    def test_multiple_files_same_module_dedupe(self):
        changed = [
            "core/modules/layout_builder/src/Entity/LayoutBuilderEntityViewDisplay.php",
            "core/modules/layout_builder/src/Section.php",
        ]
        modules = RegressionChecker.extract_affected_modules(changed)
        assert len(modules) == 1

    def test_unrelated_path_ignored(self):
        assert RegressionChecker.extract_affected_modules(["composer.json"]) == []


class TestRunFullModuleSuite:
    def test_skips_when_no_phpunit_xml(self, tmp_path):
        result = RegressionChecker.run_full_module_suite(
            str(tmp_path), [{"label": "x", "module_dir": "core/modules/x", "test_dir": "core/modules/x/tests/src"}]
        )
        assert result["skipped"] is True
        assert result["passed"] is True

    def test_skips_module_with_no_tests_dir(self, tmp_path):
        (tmp_path / "core").mkdir()
        (tmp_path / "core" / "phpunit.xml.dist").write_text("<phpunit/>")
        result = RegressionChecker.run_full_module_suite(
            str(tmp_path),
            [{"label": "x", "module_dir": "core/modules/x", "test_dir": "core/modules/x/tests/src"}],
        )
        assert result["passed"] is True
        assert result["module_results"][0]["skipped"] is True

    def test_reports_timeout_as_not_passed(self, tmp_path):
        (tmp_path / "core").mkdir()
        (tmp_path / "core" / "phpunit.xml.dist").write_text("<phpunit/>")
        test_dir = tmp_path / "core" / "modules" / "x" / "tests" / "src"
        test_dir.mkdir(parents=True)

        with patch("services.regression_checker.subprocess.run") as mock_run:
            mock_run.side_effect = __import__("subprocess").TimeoutExpired(cmd="phpunit", timeout=1)
            result = RegressionChecker.run_full_module_suite(
                str(tmp_path),
                [{"label": "x", "module_dir": "core/modules/x", "test_dir": "core/modules/x/tests/src"}],
            )
        assert result["passed"] is False
        assert result["module_results"][0]["timed_out"] is True

    def test_passes_simpletest_env_vars_to_ddev_exec(self, tmp_path):
        (tmp_path / "core").mkdir()
        (tmp_path / "core" / "phpunit.xml.dist").write_text("<phpunit/>")
        test_dir = tmp_path / "core" / "modules" / "x" / "tests" / "src"
        test_dir.mkdir(parents=True)

        with patch("services.regression_checker.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="OK", stderr="")
            RegressionChecker.run_full_module_suite(
                str(tmp_path),
                [{"label": "x", "module_dir": "core/modules/x", "test_dir": "core/modules/x/tests/src"}],
            )
        args = mock_run.call_args[0][0]
        assert args[:3] == ["ddev", "exec", "sh"]
        shell_cmd = args[4]
        assert "SIMPLETEST_BASE_URL=" in shell_cmd
        assert "SIMPLETEST_DB=" in shell_cmd
        assert "BROWSERTEST_OUTPUT_DIRECTORY=" in shell_cmd


class TestCandidateTestPaths:
    def test_core_lib_maps_correctly(self):
        paths = RegressionChecker._candidate_test_paths(
            "core/lib/Drupal/Core/Entity/Element/EntityAutocomplete.php"
        )
        assert any("EntityAutocompleteTest.php" in p for p in paths)
        assert any("core/tests/Drupal/Tests" in p for p in paths)

    def test_core_module_maps_correctly(self):
        paths = RegressionChecker._candidate_test_paths(
            "core/modules/views/src/ViewExecutable.php"
        )
        assert any("ViewExecutableTest.php" in p for p in paths)
        assert any("core/modules/views/tests" in p for p in paths)

    def test_contrib_module_maps_correctly(self):
        paths = RegressionChecker._candidate_test_paths(
            "modules/contrib/paragraphs/src/Entity/Paragraph.php"
        )
        assert any("ParagraphTest.php" in p for p in paths)

    def test_unknown_path_returns_empty(self):
        paths = RegressionChecker._candidate_test_paths("random/path/File.php")
        assert paths == []


class TestFormatReport:
    def test_pass_report(self):
        results = {
            "health": {"passed": True, "output": ""},
            "phpunit": {"passed": True, "tests_run": 2, "test_results": []},
            "compatibility": {"passed": True, "passes": ["[PASS] layout_builder"], "failures": []},
            "overall_passed": True,
        }
        report = RegressionChecker.format_report(results)
        assert "PASS" in report
        assert "FAIL" not in report.upper().replace("overall_passed", "")

    def test_fail_report_shows_details(self):
        results = {
            "health": {"passed": False, "output": "DB connection refused"},
            "compatibility": {"passed": True, "passes": [], "failures": []},
            "overall_passed": False,
        }
        report = RegressionChecker.format_report(results)
        assert "FAIL" in report
        assert "DB connection refused" in report
