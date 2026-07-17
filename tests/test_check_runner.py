"""Unit tests for CheckRunner — no live DDEV calls."""
import sys, os
from unittest.mock import patch, MagicMock
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from services.check_runner import CheckRunner


class TestRunPhpunitTest:
    def test_passing_test_has_empty_signature(self):
        with patch("services.check_runner.RegressionChecker.run_phpunit") as mock_run:
            mock_run.return_value = {
                "passed": True,
                "test_results": [{"test_file": "FooTest.php", "passed": True, "output": "OK (3 tests)"}],
            }
            result = CheckRunner.run_phpunit_test("/env", "FooTest.php")
        assert result["passed"] is True
        assert result["signature"] == []

    def test_failing_test_extracts_method_signature(self):
        output = (
            "There were 2 failures:\n\n"
            "1) Drupal\\Tests\\layout_builder\\Functional\\LayoutBuilderTest::testLayoutBuilderUi\n"
            "Some assertion failed.\n\n"
            "2) Drupal\\Tests\\layout_builder\\Functional\\LayoutBuilderTest::testAccess\n"
            "Another assertion failed.\n"
        )
        with patch("services.check_runner.RegressionChecker.run_phpunit") as mock_run:
            mock_run.return_value = {
                "passed": False,
                "test_results": [{"test_file": "LayoutBuilderTest.php", "passed": False, "output": output}],
            }
            result = CheckRunner.run_phpunit_test("/env", "LayoutBuilderTest.php")
        assert result["passed"] is False
        assert result["signature"] == [
            "Drupal\\Tests\\layout_builder\\Functional\\LayoutBuilderTest::testAccess",
            "Drupal\\Tests\\layout_builder\\Functional\\LayoutBuilderTest::testLayoutBuilderUi",
        ]

    def test_same_failure_twice_has_same_signature(self):
        # This is the exact property the bounded retry loop depends on:
        # identical failures across attempts must produce identical
        # signatures so "stuck" can be detected mechanically.
        output = "1) Foo\\BarTest::testBaz\nmessage\n"
        with patch("services.check_runner.RegressionChecker.run_phpunit") as mock_run:
            mock_run.return_value = {
                "passed": False,
                "test_results": [{"test_file": "x", "passed": False, "output": output}],
            }
            r1 = CheckRunner.run_phpunit_test("/env", "x")
            r2 = CheckRunner.run_phpunit_test("/env", "x")
        assert CheckRunner.same_signature(r1, r2)


class TestRunPhpstan:
    def test_skips_when_no_php_files(self, tmp_path):
        result = CheckRunner.run_phpstan(str(tmp_path), ["README.md", "composer.json"])
        assert result["skipped"] is True
        assert result["passed"] is True

    def test_skips_when_no_config_found(self, tmp_path):
        result = CheckRunner.run_phpstan(str(tmp_path), ["core/modules/x/src/Foo.php"])
        assert result["skipped"] is True
        assert result["passed"] is True

    def test_clean_result_passes_with_empty_signature(self, tmp_path):
        (tmp_path / "core").mkdir()
        (tmp_path / "core" / "phpstan.neon.dist").write_text("")

        clean_json = '{"totals":{"errors":0,"file_errors":0},"files":{},"errors":[]}'
        with patch("services.check_runner.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=clean_json, stderr="")
            result = CheckRunner.run_phpstan(str(tmp_path), ["core/modules/x/src/Foo.php"])
        assert result["passed"] is True
        assert result["signature"] == []

    def test_errors_produce_signature(self, tmp_path):
        (tmp_path / "core").mkdir()
        (tmp_path / "core" / "phpstan.neon.dist").write_text("")

        error_json = (
            '{"totals":{"errors":0,"file_errors":1},'
            '"files":{"/var/www/html/core/modules/x/src/Foo.php":'
            '{"errors":1,"messages":[{"message":"Missing return type","line":10}]}},'
            '"errors":[]}'
        )
        with patch("services.check_runner.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stdout=error_json, stderr="")
            result = CheckRunner.run_phpstan(str(tmp_path), ["core/modules/x/src/Foo.php"])
        assert result["passed"] is False
        assert len(result["signature"]) == 1
        assert "Missing return type" in result["signature"][0]

    def test_prefers_contrib_module_config_when_scoped_to_it(self, tmp_path):
        module_dir = tmp_path / "modules" / "contrib" / "paragraphs"
        module_dir.mkdir(parents=True)
        (module_dir / "phpstan.neon").write_text("")
        (tmp_path / "core").mkdir()
        (tmp_path / "core" / "phpstan.neon.dist").write_text("")

        config = CheckRunner._find_phpstan_config(
            str(tmp_path), ["modules/contrib/paragraphs/src/Entity/Paragraph.php"]
        )
        assert config == "modules/contrib/paragraphs/phpstan.neon"


class TestSameSignature:
    def test_different_signatures_not_equal(self):
        a = {"signature": ["A::testX"]}
        b = {"signature": ["A::testY"]}
        assert not CheckRunner.same_signature(a, b)

    def test_missing_signature_defaults_to_empty(self):
        assert CheckRunner.same_signature({}, {})
