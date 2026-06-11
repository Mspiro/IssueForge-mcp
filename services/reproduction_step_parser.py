import re


class ReproductionStepParser:
    """
    Extract ordered reproduction steps from issue description HTML.
    """

    LIST_ITEM_PATTERN = re.compile(r"<li>(.*?)</li>", re.DOTALL)

    @staticmethod
    def extract_steps(description_html):

        if not description_html:
            return []

        matches = ReproductionStepParser.LIST_ITEM_PATTERN.findall(
            description_html
        )

        steps = []

        for step in matches:
            cleaned = re.sub(r"<.*?>", "", step).strip()
            if cleaned:
                steps.append(cleaned)

        return steps