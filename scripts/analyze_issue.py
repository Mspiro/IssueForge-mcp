#!/usr/bin/env python3
import sys
import json
import argparse
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from server import IssueForgeServer
from utils.logger import setup_logging
from services.credential_manager import get_credentials, is_setup_complete


def main():
    setup_logging()
    parser = argparse.ArgumentParser(description="Analyze a Drupal issue via IssueForge")
    parser.add_argument("url", help="Drupal issue URL")
    args = parser.parse_args()

    if not is_setup_complete():
        print(
            "[Setup required] Run `python scripts/setup.py` to configure IssueForge "
            "before first use.\n"
            "                 Continuing with defaults — git identity will be generic.",
            file=sys.stderr,
        )

    creds = get_credentials()

    server = IssueForgeServer(gitlab_token=creds["gitlab_token"])
    try:
        result = server.analyze_issue(args.url)
        # Embed git identity in env_plan so provision_env.py can use it
        if result.get("environment_plan"):
            result["environment_plan"]["git_name"] = creds["git_name"]
            result["environment_plan"]["git_email"] = creds["git_email"]
        print(json.dumps(result, indent=2))
    except Exception as e:
        print(json.dumps({"error": str(e)}))
        sys.exit(1)


if __name__ == "__main__":
    main()
