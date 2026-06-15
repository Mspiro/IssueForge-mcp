#!/usr/bin/env python3
import sys
import json
import argparse
import os

# Ensure the root of the project is in the Python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.patch_applier import PatchApplier
from utils.logger import setup_logging

def main():
    setup_logging()
    parser = argparse.ArgumentParser(description="Check and apply a Drupal patch")
    parser.add_argument("issue_id", help="Drupal issue ID (used to locate the environment)")
    parser.add_argument("patch_id", help="Patch file ID to apply")
    parser.add_argument("--check-only", action="store_true", help="Only perform a dry-run check without applying")
    args = parser.parse_args()
    
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env_path = os.path.join(base_dir, "environments", f"env_{args.issue_id}")
    
    if not os.path.exists(env_path):
        print(json.dumps({"success": False, "message": f"Environment path not found: {env_path}"}))
        sys.exit(1)
        
    try:
        if args.check_only:
            result = PatchApplier.check_patch(env_path, args.patch_id)
            # check_patch returns {"clean": bool, ...}
            print(json.dumps(result, indent=2))
            if not result.get("clean"):
                sys.exit(1)
        else:
            result = PatchApplier.apply_patch(env_path, args.patch_id)
            print(json.dumps(result, indent=2))
            if not result.get("success"):
                sys.exit(1)
    except Exception as e:
        print(json.dumps({"error": str(e), "success": False}))
        sys.exit(1)

if __name__ == "__main__":
    main()
