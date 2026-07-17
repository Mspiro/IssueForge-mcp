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


def main():
    setup_logging()
    parser = argparse.ArgumentParser(description="Run regression checks against uncommitted changes")
    parser.add_argument("issue_id", help="Drupal issue ID")
    args = parser.parse_args()

    env_path = os.path.join(ENVIRONMENTS_DIR, f"env_{args.issue_id}")
    if not os.path.exists(env_path):
        print(json.dumps({"error": f"environment not found at {env_path}"}))
        sys.exit(1)

    status = GitWorkspaceManager.get_status(env_path)
    if not status["changed_files"]:
        print("[Info] No uncommitted changes — nothing to check.")
        sys.exit(0)

    print("--- Changed files ---")
    print(status["diff_stat"])
    print("---------------------")

    results = RegressionChecker.run_all(env_path, status["changed_files"])
    print(RegressionChecker.format_report(results))
    sys.exit(0 if results.get("overall_passed") else 1)


if __name__ == "__main__":
    main()
