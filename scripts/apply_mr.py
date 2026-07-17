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
import subprocess
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


def _changed_files_from_diff(diff_path: str) -> list:
    """
    Extract changed file paths from a unified diff ("+++ b/<path>" lines).
    Used in --checkout mode, where the MR's changes are commits rather than
    a working-tree diff, so `git status` can't list them (and the shallow
    clone may not contain the merge-base needed for `git diff base...HEAD`).
    """
    files = []
    try:
        with open(diff_path, errors="ignore") as f:
            for line in f:
                if line.startswith("+++ b/"):
                    files.append(line[6:].strip().split("\t")[0])
    except OSError:
        pass
    return files


def _to_env_relative(changed_files: list, env_path: str, target_root: str) -> list:
    """
    Re-anchor repo-relative paths from the nested contrib clone onto the
    Drupal root (e.g. "src/EncryptService.php" →
    "modules/contrib/encrypt/src/EncryptService.php"), so the regression
    checker's path heuristics and PHPUnit invocations (which run from the
    Drupal root) can see them.
    """
    if os.path.realpath(target_root) == os.path.realpath(env_path):
        return changed_files
    prefix = os.path.relpath(target_root, env_path)
    return [os.path.join(prefix, f) for f in changed_files]


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

    # Diff/status must come from the repo the patch landed in — for contrib
    # issues that's the nested modules/contrib/<name> clone, not the outer
    # core repo (whose diff would only show composer/scaffold noise).
    target_root = apply_result.get("target_root", env_path)
    status = GitWorkspaceManager.get_status(target_root)
    if status["diff_stat"]:
        print("\n--- Changes applied ---")
        print(status["diff_stat"])
        print("-----------------------")

    if not run_regression:
        return {"applied": True, "label": label, "regression": None,
                "target_root": target_root}

    print("\n[Regression] Running checks...")
    env_relative_files = _to_env_relative(
        status["changed_files"], env_path, target_root
    )
    reg_results = RegressionChecker.run_all(env_path, env_relative_files)
    print(RegressionChecker.format_report(reg_results))

    return {
        "applied": True,
        "label": label,
        "changed_files": env_relative_files,
        "regression": reg_results,
        "target_root": target_root,
    }


def checkout_and_check(
    env_path: str,
    diff_path: str,
    mr_details: dict,
    label: str,
    run_regression: bool,
) -> dict:
    """
    Check out the MR's own branch from the issue fork (the drupal.org flow
    for updating an existing MR), then run regression checks on it.
    The downloaded diff is used only to list the MR's changed files.
    """
    source_branch = mr_details.get("source_branch")
    if not source_branch:
        print("[FAIL] MR details unavailable (no source branch) — cannot checkout.")
        return {"applied": False, "label": label,
                "error": "No source branch in MR details."}

    print(f"\n[Checkout] {label} — branch '{source_branch}'")

    target_root = PatchApplier._get_apply_cwd(env_path, diff_path)
    remote = GitWorkspaceManager.find_issue_remote(target_root)
    if not remote:
        print("[FAIL] No issue-fork remote found in the target repo. "
              "Provision the environment first (it sets up the remote).")
        return {"applied": False, "label": label,
                "error": "Issue fork remote not found."}

    co = GitWorkspaceManager.checkout_mr_branch(target_root, remote, source_branch)
    if not co["success"]:
        print(f"[FAIL] Could not check out '{source_branch}': {co['message']}")
        return {"applied": False, "label": label, "error": co["message"]}

    print(f"[OK] On branch '{source_branch}' (tracking {remote}/{source_branch}).")
    print("     Commits made here land on the existing MR when pushed.")

    subprocess.run(["ddev", "drush", "cr"], cwd=env_path,
                   capture_output=True, text=True)

    result = {
        "applied": True,
        "label": label,
        "target_root": target_root,
        "mode": "checkout",
    }
    if not run_regression:
        result["regression"] = None
        return result

    print("\n[Regression] Running checks...")
    changed = _changed_files_from_diff(diff_path)
    env_relative_files = _to_env_relative(changed, env_path, target_root)
    reg_results = RegressionChecker.run_all(env_path, env_relative_files)
    print(RegressionChecker.format_report(reg_results))

    result["changed_files"] = env_relative_files
    result["regression"] = reg_results
    return result


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
    parser.add_argument("--checkout", action="store_true",
                        help="With --mr-url: check out the MR's own branch "
                             "(tracking the issue fork) instead of applying "
                             "its diff — required to UPDATE an existing MR, "
                             "since commits then land on the MR branch itself")
    args = parser.parse_args()

    if args.checkout and not args.mr_url:
        print("Error: --checkout requires --mr-url", file=sys.stderr)
        sys.exit(1)

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

        if args.checkout:
            result = checkout_and_check(env_path, diff_path, details, label,
                                        not args.no_regression)
        else:
            result = apply_and_check(env_path, diff_path, args.issue_id, label,
                                     not args.no_regression)
        result["mr_iid"] = mr_iid
        result["mr_source_branch"] = details.get("source_branch")
        results.append(result)

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
            details = mr_client.get_mr_details(project, mr_iid) or {}
            result = apply_and_check(env_path, diff_path, args.issue_id, label,
                                     not args.no_regression)
            result["mr_iid"] = mr_iid
            result["mr_source_branch"] = details.get("source_branch")
            results.append(result)

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

    # Show the git state of the repo the patch actually landed in — the
    # nested contrib clone for contrib issues, the core repo otherwise.
    work_root = next(
        (r["target_root"] for r in results if r.get("target_root")), env_path
    )
    status = GitWorkspaceManager.get_status(work_root)
    branch = GitWorkspaceManager._git(
        ["rev-parse", "--abbrev-ref", "HEAD"], work_root
    ).stdout.strip() or "issue-work"

    git_status = GitWorkspaceManager._git(["status", "--short"], work_root).stdout.strip()
    git_log = GitWorkspaceManager._git(
        ["log", "--oneline", "-5"], work_root
    ).stdout.strip()
    git_remotes = GitWorkspaceManager._git(["remote", "-v"], work_root).stdout.strip()

    print()
    print("=" * 65)
    print("  ENVIRONMENT GIT STATE")
    print("  (This is the repo under test inside the environment,")
    print("   separate from IssueForge itself)")
    print("=" * 65)
    print(f"  Branch  : {branch}")
    print(f"  Path    : {work_root}")
    print()
    if git_status:
        print("  Changed files (not yet committed):")
        for line in git_status.splitlines():
            print(f"    {line}")
    else:
        print("  Changed files: none (patch may already be committed)")
    print()
    if git_log:
        print("  Recent commits:")
        for line in git_log.splitlines():
            print(f"    {line}")
    print()
    if git_remotes:
        print("  Remotes:")
        for line in git_remotes.splitlines():
            print(f"    {line}")
    print("=" * 65)

    issue_page = f"https://www.drupal.org/project/drupal/issues/{args.issue_id}"
    issue_remote = GitWorkspaceManager.find_issue_remote(work_root) or "<remote>"
    mr_updates = [
        (r["mr_iid"], r["mr_source_branch"])
        for r in results
        if r.get("applied") and r.get("mr_source_branch")
    ]
    on_mr_branch = any(r.get("mode") == "checkout" for r in results)
    print()
    print("=" * 65)
    print("  NEXT STEPS")
    print("=" * 65)
    if on_mr_branch:
        # We're ON the MR's own branch — commits here update the MR directly.
        print(f"  Issue page : {issue_page}")
        print()
        print(f"  You are on the MR's own branch ('{branch}').")
        print("  After making and testing changes, publish them to the MR:")
        print(f"       git -C {work_root} add -A")
        print(f"       git -C {work_root} commit -m 'Address review feedback'")
        print(f"       git -C {work_root} push {issue_remote} {branch}")
    elif status["has_changes"]:
        print(f"  Issue page : {issue_page}")
        print()
        print("  To submit as a Merge Request:")
        print("    1. Open the issue page above")
        print("    2. Scroll to 'Merge requests' section")
        print("    3. Click 'Get push access' (creates your issue fork)")
        print("    4. Then commit:")
        print(f"       git -C {work_root} add -A")
        print(f"       git -C {work_root} commit -m 'Apply fix for #{args.issue_id}'")
        print()
        print("  To push as a NEW branch (opens a new MR):")
        print(f"       git -C {work_root} push --set-upstream {issue_remote} HEAD")
        for mr_iid, source_branch in mr_updates:
            print()
            print(f"  NOTE: to update the EXISTING MR !{mr_iid} instead, your")
            print(f"  commits must be on its branch ('{source_branch}') — this")
            print(f"  work branch has diverged history, so HEAD:{source_branch}")
            print("  would be rejected. Re-run with --checkout to work on the")
            print("  MR's own branch:")
            print(f"       python scripts/apply_mr.py {args.issue_id} "
                  f"--mr-url <MR_URL> --checkout")
        print()
        print("  Or to save as a patch file:")
        print(f"       git -C {work_root} diff HEAD > {args.issue_id}.patch")
    else:
        print("  No uncommitted changes — nothing to submit.")
    print("=" * 65)

    if any_failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
