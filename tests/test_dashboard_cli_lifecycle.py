"""Unit tests for scripts/dashboard.py's stop/restart subcommands."""
import argparse
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "scripts"))

import dashboard as dashboard_cli


class TestCmdStop:
    def test_reports_stopped_when_something_was_running(self, capsys):
        with patch("services.dashboard_server_manager.stop_if_running", return_value=True):
            result = dashboard_cli.cmd_stop(argparse.Namespace())
        assert result == 0
        assert "stopped" in capsys.readouterr().out.lower()

    def test_reports_nothing_running(self, capsys):
        with patch("services.dashboard_server_manager.stop_if_running", return_value=False):
            dashboard_cli.cmd_stop(argparse.Namespace())
        assert "no server" in capsys.readouterr().out.lower()


class TestCmdRestart:
    def test_stops_then_starts_and_prints_link(self, capsys):
        with patch("services.dashboard_server_manager.stop_if_running") as stop, \
             patch("services.dashboard_server_manager.ensure_running", return_value=(8420, False)) as start:
            result = dashboard_cli.cmd_restart(argparse.Namespace())
        assert result == 0
        stop.assert_called_once()
        start.assert_called_once()
        assert "http://localhost:8420" in capsys.readouterr().out

    def test_stop_happens_before_start(self):
        # Regression coverage: restarting must actually terminate the old
        # (possibly stale-code) process before spawning a new one — calling
        # ensure_running() first would just reuse the stale server via the
        # single-instance lockfile check and defeat the whole point of
        # "restart to pick up code changes".
        order = []
        with patch("services.dashboard_server_manager.stop_if_running",
                  side_effect=lambda: order.append("stop")), \
             patch("services.dashboard_server_manager.ensure_running",
                  side_effect=lambda: order.append("start") or (1, False)):
            dashboard_cli.cmd_restart(argparse.Namespace())
        assert order == ["stop", "start"]
