#!/usr/bin/env python3
"""
Coding-standards gate for an issue environment — run BEFORE pushing to the
issue fork or exporting a patch.

    python scripts/check_cs.py <ISSUE_ID>              # check + autofix + re-check
    python scripts/check_cs.py <ISSUE_ID> --check-only # no autofix

Checks every file that would leave the machine (uncommitted changes plus
commits not yet on the upstream branch), in the repo under test — the
nested contrib clone when one exists, the core clone otherwise.

Exit code 0 = clean (possibly after autofix; re-commit if files changed),
1 = violations remain.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import ENVIRONMENTS_DIR
from services.git_workspace_manager import GitWorkspaceManager


def _work_root(env_path: str) -> str:
    """The repo under test: nested contrib clone if present, else core."""
    contrib_base = os.path.join(env_path, "modules", "contrib")
    if os.path.isdir(contrib_base):
        nested = [
            os.path.join(contrib_base, d)
            for d in os.listdir(contrib_base)
            if os.path.isdir(os.path.join(contrib_base, d, ".git"))
        ]
        if len(nested) == 1:
            return nested[0]
    return env_path


def main():
    parser = argparse.ArgumentParser(description="PHPCS gate for pending work")
    parser.add_argument("issue_id")
    parser.add_argument("--check-only", action="store_true",
                        help="Report violations without running phpcbf")
    args = parser.parse_args()

    env_path = os.path.join(ENVIRONMENTS_DIR, f"env_{args.issue_id}")
    if not os.path.isdir(env_path):
        print(f"Error: environment not found at {env_path}", file=sys.stderr)
        sys.exit(1)

    work_root = _work_root(env_path)
    print(f"[CS] Repo under test: {work_root}")

    if args.check_only:
        from services.coding_standards_checker import CodingStandardsChecker
        pending = GitWorkspaceManager.files_pending_submission(work_root)
        ddev_root = GitWorkspaceManager._find_ddev_root(work_root)
        if os.path.realpath(ddev_root) != os.path.realpath(work_root):
            prefix = os.path.relpath(work_root, ddev_root)
            pending = [os.path.join(prefix, f) for f in pending]
        result = CodingStandardsChecker.check(ddev_root, pending)
        if result.get("skipped_reason"):
            print(f"[CS] Skipped: {result['skipped_reason']}")
            sys.exit(0)
        print(result["output"] or f"[CS] Clean ({len(result['checked'])} file(s)).")
        sys.exit(0 if result["passed"] else 1)

    clean = GitWorkspaceManager.run_coding_standards_gate(
        work_root, GitWorkspaceManager._find_ddev_root(work_root)
    )
    if clean:
        print("[CS] GATE PASSED — safe to push / export a patch.")
        print("     (If autofix changed files, include them in your commit.)")
    else:
        print("[CS] GATE FAILED — fix remaining violations before pushing.")
    sys.exit(0 if clean else 1)


if __name__ == "__main__":
    main()
