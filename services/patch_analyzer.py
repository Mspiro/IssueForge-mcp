import re
from typing import List, Dict


class PatchAnalyzer:
    """
    Analyze patch (.diff / .patch) files and extract affected files
    and modified function names.
    """

    @staticmethod
    def extract_modified_files(patch_content: str) -> List[str]:
        pattern = r"\+\+\+\s+b/(.*)"
        matches = re.findall(pattern, patch_content)
        return list(set(matches))

    @staticmethod
    def extract_modified_functions(patch_content: str) -> List[str]:
        """
        Extract modified PHP function names from patch content.
        Looks for diff hunk headers like:

        @@ ... function functionName(...)
        """

        function_pattern = r"function\s+([a-zA-Z0-9_]+)\s*\("

        matches = re.findall(function_pattern, patch_content)

        return list(set(matches))

    @staticmethod
    def extract_modified_methods(patch_content: str) -> List[str]:
        """
        Extract class method references from patch hunk context lines.
        Useful for detecting ClassName::methodName references.
        """

        method_pattern = r"([A-Za-z0-9_]+)::([A-Za-z0-9_]+)"

        matches = re.findall(method_pattern, patch_content)

        formatted = [
            f"{class_name}::{method}"
            for class_name, method in matches
        ]

        return list(set(formatted))

    @staticmethod
    def extract_patch_summary(patch_content: str) -> Dict:
        modified_files = PatchAnalyzer.extract_modified_files(
            patch_content
        )

        modified_functions = PatchAnalyzer.extract_modified_functions(
            patch_content
        )

        modified_methods = PatchAnalyzer.extract_modified_methods(
            patch_content
        )

        return {
            "modified_files": modified_files,
            "modified_functions": modified_functions,
            "modified_methods": modified_methods,
            "file_count": len(modified_files),
        }

    @staticmethod
    def analyze_patch_file(patch_path: str) -> Dict:
        with open(patch_path, "r", encoding="utf-8") as f:
            content = f.read()

        return PatchAnalyzer.extract_patch_summary(content)
