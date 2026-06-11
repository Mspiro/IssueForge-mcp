from typing import List, Union


class ReproductionScriptGenerator:
    """
    Generates a runnable shell script skeleton
    from extracted reproduction steps.
    """

    @staticmethod
    def normalize_steps(steps: Union[str, List[str]]) -> List[str]:
        """
        Ensures steps are always returned as a clean list.
        """

        if not steps:
            return []

        # Case 1: already a list
        if isinstance(steps, list):
            return [s.strip() for s in steps if s.strip()]

        # Case 2: string block → split into lines
        if isinstance(steps, str):
            return [
                line.strip()
                for line in steps.split("\n")
                if line.strip()
            ]

        return []

    @staticmethod
    def generate(steps: Union[str, List[str]]) -> str:
        """
        Convert reproduction steps into shell script skeleton.
        """

        normalized_steps = ReproductionScriptGenerator.normalize_steps(steps)

        if not normalized_steps:
            return ""

        script_lines = [
            f"echo 'Manual step: {step}'"
            for step in normalized_steps
        ]

        return "\n".join(script_lines)