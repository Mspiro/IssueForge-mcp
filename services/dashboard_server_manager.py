"""
Dashboard server lifecycle manager — auto-starts the local dashboard
server on demand, ensures only one instance ever runs, and never leaves a
resource hanging around on a low-end machine longer than needed.

Design constraints (explicit, from user requirements):
- A stable, memorable port is tried first (PREFERRED_PORT) so the link
  looks the same across sessions instead of a new random number each
  time — but this is only ever used after a REAL bind-and-release check,
  never assumed blindly. If it's taken (by DDEV, another app, or a stale
  process), an OS-assigned ephemeral port is used instead — this can never
  collide with anything already running on the system.
- Single instance — a PID+port lockfile at ~/.issueforge/dashboard_server.json
  is checked before starting; a live, responding server is reused rather
  than spawning a second one.
- Low memory footprint — a single uvicorn worker, no reload/hot-swap, and
  the server process (services/dashboard_app.py) self-terminates after an
  idle period so it doesn't sit in memory indefinitely between sessions.
- Non-blocking start — spawned detached (its own session, stdio redirected
  to a log file) so the caller returns almost immediately rather than
  waiting for uvicorn's full startup.
"""

import json
import logging
import os
import socket
import subprocess
import sys
import time
from typing import Optional, Tuple

import requests

logger = logging.getLogger("IssueForge.DashboardServerManager")

# An uncommon, high-numbered port unlikely to collide with DDEV (80, 443,
# 3306, 8080, 33000+...) or typical dev servers — tried first for a stable
# link; always verified with a real bind, never assumed available.
PREFERRED_PORT = 8420

LOCK_DIR = os.path.expanduser("~/.issueforge")
LOCK_PATH = os.path.join(LOCK_DIR, "dashboard_server.json")
LOG_PATH = os.path.join(LOCK_DIR, "dashboard_server.log")

_SERVER_SCRIPT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "scripts", "dashboard_server.py",
)

_STARTUP_WAIT_SECONDS = 5
_STARTUP_POLL_INTERVAL = 0.15


def _read_lock() -> Optional[dict]:
    if not os.path.exists(LOCK_PATH):
        return None
    try:
        with open(LOCK_PATH) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def _write_lock(pid: int, port: int) -> None:
    os.makedirs(LOCK_DIR, exist_ok=True)
    with open(LOCK_PATH, "w") as f:
        json.dump({"pid": pid, "port": port}, f)


def _remove_lock() -> None:
    try:
        os.remove(LOCK_PATH)
    except OSError:
        pass


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False
    except PermissionError:
        return True  # process exists, just owned by someone else


def _responds(port: int) -> bool:
    try:
        resp = requests.get(f"http://127.0.0.1:{port}/api/health", timeout=1)
        return resp.status_code == 200
    except Exception:
        return False


def _port_bindable(port: int) -> bool:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", port))
        return True
    except OSError:
        return False


def _find_free_port() -> int:
    """
    PREFERRED_PORT if actually free (verified by a real bind, not assumed) —
    so the dashboard link is stable across sessions — else an OS-assigned
    ephemeral port, which can never collide with anything already running.
    """
    if _port_bindable(PREFERRED_PORT):
        return PREFERRED_PORT
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def get_running_server() -> Optional[Tuple[int, int]]:
    """Return (pid, port) if a live, responding server is already running."""
    lock = _read_lock()
    if not lock:
        return None
    pid, port = lock.get("pid"), lock.get("port")
    if not pid or not port:
        _remove_lock()
        return None
    if not _pid_alive(pid) or not _responds(port):
        logger.info("Stale dashboard server lock (pid=%s port=%s) — cleaning up.", pid, port)
        _remove_lock()
        return None
    return pid, port


def ensure_running() -> Tuple[int, bool]:
    """
    Ensure the dashboard server is running. Returns (port, was_already_running).

    Spawns a detached subprocess if none is live — the caller does not wait
    for full readiness beyond a short bounded poll, keeping this fast.
    """
    existing = get_running_server()
    if existing:
        return existing[1], True

    port = _find_free_port()
    os.makedirs(LOCK_DIR, exist_ok=True)
    log_file = open(LOG_PATH, "a")
    kwargs = {}
    if sys.platform != "win32":
        kwargs["start_new_session"] = True
    else:
        kwargs["creationflags"] = getattr(subprocess, "DETACHED_PROCESS", 0)

    process = subprocess.Popen(
        [sys.executable, _SERVER_SCRIPT, "--port", str(port)],
        stdout=log_file, stderr=log_file, stdin=subprocess.DEVNULL,
        **kwargs,
    )
    _write_lock(process.pid, port)

    deadline = time.time() + _STARTUP_WAIT_SECONDS
    while time.time() < deadline:
        if _responds(port):
            break
        time.sleep(_STARTUP_POLL_INTERVAL)

    return port, False


_STOP_WAIT_SECONDS = 3
_STOP_POLL_INTERVAL = 0.1


def stop_if_running() -> bool:
    """
    Stop the dashboard server if one is running. Returns True if stopped.

    Waits (briefly, bounded) for the process to actually exit before
    returning — sending SIGTERM alone doesn't guarantee the OS has released
    its socket yet. Without this wait, an immediately-following
    ensure_running() can lose the race and fall back to a random ephemeral
    port even though the preferred port is about to free up, defeating the
    point of `restart` giving back the same stable link.
    """
    existing = get_running_server()
    if not existing:
        return False
    pid, _ = existing
    try:
        os.kill(pid, 15)  # SIGTERM
    except OSError:
        pass

    deadline = time.time() + _STOP_WAIT_SECONDS
    while time.time() < deadline and _pid_alive(pid):
        time.sleep(_STOP_POLL_INTERVAL)

    _remove_lock()
    return True
