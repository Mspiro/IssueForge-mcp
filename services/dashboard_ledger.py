"""
Dashboard ledger — the persistent local record of every issue IssueForge has
worked on, one entry per issue. Backs the local dashboard (scripts/dashboard.py).

Lives at dashboard/ledger.json in the IssueForge install directory — a
single folder alongside the dashboard's template.html/dashboard.css/
dashboard.js (see scripts/dashboard.py), gitignored since it's per-user data,
not tool source.

No timestamps are auto-generated inside this module using wall-clock time
implicitly beyond what's passed in — callers supply `today` explicitly so
this stays trivially testable.
"""

import json
import logging
import os
from typing import Dict, List, Optional

logger = logging.getLogger("IssueForge.DashboardLedger")

DASHBOARD_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "dashboard")
LEDGER_PATH = os.path.join(DASHBOARD_DIR, "ledger.json")

_EMPTY = {"issues": [], "generated_at": None}


class DashboardLedger:

    @staticmethod
    def load(path: str = LEDGER_PATH) -> Dict:
        if not os.path.exists(path):
            return {"issues": [], "generated_at": None}
        try:
            with open(path) as f:
                data = json.load(f)
            data.setdefault("issues", [])
            data.setdefault("generated_at", None)
            # Backfill "source" on entries written before that field existed —
            # every pre-existing entry was, by definition, real IssueForge work.
            for entry in data["issues"]:
                entry.setdefault("source", "issueforge")
            return data
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Could not read ledger at %s: %s — starting fresh.", path, e)
            return {"issues": [], "generated_at": None}

    @staticmethod
    def save(data: Dict, path: str = LEDGER_PATH) -> None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
            f.write("\n")

    @staticmethod
    def find(data: Dict, issue_id: str) -> Optional[Dict]:
        for entry in data.get("issues", []):
            if str(entry.get("issue_id")) == str(issue_id):
                return entry
        return None

    @staticmethod
    def upsert(
        data: Dict,
        issue_id: str,
        today: str,
        project: str = "drupal",
        title: str = "",
        issue_url: str = "",
        scenario: str = "",
        action_summary: str = "",
        comment_url: str = "",
        mr_project: str = "",
        mr_iid: str = "",
        source: str = "issueforge",
    ) -> Dict:
        """
        Create or update the ledger entry for one issue. `today` is an
        ISO date string ("2026-07-17") supplied by the caller — this module
        never calls date.today() itself, so it stays deterministic in tests.

        `source` distinguishes issues IssueForge actually worked
        ("issueforge") from ones seeded purely from the drupal.org credit
        history ("imported") — set only when CREATING an entry; an
        existing entry's source is never overwritten, so importing credit
        history can't relabel an issue IssueForge genuinely worked on, and
        an issue first seen via import that's later really worked on keeps
        its history (callers should re-upsert with source="issueforge" to
        upgrade it explicitly — see DashboardLedger.promote_to_worked()).

        Returns the (new or updated) entry dict.
        """
        entry = DashboardLedger.find(data, issue_id)
        if entry is None:
            entry = {
                "issue_id": str(issue_id),
                "project": project,
                "title": title,
                "issue_url": issue_url or f"https://www.drupal.org/project/{project}/issues/{issue_id}",
                "first_worked": today,
                "last_worked": today,
                "scenario": scenario,
                "action_summary": action_summary,
                "comment_url": comment_url,
                "source": source,
                "mr": {"project": mr_project, "iid": mr_iid, "state": None,
                       "pipeline_status": None, "pipeline_url": None},
                "status": {"value": None, "checked_at": None},
                "comments": {"count_at_last_check": None, "checked_at": None},
                "credit": {"credited": False, "checked_at": None},
            }
            data.setdefault("issues", []).append(entry)
        else:
            entry["last_worked"] = today
            if title:
                entry["title"] = title
            if scenario:
                entry["scenario"] = scenario
            if action_summary:
                entry["action_summary"] = action_summary
                # Real IssueForge work happening on an issue first seen via
                # credit import — upgrade its identity, never downgrade.
                entry["source"] = "issueforge"
            if comment_url:
                entry["comment_url"] = comment_url
            if mr_project and mr_iid:
                entry["mr"]["project"] = mr_project
                entry["mr"]["iid"] = mr_iid
        return entry

    @staticmethod
    def update_live_status(entry: Dict, *, checked_at: str, status: Optional[str] = None,
                           comment_count: Optional[int] = None,
                           mr_state: Optional[str] = None,
                           pipeline_status: Optional[str] = None,
                           pipeline_url: Optional[str] = None,
                           credited: Optional[bool] = None) -> None:
        """Apply freshly-fetched live data onto an existing entry, in place."""
        if status is not None:
            entry["status"]["value"] = status
            entry["status"]["checked_at"] = checked_at
        if comment_count is not None:
            entry["comments"]["count_at_last_check"] = comment_count
            entry["comments"]["checked_at"] = checked_at
        if mr_state is not None:
            entry["mr"]["state"] = mr_state
        if pipeline_status is not None:
            entry["mr"]["pipeline_status"] = pipeline_status
        if pipeline_url is not None:
            entry["mr"]["pipeline_url"] = pipeline_url
        if credited is not None:
            entry["credit"]["credited"] = credited
            entry["credit"]["checked_at"] = checked_at

    @staticmethod
    def all_issues(data: Dict) -> List[Dict]:
        return data.get("issues", [])
