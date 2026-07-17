"""
CreditTracker — checks the drupal.org Contribution Records system to see
whether the user has been credited on tracked issues.

Credit was moved out of issue comments into its own "Contribution Record"
content type, queryable via a public, unauthenticated GET endpoint:

    https://www.drupal.org/contribution-records-by-user
        ?username=USERNAME&machine_name=PROJECT&months=N

Each record's `field_source_link.uri` links back to the issue node it
credits (e.g. "https://www.drupal.org/node/2727281"), and on drupal.org the
issue ID in a project's issue URL IS that node ID — so matching a tracked
issue to a credit record is a plain integer comparison, no fuzzy text
matching or scraping required.

Timing note: a credit record is created when a maintainer commits the fix,
not when a review comment is posted — so "not yet credited" is the expected,
correct answer for most actively-open issues, not a tracking failure.
"""

import logging
import re
import time
from typing import Dict, List, Optional, Set, Tuple

import requests

logger = logging.getLogger("IssueForge.CreditTracker")

_BASE_URL = "https://www.drupal.org/contribution-records-by-user"
_NODE_ID_PATTERN = re.compile(r"/node/(\d+)")
_MAX_PAGES = 5  # safety cap for scoped (tracked-issue) lookups
_MAX_PAGES_FULL_HISTORY = 20  # a larger, still-bounded cap for the opt-in
                              # "lifetime credit history" view — prolific
                              # contributors can have hundreds of records,
                              # this stays a deliberate cap, never unbounded
_TIMEOUT = 15


class CreditTracker:

    @staticmethod
    def _fetch_page(username: str, project: Optional[str], months: Optional[int],
                    page: int) -> Optional[dict]:
        params = {"username": username, "page": page}
        if project:
            params["machine_name"] = project
        if months:
            params["months"] = months
        try:
            resp = requests.get(_BASE_URL, params=params, timeout=_TIMEOUT)
            if resp.status_code != 200:
                logger.warning(
                    "Contribution records HTTP %d for username=%s page=%d",
                    resp.status_code, username, page,
                )
                return None
            return resp.json()
        except Exception as e:
            logger.warning("Contribution records request failed: %s", e)
            return None

    @staticmethod
    def _fetch_all_entries(
        username: str, project: Optional[str], months: Optional[int], max_pages: int
    ) -> Tuple[List[dict], bool]:
        """
        Raw JSON:API entries across up to `max_pages` pages. Shared by both
        the scoped node-ID lookup and the full lifetime-record view so
        there is one pagination implementation, not two.

        Returns (entries, truncated) — truncated is True only when the page
        cap was hit while a "next" link still existed, i.e. there is
        provably more data beyond what was fetched. This is exact, not a
        guess based on assumed page sizes.
        """
        entries: List[dict] = []
        page = 0
        while page < max_pages:
            data = CreditTracker._fetch_page(username, project, months, page)
            if not data:
                return entries, False
            page_entries = data.get("data", [])
            if not page_entries:
                return entries, False
            entries.extend(page_entries)
            has_next = bool((data.get("links") or {}).get("next"))
            if not has_next:
                return entries, False
            page += 1
            time.sleep(0.2)  # be polite between pages
        # Loop exited because page reached max_pages — check whether the
        # last page fetched still pointed to more.
        return entries, True

    @staticmethod
    def _entry_node_id(entry: dict) -> Optional[int]:
        attrs = entry.get("attributes", {}) if isinstance(entry, dict) else {}
        source_link = attrs.get("field_source_link") or {}
        uri = source_link.get("uri", "") if isinstance(source_link, dict) else ""
        m = _NODE_ID_PATTERN.search(uri)
        return int(m.group(1)) if m else None

    @staticmethod
    def fetch_credited_node_ids(
        username: str, project: Optional[str] = None, months: Optional[int] = None
    ) -> Set[int]:
        """
        Return the set of issue node IDs the given drupal.org username has a
        contribution record for (optionally scoped to one project, and to
        the last `months` months). Empty set on any failure — never raises,
        since credit lookups must never block the rest of the dashboard.
        """
        if not username:
            return set()
        entries, _truncated = CreditTracker._fetch_all_entries(
            username, project, months, _MAX_PAGES
        )
        return {nid for e in entries if (nid := CreditTracker._entry_node_id(e)) is not None}

    @staticmethod
    def fetch_all_credit_records(
        username: str, months: Optional[int] = None
    ) -> Dict:
        """
        Fetch the user's full lifetime contribution-record history across
        ALL projects (opt-in — this is the "Load full credit history"
        action, deliberately separate from the per-refresh scoped check
        since it can be a large, slower fetch for prolific contributors).

        Returns {"records": [...], "truncated": bool} where each record is
        {"title", "project", "node_id", "issue_url", "created"}. `truncated`
        is True if the page cap was hit — more records may exist beyond
        what's returned; never silently pretend the list is complete.
        """
        if not username:
            return {"records": [], "truncated": False}

        entries, truncated = CreditTracker._fetch_all_entries(
            username, None, months, _MAX_PAGES_FULL_HISTORY
        )
        records = []
        for entry in entries:
            attrs = entry.get("attributes", {}) if isinstance(entry, dict) else {}
            source_link = attrs.get("field_source_link") or {}
            uri = source_link.get("uri", "") if isinstance(source_link, dict) else ""
            node_id = CreditTracker._entry_node_id(entry)
            records.append({
                "title": attrs.get("title", ""),
                "project": attrs.get("field_project_name", ""),
                "node_id": node_id,
                "issue_url": uri,
                "created": attrs.get("created", ""),
            })

        return {"records": records, "truncated": truncated}

    @staticmethod
    def check_credits(
        username: str, issues: List[Dict], months: Optional[int] = None
    ) -> Dict[str, bool]:
        """
        Check credit status for a batch of tracked issues at once.

        issues: list of {"issue_id": "2727281", "project": "drupal", ...}
        Groups by project to minimize requests (one request-chain per
        distinct project rather than one per issue).

        Returns {issue_id: bool} — True if a contribution record exists for
        that issue. Issues in projects that fail to fetch are simply absent
        from a positive result (treated as not-yet-credited), never crash.
        """
        if not username or not issues:
            return {}

        by_project: Dict[str, List[str]] = {}
        for issue in issues:
            by_project.setdefault(issue.get("project", "drupal"), []).append(
                str(issue.get("issue_id", ""))
            )

        result: Dict[str, bool] = {}
        for project, issue_ids in by_project.items():
            credited_nodes = CreditTracker.fetch_credited_node_ids(
                username, project=project, months=months
            )
            for issue_id in issue_ids:
                if not issue_id:
                    continue
                try:
                    result[issue_id] = int(issue_id) in credited_nodes
                except ValueError:
                    result[issue_id] = False

        return result
