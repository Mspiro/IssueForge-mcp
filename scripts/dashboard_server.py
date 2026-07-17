#!/usr/bin/env python3
"""
Entrypoint for the local dashboard server. Not meant to be run directly by
a user in the common case — services/dashboard_server_manager.py spawns
this as a detached subprocess with an OS-assigned free port.

    python scripts/dashboard_server.py --port 54321
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import uvicorn

from services.dashboard_app import app


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()

    # Single worker, no reload — minimal memory footprint by design.
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning", workers=1)


if __name__ == "__main__":
    main()
