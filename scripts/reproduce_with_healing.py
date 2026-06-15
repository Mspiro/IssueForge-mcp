#!/usr/bin/env python3
"""
Self-healing reproduction runner.

Runs a PHP reproduction script inside DDEV.  If it fails, the error output is
fed back to the LLM which rewrites the script and retries — up to MAX_ATTEMPTS
times.  On each attempt the repaired script is saved alongside the original so
you can diff them to understand what changed.

After a successful run, prints a step-by-step browser guide showing exactly
how to navigate the site and observe the bug.

Usage:
    python scripts/reproduce_with_healing.py <issue_id> <script_file> \\
        [--issue-title "..."] [--env-plan env_plan_<id>.json]
"""

import argparse
import json
import os
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.reproduction_generator_llm import ReproductionGeneratorLlm

MAX_ATTEMPTS = 3


def run_script(env_path: str, script_name: str) -> tuple[bool, str]:
    """Run the script inside DDEV.  Returns (success, combined_output)."""
    result = subprocess.run(
        ["ddev", "drush", "scr", script_name],
        cwd=env_path,
        capture_output=True,
        text=True,
        timeout=120,
    )
    combined = result.stdout + ("\n" + result.stderr if result.stderr else "")
    return result.returncode == 0, combined


def validate_php_syntax(env_path: str, script_name: str) -> tuple[bool, str]:
    """Quick syntax check before execution to catch obvious LLM mistakes."""
    result = subprocess.run(
        ["ddev", "exec", "php", "-l", script_name],
        cwd=env_path,
        capture_output=True,
        text=True,
        timeout=30,
    )
    combined = result.stdout + result.stderr
    return result.returncode == 0, combined


def _get_site_url(issue_id: str) -> str:
    return f"https://env-{issue_id}.ddev.site"


def _load_issue_context(env_plan_path: str) -> dict:
    """Return {title, reproduction_steps, subsystems, problem_summary} from env_plan.json."""
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
    parser = argparse.ArgumentParser(description="Self-healing reproduction runner")
    parser.add_argument("issue_id", help="Drupal issue ID")
    parser.add_argument("script_file", help="Path to the initial PHP setup script")
    parser.add_argument(
        "--issue-title",
        default="",
        help="Issue title (used in LLM prompts and verification guide)",
    )
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

    # Load issue context for the verification guide
    ctx = _load_issue_context(args.env_plan)
    issue_title = args.issue_title or ctx.get("title", "Drupal Issue")
    site_url = _get_site_url(args.issue_id)

    if not os.path.exists(env_path):
        print(f"Error: Environment not found at {env_path}", file=sys.stderr)
        sys.exit(1)

    if not os.path.exists(args.script_file):
        print(f"Error: Script not found: {args.script_file}", file=sys.stderr)
        sys.exit(1)

    with open(args.script_file, "r") as f:
        current_script = f.read()

    script_name = os.path.basename(args.script_file)
    target_path = os.path.join(env_path, script_name)

    for attempt in range(1, MAX_ATTEMPTS + 1):
        print(f"\n--- Attempt {attempt}/{MAX_ATTEMPTS} ---")

        # Write current script version to env
        with open(target_path, "w") as f:
            f.write(current_script)

        # PHP syntax check first (fast — avoids spinning up a full drush run)
        syntax_ok, syntax_out = validate_php_syntax(env_path, script_name)
        if not syntax_ok:
            print(f"[Syntax Error] {syntax_out.strip()}")
            error_output = syntax_out
        else:
            print(f"[Syntax OK] Running script...")
            success, output = run_script(env_path, script_name)
            print(output)

            if success:
                # Persist the final working version back to the source location
                shutil.copy2(target_path, args.script_file)
                print(f"\n[SUCCESS] Environment set up on attempt {attempt}.")

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
                sys.exit(0)

            error_output = output

        if attempt == MAX_ATTEMPTS:
            print(
                f"\n[FAILED] Could not produce a working script after {MAX_ATTEMPTS} attempts.",
                file=sys.stderr,
            )
            print("Last error output:", file=sys.stderr)
            print(error_output, file=sys.stderr)
            sys.exit(1)

        # Save broken version for diffing
        broken_path = os.path.join(
            env_path, f"{script_name}.attempt{attempt}.broken.php"
        )
        with open(broken_path, "w") as f:
            f.write(current_script)
        print(f"[Saved broken script to {broken_path}]")

        # Ask the LLM to fix it
        print(f"[Healing] Sending error to LLM for fix...")
        fixed = ReproductionGeneratorLlm.fix_script(
            broken_script=current_script,
            error_output=error_output,
            issue_title=issue_title,
            attempt=attempt,
        )

        if not fixed or not fixed.strip().startswith("<?php"):
            print("[Healing] LLM did not return valid PHP. Aborting.", file=sys.stderr)
            sys.exit(1)

        current_script = fixed
        print(f"[Healing] Script repaired. Retrying...")


if __name__ == "__main__":
    main()
