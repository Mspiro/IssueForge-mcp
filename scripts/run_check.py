#!/usr/bin/env python3
"""
Run a single deterministic check (a PHPUnit test file, or PHPStan against
changed files) and print a normalized pass/fail + failure signature.

This is the primitive behind the bounded fix/verify loop described in
.claude/commands/issueforge.md: run the check, compare the "signature" of
consecutive attempts — same signature means no progress (stop and
escalate), different signature means keep going (bounded by a max attempt
count), no signature (empty list) with passed=true means done.

Usage:
    python scripts/run_check.py <issue_id> phpunit <test_file>
    python scripts/run_check.py <issue_id> phpstan <changed_file> [<changed_file> ...]
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.logger import setup_logging
from services.check_runner import CheckRunner
from config import ENVIRONMENTS_DIR


def _env_path(issue_id: str) -> str:
    return os.path.join(ENVIRONMENTS_DIR, f"env_{issue_id}")


def main():
    setup_logging()
    parser = argparse.ArgumentParser(description="Run a bounded-retry-loop check")
    parser.add_argument("issue_id", help="Drupal issue ID")
    parser.add_argument("check_type", choices=["phpunit", "phpstan"])
    parser.add_argument("files", nargs="+", help="Test file (phpunit) or changed files (phpstan)")
    args = parser.parse_args()

    env_path = _env_path(args.issue_id)
    if not os.path.exists(env_path):
        print(json.dumps({"error": f"environment not found at {env_path}"}))
        sys.exit(1)

    if args.check_type == "phpunit":
        result = CheckRunner.run_phpunit_test(env_path, args.files[0])
    else:
        result = CheckRunner.run_phpstan(env_path, args.files)

    print(json.dumps(result, indent=2))
    sys.exit(0 if result.get("passed") else 1)


if __name__ == "__main__":
    main()
