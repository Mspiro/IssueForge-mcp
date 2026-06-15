#!/usr/bin/env python3
"""
Reproduction script runner.

Copies a PHP script into the DDEV environment and runs it via drush.

Usage:
    python scripts/reproduce_with_healing.py <issue_id> <script_file> \
        [--issue-title "..."] [--env-plan env_plan_<id>.json]
"""

import argparse
import os
import shutil
import subprocess
import sys
from typing import Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def run_script(env_path: str, script_name: str) -> Tuple[bool, str]:
    result = subprocess.run(
        ["ddev", "drush", "scr", script_name],
        cwd=env_path,
        capture_output=True,
        text=True,
        timeout=120,
    )
    combined = result.stdout + ("\n" + result.stderr if result.stderr else "")
    return result.returncode == 0, combined


def validate_php_syntax(env_path: str, script_name: str) -> Tuple[bool, str]:
    result = subprocess.run(
        ["ddev", "exec", "php", "-l", script_name],
        cwd=env_path,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return result.returncode == 0, result.stdout + result.stderr


def main():
    parser = argparse.ArgumentParser(description="Run a PHP reproduction script inside DDEV")
    parser.add_argument("issue_id", help="Drupal issue ID")
    parser.add_argument("script_file", help="Path to the PHP setup script")
    parser.add_argument("--issue-title", default="", help="Issue title (informational)")
    parser.add_argument("--env-plan", metavar="JSON_FILE", default="", help="Path to env_plan JSON")
    args = parser.parse_args()

    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env_path = os.path.join(base_dir, "environments", f"env_{args.issue_id}")

    if not os.path.exists(env_path):
        print(f"Error: Environment not found at {env_path}", file=sys.stderr)
        sys.exit(1)

    if not os.path.exists(args.script_file):
        print(f"Error: Script not found: {args.script_file}", file=sys.stderr)
        print("Write the PHP reproduction script, then re-run this command.", file=sys.stderr)
        sys.exit(1)

    script_name = os.path.basename(args.script_file)
    target_path = os.path.join(env_path, script_name)
    shutil.copy2(args.script_file, target_path)

    syntax_ok, syntax_out = validate_php_syntax(env_path, script_name)
    if not syntax_ok:
        print(f"[Syntax Error]\n{syntax_out.strip()}", file=sys.stderr)
        sys.exit(1)

    print(f"Running {script_name} inside DDEV…")
    success, output = run_script(env_path, script_name)
    print(output)

    if success:
        site_url = f"https://env-{args.issue_id}.ddev.site"
        print(f"\n[OK] Script completed successfully.")
        print(f"     Site: {site_url}  (admin / admin)")
        sys.exit(0)
    else:
        print("\n[FAILED] Script exited with an error.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
