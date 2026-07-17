"""Unit tests for CreditTracker — mocked HTTP, no live network calls."""
import os
import sys
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from services.credit_tracker import CreditTracker


def _resp(status_code=200, json_data=None):
    m = MagicMock()
    m.status_code = status_code
    m.json.return_value = json_data or {}
    return m


def _record(node_id):
    return {
        "type": "node--contribution_record",
        "attributes": {
            "title": f"Credit for node {node_id}",
            "field_source_link": {"uri": f"https://www.drupal.org/node/{node_id}"},
        },
    }


class TestFetchCreditedNodeIds:
    def test_empty_username_returns_empty_set(self):
        assert CreditTracker.fetch_credited_node_ids("") == set()

    def test_parses_node_ids_from_source_link(self):
        page = {"data": [_record(2727281), _record(2915538)], "links": {}}
        with patch("requests.get", return_value=_resp(200, page)):
            ids = CreditTracker.fetch_credited_node_ids("sunlix")
        assert ids == {2727281, 2915538}

    def test_pagination_follows_next_link(self):
        page1 = {"data": [_record(1)], "links": {"next": {"href": "..."}}}
        page2 = {"data": [_record(2)], "links": {}}
        with patch("requests.get", side_effect=[_resp(200, page1), _resp(200, page2)]) as get:
            ids = CreditTracker.fetch_credited_node_ids("sunlix")
        assert ids == {1, 2}
        assert get.call_count == 2

    def test_pagination_capped_for_safety(self):
        # Every page claims a "next" link — must not loop forever.
        page = {"data": [_record(1)], "links": {"next": {"href": "..."}}}
        with patch("requests.get", return_value=_resp(200, page)) as get, \
             patch("time.sleep"):
            CreditTracker.fetch_credited_node_ids("sunlix")
        assert get.call_count <= 5

    def test_http_failure_returns_empty_set_not_exception(self):
        with patch("requests.get", return_value=_resp(500)):
            ids = CreditTracker.fetch_credited_node_ids("sunlix")
        assert ids == set()

    def test_network_exception_returns_empty_set_not_raise(self):
        with patch("requests.get", side_effect=ConnectionError("boom")):
            ids = CreditTracker.fetch_credited_node_ids("sunlix")
        assert ids == set()

    def test_malformed_record_missing_source_link_is_skipped(self):
        page = {"data": [{"attributes": {"title": "no link here"}}], "links": {}}
        with patch("requests.get", return_value=_resp(200, page)):
            ids = CreditTracker.fetch_credited_node_ids("sunlix")
        assert ids == set()

    def test_passes_project_and_months_as_query_params(self):
        with patch("requests.get", return_value=_resp(200, {"data": [], "links": {}})) as get:
            CreditTracker.fetch_credited_node_ids("sunlix", project="encrypt", months=6)
        _, kwargs = get.call_args
        assert kwargs["params"]["machine_name"] == "encrypt"
        assert kwargs["params"]["months"] == 6


class TestCheckCredits:
    def test_no_username_returns_empty_dict(self):
        assert CreditTracker.check_credits("", [{"issue_id": "1", "project": "drupal"}]) == {}

    def test_groups_issues_by_project_one_request_chain_each(self):
        issues = [
            {"issue_id": "2727281", "project": "drupal"},
            {"issue_id": "2915538", "project": "encrypt"},
            {"issue_id": "1234", "project": "drupal"},
        ]

        def fake_get(url, params, timeout):
            if params.get("machine_name") == "drupal":
                return _resp(200, {"data": [_record(2727281)], "links": {}})
            return _resp(200, {"data": [], "links": {}})

        with patch("requests.get", side_effect=fake_get):
            result = CreditTracker.check_credits("sunlix", issues)

        assert result == {"2727281": True, "1234": False, "2915538": False}

    def test_issue_id_matching_is_exact_integer_comparison(self):
        # Regression coverage: matching must be a strict node-ID compare, not
        # substring/fuzzy matching (e.g. "272728" must not match "2727281").
        issues = [{"issue_id": "272728", "project": "drupal"}]
        with patch("requests.get", return_value=_resp(200, {"data": [_record(2727281)], "links": {}})):
            result = CreditTracker.check_credits("sunlix", issues)
        assert result == {"272728": False}


class TestFetchAllCreditRecords:
    def test_empty_username_returns_empty(self):
        result = CreditTracker.fetch_all_credit_records("")
        assert result == {"records": [], "truncated": False}

    def test_returns_structured_records_across_all_projects(self):
        page = {
            "data": [{
                "attributes": {
                    "title": "Fix the thing",
                    "field_project_name": "drupal",
                    "field_source_link": {"uri": "https://www.drupal.org/node/2727281"},
                    "created": "2026-07-17T00:00:00",
                },
            }],
            "links": {},
        }
        with patch("requests.get", return_value=_resp(200, page)) as get:
            result = CreditTracker.fetch_all_credit_records("sunlix")
        assert result["truncated"] is False
        assert result["records"] == [{
            "title": "Fix the thing", "project": "drupal", "node_id": 2727281,
            "issue_url": "https://www.drupal.org/node/2727281",
            "created": "2026-07-17T00:00:00",
        }]
        # No machine_name filter — full history spans all projects.
        _, kwargs = get.call_args
        assert "machine_name" not in kwargs["params"]

    def test_truncated_is_exact_not_a_guess(self):
        # Regression coverage: truncation must reflect "the page cap was
        # hit while a next link still existed" exactly — not a heuristic
        # based on an assumed page size (e.g. "count % 50 == 0"), which
        # would misreport whenever the real page size differs.
        full_page = {"data": [_record(1)], "links": {"next": {"href": "..."}}}
        with patch("requests.get", return_value=_resp(200, full_page)), \
             patch("time.sleep"):
            result = CreditTracker.fetch_all_credit_records("sunlix")
        assert result["truncated"] is True

    def test_not_truncated_when_pagination_ends_naturally(self):
        page1 = {"data": [_record(1)], "links": {"next": {"href": "..."}}}
        page2 = {"data": [_record(2)], "links": {}}  # no next — natural end
        with patch("requests.get", side_effect=[_resp(200, page1), _resp(200, page2)]), \
             patch("time.sleep"):
            result = CreditTracker.fetch_all_credit_records("sunlix")
        assert result["truncated"] is False
        assert len(result["records"]) == 2

    def test_network_failure_returns_empty_not_exception(self):
        with patch("requests.get", side_effect=ConnectionError("boom")):
            result = CreditTracker.fetch_all_credit_records("sunlix")
        assert result == {"records": [], "truncated": False}
