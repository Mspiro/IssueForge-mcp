import requests
import time


class DrupalCommentClient:
    """
    Safe Drupal.org comment fetcher with:

    - retry
    - exponential backoff
    - caching
    - session reuse
    - robust body parsing (dict OR list)
    """

    BASE_URL = "https://www.drupal.org/api-d7/comment"

    def __init__(self):
        self.session = requests.Session()
        self.cache = {}

    def safe_request(self, url):

        if url in self.cache:
            return self.cache[url]

        retries = 5
        backoff = 1

        for _ in range(retries):

            response = self.session.get(
                url,
                headers={"User-Agent": "IssueForge-MCP-Client"}
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
                f"Failed to fetch comment {url}. "
                f"Status code: {response.status_code}"
            )

        raise Exception("Rate limited after multiple retries")

    def extract_body(self, comment_json):
        """
        Handles inconsistent Drupal API formats:
        comment_body may be dict OR list.
        """

        body = comment_json.get("comment_body", "")

        if isinstance(body, dict):
            return body.get("value", "")

        if isinstance(body, list) and len(body) > 0:
            first = body[0]
            if isinstance(first, dict):
                return first.get("value", "")

        return ""

    def get_comment(self, comment_id):

        url = f"{self.BASE_URL}/{comment_id}.json"

        try:
            comment_json = self.safe_request(url)
            author = comment_json.get("author") or {}

            return {
                "comment_id": comment_json.get("cid"),
                "author_id": author.get("id", ""),
                # The comment resource's top-level "name" is the author's
                # username directly — no separate user-lookup call needed.
                "author_name": comment_json.get("name", ""),
                "created": comment_json.get("created"),
                "body_html": self.extract_body(comment_json),
            }

        except Exception as e:

            print(f"Skipping comment {comment_id}: {e}")

            return None

    def get_multiple_comments(self, comment_ids):

        results = []

        for cid in comment_ids:

            comment = self.get_comment(cid)

            if comment:
                results.append(comment)

        return results