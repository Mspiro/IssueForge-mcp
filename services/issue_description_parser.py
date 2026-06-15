import re
from typing import Dict, List


class IssueDescriptionParser:
    """
    Extract structured sections from Drupal issue descriptions.
    """

    @staticmethod
    def strip_html(text: str) -> str:
        if not text:
            return ""
        # Replace common tags with clean spaces/newlines, then strip HTML
        text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
        text = re.sub(r"</p>", "\n", text, flags=re.IGNORECASE)
        cleaned = re.sub(r"<.*?>", "", text)
        # Decode common HTML entities
        cleaned = (
            cleaned.replace("&amp;", "&")
            .replace("&lt;", "<")
            .replace("&gt;", ">")
            .replace("&quot;", '"')
        )
        return "\n".join(
            [line.strip() for line in cleaned.split("\n") if line.strip()]
        )

    @staticmethod
    def _segment_html(description_html: str) -> Dict[str, str]:
        if not description_html:
            return {}

        # Identify headings: <h1-6>...</h1-6> or <p><strong>...</strong></p>
        heading_patterns = [
            (r"<h([1-6])[^>]*>(.*?)</h\1>", True),
            (r"<p>\s*<strong>(.*?)</strong>\s*</p>", False),
            (r"<p>\s*<b>(.*?)</b>\s*</p>", False),
        ]

        found_headings = []
        for pattern, is_hx in heading_patterns:
            for match in re.finditer(
                pattern, description_html, re.DOTALL | re.IGNORECASE
            ):
                group_idx = 2 if is_hx else 1
                title = re.sub(r"<.*?>", "", match.group(group_idx)).strip().lower()
                found_headings.append({
                    "start": match.start(),
                    "end": match.end(),
                    "title": title
                })

        # Sort headings by start position
        found_headings.sort(key=lambda x: x["start"])

        # Map headings to our standard section keys
        section_mapping = {
            "problem": "problem",
            "motivation": "problem",
            "problem/motivation": "problem",
            "steps to reproduce": "steps",
            "steps": "steps",
            "proposed resolution": "proposed_resolution",
            "expected behaviour": "expected",
            "expected behavior": "expected",
            "expected": "expected",
            "actual behaviour": "actual",
            "actual behavior": "actual",
            "actual": "actual",
            "remaining tasks": "remaining_tasks",
        }

        sections = {}
        # If there is content before the first heading, assign it to "intro"
        if found_headings and found_headings[0]["start"] > 0:
            intro_content = description_html[:found_headings[0]["start"]].strip()
            if intro_content:
                sections["intro"] = intro_content

        for i, heading in enumerate(found_headings):
            start_pos = heading["end"]
            end_pos = (
                found_headings[i+1]["start"]
                if i + 1 < len(found_headings)
                else len(description_html)
            )
            content = description_html[start_pos:end_pos].strip()

            matched_key = None
            for key, val in section_mapping.items():
                if key in heading["title"]:
                    matched_key = val
                    break

            if matched_key:
                if matched_key in sections:
                    sections[matched_key] += "\n" + content
                else:
                    sections[matched_key] = content
            else:
                clean_title = re.sub(r"\s+", "_", heading["title"])
                sections[clean_title] = content

        return sections

    @staticmethod
    def _extract_steps_from_section(section_html: str) -> List[str]:
        if not section_html:
            return []

        # Case 1: contains ol or ul
        if "<ol" in section_html or "<ul" in section_html:
            li_items = re.findall(
                r"<li>(.*?)</li>", section_html, re.DOTALL | re.IGNORECASE
            )
            steps = [
                IssueDescriptionParser.strip_html(li)
                for li in li_items
                if li.strip()
            ]
            if steps:
                return steps

        # Case 2: contains <p> or <br> and no ol/ul
        section_html = re.sub(r"</p>", "\n</p>", section_html, flags=re.IGNORECASE)
        section_html = re.sub(r"<br\s*/?>", "\n", section_html, flags=re.IGNORECASE)
        text_lines = re.sub(r"<.*?>", "", section_html)

        raw_lines = text_lines.split("\n")
        steps = []
        for line in raw_lines:
            line_str = line.strip()
            if not line_str:
                continue
            # Exclude obvious error traces/exceptions from the reproduction steps
            if (
                line_str.lower().startswith("system generates the following error")
                or "error:" in line_str.lower()
                or "exception:" in line_str.lower()
            ):
                break
            # Also exclude common prefix markers like "1. ", "- "
            line_str = re.sub(r"^\d+[\s\.)\-]+", "", line_str)
            line_str = re.sub(r"^[\-\*\+]\s+", "", line_str)
            if line_str:
                steps.append(line_str)

        return steps

    @staticmethod
    def extract_sections(description_html: str) -> Dict:
        if not description_html:
            return {}

        sections = IssueDescriptionParser._segment_html(description_html)

        problem_html = sections.get("problem", sections.get("intro", ""))
        proposed_resolution_html = sections.get("proposed_resolution", "")
        steps_html = sections.get("steps", "")
        expected_html = sections.get("expected", "")
        actual_html = sections.get("actual", "")

        return {
            "problem": IssueDescriptionParser.strip_html(problem_html),
            "expected": IssueDescriptionParser.strip_html(expected_html),
            "actual": IssueDescriptionParser.strip_html(actual_html),
            "proposed_resolution": IssueDescriptionParser.strip_html(
                proposed_resolution_html
            ),
            "steps": IssueDescriptionParser._extract_steps_from_section(
                steps_html
            ),
        }