"""Unit tests for FixStrategyGenerator."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from classifiers.fix_strategy_generator import FixStrategyGenerator


class TestGenerate:
    def test_matches_on_root_cause_signals(self):
        # generate() is documented as (root_cause_signals, modified_functions).
        # server.py used to call it as (detected_subsystems, root_signals) —
        # subsystem names like "Views" never appear in STRATEGY_RULES, so
        # passing them as the first argument always produced zero matches.
        result = FixStrategyGenerator.generate(
            ["Likely query builder or filter processing bug"], []
        )
        assert result["fix_strategies"] == [
            "Ensure grouped filter selections merge values before query execution."
        ]

    def test_matches_on_modified_functions(self):
        result = FixStrategyGenerator.generate([], ["convertExposedInput"])
        assert result["fix_strategies"] == [
            "Ensure FilterPluginBase::convertExposedInput() aggregates grouped filter inputs correctly."
        ]

    def test_subsystem_names_never_match(self):
        # Guards against the swapped-argument regression: subsystem labels
        # are not valid keys in either rule table, so this must stay empty.
        result = FixStrategyGenerator.generate(["Views", "Plugin system"], [])
        assert result["fix_strategies"] == []

    def test_does_not_return_risk_level(self):
        # Regression guard: server.py used to read strategy_result.get(
        # "risk_level", "medium"), a key generate() never produces, so
        # llm_analysis.risk_level silently defaulted to "medium" for every
        # issue regardless of the actual patch. risk_level is computed by
        # PatchPlanGenerator instead.
        result = FixStrategyGenerator.generate(
            ["Likely query builder or filter processing bug"], ["convertExposedInput"]
        )
        assert "risk_level" not in result
