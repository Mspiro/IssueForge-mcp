"""
FastAPI app backing the local dashboard server — serves the dashboard's
static assets plus a handful of JSON endpoints, and self-terminates after
an idle period so it never sits in memory indefinitely on a low-end
machine.

Kept deliberately minimal: single-worker, no reload, no websockets/polling
loops beyond one idle-check timer. Refresh runs in FastAPI's threadpool
(plain `def`, not `async def`) so the blocking network calls it makes don't
stall the event loop for other requests (e.g. a health check while a
refresh is in flight).
"""

import logging
import os
import threading
import time
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from pydantic import BaseModel

from services.credential_manager import get_credentials
from services.credit_tracker import CreditTracker
from services.dashboard_builder import DashboardBuilder
from services.dashboard_ledger import DASHBOARD_DIR, DashboardLedger
from services.dashboard_refresh import compute_lifetime_stats, import_credit_history, refresh_all

logger = logging.getLogger("IssueForge.DashboardApp")

IDLE_TIMEOUT_SECONDS = 30 * 60  # self-shutdown after 30 minutes of no requests
IDLE_CHECK_INTERVAL_SECONDS = 60


@asynccontextmanager
async def _lifespan(app: FastAPI):
    thread = threading.Thread(target=_idle_watchdog, daemon=True)
    thread.start()
    yield


app = FastAPI(title="IssueForge Dashboard", docs_url=None, redoc_url=None, lifespan=_lifespan)

_last_activity = time.time()
_lock = threading.Lock()


def _touch():
    global _last_activity
    with _lock:
        _last_activity = time.time()


@app.middleware("http")
async def _track_activity(request, call_next):
    _touch()
    return await call_next(request)


def _idle_watchdog():
    while True:
        time.sleep(IDLE_CHECK_INTERVAL_SECONDS)
        with _lock:
            idle_for = time.time() - _last_activity
        if idle_for > IDLE_TIMEOUT_SECONDS:
            logger.info(
                "Dashboard server idle for %.0fs — shutting down to free resources.",
                idle_for,
            )
            from services.dashboard_server_manager import _remove_lock
            _remove_lock()
            os._exit(0)


@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/api/data")
def get_data():
    data = DashboardLedger.load()
    return JSONResponse(data)


@app.get("/api/lifetime")
def get_lifetime():
    data = DashboardLedger.load()
    return JSONResponse(compute_lifetime_stats(data))


class RefreshResult(BaseModel):
    ok: bool
    message: str


@app.post("/api/refresh")
def post_refresh(force: bool = False):
    """
    Runs synchronously in FastAPI's threadpool (plain def endpoint).

    force: also re-check issues already closed/credited — normally skipped
    since those facts practically never change; POST /api/refresh?force=true
    to override.

    The full per-issue progress log (one line per tracked issue) is logged
    server-side only — for 40+ tracked issues that's too much to dump into
    the page's small status box, so the browser gets a short summary
    instead. Anyone who wants the detailed trace can watch the server's
    stdout/log file, or use `dashboard.py refresh` from the CLI, which
    still prints every line (appropriate for a terminal, not a webpage).
    """
    messages = []
    try:
        data = refresh_all(progress=messages.append, force=force)
        DashboardBuilder.build(data)
        for line in messages:
            logger.info(line)

        issues = data.get("issues", [])
        skipped = sum(1 for m in messages if m.strip().startswith("[Skip]"))
        summary = f"Refreshed {len(issues)} issue(s)."
        if skipped:
            summary += f" {skipped} could not be checked (transient errors, see server log)."
        return RefreshResult(ok=True, message=summary)
    except Exception as e:
        logger.exception("Refresh failed")
        return JSONResponse(
            status_code=500,
            content={"ok": False, "message": f"Refresh failed: {e}"},
        )


@app.post("/api/credits/import")
def post_import_credit_history():
    """
    Opt-in — fetches the user's full drupal.org contribution-record history
    (all projects, all-time) and seeds the ledger with every credited
    issue, not just ones IssueForge itself worked on. Runs in FastAPI's
    threadpool (plain def) since it's a slower, larger fetch than a normal
    refresh.
    """
    creds = get_credentials()
    if not creds.get("drupal_username", ""):
        return JSONResponse(
            status_code=400,
            content={"ok": False, "message": "No Drupal.org username configured. "
                                              "Run scripts/setup.py --force to add it."},
        )
    messages = []
    try:
        data = import_credit_history(progress=messages.append)
        DashboardBuilder.build(data)
        return {"ok": True, "message": "\n".join(messages)}
    except Exception as e:
        logger.exception("Credit import failed")
        return JSONResponse(
            status_code=500,
            content={"ok": False, "message": f"Import failed: {e}"},
        )


@app.get("/dashboard.css")
def get_css():
    return FileResponse(os.path.join(DASHBOARD_DIR, "dashboard.css"), media_type="text/css")


@app.get("/dashboard.js")
def get_js():
    return FileResponse(os.path.join(DASHBOARD_DIR, "dashboard.js"), media_type="application/javascript")


@app.get("/", response_class=HTMLResponse)
def get_index():
    """
    Serve the dashboard page. Always renders fresh from template.html (not
    the pre-built static dashboard.html) so a served page never carries
    stale embedded data — dashboard.js fetches /api/data itself when
    window.DASHBOARD_DATA isn't present, which it won't be here.
    """
    template_path = os.path.join(DASHBOARD_DIR, "template.html")
    with open(template_path) as f:
        html = f.read()
    # No embedded data placeholder substitution here — leave the
    # placeholder comment out entirely; dashboard.js fetches /api/data.
    html = html.replace("<!--DASHBOARD_DATA_SCRIPT-->", "")
    return HTMLResponse(html)
