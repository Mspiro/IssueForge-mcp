"""
Credential manager for IssueForge.

Credentials are stored in ~/.issueforge/credentials — user home directory,
never the project directory.  This means:
  - They are found regardless of where you run the scripts from.
  - They persist across project re-clones or working-directory changes.
  - A single set of credentials is shared across all issues.

Prompting happens ONLY from scripts/setup.py (one-time setup).
All other scripts (analyze_issue.py, provision_env.py, etc.) load
credentials silently and NEVER prompt.  If credentials are absent they
log a hint and continue with graceful degradation.

Credentials managed:
  GITLAB_TOKEN         — GitLab PAT from git.drupalcode.org (optional)
  GIT_USER_NAME        — Name for git commits/branches in provisioned envs
  GIT_USER_EMAIL       — Email for git commits/branches in provisioned envs
  DRUPAL_ORG_USERNAME  — Drupal.org username (for uploading patches)
  DRUPAL_ORG_PASSWORD  — Drupal.org password (for uploading patches)
"""

import logging
import os
import re
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
    """Return True if the minimum required credentials (git identity) are saved."""
    return bool(
        os.getenv("GIT_USER_NAME", "").strip()
        and os.getenv("GIT_USER_EMAIL", "").strip()
    )


def get_credentials() -> dict:
    """
    Return all credentials from the store.  Never prompts.
    Missing values are returned as empty strings; callers degrade gracefully.
    """
    token = os.getenv("GITLAB_TOKEN", "").strip()
    name = os.getenv("GIT_USER_NAME", "").strip()
    email = os.getenv("GIT_USER_EMAIL", "").strip()
    drupal_user = os.getenv("DRUPAL_ORG_USERNAME", "").strip()
    drupal_pass = os.getenv("DRUPAL_ORG_PASSWORD", "").strip()

    if not name or not email:
        logger.warning(
            "Git identity not configured. Run `python scripts/setup.py` to set it up."
        )

    return {
        "gitlab_token": token,
        "git_name": name or "IssueForge User",
        "git_email": email or "issueforge@example.com",
        "drupal_username": drupal_user,
        "drupal_password": drupal_pass,
    }


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

def _validate_drupal_credentials(username: str, password: str) -> tuple:
    """
    Call the Drupal.org REST API to verify username + password.
    Returns (True, message) or (False, reason).
    """
    try:
        from services.drupal_patch_uploader import DrupalPatchUploader
        return DrupalPatchUploader.validate_credentials(username, password)
    except Exception as e:
        return False, f"Could not validate Drupal.org credentials: {e}"


def _validate_gitlab_token(token: str) -> tuple:
    """
    Call the GitLab API to verify the token.
    Returns (True, "Authenticated as <username>") or (False, "<reason>").
    """
    try:
        import requests
        resp = requests.get(
            "https://git.drupalcode.org/api/v4/user",
            headers={"PRIVATE-TOKEN": token},
            timeout=10,
        )
        if resp.status_code == 200:
            username = resp.json().get("username", "unknown")
            return True, f"Authenticated as @{username}"
        if resp.status_code == 401:
            return False, "Invalid or expired token (401 Unauthorized)."
        return False, f"GitLab API returned {resp.status_code}."
    except Exception as e:
        return False, f"Could not reach GitLab API: {e}"


def _is_valid_email(email: str) -> bool:
    return bool(re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email))


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
    Collect and validate all credentials interactively, then save them to
    ~/.issueforge/credentials.  Called only by scripts/setup.py.

    Each credential is validated before saving.  If validation fails the
    user is re-prompted and always has the option to skip.

    Args:
        force: If True, re-prompt even if credentials already exist.
    """
    print("\n" + "=" * 55)
    print("  IssueForge — First-Time Setup")
    print("  Credentials saved to:", CREDENTIALS_FILE)
    print("=" * 55 + "\n")

    # ----------------------------------------------------------------
    # Git name (required for authoring commits / PRs)
    # ----------------------------------------------------------------
    print("Git identity — used to author branches/commits in provisioned")
    print("environments. This becomes the PR author on Drupal.org.\n")

    current_name = os.getenv("GIT_USER_NAME", "").strip()
    if current_name and not force:
        print(f"  Git name  : {current_name}  (already set — press Enter to keep)")

    while True:
        name = _prompt(f"  Your full name [{current_name or 'e.g. Jane Smith'}]: ") or current_name
        if name:
            _persist("GIT_USER_NAME", name)
            break
        ans = _prompt("  No name entered. Continue without one? [y/N]: ")
        if ans.lower() in ("y", "yes"):
            print("  Skipping — commits will use a generic author name.")
            break

    # ----------------------------------------------------------------
    # Git email (required for authoring commits / PRs)
    # ----------------------------------------------------------------
    current_email = os.getenv("GIT_USER_EMAIL", "").strip()
    if current_email and not force:
        print(f"  Git email : {current_email}  (already set — press Enter to keep)")

    while True:
        email = _prompt(f"  Your email [{current_email or 'e.g. jane@example.com'}]: ") or current_email
        if not email:
            ans = _prompt("  No email entered. Continue without one? [y/N]: ")
            if ans.lower() in ("y", "yes"):
                print("  Skipping — commits will use a generic author email.")
                break
            continue
        if not _is_valid_email(email):
            print(f"  ✗ '{email}' is not a valid email address. Try again.")
            email = ""
            continue
        _persist("GIT_USER_EMAIL", email)
        break

    # ----------------------------------------------------------------
    # GitLab PAT (optional — enables MR detection + higher rate limits)
    # ----------------------------------------------------------------
    print("\nGitLab Personal Access Token — enables MR detection and higher")
    print("API rate limits.  Optional: press Enter to skip.\n")
    print("  Create one at: https://git.drupalcode.org/-/user_settings/personal_access_tokens")
    print("  Required scope: read_api\n")

    current_token = os.getenv("GITLAB_TOKEN", "").strip()
    if current_token and not force:
        masked = (
            current_token[:4] + "****" + current_token[-4:]
            if len(current_token) > 8 else "****"
        )
        print(f"  Token already set ({masked}) — press Enter to keep.")

    while True:
        token = _prompt("  GitLab PAT (hidden): ", secret=True)
        if not token:
            token = current_token if not force else ""
        if not token:
            print("  Skipping — MR detection will use the public API only.")
            break

        print("  Validating…", end=" ", flush=True)
        valid, message = _validate_gitlab_token(token)
        if valid:
            print(f"✓ {message}")
            _persist("GITLAB_TOKEN", token)
            break
        else:
            print(f"\n  ✗ {message}")
            ans = _prompt("  Try a different token? [y/N]: ")
            if ans.lower() not in ("y", "yes"):
                print("  Continuing without GitLab token.")
                break

    # ----------------------------------------------------------------
    # Drupal.org credentials (optional — needed for patch upload)
    # ----------------------------------------------------------------
    print("\nDrupal.org account — needed to upload patch files directly to")
    print("the issue page.  Optional: press Enter to skip.\n")
    print("  Your account at: https://www.drupal.org/user\n")

    current_drupal_user = os.getenv("DRUPAL_ORG_USERNAME", "").strip()
    if current_drupal_user and not force:
        print(f"  Username already set ({current_drupal_user}) — press Enter to keep.")

    drupal_user = (
        _prompt(f"  Drupal.org username [{current_drupal_user or 'e.g. janedrupal'}]: ")
        or current_drupal_user
    )

    if drupal_user:
        current_drupal_pass = os.getenv("DRUPAL_ORG_PASSWORD", "").strip()
        if current_drupal_pass and not force:
            print("  Password already set — press Enter to keep.")

        while True:
            drupal_pass = (
                _prompt("  Drupal.org password (hidden): ", secret=True)
                or (current_drupal_pass if not force else "")
            )
            if not drupal_pass:
                ans = _prompt("  No password entered. Skip Drupal.org credentials? [y/N]: ")
                if ans.lower() in ("y", "yes"):
                    print("  Skipping — patch uploads will save files locally only.")
                    drupal_user = ""
                    break
                continue

            print("  Validating…", end=" ", flush=True)
            valid, message = _validate_drupal_credentials(drupal_user, drupal_pass)
            if valid:
                print(f"✓ {message}")
                _persist("DRUPAL_ORG_USERNAME", drupal_user)
                _persist("DRUPAL_ORG_PASSWORD", drupal_pass)
                break
            else:
                print(f"\n  ✗ {message}")
                ans = _prompt("  Try different credentials? [y/N]: ")
                if ans.lower() not in ("y", "yes"):
                    print("  Continuing without Drupal.org credentials.")
                    drupal_user = ""
                    break
    else:
        print("  Skipping — patch uploads will save files locally only.")

    print("\n[OK] Credentials saved to", CREDENTIALS_FILE)
    print("     You won't be asked again.\n")

    return get_credentials()
