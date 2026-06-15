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
