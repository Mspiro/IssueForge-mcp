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
