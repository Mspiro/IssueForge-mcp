from typing import List, Dict


class FixStrategyGenerator:
    """
    Generate fix strategies based on detected root-cause signals
    and modified functions.
    """

    STRATEGY_RULES = {
        "Filter value normalization issue":
            "Normalize exposed filter values before query conditions are constructed.",

        "Query construction pipeline issue":
            "Adjust WHERE condition aggregation logic to prevent incorrect AND chaining.",

        "Likely query builder or filter processing bug":
            "Ensure grouped filter selections merge values before query execution.",

        "Plugin definition or runtime execution issue":
            "Verify plugin lifecycle handling and exposed filter processing order.",
    }

    FUNCTION_STRATEGIES = {
        "_build":
            "Review ViewExecutable::_build() query assembly loop for condition merging issues.",

        "convertExposedInput":
            "Ensure FilterPluginBase::convertExposedInput() aggregates grouped filter inputs correctly.",
    }

    @staticmethod
    def generate_from_signals(signals: List[str]) -> List[str]:

        strategies = []

        for signal in signals:
            if signal in FixStrategyGenerator.STRATEGY_RULES:
                strategies.append(
                    FixStrategyGenerator.STRATEGY_RULES[signal]
                )

        return strategies

    @staticmethod
    def generate_from_functions(functions: List[str]) -> List[str]:

        strategies = []

        for fn in functions:
            if fn in FixStrategyGenerator.FUNCTION_STRATEGIES:
                strategies.append(
                    FixStrategyGenerator.FUNCTION_STRATEGIES[fn]
                )

        return strategies

    @staticmethod
    def generate(signals: List[str], functions: List[str]) -> Dict:

        signal_strategies = FixStrategyGenerator.generate_from_signals(signals)

        function_strategies = FixStrategyGenerator.generate_from_functions(functions)

        combined = list(set(signal_strategies + function_strategies))

        return {
            "fix_strategies": combined,
            "confidence": "medium" if combined else "low"
        }