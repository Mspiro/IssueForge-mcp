#!/usr/bin/env python3
"""
IssueForge installer.

Run this one file to install IssueForge and register the /issueforge
slash command in Claude Code:

    python3 install.py

Or as a one-liner:

    curl -fsSL https://raw.githubusercontent.com/Mspiro/IssueForge-mcp/main/install.py | python3
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO_URL = "https://github.com/Mspiro/IssueForge-mcp.git"
DEFAULT_DIR = str(Path.home() / "IssueForge")
CLAUDE_DIR = Path.home() / ".claude"
CLAUDE_COMMANDS_DIR = CLAUDE_DIR / "commands"
CLAUDE_SETTINGS = CLAUDE_DIR / "settings.json"


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
    # Default to wherever install.py is located.
    # In pipe mode (curl | python3) fall back to ~/IssueForge.
    script_dir = os.path.dirname(os.path.abspath(__file__))
    default = script_dir if os.path.isdir(script_dir) else DEFAULT_DIR

    if not sys.stdin.isatty():
        print(f"Install directory: {DEFAULT_DIR} (using default)")
        return DEFAULT_DIR
    answer = input(f"Install directory [{default}]: ").strip()
    return answer or default


def clone_or_update(install_dir):
    if os.path.isdir(os.path.join(install_dir, ".git")):
        print("Existing installation found — updating to latest...")
        run(["git", "fetch", "origin"], cwd=install_dir)
        run(["git", "reset", "--hard", "origin/main"], cwd=install_dir)
    elif os.path.isdir(install_dir):
        # Directory exists but is not a git repo (e.g. user ran install.py from there).
        # Init in-place and pull from the remote.
        print(f"Setting up IssueForge in {install_dir}...")
        run(["git", "init"], cwd=install_dir)
        run(["git", "remote", "add", "origin", REPO_URL], cwd=install_dir)
        run(["git", "fetch", "origin"], cwd=install_dir)
        run(["git", "reset", "--hard", "origin/main"], cwd=install_dir)
    else:
        print(f"Cloning IssueForge into {install_dir}...")
        run(["git", "clone", REPO_URL, install_dir])


def install_dependencies(install_dir):
    print("Installing Python dependencies...")
    venv_dir = os.path.join(install_dir, "venv")
    is_win = os.name == "nt"
    pip_path = os.path.join(venv_dir, "Scripts" if is_win else "bin", "pip")
    python_path = os.path.join(venv_dir, "Scripts" if is_win else "bin", "python")

    if not os.path.exists(pip_path):
        result = subprocess.run([sys.executable, "-m", "venv", venv_dir], check=False)
        if result.returncode != 0 or not os.path.exists(pip_path):
            print("  Standard venv unavailable — bootstrapping pip manually...")
            subprocess.run([sys.executable, "-m", "venv", "--without-pip", venv_dir], check=True)
            import urllib.request
            get_pip = os.path.join(install_dir, "_get_pip.py")
            urllib.request.urlretrieve("https://bootstrap.pypa.io/get-pip.py", get_pip)
            subprocess.run([python_path, get_pip, "--quiet"], check=True)
            os.remove(get_pip)

    subprocess.run([pip_path, "install", "-q", "-r",
                    os.path.join(install_dir, "requirements.txt")], check=True)
    return python_path


def run_credential_setup(install_dir, python_bin):
    print("\nSetting up credentials (git identity, GitLab token, Drupal.org)...")
    run([python_bin, "scripts/setup.py", "--force"], cwd=install_dir)


def register_skill(install_dir):
    """Write ~/.claude/commands/issueforge.md with the correct install path."""
    skill_template = os.path.join(install_dir, ".claude", "commands", "issueforge.md")
    if not os.path.exists(skill_template):
        print("Skill template not found — skipping Claude registration.")
        return

    with open(skill_template) as f:
        content = f.read()

    content = content.replace("{{ISSUEFORGE_DIR}}", install_dir)

    CLAUDE_COMMANDS_DIR.mkdir(parents=True, exist_ok=True)
    dest = CLAUDE_COMMANDS_DIR / "issueforge.md"
    dest.write_text(content)
    print("Registered /issueforge command in Claude Code.")


def register_permissions(install_dir):
    """Add IssueForge bash commands to Claude Code's auto-allow list."""
    new_rules = [
        f"Bash(python {install_dir}/scripts/*)",
        f"Bash(python3 {install_dir}/scripts/*)",
        f"Bash(ddev describe*)",
        f"Bash(ddev start*)",
        f"Bash(ddev stop*)",
        f"Bash(ddev poweroff*)",
        f"Bash(ddev drush*)",
        f"Bash(git -C {install_dir}*)",
    ]

    settings = {}
    if CLAUDE_SETTINGS.exists():
        try:
            settings = json.loads(CLAUDE_SETTINGS.read_text())
        except Exception:
            pass

    permissions = settings.setdefault("permissions", {})
    allow = permissions.setdefault("allow", [])

    added = 0
    for rule in new_rules:
        if rule not in allow:
            allow.append(rule)
            added += 1

    CLAUDE_DIR.mkdir(parents=True, exist_ok=True)
    CLAUDE_SETTINGS.write_text(json.dumps(settings, indent=2))
    if added:
        print(f"Added {added} auto-allow rules to Claude Code settings.")
    else:
        print("Claude Code permissions already up to date.")


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
    register_permissions(install_dir)

    print("\n" + "=" * 50)
    print("  Done!")
    print(f"  Installed at : {install_dir}")
    print("  Restart Claude Code, then type:")
    print("  /issueforge <drupal-issue-url>")
    print("=" * 50)


if __name__ == "__main__":
    main()
