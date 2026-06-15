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
    except Exception as e:
        print(json.dumps({"error": str(e), "success": False}))
        sys.exit(1)

if __name__ == "__main__":
    main()
