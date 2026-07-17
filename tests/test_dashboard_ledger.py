"""Unit tests for DashboardLedger — pure data model, no network."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from services.dashboard_ledger import DashboardLedger


class TestLoadSave:
    def test_load_missing_file_returns_empty_shape(self, tmp_path):
        data = DashboardLedger.load(str(tmp_path / "ledger.json"))
        assert data == {"issues": [], "generated_at": None}

    def test_load_malformed_json_falls_back_to_empty(self, tmp_path):
        path = tmp_path / "ledger.json"
        path.write_text("{not valid json")
        data = DashboardLedger.load(str(path))
        assert data == {"issues": [], "generated_at": None}

    def test_save_then_load_roundtrip(self, tmp_path):
        # "source" is backfilled on load for entries that already have it
        # explicitly set, so a full entry (as upsert() actually produces)
        # round-trips exactly.
        path = str(tmp_path / "ledger.json")
        data = {"issues": [{"issue_id": "123", "source": "issueforge"}],
               "generated_at": "2026-07-17"}
        DashboardLedger.save(data, path)
        loaded = DashboardLedger.load(path)
        assert loaded == data

    def test_save_creates_parent_directory(self, tmp_path):
        path = str(tmp_path / "nested" / "dir" / "ledger.json")
        DashboardLedger.save({"issues": [], "generated_at": None}, path)
        assert os.path.exists(path)


class TestUpsert:
    def test_creates_new_entry_with_defaults(self):
        data = {"issues": []}
        entry = DashboardLedger.upsert(
            data, issue_id="2727281", today="2026-07-17", project="drupal",
            title="Link to file", scenario="B", action_summary="Rebased MR",
            comment_url="https://x", mr_project="drupal", mr_iid="12139",
        )
        assert entry["issue_id"] == "2727281"
        assert entry["first_worked"] == "2026-07-17"
        assert entry["last_worked"] == "2026-07-17"
        assert entry["mr"] == {"project": "drupal", "iid": "12139", "state": None,
                               "pipeline_status": None, "pipeline_url": None}
        assert entry["credit"] == {"credited": False, "checked_at": None}
        assert len(data["issues"]) == 1

    def test_default_issue_url_derived_from_project_and_id(self):
        data = {"issues": []}
        entry = DashboardLedger.upsert(data, issue_id="999", today="2026-07-17", project="webform")
        assert entry["issue_url"] == "https://www.drupal.org/project/webform/issues/999"

    def test_upsert_existing_updates_last_worked_not_first_worked(self):
        data = {"issues": []}
        DashboardLedger.upsert(data, issue_id="1", today="2026-07-01", project="drupal")
        entry = DashboardLedger.upsert(
            data, issue_id="1", today="2026-07-17", project="drupal",
            action_summary="Second pass",
        )
        assert entry["first_worked"] == "2026-07-01"
        assert entry["last_worked"] == "2026-07-17"
        assert entry["action_summary"] == "Second pass"
        assert len(data["issues"]) == 1  # not duplicated

    def test_upsert_existing_preserves_prior_fields_when_blank(self):
        data = {"issues": []}
        DashboardLedger.upsert(
            data, issue_id="1", today="2026-07-01", project="drupal",
            title="Original title",
        )
        entry = DashboardLedger.upsert(data, issue_id="1", today="2026-07-17", project="drupal")
        assert entry["title"] == "Original title"


class TestSource:
    def test_default_source_is_issueforge(self):
        data = {"issues": []}
        entry = DashboardLedger.upsert(data, issue_id="1", today="2026-07-17")
        assert entry["source"] == "issueforge"

    def test_explicit_imported_source_on_create(self):
        data = {"issues": []}
        entry = DashboardLedger.upsert(
            data, issue_id="1", today="2026-07-17", source="imported"
        )
        assert entry["source"] == "imported"

    def test_existing_source_is_never_downgraded_by_reupsert(self):
        # A real IssueForge-worked issue that later also shows up in a
        # credit-history import must keep its "issueforge" identity.
        data = {"issues": []}
        DashboardLedger.upsert(data, issue_id="1", today="2026-07-01", source="issueforge")
        entry = DashboardLedger.upsert(data, issue_id="1", today="2026-07-17", source="imported")
        assert entry["source"] == "issueforge"

    def test_action_summary_on_existing_entry_upgrades_source_to_issueforge(self):
        # An issue first seen via credit import that's later genuinely
        # worked on through IssueForge (record with a real summary) must
        # be promoted, not stay labeled "imported" forever.
        data = {"issues": []}
        DashboardLedger.upsert(data, issue_id="1", today="2026-07-01", source="imported")
        entry = DashboardLedger.upsert(
            data, issue_id="1", today="2026-07-17",
            action_summary="Actually fixed this now",
        )
        assert entry["source"] == "issueforge"
        assert entry["action_summary"] == "Actually fixed this now"

    def test_load_backfills_source_on_legacy_entries(self, tmp_path):
        # Regression coverage: entries written before "source" existed
        # (this session's own earlier ledger.json) must not crash or show
        # as blank — they were, by definition, real IssueForge work.
        path = tmp_path / "ledger.json"
        path.write_text(
            '{"issues": [{"issue_id": "1", "project": "drupal"}], "generated_at": null}'
        )
        data = DashboardLedger.load(str(path))
        assert data["issues"][0]["source"] == "issueforge"


class TestFind:
    def test_finds_by_issue_id_as_string_or_int_like(self):
        data = {"issues": [{"issue_id": "2727281"}]}
        assert DashboardLedger.find(data, "2727281") is not None
        assert DashboardLedger.find(data, 2727281) is not None
        assert DashboardLedger.find(data, "9999") is None


class TestUpdateLiveStatus:
    def test_updates_only_provided_fields(self):
        entry = {
            "status": {"value": None, "checked_at": None},
            "comments": {"count_at_last_check": None, "checked_at": None},
            "mr": {"project": "drupal", "iid": "1", "state": None,
                   "pipeline_status": None, "pipeline_url": None},
            "credit": {"credited": False, "checked_at": None},
        }
        DashboardLedger.update_live_status(entry, checked_at="2026-07-17", status="Needs review")
        assert entry["status"]["value"] == "Needs review"
        assert entry["status"]["checked_at"] == "2026-07-17"
        # Untouched fields remain untouched.
        assert entry["mr"]["state"] is None
        assert entry["credit"]["credited"] is False

    def test_updates_credit_flag(self):
        entry = {"credit": {"credited": False, "checked_at": None}}
        DashboardLedger.update_live_status(entry, checked_at="2026-07-17", credited=True)
        assert entry["credit"]["credited"] is True
        assert entry["credit"]["checked_at"] == "2026-07-17"
