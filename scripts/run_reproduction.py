#!/usr/bin/env python3
"""
Run a reproduction PHP script inside the DDEV environment.

After a successful run, prints a step-by-step browser guide showing exactly
how to navigate the site and observe the bug.

For a self-healing loop that automatically retries on failure, use
scripts/reproduce_with_healing.py instead.

Usage:
    python scripts/run_reproduction.py <issue_id> <script_file> [--env-plan JSON]
"""

import argparse
import json
import os
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.reproduction_generator_llm import ReproductionGeneratorLlm


def _get_site_url(issue_id: str) -> str:
    return f"https://env-{issue_id}.ddev.site"


def _load_issue_context(env_plan_path: str) -> dict:
    if not env_plan_path or not os.path.exists(env_plan_path):
        return {}
    try:
        with open(env_plan_path) as f:
            data = json.load(f)
        return {
            "title": data.get("issue_title") or data.get("title", ""),
            "reproduction_steps": data.get("reproduction_steps", []),
            "subsystems": data.get("detected_subsystems", []),
            "problem_summary": (data.get("llm_analysis") or {}).get("root_cause", ""),
        }
    except Exception:
        return {}


def main():
    parser = argparse.ArgumentParser(description="Run reproduction script inside DDEV")
    parser.add_argument("issue_id", help="Drupal issue ID")
    parser.add_argument("script_file", help="Path to the PHP setup script")
    parser.add_argument(
        "--env-plan",
        metavar="JSON_FILE",
        default="",
        help="Path to env_plan JSON (output of analyze_issue.py) — enables a richer "
             "verification guide after the script succeeds",
    )
    args = parser.parse_args()

    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env_path = os.path.join(base_dir, "environments", f"env_{args.issue_id}")

    if not os.path.exists(env_path):
        print(f"Error: Environment path not found: {env_path}", file=sys.stderr)
        sys.exit(1)

    if not os.path.exists(args.script_file):
        print(f"Error: Script file not found: {args.script_file}", file=sys.stderr)
        sys.exit(1)

    ctx = _load_issue_context(args.env_plan)
    site_url = _get_site_url(args.issue_id)
    issue_title = ctx.get("title", "Drupal Issue")

    script_name = os.path.basename(args.script_file)
    target_script = os.path.join(env_path, script_name)
    if os.path.abspath(args.script_file) != os.path.abspath(target_script):
        shutil.copy2(args.script_file, target_script)

    # PHP syntax check before execution — catches obvious LLM mistakes cheaply.
    syntax_result = subprocess.run(
        ["ddev", "exec", "php", "-l", script_name],
        cwd=env_path,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if syntax_result.returncode != 0:
        print("PHP syntax error detected:", file=sys.stderr)
        print(syntax_result.stdout + syntax_result.stderr, file=sys.stderr)
        print(
            "Tip: use scripts/reproduce_with_healing.py to auto-fix via LLM.",
            file=sys.stderr,
        )
        sys.exit(1)

    print(f"Executing {script_name} inside DDEV...")
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
            print(
                f"Execution failed with exit code {process.returncode}",
                file=sys.stderr,
            )
            print(process.stderr, file=sys.stderr)
            print(
                "\nTip: use scripts/reproduce_with_healing.py to auto-fix via LLM.",
                file=sys.stderr,
            )
            sys.exit(1)

        print("\n--- SETUP COMPLETE ---")

        # Generate and print the browser verification guide
        print("\nGenerating verification guide (calling LLM)...", flush=True)
        guide_text = ReproductionGeneratorLlm.generate_verification_guide(
            issue_id=args.issue_id,
            issue_title=issue_title,
            site_url=site_url,
            reproduction_steps=ctx.get("reproduction_steps", []),
            subsystems=ctx.get("subsystems"),
            problem_summary=ctx.get("problem_summary"),
        )
        print(ReproductionGeneratorLlm.format_verification_guide(
            issue_id=args.issue_id,
            issue_title=issue_title,
            site_url=site_url,
            guide_text=guide_text,
            env_path=env_path,
        ))

    except subprocess.TimeoutExpired:
        print("Error: Script execution timed out after 120s.", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
