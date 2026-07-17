"""Unit tests for the dashboard FastAPI app — TestClient only, no real
socket bound, no real network calls."""
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from fastapi.testclient import TestClient

from services.dashboard_app import app
import services.dashboard_ledger as ledger_mod

client = TestClient(app)


class TestHealth:
    def test_health_ok(self):
        resp = client.get("/api/health")
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}


class TestGetData:
    def test_returns_ledger_contents(self):
        fake = {"issues": [{"issue_id": "1"}], "generated_at": "2026-07-17"}
        with patch("services.dashboard_app.DashboardLedger.load", return_value=fake):
            resp = client.get("/api/data")
        assert resp.status_code == 200
        assert resp.json()["issues"][0]["issue_id"] == "1"

    def test_missing_ledger_returns_empty_shape(self):
        empty = {"issues": [], "generated_at": None}
        with patch("services.dashboard_app.DashboardLedger.load", return_value=empty):
            resp = client.get("/api/data")
        assert resp.json() == empty


class TestLifetime:
    def test_computes_from_ledger(self):
        fake = {"issues": [
            {"issue_id": "1", "status": {"value": "Fixed"}, "credit": {"credited": True}},
            {"issue_id": "2", "status": {"value": "Needs review"}, "credit": {"credited": False}},
        ], "generated_at": None}
        with patch("services.dashboard_app.DashboardLedger.load", return_value=fake):
            resp = client.get("/api/lifetime")
        assert resp.json() == {"issues_tracked": 2, "issues_resolved": 1, "issues_credited": 1}


class TestRefresh:
    def test_success_returns_concise_summary_not_full_log(self, tmp_path):
        # Regression coverage: the browser's status box used to get the
        # FULL per-issue progress log joined with newlines — unreadable
        # for 40+ tracked issues in a small fixed-height box. The response
        # must be a short summary; detailed lines are logged server-side.
        built = {}

        def fake_refresh_all(progress=None, force=False):
            if progress:
                for i in range(50):
                    progress(f"  #{i}: status=Closed (fixed)")
            return {"issues": [{"issue_id": str(i)} for i in range(50)],
                   "generated_at": "2026-07-17"}

        def fake_build(data, *a, **kw):
            built["called_with"] = data
            return str(tmp_path / "dashboard.html")

        with patch("services.dashboard_app.refresh_all", side_effect=fake_refresh_all), \
             patch("services.dashboard_app.DashboardBuilder.build", side_effect=fake_build):
            resp = client.post("/api/refresh")

        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert "50 issue(s)" in body["message"]
        assert len(body["message"]) < 200  # concise, not a 50-line dump
        assert built["called_with"]["generated_at"] == "2026-07-17"

    def test_skipped_issues_are_counted_in_summary(self):
        def fake_refresh_all(progress=None, force=False):
            if progress:
                progress("Refreshing 2 tracked issue(s)...")
                progress("  [Skip] #1: could not fetch issue status (503)")
                progress("  #1: status=?")
                progress("  #2: status=Closed (fixed)")
            return {"issues": [{"issue_id": "1"}, {"issue_id": "2"}], "generated_at": None}

        with patch("services.dashboard_app.refresh_all", side_effect=fake_refresh_all), \
             patch("services.dashboard_app.DashboardBuilder.build"):
            resp = client.post("/api/refresh")

        body = resp.json()
        assert "1 could not be checked" in body["message"]

    def test_failure_returns_500_not_crash(self):
        with patch("services.dashboard_app.refresh_all", side_effect=RuntimeError("boom")):
            resp = client.post("/api/refresh")
        assert resp.status_code == 500
        assert resp.json()["ok"] is False
        assert "boom" in resp.json()["message"]


class TestImportCreditHistory:
    def test_no_username_returns_400(self):
        with patch("services.dashboard_app.get_credentials",
                   return_value={"drupal_username": ""}):
            resp = client.post("/api/credits/import")
        assert resp.status_code == 400
        assert resp.json()["ok"] is False

    def test_success_imports_into_ledger_and_rebuilds(self, tmp_path):
        # Regression coverage: this endpoint must MUTATE the ledger (seed
        # it with the user's full credit history), not just return records
        # for display — that was the whole point of the redesign.
        imported_data = {"issues": [{"issue_id": "1", "source": "imported"}],
                         "generated_at": "2026-07-17"}
        built = {}

        def fake_build(data, *a, **kw):
            built["data"] = data
            return str(tmp_path / "dashboard.html")

        with patch("services.dashboard_app.get_credentials",
                   return_value={"drupal_username": "sunlix"}), \
             patch("services.dashboard_app.import_credit_history",
                   return_value=imported_data) as import_fn, \
             patch("services.dashboard_app.DashboardBuilder.build", side_effect=fake_build):
            resp = client.post("/api/credits/import")
        assert resp.status_code == 200
        assert resp.json()["ok"] is True
        import_fn.assert_called_once()
        assert built["data"] == imported_data

    def test_failure_returns_500_not_crash(self):
        with patch("services.dashboard_app.get_credentials",
                   return_value={"drupal_username": "sunlix"}), \
             patch("services.dashboard_app.import_credit_history",
                   side_effect=RuntimeError("boom")):
            resp = client.post("/api/credits/import")
        assert resp.status_code == 500
        assert resp.json()["ok"] is False


class TestStaticAssets:
    def test_serves_index_without_embedded_data(self):
        resp = client.get("/")
        assert resp.status_code == 200
        assert "window.DASHBOARD_DATA" not in resp.text
        assert "dashboard.js" in resp.text

    def test_serves_css_and_js(self):
        css = client.get("/dashboard.css")
        js = client.get("/dashboard.js")
        assert css.status_code == 200
        assert js.status_code == 200
        assert "text/css" in css.headers["content-type"]
