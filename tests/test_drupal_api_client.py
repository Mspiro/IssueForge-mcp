"""Unit tests for DrupalAPIClient.parse_issue_metadata — no network."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from services.drupal_api_client import DrupalAPIClient


class TestParseIssueMetadataBody:
    def test_normal_body_dict_parses_value(self):
        issue_json = {"body": {"value": "<p>Steps to reproduce...</p>"}, "field_issue_files": [], "comments": []}
        result = DrupalAPIClient().parse_issue_metadata(issue_json)
        assert result["problem_description_html"] == "<p>Steps to reproduce...</p>"

    def test_empty_list_body_does_not_crash(self):
        # Regression coverage: api-d7 serializes an EMPTY body field as []
        # rather than {} (a Drupal 7 REST quirk for empty field
        # collections) — terse housekeeping issues with no description at
        # all (e.g. "Fix PHPCS & cspell") hit this, and [].get(...) raised
        # AttributeError, crashing metadata parsing for the whole issue.
        issue_json = {"body": [], "field_issue_files": [], "comments": []}
        result = DrupalAPIClient().parse_issue_metadata(issue_json)
        assert result["problem_description_html"] == ""

    def test_missing_body_key_does_not_crash(self):
        issue_json = {"field_issue_files": [], "comments": []}
        result = DrupalAPIClient().parse_issue_metadata(issue_json)
        assert result["problem_description_html"] == ""

    def test_null_body_does_not_crash(self):
        issue_json = {"body": None, "field_issue_files": [], "comments": []}
        result = DrupalAPIClient().parse_issue_metadata(issue_json)
        assert result["problem_description_html"] == ""
