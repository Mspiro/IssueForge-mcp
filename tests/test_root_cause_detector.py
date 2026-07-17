"""Unit tests for RootCauseDetector."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from classifiers.root_cause_detector import RootCauseDetector


class TestDetect:
    def test_no_signals_is_low_confidence(self):
        result = RootCauseDetector.detect([], [])
        assert result["root_cause_signals"] == []
        assert result["confidence"] == "low"

    def test_subsystem_only_match_is_low_confidence(self):
        # Regression coverage: a subsystem hint fires whenever a modified file
        # merely lives under a module directory whose name matches a keyword
        # (e.g. any file under core/modules/views/, including a renamed CSS
        # asset, matches "Views") — that's not evidence of *why* the bug
        # exists, so it must not be reported with the same confidence as an
        # actual function-level match. Previously this returned "medium".
        result = RootCauseDetector.detect([], ["Views"])
        assert result["root_cause_signals"] == ["Likely query builder or filter processing bug"]
        assert result["confidence"] == "low"

    def test_function_match_is_medium_confidence(self):
        result = RootCauseDetector.detect(["convertExposedInput"], [])
        assert result["confidence"] == "medium"

    def test_function_and_subsystem_match_is_medium_confidence(self):
        result = RootCauseDetector.detect(["convertExposedInput"], ["Views"])
        assert result["confidence"] == "medium"
        assert set(result["root_cause_signals"]) == {
            "Filter value normalization issue",
            "Likely query builder or filter processing bug",
        }
