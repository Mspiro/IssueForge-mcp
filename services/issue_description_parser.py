import re
from typing import Dict, List


class IssueDescriptionParser:
    """
    Extract structured sections from Drupal issue descriptions.
    """

    @staticmethod
    def strip_html(text: str) -> str:
        return re.sub(r"<.*?>", "", text).strip()

    @staticmethod
    def extract_steps(description_html: str) -> List[str]:
        """
        Extract ordered reproduction steps from the correct section only.
        """

        if not description_html:
            return []

        # Locate the steps section explicitly
        steps_section_match = re.search(
            r"Steps to reproduce.*?<ol>(.*?)</ol>",
            description_html,
            re.DOTALL | re.IGNORECASE,
        )

        if not steps_section_match:
            return []

        ol_block = steps_section_match.group(1)

        raw_steps = re.findall(r"<li>(.*?)</li>", ol_block, re.DOTALL)

        return [
            IssueDescriptionParser.strip_html(step)
            for step in raw_steps
            if step.strip()
        ]

    @staticmethod
    def extract_section(description_html: str, header: str) -> str:
        """
        Extract section text by heading label.
        """

        match = re.search(
            rf"{header}.*?<p>(.*?)</p>",
            description_html,
            re.DOTALL | re.IGNORECASE,
        )

        if not match:
            return ""

        return IssueDescriptionParser.strip_html(match.group(1))

    @staticmethod
    def extract_sections(description_html: str) -> Dict:

        if not description_html:
            return {}

        return {
            "problem": IssueDescriptionParser.extract_section(
                description_html,
                "Problem"
            ),
            "expected": IssueDescriptionParser.extract_section(
                description_html,
                "Expected behaviour"
            ),
            "actual": IssueDescriptionParser.extract_section(
                description_html,
                "Actual behaviour"
            ),
            "proposed_resolution": IssueDescriptionParser.extract_section(
                description_html,
                "Proposed resolution"
            ),
            "steps": IssueDescriptionParser.extract_steps(
                description_html
            ),
        }