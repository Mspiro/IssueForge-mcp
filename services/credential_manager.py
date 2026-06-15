"""
Credential manager for IssueForge.

Credentials are stored in ~/.issueforge/credentials — user home directory,
never the project directory.

Setup only asks for one thing: the GitLab Personal Access Token.
Name and email are derived automatically from the GitLab API.
"""

import logging
import os
import sys
from pathlib import Path
from dotenv import load_dotenv, set_key

logger = logging.getLogger("IssueForge.CredentialManager")

# Fixed location — always the same regardless of cwd or project path.
CREDENTIALS_DIR = Path.home() / ".issueforge"
CREDENTIALS_FILE = CREDENTIALS_DIR / "credentials"

# Load on import so os.getenv() works everywhere in the process.
# override=False means real env vars (e.g. from CI) always win.
def _load():
    if CREDENTIALS_FILE.exists():
        load_dotenv(dotenv_path=str(CREDENTIALS_FILE), override=False)

_load()


def _persist(key: str, value: str):
    """Write a key=value pair to ~/.issueforge/credentials."""
    CREDENTIALS_DIR.mkdir(parents=True, exist_ok=True)
    CREDENTIALS_FILE.touch(exist_ok=True)
    set_key(str(CREDENTIALS_FILE), key, value)
    os.environ[key] = value  # make visible in the current process immediately


def is_setup_complete() -> bool:
    """Return True if the GitLab token has been saved."""
    return bool(os.getenv("GITLAB_TOKEN", "").strip())


def get_credentials() -> dict:
    """Return all credentials from the store. Never prompts."""
    token = os.getenv("GITLAB_TOKEN", "").strip()
    name = os.getenv("GIT_USER_NAME", "").strip()
    email = os.getenv("GIT_USER_EMAIL", "").strip()
    return {
        "gitlab_token": token,
        "git_name": name or "IssueForge User",
        "git_email": email or "issueforge@example.com",
        "drupal_username": "",
        "drupal_password": "",
    }


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

def _validate_gitlab_token(token: str) -> tuple:
    """
    Validate the token against the GitLab API.
    Returns (True, user_info_dict) or (False, error_string).
    user_info_dict has keys: username, name, email.
    """
    try:
        import requests
        resp = requests.get(
            "https://git.drupalcode.org/api/v4/user",
            headers={"PRIVATE-TOKEN": token},
            timeout=10,
        )
        if resp.status_code == 200:
            data = resp.json()
            return True, {
                "username": data.get("username", ""),
                "name": data.get("name", ""),
                "email": data.get("email", ""),
            }
        if resp.status_code == 401:
            return False, "Invalid or expired token (401 Unauthorized)."
        return False, f"GitLab API returned {resp.status_code}."
    except Exception as e:
        return False, f"Could not reach GitLab API: {e}"


# ---------------------------------------------------------------------------
# Setup helpers — called only from scripts/setup.py
# ---------------------------------------------------------------------------

def _prompt(prompt_text: str, secret: bool = False) -> str:
    """Interactive prompt. Returns empty string if stdin is not a TTY."""
    if not sys.stdin.isatty():
        return ""
    try:
        if secret:
            import getpass
            return getpass.getpass(prompt_text).strip()
        return input(prompt_text).strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return ""


def run_interactive_setup(force: bool = False) -> dict:
    """
    Ask only for the GitLab token. Name and email are auto-derived from it.
    Called only by scripts/setup.py.
    """
    print("\n" + "=" * 55)
    print("  IssueForge — Setup")
    print("=" * 55)
    print()
    print("  You need a GitLab Personal Access Token from git.drupalcode.org")
    print("  to use IssueForge. It enables MR detection and push access.")
    print()
    print("  Create one here (scope: read_api):")
    print("  https://git.drupalcode.org/-/user_settings/personal_access_tokens")
    print()

    current_token = os.getenv("GITLAB_TOKEN", "").strip()
    if current_token and not force:
        masked = (
            current_token[:4] + "****" + current_token[-4:]
            if len(current_token) > 8 else "****"
        )
        print(f"  Token already set ({masked}) — press Enter to keep.")

    while True:
        token = _prompt("  GitLab token (hidden): ", secret=True)
        if not token:
            token = current_token if not force else ""
        if not token:
            print("  No token entered. Run setup again when you have one.")
            print("  MR detection and push will not be available.")
            break

        print("  Validating…", end=" ", flush=True)
        valid, result = _validate_gitlab_token(token)
        if valid:
            name = result.get("name", "")
            email = result.get("email", "")
            username = result.get("username", "")
            print(f"OK — logged in as @{username}")
            _persist("GITLAB_TOKEN", token)
            if name:
                _persist("GIT_USER_NAME", name)
                print(f"  Name  : {name}")
            if email:
                _persist("GIT_USER_EMAIL", email)
                print(f"  Email : {email}")
            break
        else:
            print(f"\n  ✗ {result}")
            ans = _prompt("  Try a different token? [y/N]: ")
            if ans.lower() not in ("y", "yes"):
                print("  Setup cancelled.")
                break

    print()
    print("[OK] Credentials saved to", CREDENTIALS_FILE)
    print()

    return get_credentials()
