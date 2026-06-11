class InstallProfileDetector:
    """
    Detect correct Drupal install profile required for issue reproduction.
    """

    TESTING_KEYWORDS = [
        "kernel test",
        "functional test",
        "browser test",
        "phpunit",
        "test module",
    ]

    MINIMAL_KEYWORDS = [
        "minimal install",
        "clean install",
        "fresh install",
        "no demo content",
    ]

    STANDARD_KEYWORDS = [
        "create content",
        "create view",
        "admin ui",
        "content type",
        "media library",
    ]

    @staticmethod
    def detect(description_sections, required_modules):

        combined_text = " ".join(
            filter(
                None,
                [
                    description_sections.get("problem", ""),
                    description_sections.get("steps", ""),
                    description_sections.get("expected", ""),
                    description_sections.get("actual", ""),
                    description_sections.get("proposed_resolution", ""),
                ],
            )
        ).lower()

        # Rule 1: test modules always imply testing profile
        for module in required_modules:

            if module.endswith("_test"):
                return "testing"

        # Rule 2: explicit testing keywords
        for keyword in InstallProfileDetector.TESTING_KEYWORDS:

            if keyword in combined_text:
                return "testing"

        # Rule 3: minimal install indicators
        for keyword in InstallProfileDetector.MINIMAL_KEYWORDS:

            if keyword in combined_text:
                return "minimal"

        # Rule 4: standard UI workflows
        for keyword in InstallProfileDetector.STANDARD_KEYWORDS:

            if keyword in combined_text:
                return "standard"

        # Default fallback
        return "standard"