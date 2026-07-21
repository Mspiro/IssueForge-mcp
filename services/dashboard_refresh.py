"""
Shared refresh logic for the dashboard — the single place that re-fetches
live status (issue status, comment counts, MR/pipeline state, credit) for
every tracked issue. Used by BOTH scripts/dashboard.py (CLI) and the local
server's /api/refresh route, so there is exactly one implementation.
"""

import datetime
import logging
from typing import Dict, Optional

from services.credential_manager import get_credentials
from services.credit_tracker import CreditTracker
from services.dashboard_ledger import DashboardLedger
from services.drupal_api_client import DrupalAPIClient
from services.gitlab_mr_client import GitlabMrClient

logger = logging.getLogger("IssueForge.DashboardRefresh")

# A closed/fixed issue's status is a practical dead-end on drupal.org — it
# essentially never changes again (reopens happen, but rarely enough that
# defaulting to "assume stable" is the right tradeoff for a personal
# dashboard). Re-fetching these on every refresh scales refresh cost with
# TOTAL lifetime history instead of with actual in-flight work — the exact
# waste this constant exists to avoid. Shared with compute_lifetime_stats()
# so "resolved" and "considered stable, skip re-checking" stay in sync.
TERMINAL_STATUSES = {
    "fixed", "closed (fixed)", "closed (duplicate)",
    "closed (works as designed)", "closed (won't fix)",
}


def today() -> str:
    return datetime.date.today().isoformat()


def _refresh_entry(entry: Dict, api_client: DrupalAPIClient, mr_client: GitlabMrClient,
                    day: str) -> Dict[str, Optional[str]]:
    """
    Re-fetch live status (issue status, comment count, MR state/pipeline)
    for ONE ledger entry and apply it in place. Shared by refresh_all()
    (loops this over every tracked issue) and refresh_after_record() (calls
    it once, right after Step 7 records a session, so the issue just
    worked shows real status immediately instead of "unknown" until the
    next full refresh).

    Returns {"status": ..., "mr_state": ..., "pipeline_status": ...,
    "pipeline_label": ..., "status_error": ...} for logging/progress
    messages — the entry itself already has the update applied.
    "status_error" is the exception message when the issue-status fetch
    failed, else None — refresh_all() surfaces this as a "[Skip]" progress
    line, which dashboard_app.py's /api/refresh counts for its summary.
    """
    issue_id = entry["issue_id"]
    project = entry.get("project", "drupal")
    issue_url = entry.get("issue_url") or f"https://www.drupal.org/project/{project}/issues/{issue_id}"

    status_value = None
    comment_count = None
    status_error = None
    try:
        metadata = api_client.get_issue_metadata(issue_url)
        status_value = metadata.get("status")
        comment_count = len(metadata.get("comment_ids", []))
    except Exception as e:
        logger.warning("Could not fetch issue status for #%s: %s", issue_id, e)
        status_error = str(e)

    prior_count = entry.get("comments", {}).get("count_at_last_check")
    new_since = None
    if comment_count is not None and prior_count is not None:
        new_since = max(0, comment_count - prior_count)

    pipeline_status = None
    pipeline_label = None
    pipeline_url = None
    mr_state = None
    mr = entry.get("mr", {})
    if mr.get("project") and mr.get("iid"):
        details = mr_client.get_mr_details(mr["project"], mr["iid"])
        if details:
            mr_state = details.get("state")
            source_branch = details.get("source_branch")
            source_project_id = details.get("source_project_id")
            # Pipelines run in the SOURCE project (the issue fork),
            # not the target project this MR is opened against.
            if source_branch and source_project_id:
                pipeline = mr_client.get_latest_pipeline_status(
                    source_project_id, source_branch
                )
                if pipeline:
                    pipeline_status = pipeline.get("status")
                    pipeline_label = pipeline.get("detailed_label")
                    pipeline_url = pipeline.get("web_url")

    DashboardLedger.update_live_status(
        entry,
        checked_at=day,
        status=status_value,
        comment_count=comment_count,
        mr_state=mr_state,
        pipeline_status=pipeline_status,
        pipeline_label=pipeline_label,
        pipeline_url=pipeline_url,
    )
    if new_since is not None:
        entry.setdefault("comments", {})["new_since_last_check"] = new_since

    return {
        "status": status_value,
        "mr_state": mr_state,
        "pipeline_status": pipeline_status,
        "pipeline_label": pipeline_label,
        "new_since": new_since,
        "status_error": status_error,
    }


def refresh_after_record(issue_id: str) -> str:
    """
    Best-effort, single-issue live refresh — called right after
    scripts/dashboard.py record so the just-worked issue shows real status
    (issue status, MR state, pipeline) immediately instead of "unknown"
    until the next full refresh. Deliberately scoped to ONE issue: a full
    refresh_all() would re-check every tracked issue's live state on every
    single Step 7 call, which scales with lifetime history instead of the
    one issue that actually just changed.

    Never raises — network failures here are non-fatal to Step 7's
    bookkeeping; on any error this returns a short message and leaves the
    entry's fields as record() set them (i.e. still "unknown" until the
    next refresh).
    """
    data = DashboardLedger.load()
    entry = DashboardLedger.find(data, issue_id)
    if entry is None:
        return "not found in ledger"

    try:
        creds = get_credentials()
        api_client = DrupalAPIClient()
        mr_client = GitlabMrClient(token=creds.get("gitlab_token", ""))
        result = _refresh_entry(entry, api_client, mr_client, today())
        DashboardLedger.save(data)
        summary = f"status={result['status'] or '?'}"
        if entry.get("mr", {}).get("iid"):
            pipeline_desc = result["pipeline_label"] or result["pipeline_status"] or "?"
            summary += f" mr!{entry['mr']['iid']}={result['mr_state'] or '?'}/{pipeline_desc}"
        return summary
    except Exception as e:
        logger.warning("Could not live-refresh #%s after record: %s", issue_id, e)
        return f"skipped ({e})"


def refresh_all(progress=None, force: bool = False) -> Dict:
    """
    Re-fetch live status for every tracked issue and persist the ledger.

    progress: optional callable(str) called with a one-line status message
    per issue as it's processed — lets callers (CLI print, server log) show
    progress without this function knowing about stdout vs. logging.

    force: bypass the terminal-status/already-credited skip and re-check
    everything (in case a closed issue was reopened, or you just don't
    trust the cache). Default False — the whole point of this function
    scaling with active work, not lifetime history, depends on it.

    Returns the updated ledger data dict. Never raises — a failure on any
    one issue or data source is logged/reported via `progress` and treated
    as "no update for that field", not a crash of the whole refresh.
    """
    def _report(msg: str):
        if progress:
            progress(msg)
        else:
            logger.info(msg)

    data = DashboardLedger.load()
    issues = DashboardLedger.all_issues(data)
    if not issues:
        _report("No tracked issues yet — nothing to refresh.")
        return data

    creds = get_credentials()
    api_client = DrupalAPIClient()
    mr_client = GitlabMrClient(token=creds.get("gitlab_token", ""))
    drupal_username = creds.get("drupal_username", "")
    day = today()

    _report(f"Refreshing {len(issues)} tracked issue(s)...")

    skipped_terminal = 0
    for entry in issues:
        issue_id = entry["issue_id"]

        current_status = (entry.get("status", {}).get("value") or "").lower()
        if not force and current_status in TERMINAL_STATUSES:
            # Closed/fixed issues don't change, and any MR they had is
            # already merged — nothing here is worth a live check.
            skipped_terminal += 1
            continue

        result = _refresh_entry(entry, api_client, mr_client, day)
        if result["status_error"]:
            _report(f"  [Skip] #{issue_id}: could not fetch issue status ({result['status_error']})")
            continue
        mr = entry.get("mr", {})
        pipeline_desc = result["pipeline_label"] or result["pipeline_status"]
        _report(
            f"  #{issue_id}: status={result['status'] or '?'}"
            + (f" mr!{mr['iid']}={result['mr_state']}/{pipeline_desc}" if mr.get("iid") else "")
            + (f" (+{result['new_since']} new comments)" if result["new_since"] else "")
        )

    if skipped_terminal:
        _report(f"{skipped_terminal} issue(s) already in a terminal state — skipped "
                f"(pass force=True to re-check anyway).")

    # Credit is a one-way, permanent fact on drupal.org — once an issue is
    # credited it never becomes un-credited, so re-checking an issue that's
    # already credited=True is pure waste. Only issues not yet confirmed
    # credited (in practice: currently in-flight IssueForge work) need a
    # live check. This is what keeps refresh cheap even with 40+ imported
    # historical credits sitting in the ledger — it scales with active
    # work, not with total lifetime history.
    uncredited = issues if force else [e for e in issues if not e.get("credit", {}).get("credited")]
    if not uncredited:
        _report("All tracked issues already credited — nothing to check.")
    elif drupal_username:
        _report(f"Checking credit records for @{drupal_username} "
                f"({len(uncredited)} not-yet-credited issue(s))...")
        credit_results = CreditTracker.check_credits(
            drupal_username,
            [{"issue_id": e["issue_id"], "project": e.get("project", "drupal")} for e in uncredited],
        )
        for entry in uncredited:
            credited = credit_results.get(entry["issue_id"], False)
            DashboardLedger.update_live_status(entry, checked_at=day, credited=credited)
    else:
        _report("No drupal.org username configured — skipping credit check.")

    data["generated_at"] = day
    DashboardLedger.save(data)
    _report("Refresh complete.")
    return data


def import_credit_history(progress=None) -> Dict:
    """
    Pull the user's full drupal.org contribution-record history (all
    projects, all-time) and seed the ledger with every credited issue —
    not just what IssueForge itself worked on. This is what makes the
    dashboard a complete personal contribution record rather than only a
    log of IssueForge sessions.

    Each imported issue is marked source="imported" (vs "issueforge" for
    issues actually worked through this tool) so the two are visually
    distinguishable but sit in the SAME tracked-issues list — re-running
    `refresh` afterward will fetch live status for the newly-imported
    issues exactly like any other tracked issue, since refresh_all()
    iterates the whole ledger with no special-casing needed.

    Returns the updated ledger data. Never raises.
    """
    def _report(msg: str):
        if progress:
            progress(msg)
        else:
            logger.info(msg)

    creds = get_credentials()
    username = creds.get("drupal_username", "")
    data = DashboardLedger.load()

    if not username:
        _report("No drupal.org username configured — cannot import credit "
                "history. Run scripts/setup.py --force to add it.")
        return data

    _report(f"Fetching full credit history for @{username}...")
    result = CreditTracker.fetch_all_credit_records(username)
    records = result.get("records", [])
    day = today()

    imported, updated = 0, 0
    for record in records:
        node_id = record.get("node_id")
        if node_id is None:
            continue
        issue_id = str(node_id)
        project = record.get("project", "drupal")
        existed_before = DashboardLedger.find(data, issue_id) is not None
        entry = DashboardLedger.upsert(
            data,
            issue_id=issue_id,
            today=day,
            project=project,
            title=record.get("title", ""),
            # NOT record.get("issue_url") — the credit record's
            # field_source_link.uri is a bare "/node/<id>" link.
            # DrupalAPIClient.get_issue_metadata() requires the canonical
            # "/project/<name>/issues/<id>" form (it regexes for both
            # "/project/" and "/issues/"), so a raw node URL fails refresh
            # with "Invalid Drupal issue URL" for every imported issue.
            # DashboardLedger.upsert() already builds this canonical form
            # by default when issue_url is omitted.
            source="imported",
        )
        DashboardLedger.update_live_status(entry, checked_at=day, credited=True)
        if existed_before:
            updated += 1
        else:
            imported += 1

    DashboardLedger.save(data)
    msg = f"Imported {imported} new issue(s), updated credit status on {updated} existing."
    if result.get("truncated"):
        msg += " More records exist beyond the fetch cap — this is a partial import."
    _report(msg)
    return data


def compute_lifetime_stats(data: Dict) -> Dict:
    """
    Free, local, always-available aggregate stats computed purely from the
    ledger — no network calls. Available via GET /api/lifetime; not shown
    on the main dashboard page by default.
    """
    issues = DashboardLedger.all_issues(data)
    resolved = sum(
        1 for e in issues
        if (e.get("status", {}).get("value") or "").lower() in TERMINAL_STATUSES
    )
    credited = sum(1 for e in issues if e.get("credit", {}).get("credited"))
    return {
        "issues_tracked": len(issues),
        "issues_resolved": resolved,
        "issues_credited": credited,
    }
