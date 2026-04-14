import re
from typing import Dict

import re


def strip_html_tags(text):
    clean = re.sub(r"<.*?>", "", text)
    return clean.strip()


class IssueDescriptionParser:
    """
    Extract structured sections from Drupal issue HTML description.
    """

    SECTION_PATTERNS = {
        "problem": r"Problem/Motivation</h3>\s*(.*?)<h",
        "steps": r"Steps to reproduce</h4>\s*(.*?)<h",
        "expected": r"Expected behaviour:</h5>\s*(.*?)<h",
        "actual": r"Actual behaviour:</h5>\s*(.*?)<h",
        "proposed_resolution": r"Proposed resolution</h3>\s*(.*?)<h",
    }

    @staticmethod
    def extract_sections(html: str) -> Dict:

        extracted = {}

        for section, pattern in IssueDescriptionParser.SECTION_PATTERNS.items():

            match = re.search(pattern, html, re.DOTALL | re.IGNORECASE)

            if match:
                extracted[section] = strip_html_tags(match.group(1))
            else:
                extracted[section] = ""

        return extracted
