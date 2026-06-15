#!/usr/bin/env python3
"""
Generate and apply a code fix for an unresolved Drupal issue.

Usage:
    python scripts/generate_fix.py <issue_id> <env_plan_json>

Flow:
    1. Load env_plan.json for issue context and determine module path
    2. LLM generates a structured fix plan (files, reasons, changes)
    3. Show plan to user → explicit confirmation required to proceed
    4. Apply code changes file by file via LLM code generation
    5. Self-healing validation loop (up to 3 attempts):
         a. PHPCBF  — auto-fix coding style
         b. PHPCS   — coding standards check
         c. PHPStan — static analysis
         d. PHPUnit — existing test suite (if any)
       On failure: feed errors back to LLM, regenerate affected files, retry
    6. Offer to submit: push MR to issue fork or upload patch to Drupal.org
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.logger import setup_logging
from services.credential_manager import get_credentials
from services.fix_generator import FixGenerator
from services.code_validator import CodeValidator
from services.git_workspace_manager import GitWorkspaceManager
from config import ENVIRONMENTS_DIR

_MAX_HEALING_ATTEMPTS = 3


def _env_path(issue_id: str) -> str:
    return os.path.join(ENVIRONMENTS_DIR, f"env_{issue_id}")


def _confirm(prompt: str) -> bool:
    """Return True only when user explicitly types y/yes. Blank Enter = no."""
    try:
        ans = input(prompt).strip().lower()
        return ans in ("y", "yes")
    except (EOFError, KeyboardInterrupt):
        print()
        return False


def _determine_module_rel_path(env_plan: dict) -> str:
    """
    Return the module path relative to the DDEV webroot.
    The env_plan may already carry a 'module_path' key; otherwise infer from project_name.
    """
    if env_plan.get("module_path"):
        return env_plan["module_path"]
    project = env_plan.get("project_name", "")
    if not project or project == "drupal":
        # Core issue — scope cannot be narrowed automatically; caller should specify --module-path
        return ""
    return f"modules/contrib/{project}"


def _apply_changes(
    env_path: str,
    plan: dict,
    issue_context: dict,
    errors_by_container_path: dict = None,
    attempt: int = 1,
) -> list:
    """
    Generate and write code for every file in the plan.

    errors_by_container_path: {container_abs_path: [error_dicts]} for self-healing.
    Returns list of (rel_path, wrote_ok) tuples.
    """
    # Merge regular files and new files into one list
    entries = list(plan.get("files", []))
    for nf in plan.get("new_files", []):
        entries.append({
            "path": nf["path"],
            "reason": nf.get("reason", ""),
            "changes": nf.get("content_hint", "Create new file as described."),
            "risk": "low",
        })

    applied = []

    for entry in entries:
        rel_path = entry.get("path", "").strip()
        if not rel_path:
            continue

        abs_path = os.path.join(env_path, rel_path)

        # Read current content
        current_content = ""
        if os.path.exists(abs_path):
            try:
                with open(abs_path, encoding="utf-8") as f:
                    current_content = f.read()
            except Exception as exc:
                print(f"  [Warn] Could not read {rel_path}: {exc}")

        # Match container-side errors to this file
        file_errors = []
        if errors_by_container_path:
            for container_path, errs in errors_by_container_path.items():
                # Container path: /var/www/html/modules/contrib/mod/src/Foo.php
                # rel_path:       modules/contrib/mod/src/Foo.php
                if rel_path in container_path or container_path.endswith(rel_path):
                    file_errors.extend(errs)

        print(f"  Generating: {rel_path} ...", end=" ", flush=True)

        new_content = FixGenerator.generate_code_for_file(
            file_rel_path=rel_path,
            current_content=current_content,
            change_instructions=entry.get("changes", ""),
            issue_context=issue_context,
            validation_errors=file_errors if file_errors else None,
            attempt=attempt,
        )

        if not new_content:
            print("FAIL (LLM returned empty)")
            applied.append((rel_path, False))
            continue

        os.makedirs(os.path.dirname(abs_path), exist_ok=True)

        try:
            with open(abs_path, "w", encoding="utf-8") as f:
                f.write(new_content)
            print(f"OK ({len(new_content):,} chars)")
            applied.append((rel_path, True))
        except Exception as exc:
            print(f"FAIL ({exc})")
            applied.append((rel_path, False))

    return applied


def main():
    setup_logging()
    parser = argparse.ArgumentParser(
        description="Generate and apply a code fix for an unresolved Drupal issue"
    )
    parser.add_argument("issue_id", help="Drupal issue ID")
    parser.add_argument(
        "env_plan_json",
        help="Path to JSON file produced by analyze_issue.py",
    )
    parser.add_argument(
        "--module-path",
        metavar="PATH",
        help="Module path relative to Drupal webroot (e.g. modules/contrib/mymod). "
             "Auto-detected from env_plan when omitted.",
    )
    parser.add_argument(
        "--no-submit",
        action="store_true",
        help="Stop after validation — skip the submit step.",
    )
    args = parser.parse_args()

    env_path = _env_path(args.issue_id)
    if not os.path.exists(env_path):
        print(f"Error: environment not found at {env_path}", file=sys.stderr)
        print("       Run provision_env.py first.", file=sys.stderr)
        sys.exit(1)

    if not os.path.exists(args.env_plan_json):
        print(f"Error: plan file not found: {args.env_plan_json}", file=sys.stderr)
        sys.exit(1)

    with open(args.env_plan_json) as f:
        full_context = json.load(f)

    env_plan = full_context.get("environment_plan", full_context)

    module_rel_path = args.module_path or _determine_module_rel_path(env_plan)
    if not module_rel_path:
        print(
            "Error: cannot determine module path. Use --module-path modules/contrib/<name>",
            file=sys.stderr,
        )
        sys.exit(1)

    issue_context = {
        "issue_id": args.issue_id,
        "title": full_context.get("title", env_plan.get("title", "Unknown issue")),
        "status": full_context.get("status", "Unknown"),
        "project_name": env_plan.get("project_name", "drupal"),
        "drupal_version": env_plan.get("drupal_version", "10"),
        "root_cause": full_context.get("root_cause", full_context.get("analysis", "")),
        "fix_approach": full_context.get("fix_approach", ""),
        "subsystems": full_context.get("subsystems", []),
        "analysis": full_context.get("analysis", ""),
    }

    print(f"\n[IssueForge] Auto-fix for issue #{args.issue_id}")
    print(f"  Title   : {issue_context['title']}")
    print(f"  Project : {issue_context['project_name']}")
    print(f"  Module  : {module_rel_path}")

    # ------------------------------------------------------------------
    # Step 1: Generate fix plan
    # ------------------------------------------------------------------
    print("\n[1/4] Generating fix plan (calling LLM)...")

    plan = FixGenerator.generate_plan(env_path, issue_context, module_rel_path)
    if not plan:
        print("Error: LLM could not generate a fix plan. Check your API key.", file=sys.stderr)
        sys.exit(1)

    print(FixGenerator.format_plan(plan))

    if not _confirm("Proceed with applying these changes? [y/N] "):
        print("Aborted — no changes made.")
        sys.exit(0)

    # ------------------------------------------------------------------
    # Step 2: First-pass code generation
    # ------------------------------------------------------------------
    print("\n[2/4] Applying code changes...")

    applied = _apply_changes(env_path, plan, issue_context, attempt=1)
    ok = sum(1 for _, wrote in applied if wrote)
    print(f"  Written {ok}/{len(applied)} file(s).")

    if ok == 0:
        print("Error: no files were written. Aborting.", file=sys.stderr)
        sys.exit(1)

    # ------------------------------------------------------------------
    # Step 3: Self-healing validation loop
    # ------------------------------------------------------------------
    print(f"\n[3/4] Running validation (up to {_MAX_HEALING_ATTEMPTS} attempt(s))...")

    val_results = None
    passed = False

    for attempt in range(1, _MAX_HEALING_ATTEMPTS + 1):
        print(f"\n--- Validation attempt {attempt}/{_MAX_HEALING_ATTEMPTS} ---")
        val_results = CodeValidator.run_all(env_path, module_rel_path)
        print(CodeValidator.format_report(val_results))

        if val_results.get("overall_passed"):
            passed = True
            break

        if attempt >= _MAX_HEALING_ATTEMPTS:
            break

        errors_by_file = CodeValidator.collect_errors_by_file(val_results)
        total_errors = sum(len(v) for v in errors_by_file.values())

        if not errors_by_file:
            print("\nNo PHPCS/PHPStan errors to self-heal (PHPUnit failure?). Manual review needed.")
            break

        print(f"\nSelf-healing: regenerating code to fix {total_errors} error(s)...")
        _apply_changes(env_path, plan, issue_context, errors_by_file, attempt=attempt + 1)

    if not passed:
        print("\n⚠  Validation did not fully pass after all attempts.")
        if not _confirm("Continue to submit anyway? [y/N] "):
            print("Aborted. Changes remain in the working tree for manual review.")
            sys.exit(1)

    # ------------------------------------------------------------------
    # Step 4: Submit
    # ------------------------------------------------------------------
    if args.no_submit:
        print("\n[4/4] --no-submit set — skipping submission.")
        sys.exit(0)

    print("\n[4/4] Preparing submission...")

    status = GitWorkspaceManager.get_status(env_path)
    if not status.get("has_changes"):
        print("No uncommitted changes — nothing to submit.")
        sys.exit(0)

    creds = get_credentials()
    suggested_msg = f"Fix #{args.issue_id}: {issue_context['title'][:60]}"

    GitWorkspaceManager.submit_with_confirmation(
        env_path,
        issue_id=args.issue_id,
        suggested_commit_msg=suggested_msg,
        drupal_username=creds.get("drupal_username", ""),
        drupal_password=creds.get("drupal_password", ""),
    )


if __name__ == "__main__":
    main()
