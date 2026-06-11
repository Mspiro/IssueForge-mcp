from typing import Dict, List
from services.text_normalizer import TextNormalizer


class ThemeRequirementDetector:
    """
    Detect required themes based on metadata and modified files.
    """

    KNOWN_THEMES = [
        "claro",
        "olivero",
        "stark",
    ]

    KNOWN_CONTRIB_THEMES = [
        "gin",
        "bootstrap",
        "zen",
        "omega",
        "radix",
        "bootstrap_barrio",
        "adaptivetheme",
        "adminimal_theme",
    ]

    @staticmethod
    def is_contrib(theme_name: str) -> bool:
        return theme_name.lower() not in ThemeRequirementDetector.KNOWN_THEMES

    @staticmethod
    def detect(metadata: Dict, modified_files: List[str]) -> List[str]:
        """
        Detect theme dependencies from issue metadata and file paths.
        """
        import re

        searchable_fields = [
            metadata.get("title"),
            metadata.get("component"),
            metadata.get("problem_description_html"),
            metadata.get("tags"),
        ]

        combined_text = TextNormalizer.flatten(
            searchable_fields
        ).lower()

        detected = set()

        # Detect from metadata text (core + contrib) using whole word boundaries
        all_known = ThemeRequirementDetector.KNOWN_THEMES + ThemeRequirementDetector.KNOWN_CONTRIB_THEMES
        for theme in all_known:
            if re.search(r"\b" + re.escape(theme) + r"\b", combined_text):
                detected.add(theme)

        # Detect from modified file paths using regex
        for path in modified_files:
            # Check core themes
            core_match = re.search(r"core/themes/([^/]+)", path)
            if core_match:
                detected.add(core_match.group(1))
            else:
                # Check contrib/custom themes
                contrib_match = re.search(r"themes/(?:contrib/|custom/)?([^/]+)", path)
                if contrib_match and "themes/" in path:
                    theme_candidate = contrib_match.group(1)
                    if theme_candidate not in ["contrib", "custom"]:
                        detected.add(theme_candidate)

        # Filter out stable/stable9/seven/bartik as they cannot be enabled directly or are removed in D11
        invalid_themes = {"stable", "stable9", "seven", "bartik"}
        detected = {t for t in detected if t not in invalid_themes}

        return sorted(list(detected))