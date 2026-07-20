#!/usr/bin/env python3
"""
Run the full regression check suite against whatever is currently
uncommitted in the environment — used after an AI-authored fix (no patch
file to apply, the edits are already sitting in the working tree), so it
gets the exact same safety net apply_mr.py gives a downloaded MR/patch:
health check, targeted PHPUnit, full-module sweep, module compatibility.

Usage:
    python scripts/check_regression.py <issue_id>
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.logger import setup_logging
from services.git_workspace_manager import GitWorkspaceManager
from services.regression_checker import RegressionChecker
from config import ENVIRONMENTS_DIR


def _work_root(env_path: str) -> str:
    """The repo under test: nested contrib clone if present, else core.

    For contrib issues, `env_path` is the outer Drupal core checkout, but
    the actual changes live in a separate nested git repo at
    modules/contrib/<name> — `git status` at env_path never sees them
    (they're a different repo, not a submodule). Same detection check_cs.py
    already uses for the same reason.
    """
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


def _reanchor(files, work_root, env_path):
    """Re-anchor paths from a nested contrib repo onto the outer ddev root.

    RegressionChecker always operates relative to env_path (core/phpunit.xml.dist,
    core/modules/... live there, not in the nested repo) — a contrib file like
    "src/Foo.php" (relative to work_root) becomes "modules/contrib/<name>/src/Foo.php",
    matching what discover_test_files()/extract_affected_modules() expect.
    """
    if os.path.realpath(work_root) == os.path.realpath(env_path):
        return list(files)
    prefix = os.path.relpath(work_root, env_path)
    return [os.path.join(prefix, f) for f in files]


def main():
    setup_logging()
    parser = argparse.ArgumentParser(description="Run regression checks against uncommitted changes")
    parser.add_argument("issue_id", help="Drupal issue ID")
    args = parser.parse_args()

    env_path = os.path.join(ENVIRONMENTS_DIR, f"env_{args.issue_id}")
    if not os.path.exists(env_path):
        print(json.dumps({"error": f"environment not found at {env_path}"}))
        sys.exit(1)

    work_root = _work_root(env_path)
    if os.path.realpath(work_root) != os.path.realpath(env_path):
        print(f"[Info] Contrib repo detected — checking {work_root}")

    status = GitWorkspaceManager.get_status(work_root)
    if not status["changed_files"]:
        print("[Info] No uncommitted changes — nothing to check.")
        sys.exit(0)

    changed_files = _reanchor(status["changed_files"], work_root, env_path)

    print("--- Changed files ---")
    print(status["diff_stat"])
    print("---------------------")

    results = RegressionChecker.run_all(env_path, changed_files)
    print(RegressionChecker.format_report(results))
    sys.exit(0 if results.get("overall_passed") else 1)


if __name__ == "__main__":
    main()
