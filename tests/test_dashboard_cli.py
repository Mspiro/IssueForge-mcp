"""Unit tests for scripts/dashboard.py's CLI wiring — no real server/network."""
import argparse
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "scripts"))

import dashboard as dashboard_cli


def _args(no_server=False, table=False):
    return argparse.Namespace(no_server=no_server, table=table)


class TestCmdSummary:
    def test_auto_starts_server_by_default(self, capsys):
        with patch("services.dashboard_ledger.DashboardLedger.load",
                   return_value={"issues": [], "generated_at": None}), \
             patch("dashboard.get_credentials", return_value={"drupal_username": ""}), \
             patch("services.dashboard_server_manager.ensure_running",
                   return_value=(54321, False)):
            dashboard_cli.cmd_summary(_args())
        out = capsys.readouterr().out
        assert "http://localhost:54321" in out

    def test_no_server_flag_skips_server_and_uses_file_link(self, capsys):
        with patch("services.dashboard_ledger.DashboardLedger.load",
                   return_value={"issues": [], "generated_at": None}), \
             patch("dashboard.get_credentials", return_value={"drupal_username": ""}), \
             patch("services.dashboard_server_manager.ensure_running") as ensure_running:
            dashboard_cli.cmd_summary(_args(no_server=True))
        ensure_running.assert_not_called()
        out = capsys.readouterr().out
        assert "file://" in out

    def test_server_start_failure_falls_back_gracefully(self, capsys):
        # Regression coverage: if the local server can't start (e.g. a
        # sandboxed/restricted environment with no loopback sockets), the
        # summary must still print rather than crash the whole invocation.
        with patch("services.dashboard_ledger.DashboardLedger.load",
                   return_value={"issues": [], "generated_at": None}), \
             patch("dashboard.get_credentials", return_value={"drupal_username": ""}), \
             patch("services.dashboard_server_manager.ensure_running",
                   side_effect=OSError("no sockets allowed")):
            result = dashboard_cli.cmd_summary(_args())
        out = capsys.readouterr().out
        assert result == 0
        assert "file://" in out
        assert "Could not start local server" in out

    def test_default_output_is_terse_no_table(self, capsys):
        # Regression coverage: dumping every tracked issue as a table on
        # every plain `dashboard.py` invocation was too noisy once the
        # ledger grew past a couple of entries (e.g. after importing 40+
        # credit records) — default output must be just the summary + link.
        ledger = {"issues": [{
            "issue_id": "1", "project": "drupal", "title": "A bug",
            "status": {"value": "Needs review"},
            "mr": {"iid": "99", "pipeline_status": None},
            "credit": {"credited": False},
            "comments": {"new_since_last_check": 0},
        }], "generated_at": None}
        with patch("services.dashboard_ledger.DashboardLedger.load", return_value=ledger), \
             patch("services.dashboard_server_manager.ensure_running", return_value=(1, True)):
            dashboard_cli.cmd_summary(_args())
        out = capsys.readouterr().out
        assert "1 tracked" in out
        assert "!99" not in out
        assert "A bug" not in out

    def test_table_flag_prints_full_table(self, capsys):
        ledger = {"issues": [{
            "issue_id": "1", "project": "drupal", "title": "A bug",
            "status": {"value": "Needs review"},
            "mr": {"iid": "99", "pipeline_status": None},
            "credit": {"credited": False},
            "comments": {"new_since_last_check": 0},
        }], "generated_at": None}
        with patch("services.dashboard_ledger.DashboardLedger.load", return_value=ledger), \
             patch("services.dashboard_server_manager.ensure_running", return_value=(1, True)):
            dashboard_cli.cmd_summary(_args(table=True))
        out = capsys.readouterr().out
        assert "1 tracked" in out
        assert "!99" in out
        assert "A bug" in out


class TestMaybeAutoImportCredits:
    """
    Regression coverage: a brand-new user's ledger starts genuinely empty
    (it's gitignored, never shipped with the tool) — without this, they'd
    see "0 tracked" forever unless they happened to discover
    `import-credits` exists on their own.
    """

    def test_non_empty_ledger_is_a_noop(self, capsys):
        ledger = {"issues": [{"issue_id": "1"}], "generated_at": None}
        with patch("dashboard.get_credentials") as mock_creds, \
             patch("dashboard.import_credit_history") as mock_import:
            result = dashboard_cli._maybe_auto_import_credits(ledger)
        mock_creds.assert_not_called()
        mock_import.assert_not_called()
        assert result is ledger

    def test_empty_ledger_no_username_is_a_noop(self, capsys):
        empty = {"issues": [], "generated_at": None}
        with patch("dashboard.get_credentials", return_value={"drupal_username": ""}), \
             patch("dashboard.import_credit_history") as mock_import:
            result = dashboard_cli._maybe_auto_import_credits(empty)
        mock_import.assert_not_called()
        assert result is empty

    def test_empty_ledger_with_username_triggers_import(self, capsys):
        empty = {"issues": [], "generated_at": None}
        imported = {"issues": [{"issue_id": "1"}], "generated_at": None}
        with patch("dashboard.get_credentials", return_value={"drupal_username": "meeni_dhobale"}), \
             patch("dashboard.import_credit_history", return_value=imported) as mock_import, \
             patch("services.dashboard_builder.DashboardBuilder.build") as mock_build:
            result = dashboard_cli._maybe_auto_import_credits(empty)
        mock_import.assert_called_once()
        mock_build.assert_called_once_with(imported)
        assert result == imported
        out = capsys.readouterr().out
        assert "First run detected" in out
