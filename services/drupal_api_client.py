import re
import requests


DRUPAL_API_BASE = "https://www.drupal.org/api-d7/node"


ISSUE_STATUS_MAP = {
    "1": "Active",
    "2": "Needs work",
    "3": "Needs review",
    "4": "Reviewed & tested by the community",
    "5": "Patch needs improvement",
    "6": "Postponed",
    "7": "Closed (fixed)",
    "8": "Closed (duplicate)",
    "9": "Closed (won’t fix)",
    "10": "Closed (works as designed)",
    "11": "Closed (cannot reproduce)",
    "12": "Closed (outdated)",
    "13": "Active",
}


ISSUE_PRIORITY_MAP = {
    "400": "Critical",
    "300": "Major",
    "200": "Normal",
    "100": "Minor",
}


ISSUE_CATEGORY_MAP = {
    "1": "Bug report",
    "2": "Feature request",
    "3": "Support request",
    "4": "Task",
    "5": "Plan",
}


class DrupalAPIClient:
    """
    Client for interacting with Drupal.org issue JSON endpoints.
    """

    @staticmethod
    def extract_issue_id(issue_url: str) -> str:
        match = re.search(r'/issues/(\d+)', issue_url)

        if not match:
            raise ValueError("Invalid Drupal issue URL format.")

        return match.group(1)

    @staticmethod
    def fetch_issue_data(issue_id: str) -> dict:
        url = f"{DRUPAL_API_BASE}/{issue_id}.json"

        response = requests.get(url)

        if response.status_code != 200:
            raise Exception(
                f"Failed to fetch issue data. Status code: {response.status_code}"
            )

        return response.json()

    @staticmethod
    def parse_issue_metadata(issue_json: dict) -> dict:
        """
        Extract structured metadata from Drupal issue JSON.
        """

        body_html = issue_json.get("body", {}).get("value", "")

        return {
            "title": issue_json.get("title"),

            "status": ISSUE_STATUS_MAP.get(
                issue_json.get("field_issue_status"),
                issue_json.get("field_issue_status")
            ),

            "component": issue_json.get("field_issue_component"),

            "version": issue_json.get("field_issue_version"),

            "priority": ISSUE_PRIORITY_MAP.get(
                issue_json.get("field_issue_priority"),
                issue_json.get("field_issue_priority")
            ),

            "category": ISSUE_CATEGORY_MAP.get(
                issue_json.get("field_issue_category"),
                issue_json.get("field_issue_category")
            ),

            "problem_description_html": body_html,

            "patch_file_ids": [
                f["file"]["id"]
                for f in issue_json.get("field_issue_files", [])
            ],

            "comment_ids": [
                c["id"]
                for c in issue_json.get("comments", [])
            ],
        }

    def get_issue_metadata(self, issue_url: str) -> dict:
        issue_id = self.extract_issue_id(issue_url)

        issue_json = self.fetch_issue_data(issue_id)

        metadata = self.parse_issue_metadata(issue_json)

        metadata["issue_id"] = issue_id
        metadata["issue_url"] = issue_url

        return metadata