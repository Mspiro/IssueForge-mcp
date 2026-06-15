#!/usr/bin/env python3
"""
IssueForge installer.

Run this one file to install IssueForge and register the /issueforge
slash command in Claude Code:

    python3 install.py

Or as a one-liner:

    curl -fsSL https://raw.githubusercontent.com/Mspiro/IssueForge-mcp/main/install.py | python3
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO_URL = "https://github.com/Mspiro/IssueForge-mcp.git"
DEFAULT_DIR = str(Path.home() / "IssueForge")
CLAUDE_COMMANDS_DIR = Path.home() / ".claude" / "commands"


def run(cmd, cwd=None, check=True):
    return subprocess.run(cmd, cwd=cwd, check=check)


def check_prerequisites():
    missing = []
    for tool in ("git", "python3", "ddev"):
        if not shutil.which(tool):
            missing.append(tool)
    if missing:
        print(f"Missing required tools: {', '.join(missing)}")
        print("Install them and re-run.")
        sys.exit(1)
    if sys.version_info < (3, 8):
        print("Python 3.8 or higher is required.")
        sys.exit(1)


def get_install_dir():
    answer = input(f"Install directory [{DEFAULT_DIR}]: ").strip()
    return answer or DEFAULT_DIR


def clone_or_update(install_dir):
    if os.path.isdir(os.path.join(install_dir, ".git")):
        print("Existing installation found — pulling latest changes...")
        run(["git", "pull"], cwd=install_dir)
    else:
        print(f"Cloning IssueForge into {install_dir}...")
        run(["git", "clone", REPO_URL, install_dir])


def install_dependencies(install_dir):
    print("Installing Python dependencies...")
    venv_dir = os.path.join(install_dir, "venv")
    run([sys.executable, "-m", "venv", venv_dir])
    pip = os.path.join(venv_dir, "bin", "pip") if os.name != "nt" else os.path.join(venv_dir, "Scripts", "pip")
    run([pip, "install", "-q", "-r", os.path.join(install_dir, "requirements.txt")])
    return os.path.join(venv_dir, "bin", "python") if os.name != "nt" else os.path.join(venv_dir, "Scripts", "python")


def run_credential_setup(install_dir, python_bin):
    print("\nSetting up credentials (GitLab token, git identity, Drupal.org)...")
    run([python_bin, "scripts/setup.py"], cwd=install_dir)


def register_skill(install_dir):
    """Write ~/.claude/commands/issueforge.md with the correct install path."""
    skill_template = os.path.join(install_dir, ".claude", "commands", "issueforge.md")
    if not os.path.exists(skill_template):
        print("Skill template not found — skipping Claude registration.")
        return

    with open(skill_template) as f:
        content = f.read()

    # Substitute the placeholder with the real install path
    content = content.replace("{{ISSUEFORGE_DIR}}", install_dir)

    CLAUDE_COMMANDS_DIR.mkdir(parents=True, exist_ok=True)
    dest = CLAUDE_COMMANDS_DIR / "issueforge.md"
    dest.write_text(content)
    print(f"Registered /issueforge command in Claude Code.")


def main():
    print("=" * 50)
    print("  IssueForge Installer")
    print("=" * 50 + "\n")

    check_prerequisites()
    install_dir = get_install_dir()

    clone_or_update(install_dir)
    python_bin = install_dependencies(install_dir)
    run_credential_setup(install_dir, python_bin)
    register_skill(install_dir)

    print("\n" + "=" * 50)
    print("  Done!")
    print(f"  Installed at : {install_dir}")
    print("  Open Claude Code in any project and type:")
    print("  /issueforge <drupal-issue-url>")
    print("=" * 50)


if __name__ == "__main__":
    main()
