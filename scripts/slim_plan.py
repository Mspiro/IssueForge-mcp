#!/usr/bin/env python3
"""Output a slim summary of env_plan JSON — only the fields Claude Code reads in Step 2."""
import json
import os
import sys


def main():
    if len(sys.argv) < 2:
        print("Usage: slim_plan.py <env_plan.json>", file=sys.stderr)
        sys.exit(1)
    path = sys.argv[1]
    if not os.path.exists(path):
        print(f"Error: {path} not found", file=sys.stderr)
        sys.exit(1)
    with open(path) as f:
        plan = json.load(f)

    ep = plan.get("environment_plan", {})
    slim = {
        "issue_title":              plan.get("issue_title"),
        # EVIDENCE is the primary input for root-cause reasoning — its
        # embedded "guidance" field says how to read it for this issue's
        # category. heuristic_hints below are keyword guesses, not
        # conclusions.
        "evidence":                 plan.get("evidence", {}),
        "heuristic_hints":          plan.get("heuristic_hints",
                                             plan.get("llm_analysis", {})),
        "detected_subsystems":      plan.get("detected_subsystems", []),
        "suggested_fix_strategies": plan.get("suggested_fix_strategies", []),
        "patch_status":             plan.get("patch_status", ""),
        "comment_signals":          plan.get("comment_signals", []),
        "comment_signal_details":   plan.get("comment_signal_details", []),
        # Flagged only when a comment references another issue number near
        # redirect/duplicate language (e.g. "favor closing this in favor of
        # #NNNNNNN") — read-only signal, never auto-fetched. See Step 2.
        "related_issues":          plan.get("related_issues", []),
        "modified_files":           plan.get("modified_files", []),
        "reproduction_steps":       plan.get("reproduction_steps", []),
        "detected_mrs":             plan.get("detected_mrs", []),
        "environment_plan": {
            "project_name":     ep.get("project_name"),
            "checkout_ref":     ep.get("checkout_ref"),
            "php_version":      ep.get("php_version"),
            "is_contrib":       ep.get("is_contrib"),
            "contrib_modules":  ep.get("contrib_modules", []),
            "required_modules": ep.get("required_modules", []),
            "patch_available":  ep.get("patch_available"),
            "latest_patch_id":  ep.get("latest_patch_id"),
        },
    }
    print(json.dumps(slim, indent=2))


if __name__ == "__main__":
    main()
