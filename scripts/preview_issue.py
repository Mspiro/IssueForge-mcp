#!/usr/bin/env python3
"""
Fetch and display a Drupal.org issue preview.

Prints title, status, patches, and MRs, then exits 0.
Claude Code handles the conversation and next steps.

Usage:
    python scripts/preview_issue.py <ISSUE_URL_OR_ID>
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.logger import setup_logging
from services.credential_manager import get_credentials
from services.issue_previewer import IssuePreviewer


def _normalise(arg: str) -> str:
    return f"https://www.drupal.org/node/{arg}" if arg.strip().isdigit() else arg.strip()


def main():
    setup_logging()
    parser = argparse.ArgumentParser(description="Preview a Drupal.org issue")
    parser.add_argument("issue", help="Drupal issue URL or numeric ID")
    args = parser.parse_args()

    creds = get_credentials()
    issue_url = _normalise(args.issue)

    print(f"Fetching issue data for {issue_url} …", flush=True)
    try:
        preview = IssuePreviewer.fetch_preview(issue_url, gitlab_token=creds["gitlab_token"])
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    print(IssuePreviewer.format_report(preview))


if __name__ == "__main__":
    main()
