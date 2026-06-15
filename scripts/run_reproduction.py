#!/usr/bin/env python3
"""
Run a reproduction PHP script inside the DDEV environment.

Usage:
    python scripts/run_reproduction.py <issue_id> <script_file> [--env-plan JSON]
"""

import argparse
import os
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main():
    parser = argparse.ArgumentParser(description="Run reproduction script inside DDEV")
    parser.add_argument("issue_id", help="Drupal issue ID")
    parser.add_argument("script_file", help="Path to the PHP setup script")
    parser.add_argument("--env-plan", metavar="JSON_FILE", default="")
    args = parser.parse_args()

    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env_path = os.path.join(base_dir, "environments", f"env_{args.issue_id}")

    if not os.path.exists(env_path):
        print(f"Error: Environment path not found: {env_path}", file=sys.stderr)
        sys.exit(1)

    if not os.path.exists(args.script_file):
        print(f"Error: Script file not found: {args.script_file}", file=sys.stderr)
        sys.exit(1)

    script_name = os.path.basename(args.script_file)
    target_script = os.path.join(env_path, script_name)
    if os.path.abspath(args.script_file) != os.path.abspath(target_script):
        shutil.copy2(args.script_file, target_script)

    syntax_result = subprocess.run(
        ["ddev", "exec", "php", "-l", script_name],
        cwd=env_path,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if syntax_result.returncode != 0:
        print("PHP syntax error:", file=sys.stderr)
        print(syntax_result.stdout + syntax_result.stderr, file=sys.stderr)
        sys.exit(1)

    print(f"Running {script_name} inside DDEV…")
    try:
        process = subprocess.run(
            ["ddev", "drush", "scr", script_name],
            cwd=env_path,
            capture_output=True,
            text=True,
            timeout=120,
        )
        print(process.stdout)
        if process.returncode != 0:
            print(process.stderr, file=sys.stderr)
            sys.exit(1)

        site_url = f"https://env-{args.issue_id}.ddev.site"
        print(f"\n[OK] Script completed. Site: {site_url}  (admin / admin)")

    except subprocess.TimeoutExpired:
        print("Error: timed out after 120s.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
