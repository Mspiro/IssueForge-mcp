#!/usr/bin/env python3
"""
Interactive issue browser — preview, decide, loop.

Shows a full briefing (metadata, patches, MRs, discussion summary) for
each issue the user brings up, then offers three choices:

  [y] Proceed fully  — run analysis + provision environment
  [a] Analysis only  — run analysis, show the plan, then decide on provisioning
  [n] Different issue — ask for another URL/ID and repeat

The loop continues until the user provisions an environment or explicitly quits.

Usage:
    python scripts/preview_issue.py <ISSUE_URL_OR_ID>
    python scripts/preview_issue.py <URL> --proceed   # skip first prompt
"""

import argparse
import json
import os
import subprocess
import sys
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.logger import setup_logging
from services.credential_manager import get_credentials, is_setup_complete
from services.issue_previewer import IssuePreviewer


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _normalise(arg: str) -> str:
    """Accept a bare numeric issue ID as well as a full URL."""
    return f"https://www.drupal.org/node/{arg}" if arg.strip().isdigit() else arg.strip()


def _prompt(msg: str) -> str:
    try:
        return input(msg).strip().lower()
    except (EOFError, KeyboardInterrupt):
        print("\nAborted.")
        sys.exit(0)


def _ask_next_issue() -> Optional[str]:
    """Prompt for another issue URL/ID; return None if the user wants to quit."""
    raw = _prompt("\nEnter another issue URL or ID (or press Enter to quit): ").strip()
    return _normalise(raw) if raw else None


def _run_analysis(issue_url: str, output: str) -> bool:
    """Run analyze_issue.py and write JSON to `output`. Returns True on success."""
    script = os.path.join(os.path.dirname(__file__), "analyze_issue.py")
    print(f"\nRunning full analysis → {output}\n")
    with open(output, "w") as f:
        result = subprocess.run(
            [sys.executable, script, issue_url],
            stdout=f,
            stderr=sys.stderr,
        )
    if result.returncode != 0:
        print(f"Analysis failed (exit {result.returncode}).", file=sys.stderr)
        return False
    print(f"[OK] Analysis complete — {output}")
    return True


def _run_provision(issue_id: str, plan_file: str) -> int:
    script = os.path.join(os.path.dirname(__file__), "provision_env.py")
    print(f"\nProvisioning environment for issue #{issue_id}…\n")
    result = subprocess.run(
        [sys.executable, script, issue_id, plan_file],
        stderr=sys.stderr,
    )
    return result.returncode


def _load_plan(plan_file: str) -> dict:
    try:
        with open(plan_file) as f:
            return json.load(f)
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def main():
    setup_logging()
    parser = argparse.ArgumentParser(
        description="Preview Drupal issues interactively before provisioning"
    )
    parser.add_argument("issue", help="Drupal issue URL or numeric ID")
    parser.add_argument(
        "--proceed",
        action="store_true",
        help="Skip the interactive prompt and immediately run full analysis + provision",
    )
    args = parser.parse_args()

    if not is_setup_complete():
        print(
            "[Tip] Run `python scripts/setup.py` to configure git identity "
            "and a GitLab token for richer MR details.\n"
        )

    creds = get_credentials()
    issue_url = _normalise(args.issue)

    while True:
        # ----------------------------------------------------------------
        # 1. Fetch and show the issue preview
        # ----------------------------------------------------------------
        print(f"\nFetching issue data for {issue_url} …", flush=True)
        try:
            preview = IssuePreviewer.fetch_preview(
                issue_url, gitlab_token=creds["gitlab_token"]
            )
        except Exception as e:
            print(f"Error fetching issue: {e}", file=sys.stderr)
            issue_url = _ask_next_issue()
            if not issue_url:
                sys.exit(0)
            continue

        print(IssuePreviewer.format_report(preview))
        issue_id = str(preview["issue_id"])
        plan_file = f"env_plan_{issue_id}.json"

        # ----------------------------------------------------------------
        # 2. --proceed flag skips the prompt entirely
        # ----------------------------------------------------------------
        if args.proceed:
            if _run_analysis(issue_url, plan_file):
                sys.exit(_run_provision(issue_id, plan_file))
            sys.exit(1)

        # ----------------------------------------------------------------
        # 3. Interactive choice
        # ----------------------------------------------------------------
        print("What would you like to do?")
        print("  [y] Proceed fully   — run analysis + provision environment")
        print("  [a] Analysis only   — see detailed plan, then decide on provisioning")
        print("  [n] Different issue — enter another issue URL/ID")
        print()
        choice = _prompt("Choice [y/a/N]: ")

        # ---- Option y: full flow ----------------------------------------
        if choice in ("y", "yes"):
            if _run_analysis(issue_url, plan_file):
                sys.exit(_run_provision(issue_id, plan_file))
            sys.exit(1)

        # ---- Option a: analysis → summary → ask again ------------------
        elif choice == "a":
            if not _run_analysis(issue_url, plan_file):
                sys.exit(1)

            plan = _load_plan(plan_file)
            print(IssuePreviewer.format_analysis_summary(plan))

            print("What would you like to do now?")
            print("  [y] Provision environment for this issue")
            print("  [n] Pick a different issue")
            print()
            choice2 = _prompt("Choice [y/N]: ")

            if choice2 in ("y", "yes"):
                sys.exit(_run_provision(issue_id, plan_file))
            else:
                print(f"\n[Info] Plan saved to {plan_file} — you can provision later with:")
                print(f"       python scripts/provision_env.py {issue_id} {plan_file}\n")
                issue_url = _ask_next_issue()
                if not issue_url:
                    sys.exit(0)

        # ---- Option n: different issue ----------------------------------
        else:
            issue_url = _ask_next_issue()
            if not issue_url:
                sys.exit(0)


if __name__ == "__main__":
    main()
