from typing import Dict, List


class PatchPlanGenerator:
    """
    Generate structured patch-edit plan from reasoning signals.
    """

    FUNCTION_STRATEGY_MAP = {
        "_build":
            "Refactor query condition assembly loop to merge grouped filter values before WHERE clause construction.",

        "convertExposedInput":
            "Normalize exposed grouped filter inputs into a single merged condition set.",

        "exposedInfo":
            "Verify exposed filter metadata propagation does not duplicate conditions."
    }

    SUBSYSTEM_TEST_HINTS = {
        "Views":
            "Ensure exposed filter combinations return OR-matched results across grouped selections.",

        "Plugin system":
            "Verify plugin lifecycle execution order preserves merged filter input integrity."
    }

    @staticmethod
    def build_plan(
        modified_files: List[str],
        modified_functions: List[str],
        detected_subsystems: List[str],
        root_cause_signals: List[str]
    ) -> Dict:

        edit_strategy = []

        for fn in modified_functions:
            if fn in PatchPlanGenerator.FUNCTION_STRATEGY_MAP:
                edit_strategy.append(
                    PatchPlanGenerator.FUNCTION_STRATEGY_MAP[fn]
                )

        test_expectations = []

        for subsystem in detected_subsystems:
            if subsystem in PatchPlanGenerator.SUBSYSTEM_TEST_HINTS:
                test_expectations.append(
                    PatchPlanGenerator.SUBSYSTEM_TEST_HINTS[subsystem]
                )

        risk_level = "medium"

        if "Query construction pipeline issue" in root_cause_signals:
            risk_level = "high"

        return {
            "target_files": modified_files,
            "target_functions": modified_functions,
            "edit_strategy": edit_strategy,
            "risk_level": risk_level,
            "test_expectations": test_expectations,
        }