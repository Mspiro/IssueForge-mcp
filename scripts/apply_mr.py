#!/usr/bin/env python3
"""
Apply a Merge Request (or patch) to the provisioned environment, then run
the full regression check suite.

Usage:
    # Apply a specific MR by URL
    python scripts/apply_mr.py <issue_id> --mr-url https://git.drupalcode.org/project/drupal/-/merge_requests/3456

    # Apply a specific patch by ID (same regression check follows)
    python scripts/apply_mr.py <issue_id> --patch-id 7130901

    # Apply all MRs detected in env_plan.json
    python scripts/apply_mr.py <issue_id> --from-plan env_plan.json

    # Skip regression check (faster, useful during development)
    python scripts/apply_mr.py <issue_id> --mr-url <url> --no-regression
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.logger import setup_logging
from services.credential_manager import get_credentials
from services.gitlab_mr_client import GitlabMrClient
from services.patch_applier import PatchApplier
from services.git_workspace_manager import GitWorkspaceManager
from services.regression_checker import RegressionChecker
from config import ENVIRONMENTS_DIR


def _env_path(issue_id: str) -> str:
    return os.path.join(ENVIRONMENTS_DIR, f"env_{issue_id}")


def apply_and_check(
    env_path: str,
    diff_path: str,
    issue_id: str,
    label: str,
    run_regression: bool,
) -> dict:
    """Apply diff_path as a patch, then run regression check."""
    print(f"\n[Apply] {label}")

    # Apply using the existing patch applier (git apply with strategy fallbacks)
    apply_result = PatchApplier.apply_patch_file(env_path, diff_path)
    if not apply_result["success"]:
        print(f"[FAIL] Could not apply: {apply_result['message']}")
        return {"applied": False, "label": label, "error": apply_result["message"]}

    print(f"[OK] Applied successfully.")

    # Show git diff stat so user sees what changed
    status = GitWorkspaceManager.get_status(env_path)
    if status["diff_stat"]:
        print("\n--- Changes applied ---")
        print(status["diff_stat"])
        print("-----------------------")

    if not run_regression:
        return {"applied": True, "label": label, "regression": None}

    print("\n[Regression] Running checks...")
    reg_results = RegressionChecker.run_all(env_path, status["changed_files"])
    print(RegressionChecker.format_report(reg_results))

    return {
        "applied": True,
        "label": label,
        "changed_files": status["changed_files"],
        "regression": reg_results,
    }


def main():
    setup_logging()
    parser = argparse.ArgumentParser(
        description="Apply an MR or patch and run regression checks"
    )
    parser.add_argument("issue_id", help="Drupal issue ID")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--mr-url", help="GitLab MR URL to apply")
    group.add_argument("--patch-id", help="Drupal.org patch file ID to apply")
    group.add_argument("--from-plan", metavar="ENV_PLAN_JSON",
                       help="Apply all MRs detected in env_plan.json")
    parser.add_argument("--no-regression", action="store_true",
                        help="Skip regression checks")
    args = parser.parse_args()

    env_path = _env_path(args.issue_id)
    if not os.path.exists(env_path):
        print(f"Error: environment not found at {env_path}", file=sys.stderr)
        sys.exit(1)

    creds = get_credentials()
    mr_client = GitlabMrClient(token=creds["gitlab_token"])
    drupal_username = creds.get("drupal_username", "")
    drupal_password = creds.get("drupal_password", "")

    results = []

    # ------------------------------------------------------------------
    # Case 1: single MR by URL
    # ------------------------------------------------------------------
    if args.mr_url:
        import re
        m = re.search(
            r"git\.drupalcode\.org/project/([^/]+)/-/merge_requests/(\d+)",
            args.mr_url
        )
        if not m:
            print(f"Error: cannot parse MR URL: {args.mr_url}", file=sys.stderr)
            sys.exit(1)
        project, mr_iid = m.group(1), m.group(2)
        diff_filename = f"mr_{project}_{mr_iid}.patch"
        diff_path = os.path.join(env_path, diff_filename)

        downloaded = mr_client.download_mr_diff(project, mr_iid, diff_path)
        if not downloaded:
            print(f"Error: failed to download MR diff for {args.mr_url}", file=sys.stderr)
            sys.exit(1)

        details = mr_client.get_mr_details(project, mr_iid) or {}
        label = f"MR !{mr_iid} — {details.get('title', 'untitled')} [{details.get('state', '?')}]"
        results.append(apply_and_check(env_path, diff_path, args.issue_id, label,
                                       not args.no_regression))

    # ------------------------------------------------------------------
    # Case 2: patch by ID
    # ------------------------------------------------------------------
    elif args.patch_id:
        patch_path = PatchApplier.download_if_missing(env_path, args.patch_id)
        results.append(apply_and_check(env_path, patch_path, args.issue_id,
                                       f"Patch {args.patch_id}",
                                       not args.no_regression))

    # ------------------------------------------------------------------
    # Case 3: all MRs from env_plan.json
    # ------------------------------------------------------------------
    elif args.from_plan:
        if not os.path.exists(args.from_plan):
            print(f"Error: plan file not found: {args.from_plan}", file=sys.stderr)
            sys.exit(1)
        with open(args.from_plan) as f:
            plan = json.load(f)
        mrs = plan.get("detected_mrs", [])
        if not mrs:
            print("[Info] No MRs detected in the plan — nothing to apply.")
            sys.exit(0)
        print(f"[Plan] Found {len(mrs)} MR(s) to apply.")
        for mr in mrs:
            project = mr.get("project", "drupal")
            mr_iid = mr.get("mr_iid", "")
            diff_filename = f"mr_{project}_{mr_iid}.patch"
            diff_path = os.path.join(env_path, diff_filename)
            if not os.path.exists(diff_path):
                downloaded = mr_client.download_mr_diff(project, mr_iid, diff_path)
                if not downloaded:
                    print(f"[Skip] Could not download diff for MR !{mr_iid}")
                    continue
            label = f"MR !{mr_iid} ({project}) — {mr.get('title', 'untitled')}"
            results.append(apply_and_check(env_path, diff_path, args.issue_id, label,
                                           not args.no_regression))

    # Summary
    applied = sum(1 for r in results if r.get("applied"))
    passed = sum(1 for r in results
                 if r.get("regression", {}) and r["regression"].get("overall_passed", True))
    print(f"\n[Summary] {applied}/{len(results)} applied. {passed}/{applied} passed regression.")

    any_failed = any(
        not r.get("applied") or
        (r.get("regression") and not r["regression"].get("overall_passed"))
        for r in results
    )

    # Print next steps so Claude can guide the user
    status = GitWorkspaceManager.get_status(env_path)
    branch = GitWorkspaceManager._git(
        ["rev-parse", "--abbrev-ref", "HEAD"], env_path
    ).stdout.strip() or "issue-work"
    issue_page = f"https://www.drupal.org/project/drupal/issues/{args.issue_id}"

    print()
    print("=" * 65)
    print("  NEXT STEPS")
    print("=" * 65)
    if status["has_changes"]:
        print(f"  Branch     : {branch}")
        print(f"  Issue page : {issue_page}")
        print()
        print("  To submit as a Merge Request:")
        print("    1. Open the issue page above")
        print("    2. Scroll to 'Merge requests' section")
        print("    3. Click 'Get push access' (creates your issue fork)")
        print("    4. Then push:")
        print(f"       git -C {env_path} add -A")
        print(f"       git -C {env_path} commit -m 'Apply fix for #{args.issue_id}'")
        print(f"       git -C {env_path} push issue HEAD:{branch}")
        print()
        print("  Or to save as a patch file:")
        print(f"       git -C {env_path} diff HEAD > {args.issue_id}.patch")
    else:
        print("  No uncommitted changes — nothing to submit.")
    print("=" * 65)

    if any_failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
