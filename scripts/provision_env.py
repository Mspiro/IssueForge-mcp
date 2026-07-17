#!/usr/bin/env python3
import sys
import json
import argparse
import os

# Ensure the root of the project is in the Python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.environment_provisioner import EnvironmentProvisioner
from utils.logger import setup_logging

def main():
    setup_logging()
    parser = argparse.ArgumentParser(description="Provision a DDEV environment")
    parser.add_argument("issue_id", help="Drupal issue ID")
    parser.add_argument("env_plan_json", help="Path to JSON file containing the env_plan dictionary")
    args = parser.parse_args()
    
    if not os.path.exists(args.env_plan_json):
        print(f"Error: Could not find env plan file {args.env_plan_json}")
        sys.exit(1)
        
    with open(args.env_plan_json, "r") as f:
        full_context = json.load(f)

    # analyze_issue.py writes the full context dict; the provisioner only
    # needs the environment_plan sub-dict (where project_name, checkout_ref,
    # php_version, modules, etc. live).  Fall back to the full dict so the
    # script also works if someone passes a bare environment_plan JSON.
    env_plan = full_context.get("environment_plan", full_context)

    try:
        result = EnvironmentProvisioner.provision(args.issue_id, env_plan)
        print(json.dumps(result, indent=2))
        if not result.get("success"):
            sys.exit(1)
        _write_workspace_file(
            args.issue_id,
            result.get("env_path", ""),
            result.get("work_root", ""),
        )
    except Exception as e:
        print(json.dumps({"error": str(e), "success": False}))
        sys.exit(1)


def _write_workspace_file(issue_id: str, env_path: str, work_root: str = "",
                          output_dir: str = ""):
    """
    Generate a .code-workspace file so the IDE shows the Drupal
    environment's git changes in its Source Control panel alongside
    the IssueForge project.

    For contrib issues the repo under test is the NESTED clone at
    modules/contrib/<project> — VS Code does not scan nested git repos
    inside a workspace folder (and openRepositoryInParentFolders is off),
    so unless that folder is added as its own workspace entry, the applied
    MR/patch diff is invisible in the Source Control panel.
    """
    if not env_path or not os.path.isdir(env_path):
        return

    issueforge_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    folders = [
        {
            "path": issueforge_dir,
            "name": "IssueForge"
        },
        {
            "path": env_path,
            "name": f"Drupal env-{issue_id} (issue #{issue_id})"
        }
    ]
    if (
        work_root
        and os.path.isdir(work_root)
        and os.path.realpath(work_root) != os.path.realpath(env_path)
    ):
        project = os.path.basename(work_root.rstrip("/"))
        folders.append({
            "path": work_root,
            "name": f"{project} (issue #{issue_id} repo)"
        })

    workspace = {
        "folders": folders,
        "settings": {
            "git.openRepositoryInParentFolders": "never"
        }
    }

    workspace_file = os.path.join(
        output_dir or issueforge_dir, f"env-{issue_id}.code-workspace"
    )
    with open(workspace_file, "w") as f:
        json.dump(workspace, f, indent=2)

    print()
    print("=" * 65)
    print("  IDE WORKSPACE")
    print("=" * 65)
    print(f"  To see git changes in your IDE's Source Control panel:")
    print(f"  Open this file in VS Code:")
    print(f"    {workspace_file}")
    print()
    print("  Or from terminal:")
    print(f"    code {workspace_file}")
    print("=" * 65)

if __name__ == "__main__":
    main()
