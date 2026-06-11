from typing import Dict, List
from services.text_normalizer import TextNormalizer


class TestModuleDetector:
    """
    Detect testing-related module dependencies mentioned
    inside issue metadata and descriptions.
    """

    @staticmethod
    def detect(metadata: Dict) -> List[str]:

        searchable_fields = [
            metadata.get("title"),
            metadata.get("component"),
            metadata.get("problem_description_html"),
            metadata.get("version"),
            metadata.get("tags"),
        ]

        combined_text = TextNormalizer.flatten(
            searchable_fields
        ).lower()

        known_test_modules = [
            "simpletest",
            "phpunit",
            "kerneltestbase",
            "browser_test_base",
            "functionaljavascript",
        ]

        return [
            module
            for module in known_test_modules
            if module in combined_text
        ]