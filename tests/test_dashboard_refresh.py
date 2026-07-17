"""Unit tests for dashboard_refresh — mocked API clients, no network."""
import os
import sys
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from services.dashboard_refresh import (
    compute_lifetime_stats, import_credit_history, refresh_all,
)
from services.dashboard_ledger import DashboardLedger


class TestRefreshAll:
    def _ledger(self, issues):
        return {"issues": issues, "generated_at": None}

    def test_no_issues_short_circuits(self):
        messages = []
        with patch("services.dashboard_refresh.DashboardLedger.load",
                   return_value=self._ledger([])):
            result = refresh_all(progress=messages.append)
        assert result["issues"] == []
        assert any("nothing to refresh" in m for m in messages)

    def test_updates_status_and_comment_delta(self):
        entry = {
            "issue_id": "1", "project": "drupal", "issue_url": "https://x",
            "mr": {"project": "", "iid": ""},
            "status": {"value": None, "checked_at": None},
            "comments": {"count_at_last_check": 3, "checked_at": None},
            "credit": {"credited": False, "checked_at": None},
        }
        ledger = self._ledger([entry])

        with patch("services.dashboard_refresh.DashboardLedger.load", return_value=ledger), \
             patch("services.dashboard_refresh.DashboardLedger.save"), \
             patch("services.dashboard_refresh.get_credentials",
                   return_value={"gitlab_token": "", "drupal_username": ""}), \
             patch("services.dashboard_refresh.DrupalAPIClient") as api_cls:
            api_cls.return_value.get_issue_metadata.return_value = {
                "status": "Needs review", "comment_ids": list(range(7)),
            }
            result = refresh_all()

        updated = result["issues"][0]
        assert updated["status"]["value"] == "Needs review"
        assert updated["comments"]["count_at_last_check"] == 7
        assert updated["comments"]["new_since_last_check"] == 4

    def test_mr_pipeline_uses_source_project_id_not_target(self):
        entry = {
            "issue_id": "2727281", "project": "drupal", "issue_url": "https://x",
            "mr": {"project": "drupal", "iid": "12139"},
            "status": {"value": None, "checked_at": None},
            "comments": {"count_at_last_check": None, "checked_at": None},
            "credit": {"credited": False, "checked_at": None},
        }
        ledger = self._ledger([entry])

        with patch("services.dashboard_refresh.DashboardLedger.load", return_value=ledger), \
             patch("services.dashboard_refresh.DashboardLedger.save"), \
             patch("services.dashboard_refresh.get_credentials",
                   return_value={"gitlab_token": "tok", "drupal_username": ""}), \
             patch("services.dashboard_refresh.DrupalAPIClient") as api_cls, \
             patch("services.dashboard_refresh.GitlabMrClient") as mr_cls:
            api_cls.return_value.get_issue_metadata.return_value = {"status": "Needs review", "comment_ids": []}
            mr_cls.return_value.get_mr_details.return_value = {
                "state": "opened", "source_branch": "some-branch", "source_project_id": 4218,
            }
            mr_cls.return_value.get_latest_pipeline_status.return_value = {
                "status": "success", "web_url": "https://x",
            }
            result = refresh_all()

        mr_cls.return_value.get_latest_pipeline_status.assert_called_once_with(4218, "some-branch")
        assert result["issues"][0]["mr"]["pipeline_status"] == "success"

    def test_no_source_project_id_skips_pipeline_lookup(self):
        # Without source_project_id we can't reliably guess the fork's
        # project — must skip rather than call with a wrong value.
        entry = {
            "issue_id": "1", "project": "drupal", "issue_url": "https://x",
            "mr": {"project": "drupal", "iid": "1"},
            "status": {"value": None, "checked_at": None},
            "comments": {"count_at_last_check": None, "checked_at": None},
            "credit": {"credited": False, "checked_at": None},
        }
        ledger = self._ledger([entry])
        with patch("services.dashboard_refresh.DashboardLedger.load", return_value=ledger), \
             patch("services.dashboard_refresh.DashboardLedger.save"), \
             patch("services.dashboard_refresh.get_credentials",
                   return_value={"gitlab_token": "tok", "drupal_username": ""}), \
             patch("services.dashboard_refresh.DrupalAPIClient") as api_cls, \
             patch("services.dashboard_refresh.GitlabMrClient") as mr_cls:
            api_cls.return_value.get_issue_metadata.return_value = {"status": "x", "comment_ids": []}
            mr_cls.return_value.get_mr_details.return_value = {
                "state": "opened", "source_branch": "b", "source_project_id": None,
            }
            refresh_all()
        mr_cls.return_value.get_latest_pipeline_status.assert_not_called()

    def test_credit_check_skipped_without_username(self):
        entry = {
            "issue_id": "1", "project": "drupal", "issue_url": "https://x",
            "mr": {"project": "", "iid": ""},
            "status": {"value": None, "checked_at": None},
            "comments": {"count_at_last_check": None, "checked_at": None},
            "credit": {"credited": False, "checked_at": None},
        }
        ledger = self._ledger([entry])
        messages = []
        with patch("services.dashboard_refresh.DashboardLedger.load", return_value=ledger), \
             patch("services.dashboard_refresh.DashboardLedger.save"), \
             patch("services.dashboard_refresh.get_credentials",
                   return_value={"gitlab_token": "", "drupal_username": ""}), \
             patch("services.dashboard_refresh.DrupalAPIClient") as api_cls, \
             patch("services.dashboard_refresh.CreditTracker.check_credits") as check_credits:
            api_cls.return_value.get_issue_metadata.return_value = {"status": "x", "comment_ids": []}
            refresh_all(progress=messages.append)
        check_credits.assert_not_called()
        assert any("skipping credit check" in m for m in messages)

    def test_issue_metadata_failure_does_not_crash_whole_refresh(self):
        entry = {
            "issue_id": "1", "project": "drupal", "issue_url": "https://x",
            "mr": {"project": "", "iid": ""},
            "status": {"value": None, "checked_at": None},
            "comments": {"count_at_last_check": None, "checked_at": None},
            "credit": {"credited": False, "checked_at": None},
        }
        ledger = self._ledger([entry])
        with patch("services.dashboard_refresh.DashboardLedger.load", return_value=ledger), \
             patch("services.dashboard_refresh.DashboardLedger.save"), \
             patch("services.dashboard_refresh.get_credentials",
                   return_value={"gitlab_token": "", "drupal_username": ""}), \
             patch("services.dashboard_refresh.DrupalAPIClient") as api_cls:
            api_cls.return_value.get_issue_metadata.side_effect = ConnectionError("down")
            result = refresh_all()  # must not raise
        assert result["issues"][0]["status"]["value"] is None


class TestImportCreditHistory:
    def test_no_username_reports_and_returns_unchanged(self):
        messages = []
        existing = {"issues": [{"issue_id": "1"}], "generated_at": None}
        with patch("services.dashboard_refresh.get_credentials",
                   return_value={"drupal_username": ""}), \
             patch("services.dashboard_refresh.DashboardLedger.load", return_value=existing):
            result = import_credit_history(progress=messages.append)
        assert result == existing
        assert any("No drupal.org username" in m for m in messages)

    def test_new_records_imported_with_imported_source(self):
        records = [
            {"title": "Fix A", "project": "drupal", "node_id": 111,
             "issue_url": "https://www.drupal.org/node/111", "created": "2026-01-01"},
            {"title": "Fix B", "project": "webform", "node_id": 222,
             "issue_url": "https://www.drupal.org/node/222", "created": "2026-02-01"},
        ]
        with patch("services.dashboard_refresh.get_credentials",
                   return_value={"drupal_username": "sunlix"}), \
             patch("services.dashboard_refresh.DashboardLedger.load",
                   return_value={"issues": [], "generated_at": None}), \
             patch("services.dashboard_refresh.DashboardLedger.save"), \
             patch("services.dashboard_refresh.CreditTracker.fetch_all_credit_records",
                   return_value={"records": records, "truncated": False}):
            result = import_credit_history()

        issues = result["issues"]
        assert len(issues) == 2
        assert {i["issue_id"] for i in issues} == {"111", "222"}
        assert all(i["source"] == "imported" for i in issues)
        assert all(i["credit"]["credited"] is True for i in issues)

    def test_existing_issueforge_entry_keeps_its_source_and_work(self):
        # Regression coverage for the exact scenario reported: an issue we
        # genuinely worked (source="issueforge", real action_summary) must
        # NOT be relabeled or have its work summary erased just because it
        # also shows up in the credit-history import.
        existing_entry = {
            "issue_id": "2727281", "project": "drupal", "title": "Old title",
            "source": "issueforge", "action_summary": "Rebased MR !12139",
            "scenario": "B", "first_worked": "2026-07-17", "last_worked": "2026-07-17",
            "issue_url": "https://www.drupal.org/project/drupal/issues/2727281",
            "comment_url": "", "mr": {"project": "drupal", "iid": "12139", "state": None,
                                      "pipeline_status": None, "pipeline_url": None},
            "status": {"value": None, "checked_at": None},
            "comments": {"count_at_last_check": None, "checked_at": None},
            "credit": {"credited": False, "checked_at": None},
        }
        ledger = {"issues": [existing_entry], "generated_at": None}
        records = [{"title": "Link to file...", "project": "drupal", "node_id": 2727281,
                   "issue_url": "https://www.drupal.org/node/2727281", "created": "2026-07-17"}]

        with patch("services.dashboard_refresh.get_credentials",
                   return_value={"drupal_username": "sunlix"}), \
             patch("services.dashboard_refresh.DashboardLedger.load", return_value=ledger), \
             patch("services.dashboard_refresh.DashboardLedger.save"), \
             patch("services.dashboard_refresh.CreditTracker.fetch_all_credit_records",
                   return_value={"records": records, "truncated": False}):
            result = import_credit_history()

        entry = result["issues"][0]
        assert entry["source"] == "issueforge"
        assert entry["action_summary"] == "Rebased MR !12139"
        assert entry["credit"]["credited"] is True  # credit flag still updates

    def test_records_without_node_id_are_skipped(self):
        records = [{"title": "no link", "project": "drupal", "node_id": None,
                   "issue_url": "", "created": ""}]
        with patch("services.dashboard_refresh.get_credentials",
                   return_value={"drupal_username": "sunlix"}), \
             patch("services.dashboard_refresh.DashboardLedger.load",
                   return_value={"issues": [], "generated_at": None}), \
             patch("services.dashboard_refresh.DashboardLedger.save"), \
             patch("services.dashboard_refresh.CreditTracker.fetch_all_credit_records",
                   return_value={"records": records, "truncated": False}):
            result = import_credit_history()
        assert result["issues"] == []

    def test_truncated_flag_is_reported(self):
        messages = []
        with patch("services.dashboard_refresh.get_credentials",
                   return_value={"drupal_username": "sunlix"}), \
             patch("services.dashboard_refresh.DashboardLedger.load",
                   return_value={"issues": [], "generated_at": None}), \
             patch("services.dashboard_refresh.DashboardLedger.save"), \
             patch("services.dashboard_refresh.CreditTracker.fetch_all_credit_records",
                   return_value={"records": [], "truncated": True}):
            import_credit_history(progress=messages.append)
        assert any("partial import" in m for m in messages)


class TestRefreshSkipsStableIssues:
    """
    Regression coverage for the scaling problem: refresh used to re-check
    EVERY tracked issue on every run, including already-closed,
    already-credited historical imports — cost grew with total lifetime
    history instead of active work. A closed issue's status and an issue's
    credited=True are both effectively permanent facts on drupal.org, so
    both are skipped by default.
    """

    def _ledger(self, issues):
        return {"issues": issues, "generated_at": None}

    def _closed_entry(self, issue_id, credited=True):
        return {
            "issue_id": issue_id, "project": "drupal", "issue_url": "https://x",
            "mr": {"project": "", "iid": ""},
            "status": {"value": "Closed (fixed)", "checked_at": None},
            "comments": {"count_at_last_check": None, "checked_at": None},
            "credit": {"credited": credited, "checked_at": None},
        }

    def test_terminal_status_issue_skips_api_call_entirely(self):
        entry = self._closed_entry("1")
        messages = []
        with patch("services.dashboard_refresh.DashboardLedger.load",
                  return_value=self._ledger([entry])), \
             patch("services.dashboard_refresh.DashboardLedger.save"), \
             patch("services.dashboard_refresh.get_credentials",
                  return_value={"gitlab_token": "", "drupal_username": ""}), \
             patch("services.dashboard_refresh.DrupalAPIClient") as api_cls:
            refresh_all(progress=messages.append)
        api_cls.return_value.get_issue_metadata.assert_not_called()
        assert any("already in a terminal state" in m for m in messages)

    def test_force_bypasses_terminal_status_skip(self):
        entry = self._closed_entry("1")
        with patch("services.dashboard_refresh.DashboardLedger.load",
                  return_value=self._ledger([entry])), \
             patch("services.dashboard_refresh.DashboardLedger.save"), \
             patch("services.dashboard_refresh.get_credentials",
                  return_value={"gitlab_token": "", "drupal_username": ""}), \
             patch("services.dashboard_refresh.DrupalAPIClient") as api_cls:
            api_cls.return_value.get_issue_metadata.return_value = {
                "status": "Closed (fixed)", "comment_ids": [],
            }
            refresh_all(force=True)
        api_cls.return_value.get_issue_metadata.assert_called_once()

    def test_already_credited_issue_skipped_from_credit_check(self):
        entry = self._closed_entry("1", credited=True)
        messages = []
        with patch("services.dashboard_refresh.DashboardLedger.load",
                  return_value=self._ledger([entry])), \
             patch("services.dashboard_refresh.DashboardLedger.save"), \
             patch("services.dashboard_refresh.get_credentials",
                  return_value={"gitlab_token": "", "drupal_username": "sunlix"}), \
             patch("services.dashboard_refresh.CreditTracker.check_credits") as check_credits:
            refresh_all(progress=messages.append)
        check_credits.assert_not_called()
        assert any("already credited" in m for m in messages)

    def test_force_bypasses_credit_skip_too(self):
        entry = self._closed_entry("1", credited=True)
        with patch("services.dashboard_refresh.DashboardLedger.load",
                  return_value=self._ledger([entry])), \
             patch("services.dashboard_refresh.DashboardLedger.save"), \
             patch("services.dashboard_refresh.get_credentials",
                  return_value={"gitlab_token": "", "drupal_username": "sunlix"}), \
             patch("services.dashboard_refresh.DrupalAPIClient") as api_cls, \
             patch("services.dashboard_refresh.CreditTracker.check_credits",
                  return_value={"1": True}) as check_credits:
            api_cls.return_value.get_issue_metadata.return_value = {
                "status": "Closed (fixed)", "comment_ids": [],
            }
            refresh_all(force=True)
        check_credits.assert_called_once()

    def test_mixed_ledger_only_processes_active_issue(self):
        # The realistic shape: 1 active in-flight issue + 1 closed/credited
        # historical import — only the active one should trigger network
        # calls.
        active = {
            "issue_id": "999", "project": "drupal", "issue_url": "https://x",
            "mr": {"project": "", "iid": ""},
            "status": {"value": "Needs review", "checked_at": None},
            "comments": {"count_at_last_check": None, "checked_at": None},
            "credit": {"credited": False, "checked_at": None},
        }
        closed = self._closed_entry("1")
        with patch("services.dashboard_refresh.DashboardLedger.load",
                  return_value=self._ledger([active, closed])), \
             patch("services.dashboard_refresh.DashboardLedger.save"), \
             patch("services.dashboard_refresh.get_credentials",
                  return_value={"gitlab_token": "", "drupal_username": "sunlix"}), \
             patch("services.dashboard_refresh.DrupalAPIClient") as api_cls, \
             patch("services.dashboard_refresh.CreditTracker.check_credits",
                  return_value={"999": False}) as check_credits:
            api_cls.return_value.get_issue_metadata.return_value = {
                "status": "Needs review", "comment_ids": [],
            }
            refresh_all()
        api_cls.return_value.get_issue_metadata.assert_called_once()
        checked_issues = check_credits.call_args[0][1]
        assert [i["issue_id"] for i in checked_issues] == ["999"]


class TestComputeLifetimeStats:
    def test_counts_resolved_and_credited(self):
        data = {"issues": [
            {"status": {"value": "Fixed"}, "credit": {"credited": True}},
            {"status": {"value": "Closed (duplicate)"}, "credit": {"credited": False}},
            {"status": {"value": "Needs review"}, "credit": {"credited": False}},
        ]}
        stats = compute_lifetime_stats(data)
        assert stats == {"issues_tracked": 3, "issues_resolved": 2, "issues_credited": 1}

    def test_empty_ledger(self):
        assert compute_lifetime_stats({"issues": []}) == {
            "issues_tracked": 0, "issues_resolved": 0, "issues_credited": 0,
        }
