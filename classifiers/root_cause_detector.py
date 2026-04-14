from typing import Dict, List


class RootCauseDetector:
    """
    Detect likely root-cause strategy based on subsystem
    and modified function names.
    """

    FUNCTION_PATTERNS = {
        "convertExposedInput": "Filter value normalization issue",
        "_build": "Query construction pipeline issue",
        "buildForm": "Form API processing issue",
        "submitForm": "Form submission handling issue",
        "access": "Access control logic issue",
        "save": "Entity persistence issue",
        "load": "Entity loading issue",
        "render": "Render pipeline issue",
    }

    SUBSYSTEM_HINTS = {
        "Views": "Likely query builder or filter processing bug",
        "Plugin system": "Plugin definition or runtime execution issue",
        "Entity API": "Entity storage or schema issue",
        "Routing": "Route definition or cache invalidation issue",
        "Form API": "Form state or validation issue",
    }

    @staticmethod
    def detect_from_functions(functions: List[str]) -> List[str]:
        detected = []

        for fn in functions:
            if fn in RootCauseDetector.FUNCTION_PATTERNS:
                detected.append(
                    RootCauseDetector.FUNCTION_PATTERNS[fn]
                )

        return detected

    @staticmethod
    def detect_from_subsystems(subsystems: List[str]) -> List[str]:
        detected = []

        for subsystem in subsystems:
            if subsystem in RootCauseDetector.SUBSYSTEM_HINTS:
                detected.append(
                    RootCauseDetector.SUBSYSTEM_HINTS[subsystem]
                )

        return detected

    @staticmethod
    def detect(functions: List[str], subsystems: List[str]) -> Dict:

        function_signals = RootCauseDetector.detect_from_functions(functions)

        subsystem_signals = RootCauseDetector.detect_from_subsystems(subsystems)

        combined = list(set(function_signals + subsystem_signals))

        return {
            "root_cause_signals": combined,
            "confidence": "medium" if combined else "low"
        }