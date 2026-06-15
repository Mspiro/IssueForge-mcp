#!/usr/bin/env python3
"""
One-time credential setup for IssueForge.

Run this once before using any IssueForge scripts:
    python scripts/setup.py

To reset / update existing credentials:
    python scripts/setup.py --force
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.credential_manager import run_interactive_setup, is_setup_complete


def main():
    parser = argparse.ArgumentParser(
        description="Configure IssueForge credentials (run once)"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-prompt even if credentials are already saved",
    )
    args = parser.parse_args()

    if is_setup_complete() and not args.force:
        print("[OK] IssueForge is already configured.")
        print("     Use --force to update existing credentials.")
        sys.exit(0)

    run_interactive_setup(force=args.force)


if __name__ == "__main__":
    main()
