import requests
from typing import List, Dict, Any


DRUPAL_COMMENT_API = "https://www.drupal.org/api-d7/comment"


class DrupalCommentClient:
    """
    Client for fetching Drupal.org issue comment data.
    Handles inconsistent Drupal API response structures.
    """

    @staticmethod
    def fetch_comment(comment_id: int) -> Dict:
        url = f"{DRUPAL_COMMENT_API}/{comment_id}.json"

        response = requests.get(url)

        if response.status_code != 200:
            raise Exception(
                f"Failed to fetch comment {comment_id}. Status code: {response.status_code}"
            )

        data = response.json()

        # Sometimes API returns list instead of dict
        if isinstance(data, list):
            if not data:
                raise Exception(f"Empty response for comment {comment_id}")
            data = data[0]

        return data

    @staticmethod
    def extract_author_id(author_field: Any):
        """
        Normalize author field (dict OR list)
        """
        if isinstance(author_field, dict):
            return author_field.get("id")

        if isinstance(author_field, list) and author_field:
            return author_field[0].get("id")

        return None

    @staticmethod
    def extract_body_html(body_field: Any):
        """
        Normalize comment_body field (dict OR list)
        """
        if isinstance(body_field, dict):
            return body_field.get("value", "")

        if isinstance(body_field, list) and body_field:
            return body_field[0].get("value", "")

        return ""

    @staticmethod
    def parse_comment(comment_json: Dict) -> Dict:
        author_id = DrupalCommentClient.extract_author_id(
            comment_json.get("author")
        )

        body_html = DrupalCommentClient.extract_body_html(
            comment_json.get("comment_body")
        )

        return {
            "comment_id": comment_json.get("cid"),
            "author_id": author_id,
            "created": comment_json.get("created"),
            "body_html": body_html,
        }

    def get_comment(self, comment_id: int) -> Dict:
        raw_comment = self.fetch_comment(comment_id)

        return self.parse_comment(raw_comment)

    def get_multiple_comments(self, comment_ids: List[int]) -> List[Dict]:
        comments = []

        for cid in comment_ids:
            try:
                comments.append(self.get_comment(cid))
            except Exception as e:
                print(f"Skipping comment {cid}: {e}")

        return comments