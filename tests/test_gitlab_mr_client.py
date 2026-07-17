"""Unit tests for GitlabMrClient — no network calls."""
import pytest
import sys, os
from unittest.mock import patch, MagicMock
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from services.gitlab_mr_client import GitlabMrClient


class TestDetectMrUrlsFromComments:
    def setup_method(self):
        self.client = GitlabMrClient(token="")

    def test_detects_single_mr(self):
        comments = [
            "I opened https://git.drupalcode.org/project/drupal/-/merge_requests/3456 for this."
        ]
        result = self.client.detect_mr_urls_from_comments(comments)
        assert len(result) == 1
        assert result[0]["project"] == "drupal"
        assert result[0]["mr_iid"] == "3456"

    def test_detects_multiple_mrs_across_comments(self):
        comments = [
            "MR: https://git.drupalcode.org/project/drupal/-/merge_requests/100",
            "Another: https://git.drupalcode.org/project/paragraphs/-/merge_requests/200",
        ]
        result = self.client.detect_mr_urls_from_comments(comments)
        assert len(result) == 2
        projects = {r["project"] for r in result}
        assert "drupal" in projects
        assert "paragraphs" in projects

    def test_deduplicates_same_mr(self):
        comments = [
            "See https://git.drupalcode.org/project/drupal/-/merge_requests/99",
            "Related: https://git.drupalcode.org/project/drupal/-/merge_requests/99",
        ]
        result = self.client.detect_mr_urls_from_comments(comments)
        assert len(result) == 1

    def test_ignores_unrelated_urls(self):
        comments = ["See https://drupal.org/node/1234 for more context."]
        result = self.client.detect_mr_urls_from_comments(comments)
        assert result == []

    def test_empty_comments(self):
        assert self.client.detect_mr_urls_from_comments([]) == []

    def test_mr_in_issue_body(self):
        body = "<p>Opened MR: https://git.drupalcode.org/project/drupal/-/merge_requests/777</p>"
        result = self.client.detect_mr_urls_from_issue_body(body)
        assert len(result) == 1
        assert result[0]["mr_iid"] == "777"


class TestDetectMrsForIssue:
    """
    Regression coverage for a real inconsistency: preview_issue.py found
    MR !13200 for issue #3115759 (77 comments) while analyze_issue.py did
    not, because each fetched its own small, differently-windowed comment
    sample. detect_mrs_for_issue() is the single shared path both now use.
    """

    def setup_method(self):
        self.client = GitlabMrClient(token="")

    def _comment_client(self, id_to_body):
        mock = MagicMock()
        mock.get_multiple_comments.side_effect = lambda ids: [
            {"comment_id": i, "body_html": id_to_body[i]} for i in ids if i in id_to_body
        ]
        return mock

    def test_finds_mr_buried_deep_in_a_long_thread(self):
        # Simulate a long thread where the MR link is mentioned partway
        # through — not in the first/middle/last few comments a naive
        # sample would grab, but still within the recent window.
        comment_ids = list(range(1, 78))  # 77 comments, like the real issue
        bodies = {i: f"comment {i}" for i in comment_ids}
        bodies[70] = "Opened https://git.drupalcode.org/project/drupal/-/merge_requests/13200"
        metadata = {"problem_description_html": "", "comment_ids": comment_ids}

        result = self.client.detect_mrs_for_issue(metadata, self._comment_client(bodies))
        assert len(result) == 1
        assert result[0]["mr_iid"] == "13200"

    def test_no_comments_returns_empty(self):
        metadata = {"problem_description_html": "", "comment_ids": []}
        result = self.client.detect_mrs_for_issue(metadata, self._comment_client({}))
        assert result == []

    def test_issue_body_alone_is_still_scanned(self):
        metadata = {
            "problem_description_html": (
                "See https://git.drupalcode.org/project/drupal/-/merge_requests/42"
            ),
            "comment_ids": [],
        }
        result = self.client.detect_mrs_for_issue(metadata, self._comment_client({}))
        assert result[0]["mr_iid"] == "42"

    def test_dedupes_across_body_and_comments(self):
        comment_ids = [1, 2]
        bodies = {
            1: "https://git.drupalcode.org/project/drupal/-/merge_requests/5",
            2: "no mr here",
        }
        metadata = {
            "problem_description_html": (
                "https://git.drupalcode.org/project/drupal/-/merge_requests/5"
            ),
            "comment_ids": comment_ids,
        }
        result = self.client.detect_mrs_for_issue(metadata, self._comment_client(bodies))
        assert len(result) == 1


class TestGetMrDetails:
    def test_returns_none_without_token(self):
        client = GitlabMrClient(token="")
        # Without token, the API call should not be made or should return None gracefully
        with patch.object(client, "_safe_get", return_value=None):
            result = client.get_mr_details("drupal", "123")
            assert result is None

    def test_parses_api_response(self):
        client = GitlabMrClient(token="fake-token")
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "iid": 123,
            "title": "Fix EntityAutocomplete validation",
            "state": "opened",
            "source_branch": "2692289-fix-autocomplete",
            "target_branch": "11.x",
            "description": "Fixes #2692289",
            "author": {"name": "Contributor"},
            "web_url": "https://git.drupalcode.org/project/drupal/-/merge_requests/123",
            "created_at": "2024-01-01T00:00:00Z",
            "updated_at": "2024-01-02T00:00:00Z",
        }
        with patch.object(client, "_safe_get", return_value=mock_resp):
            result = client.get_mr_details("drupal", "123")
        assert result["title"] == "Fix EntityAutocomplete validation"
        assert result["state"] == "opened"
        assert result["source_branch"] == "2692289-fix-autocomplete"
        assert result["project"] == "drupal"
        assert result["mr_iid"] == "123"


class TestDownloadMrDiff:
    def test_saves_diff_to_file(self, tmp_path):
        client = GitlabMrClient(token="")
        diff_content = b"diff --git a/core/a.php b/core/a.php\n+fix"
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = diff_content

        output_path = str(tmp_path / "mr_drupal_123.patch")
        with patch.object(client.session, "get", return_value=mock_resp):
            result = client.download_mr_diff("drupal", "123", output_path)

        assert result == output_path
        with open(output_path, "rb") as f:
            assert f.read() == diff_content

    def test_returns_none_on_404(self, tmp_path):
        client = GitlabMrClient(token="")
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_resp.content = b""

        output_path = str(tmp_path / "mr_drupal_999.patch")
        with patch.object(client.session, "get", return_value=mock_resp):
            result = client.download_mr_diff("drupal", "999", output_path)
        assert result is None
