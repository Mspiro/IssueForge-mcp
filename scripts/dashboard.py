#!/usr/bin/env python3
"""
IssueForge dashboard — a local ledger of every issue worked on, viewable as
a static HTML page (dashboard/dashboard.html) with live status refreshed on
demand. No data leaves this machine except the read-only API calls refresh
itself makes to Drupal.org and GitLab.

    python scripts/dashboard.py record <ISSUE_ID> --project drupal \\
        --title "..." --scenario B --summary "..." --comment-url "..." \\
        [--mr-project drupal --mr-iid 12345]
        Add/update a ledger entry — call this at the end of Step 6.

    python scripts/dashboard.py refresh
        Re-fetch live status (issue status, comment counts, MR/pipeline
        state, credit) for every tracked issue, rebuild dashboard.html.

    python scripts/dashboard.py import-credits
        Import your FULL drupal.org contribution-record history (all
        projects, all-time) as ledger entries — not just issues IssueForge
        itself worked on. Marked source="imported" so they're visually
        distinct from source="issueforge" entries, but sit in the same list.

    python scripts/dashboard.py build
        Rebuild dashboard.html from the current ledger without any network
        calls (e.g. after manually editing ledger.json).

    python scripts/dashboard.py            (no args)
        Ensure the local dashboard server is running (auto-starts it if
        not) and print its http://localhost:<port> link plus a free,
        instant summary from the last-saved ledger — no live network
        calls here; that only happens on refresh.

    python scripts/dashboard.py --no-server
        Same summary, but skip starting/checking the server — just print
        a file:// link to the last-built static dashboard.html.

    python scripts/dashboard.py stop / restart
        Stop, or stop-then-restart, the local server. Restart is needed
        after editing any dashboard*.py source file — the running server
        keeps its already-imported code in memory and won't pick up edits
        until it's restarted.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.credential_manager import get_credentials
from services.dashboard_builder import DashboardBuilder, OUTPUT_PATH
from services.dashboard_ledger import DashboardLedger
from services.dashboard_refresh import (
    compute_lifetime_stats, import_credit_history, refresh_all, today,
)


def cmd_record(args):
    data = DashboardLedger.load()
    entry = DashboardLedger.upsert(
        data,
        issue_id=args.issue_id,
        today=today(),
        project=args.project,
        title=args.title or "",
        issue_url=args.issue_url or "",
        scenario=args.scenario or "",
        action_summary=args.summary or "",
        comment_url=args.comment_url or "",
        mr_project=args.mr_project or "",
        mr_iid=args.mr_iid or "",
    )
    DashboardLedger.save(data)
    DashboardBuilder.build(data)
    print(f"[Dashboard] Recorded issue #{args.issue_id} ({args.project}).")
    print(f"[Dashboard] {OUTPUT_PATH}")
    return 0


def cmd_refresh(args):
    data = refresh_all(progress=print, force=getattr(args, "force", False))
    DashboardBuilder.build(data)
    print(f"[Dashboard] {OUTPUT_PATH}")
    return 0


def cmd_import_credits(args):
    data = import_credit_history(progress=print)
    DashboardBuilder.build(data)
    print(f"[Dashboard] {OUTPUT_PATH}")
    return 0


def cmd_stop(args):
    from services.dashboard_server_manager import stop_if_running
    stopped = stop_if_running()
    print("[Dashboard] Server stopped." if stopped else "[Dashboard] No server was running.")
    return 0


def cmd_restart(args):
    from services.dashboard_server_manager import ensure_running, stop_if_running
    stop_if_running()
    port, _ = ensure_running()
    print(f"[Dashboard] Restarted. Link: http://localhost:{port}")
    return 0


def cmd_build(args):
    data = DashboardLedger.load()
    DashboardBuilder.build(data)
    print(f"[Dashboard] {OUTPUT_PATH}")
    return 0


def _maybe_auto_import_credits(data: dict) -> dict:
    """
    First-run seed: a brand-new user's ledger starts genuinely empty (it's
    gitignored — never shipped with the tool), so without this they'd see
    "0 tracked" until they happened to discover `import-credits` exists on
    their own. If the ledger is empty AND a drupal.org username is already
    configured (from scripts/setup.py), pull the full credit history
    automatically instead. Only fires once — after the first successful
    import the ledger is no longer empty, so this is a no-op on every
    later invocation.
    """
    if DashboardLedger.all_issues(data):
        return data
    if not get_credentials().get("drupal_username"):
        return data
    print("[Dashboard] First run detected — importing your drupal.org credit history...")
    data = import_credit_history(progress=print)
    DashboardBuilder.build(data)
    return data


def cmd_summary(args):
    data = DashboardLedger.load()
    data = _maybe_auto_import_credits(data)
    issues = DashboardLedger.all_issues(data)

    link = f"file://{OUTPUT_PATH}"
    if not getattr(args, "no_server", False):
        try:
            from services.dashboard_server_manager import ensure_running
            port, was_running = ensure_running()
            link = f"http://localhost:{port}"
        except Exception as e:
            print(f"[Dashboard] Could not start local server ({e}) — "
                  f"falling back to the static file.")

    if not issues:
        print("[Dashboard] No issues tracked yet.")
        print(f"[Dashboard] Link: {link}")
        return 0

    new_activity = sum(1 for e in issues if e.get("comments", {}).get("new_since_last_check", 0))
    red = sum(1 for e in issues if e.get("mr", {}).get("pipeline_status") == "failed")
    credited = sum(1 for e in issues if e.get("credit", {}).get("credited"))

    print(f"[Dashboard] {len(issues)} tracked, {new_activity} with new activity, "
          f"{red} red pipeline(s), {credited} credited.")
    print(f"[Dashboard] Link: {link}")

    if getattr(args, "table", False):
        print()
        print(f"{'ID':<9}{'Project':<12}{'Status':<20}{'MR':<10}{'Credit':<10}Title")
        for e in issues:
            mr = e.get("mr", {})
            mr_str = f"!{mr['iid']}" if mr.get("iid") else "-"
            credit_str = "yes" if e.get("credit", {}).get("credited") else "no"
            status = (e.get("status", {}).get("value") or "?")[:19]
            print(f"{e['issue_id']:<9}{e.get('project', ''):<12}{status:<20}{mr_str:<10}{credit_str:<10}{e.get('title', '')[:50]}")
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--no-server", action="store_true",
                        help="Don't start/check the local server; print a file:// link instead")
    parser.add_argument("--table", action="store_true",
                        help="Also print the full per-issue table (default: just the summary line + link)")
    sub = parser.add_subparsers(dest="command")

    p_record = sub.add_parser("record", help="Add/update a ledger entry")
    p_record.add_argument("issue_id")
    p_record.add_argument("--project", default="drupal")
    p_record.add_argument("--title", default="")
    p_record.add_argument("--issue-url", default="")
    p_record.add_argument("--scenario", default="", choices=["", "A", "B", "C", "D"])
    p_record.add_argument("--summary", default="")
    p_record.add_argument("--comment-url", default="")
    p_record.add_argument("--mr-project", default="")
    p_record.add_argument("--mr-iid", default="")
    p_record.set_defaults(func=cmd_record)

    p_refresh = sub.add_parser("refresh", help="Re-fetch live status for all tracked issues")
    p_refresh.add_argument("--force", action="store_true",
                           help="Also re-check issues already closed/credited "
                                "(normally skipped — they rarely change)")
    p_refresh.set_defaults(func=cmd_refresh)

    p_import = sub.add_parser("import-credits",
                              help="Import full drupal.org credit history as ledger entries")
    p_import.set_defaults(func=cmd_import_credits)

    p_stop = sub.add_parser("stop", help="Stop the local dashboard server if running")
    p_stop.set_defaults(func=cmd_stop)

    p_restart = sub.add_parser(
        "restart",
        help="Stop and restart the dashboard server — needed after any "
             "dashboard*.py source change, since the running process keeps "
             "its already-imported code in memory and won't pick up edits",
    )
    p_restart.set_defaults(func=cmd_restart)

    p_build = sub.add_parser("build", help="Rebuild dashboard.html, no network calls")
    p_build.set_defaults(func=cmd_build)

    args = parser.parse_args()
    if args.command is None:
        return cmd_summary(args)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main() or 0)
