"""Unit tests for DashboardServerManager — no real subprocess/socket use."""
import json
import os
import sys
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import services.dashboard_server_manager as mgr


class TestLockFile:
    def test_read_missing_lock_returns_none(self, tmp_path, monkeypatch):
        monkeypatch.setattr(mgr, "LOCK_PATH", str(tmp_path / "lock.json"))
        assert mgr._read_lock() is None

    def test_write_then_read_roundtrip(self, tmp_path, monkeypatch):
        monkeypatch.setattr(mgr, "LOCK_PATH", str(tmp_path / "lock.json"))
        monkeypatch.setattr(mgr, "LOCK_DIR", str(tmp_path))
        mgr._write_lock(12345, 54321)
        assert mgr._read_lock() == {"pid": 12345, "port": 54321}

    def test_malformed_lock_returns_none(self, tmp_path, monkeypatch):
        path = tmp_path / "lock.json"
        path.write_text("{not json")
        monkeypatch.setattr(mgr, "LOCK_PATH", str(path))
        assert mgr._read_lock() is None

    def test_remove_lock_is_safe_when_missing(self, tmp_path, monkeypatch):
        monkeypatch.setattr(mgr, "LOCK_PATH", str(tmp_path / "nope.json"))
        mgr._remove_lock()  # must not raise


class TestPidAlive:
    def test_current_process_is_alive(self):
        assert mgr._pid_alive(os.getpid()) is True

    def test_bogus_pid_is_not_alive(self):
        # A PID astronomically unlikely to exist.
        assert mgr._pid_alive(2**30) is False


class TestPortBindable:
    def test_free_port_is_bindable(self):
        # A port we just released should be reported bindable.
        import socket
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            free_port = s.getsockname()[1]
        assert mgr._port_bindable(free_port) is True

    def test_occupied_port_is_not_bindable(self):
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind(("127.0.0.1", 0))
        s.listen(1)
        occupied_port = s.getsockname()[1]
        try:
            assert mgr._port_bindable(occupied_port) is False
        finally:
            s.close()


class TestFindFreePort:
    def test_prefers_the_stable_port_when_free(self):
        # Regression coverage: the link should be stable across sessions,
        # not a new random number every time — PREFERRED_PORT is used
        # whenever it's genuinely free (verified by a real bind, not
        # assumed), only falling back to an OS-assigned port if it's taken.
        with patch.object(mgr, "_port_bindable", return_value=True):
            assert mgr._find_free_port() == mgr.PREFERRED_PORT

    def test_falls_back_to_ephemeral_when_preferred_is_taken(self):
        with patch.object(mgr, "_port_bindable", return_value=False):
            port = mgr._find_free_port()
        assert port != mgr.PREFERRED_PORT
        assert 1024 < port < 65536

    def test_returns_a_bindable_port(self):
        import socket
        port = mgr._find_free_port()
        assert 1024 < port < 65536
        # Genuinely free at the moment it was returned.
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", port))  # must not raise


class TestGetRunningServer:
    def test_no_lock_returns_none(self, tmp_path, monkeypatch):
        monkeypatch.setattr(mgr, "LOCK_PATH", str(tmp_path / "lock.json"))
        assert mgr.get_running_server() is None

    def test_live_and_responding_is_reused(self, tmp_path, monkeypatch):
        monkeypatch.setattr(mgr, "LOCK_PATH", str(tmp_path / "lock.json"))
        mgr._write_lock(os.getpid(), 9999)
        with patch.object(mgr, "_responds", return_value=True):
            result = mgr.get_running_server()
        assert result == (os.getpid(), 9999)

    def test_dead_pid_cleans_up_stale_lock(self, tmp_path, monkeypatch):
        lock_path = tmp_path / "lock.json"
        monkeypatch.setattr(mgr, "LOCK_PATH", str(lock_path))
        mgr._write_lock(2**30, 9999)  # bogus/dead pid
        result = mgr.get_running_server()
        assert result is None
        assert not lock_path.exists()

    def test_alive_pid_but_not_responding_is_stale(self, tmp_path, monkeypatch):
        # Regression coverage: a process with this PID could be alive but
        # be a completely unrelated program (PID reuse) — liveness alone
        # isn't enough, it must also answer the health check.
        lock_path = tmp_path / "lock.json"
        monkeypatch.setattr(mgr, "LOCK_PATH", str(lock_path))
        mgr._write_lock(os.getpid(), 9999)
        with patch.object(mgr, "_responds", return_value=False):
            result = mgr.get_running_server()
        assert result is None
        assert not lock_path.exists()


class TestEnsureRunning:
    def test_reuses_existing_server_without_spawning(self, tmp_path, monkeypatch):
        monkeypatch.setattr(mgr, "LOCK_DIR", str(tmp_path))
        monkeypatch.setattr(mgr, "LOCK_PATH", str(tmp_path / "lock.json"))
        with patch.object(mgr, "get_running_server", return_value=(111, 8888)), \
             patch("subprocess.Popen") as popen:
            port, was_running = mgr.ensure_running()
        assert (port, was_running) == (8888, True)
        popen.assert_not_called()

    def test_spawns_when_none_running(self, tmp_path, monkeypatch):
        monkeypatch.setattr(mgr, "LOCK_DIR", str(tmp_path))
        monkeypatch.setattr(mgr, "LOCK_PATH", str(tmp_path / "lock.json"))
        monkeypatch.setattr(mgr, "LOG_PATH", str(tmp_path / "log.txt"))
        fake_process = MagicMock(pid=4242)
        with patch.object(mgr, "get_running_server", return_value=None), \
             patch.object(mgr, "_find_free_port", return_value=54321), \
             patch("subprocess.Popen", return_value=fake_process) as popen, \
             patch.object(mgr, "_responds", return_value=True):
            port, was_running = mgr.ensure_running()
        assert (port, was_running) == (54321, False)
        popen.assert_called_once()
        # Lock file reflects the spawned process.
        assert mgr._read_lock() == {"pid": 4242, "port": 54321}

    def test_spawn_uses_detached_session_on_posix(self, tmp_path, monkeypatch):
        monkeypatch.setattr(mgr, "LOCK_DIR", str(tmp_path))
        monkeypatch.setattr(mgr, "LOCK_PATH", str(tmp_path / "lock.json"))
        monkeypatch.setattr(mgr, "LOG_PATH", str(tmp_path / "log.txt"))
        monkeypatch.setattr(mgr.sys, "platform", "linux")
        fake_process = MagicMock(pid=1)
        with patch.object(mgr, "get_running_server", return_value=None), \
             patch.object(mgr, "_find_free_port", return_value=1), \
             patch("subprocess.Popen", return_value=fake_process) as popen, \
             patch.object(mgr, "_responds", return_value=True):
            mgr.ensure_running()
        _, kwargs = popen.call_args
        assert kwargs.get("start_new_session") is True


class TestStopIfRunning:
    def test_returns_false_when_nothing_running(self, tmp_path, monkeypatch):
        monkeypatch.setattr(mgr, "LOCK_PATH", str(tmp_path / "lock.json"))
        with patch.object(mgr, "get_running_server", return_value=None):
            assert mgr.stop_if_running() is False

    def test_sends_sigterm_and_clears_lock(self, tmp_path, monkeypatch):
        lock_path = tmp_path / "lock.json"
        monkeypatch.setattr(mgr, "LOCK_PATH", str(lock_path))
        mgr._write_lock(999, 8888)
        with patch.object(mgr, "get_running_server", return_value=(999, 8888)), \
             patch.object(mgr, "_pid_alive", return_value=False), \
             patch("os.kill") as kill:
            result = mgr.stop_if_running()
        assert result is True
        kill.assert_called_once_with(999, 15)
        assert not lock_path.exists()

    def test_waits_for_process_to_actually_exit_before_returning(self, tmp_path, monkeypatch):
        # Regression coverage: sending SIGTERM alone doesn't guarantee the
        # OS has released the process's socket yet. An immediately-
        # following ensure_running() could lose that race and fall back to
        # a random ephemeral port even though the preferred port is about
        # to free up — defeating the point of `restart` giving back the
        # same stable link. stop_if_running() must wait (briefly, bounded)
        # for the PID to actually stop being alive.
        lock_path = tmp_path / "lock.json"
        monkeypatch.setattr(mgr, "LOCK_PATH", str(lock_path))
        monkeypatch.setattr(mgr, "_STOP_WAIT_SECONDS", 1)
        monkeypatch.setattr(mgr, "_STOP_POLL_INTERVAL", 0.01)
        mgr._write_lock(999, 8888)
        alive_sequence = iter([True, True, False])
        with patch.object(mgr, "get_running_server", return_value=(999, 8888)), \
             patch.object(mgr, "_pid_alive", side_effect=lambda pid: next(alive_sequence)), \
             patch("os.kill"), patch("time.sleep") as sleep:
            result = mgr.stop_if_running()
        assert result is True
        assert sleep.call_count == 2  # polled twice before seeing it exit

    def test_gives_up_waiting_after_timeout_but_still_clears_lock(self, tmp_path, monkeypatch):
        # A process that never exits (stuck/zombie) must not hang
        # stop_if_running() forever — bounded wait, then proceed anyway.
        lock_path = tmp_path / "lock.json"
        monkeypatch.setattr(mgr, "LOCK_PATH", str(lock_path))
        monkeypatch.setattr(mgr, "_STOP_WAIT_SECONDS", 0.05)
        monkeypatch.setattr(mgr, "_STOP_POLL_INTERVAL", 0.01)
        mgr._write_lock(999, 8888)
        with patch.object(mgr, "get_running_server", return_value=(999, 8888)), \
             patch.object(mgr, "_pid_alive", return_value=True), \
             patch("os.kill"):
            result = mgr.stop_if_running()
        assert result is True
        assert not lock_path.exists()
