import requests
import time
import re


class DrupalAPIClient:
    """
    Client for fetching Drupal.org issue metadata safely with:

    - session reuse
    - exponential backoff
    - caching
    - rate-limit handling
    """

    BASE_URL = "https://www.drupal.org/api-d7"

    STATUS_MAP = {
        1: "Active",
        2: "Fixed",
        3: "Closed (outdated)",
        4: "Postponed",
        5: "Closed (won't fix)",
        6: "Closed (duplicate)",
        7: "Closed (fixed)",
        8: "Needs work",
        13: "Needs review",
        14: "Reviewed & tested by the community",
        15: "Patch (to be ported)",
        16: "Postponed (maintainer needs more info)",
        18: "Closed (cannot reproduce)",
    }

    PRIORITY_MAP = {
        "50": "Critical",
        "100": "Major",
        "150": "Normal",
        "200": "Minor",
    }

    CATEGORY_MAP = {
        "1": "Bug report",
        "2": "Task",
        "3": "Feature request",
        "4": "Support request",
        "5": "Plan",
    }

    def __init__(self):
        self.session = requests.Session()
        self.cache = {}

    def extract_issue_id(self, issue_url: str):

        match = re.search(r"/issues/(\d+)", issue_url)

        if not match:
            raise ValueError("Invalid Drupal issue URL")

        return match.group(1)

    def safe_request(self, url):

        if url in self.cache:
            return self.cache[url]

        retries = 5
        backoff = 1

        for _ in range(retries):

            response = self.session.get(
                url,
                headers={
                    "User-Agent": "IssueForge-MCP-Client"
                }
            )

            if response.status_code == 200:
                data = response.json()
                self.cache[url] = data
                return data

            if response.status_code == 429:
                time.sleep(backoff)
                backoff *= 2
                continue

            raise Exception(
                f"Failed request: {url} (status {response.status_code})"
            )

        raise Exception("Rate limited after multiple retries")

    def fetch_issue_data(self, issue_id):

        url = f"{self.BASE_URL}/node/{issue_id}.json"

        return self.safe_request(url)

    def parse_issue_metadata(self, issue_json):

        patch_ids = []

        for file_entry in issue_json.get("field_issue_files", []):

            file_data = file_entry.get("file")

            if file_data and "id" in file_data:
                patch_ids.append(file_data["id"])

        comment_ids = []

        for comment in issue_json.get("comments", []):
            comment_ids.append(comment["id"])

        return {
            "title": issue_json.get("title"),
            "status": self.STATUS_MAP.get(
                int(issue_json.get("field_issue_status") or 0),
                issue_json.get("field_issue_status")
            ),
            "component": issue_json.get("field_issue_component"),
            "version": issue_json.get("field_issue_version"),
            "priority": self.PRIORITY_MAP.get(
                issue_json.get("field_issue_priority"),
                issue_json.get("field_issue_priority")
            ),
            "category": self.CATEGORY_MAP.get(
                issue_json.get("field_issue_category"),
                issue_json.get("field_issue_category")
            ),
            "problem_description_html": issue_json.get(
                "body", {}
            ).get("value", ""),
            "patch_file_ids": patch_ids,
            "comment_ids": comment_ids,
            "issue_id": issue_json.get("nid"),
            "issue_url": issue_json.get("url"),
        }

    def get_issue_metadata(self, issue_url: str):

        issue_id = self.extract_issue_id(issue_url)

        issue_json = self.fetch_issue_data(issue_id)

        metadata = self.parse_issue_metadata(issue_json)

        # Extract project name from URL: e.g. /project/layout_paragraphs/issues/3401176
        project_name = "drupal"
        match = re.search(r"/project/([^/]+)", issue_url)
        if match:
            project_name = match.group(1)

        metadata["project_name"] = project_name
        return metadata