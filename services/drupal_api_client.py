import requests
import time
import re

from services import gitlab_issue_client


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
        400: "Critical",
        300: "Major",
        200: "Normal",
        100: "Minor",
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
        self._gitlab_raw = {}

    def extract_issue_id(self, issue_url: str):

        match = re.search(r"/(?:issues|node|i)/(\d+)", issue_url)

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

        if str(issue_id) in self._gitlab_raw:
            return self._gitlab_raw[str(issue_id)]

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
                int(issue_json.get("field_issue_priority") or 0),
                issue_json.get("field_issue_priority")
            ),
            "category": self.CATEGORY_MAP.get(
                issue_json.get("field_issue_category"),
                issue_json.get("field_issue_category")
            ),
            # api-d7 serializes an EMPTY body field as [] rather than {} or
            # null (a known Drupal 7 REST quirk for empty field
            # collections) — issues with no description at all (common for
            # terse housekeeping tickets, e.g. "Fix PHPCS & cspell") hit
            # this, and `[].get(...)` raised AttributeError, crashing
            # metadata parsing for that issue entirely.
            "problem_description_html": (
                issue_json.get("body").get("value", "")
                if isinstance(issue_json.get("body"), dict) else ""
            ),
            "patch_file_ids": patch_ids,
            "comment_ids": comment_ids,
            "issue_id": issue_json.get("nid"),
            "issue_url": issue_json.get("url"),
        }

    def _gitlab_metadata(self, project, iid):
        metadata, raw = gitlab_issue_client.get_issue(project, iid)
        self._gitlab_raw[metadata["issue_id"]] = raw
        return metadata

    def get_issue_metadata(self, issue_url: str):

        # Queues moved to GitLab work items (e.g. ai, ai_agents)
        gitlab_ref = gitlab_issue_client.parse_url(issue_url)
        if gitlab_ref:
            return self._gitlab_metadata(*gitlab_ref)

        issue_id = self.extract_issue_id(issue_url)

        issue_json = self.fetch_issue_data(issue_id)

        # Extract project name from URL: e.g. /project/layout_paragraphs/issues/3401176
        url_project = None
        match = re.search(r"/project/([^/]+)", issue_url)
        if match:
            url_project = match.group(1)

        # drupal.org answers {"new_url": ...} for issues migrated to GitLab
        gitlab_ref = gitlab_issue_client.parse_url(issue_json.get("new_url", ""))
        if gitlab_ref:
            return self._gitlab_metadata(*gitlab_ref)

        # New GitLab-only issue IDs can collide with an unrelated drupal.org node
        node_project = (issue_json.get("field_project") or {}).get("machine_name")
        if issue_json.get("type", "project_issue") != "project_issue":
            if url_project:
                return self._gitlab_metadata(url_project, issue_id)
            raise ValueError(
                f"#{issue_id} is not a drupal.org issue. If it is a GitLab work "
                f"item, pass its git.drupalcode.org URL."
            )
        if (url_project and node_project and node_project != url_project
                and gitlab_issue_client.issue_exists(url_project, issue_id)):
            return self._gitlab_metadata(url_project, issue_id)

        metadata = self.parse_issue_metadata(issue_json)
        metadata["project_name"] = url_project or node_project or "drupal"
        metadata["source"] = "drupal.org"
        return metadata