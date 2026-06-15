"""
Central configuration for IssueForge.

All magic values (model names, timeouts, retry counts) live here so they
are easy to find, change, and override via environment variables.
"""

import os

# ---------------------------------------------------------------------------
# LLM
# ---------------------------------------------------------------------------

LLM_PRIMARY_MODEL_ANTHROPIC = os.getenv(
    "ISSUEFORGE_ANTHROPIC_MODEL", "claude-sonnet-4-5"
)
LLM_PRIMARY_MODEL_GEMINI = os.getenv(
    "ISSUEFORGE_GEMINI_MODEL", "gemini-2.5-flash"
)
LLM_FALLBACK_MODEL_GEMINI = os.getenv(
    "ISSUEFORGE_GEMINI_FALLBACK_MODEL", "gemini-2.5-flash-lite"
)
LLM_PRIMARY_MODEL_OPENAI = os.getenv(
    "ISSUEFORGE_OPENAI_MODEL", "gpt-4o"
)

LLM_MAX_TOKENS = int(os.getenv("ISSUEFORGE_LLM_MAX_TOKENS", "8096"))
LLM_TEMPERATURE = float(os.getenv("ISSUEFORGE_LLM_TEMPERATURE", "0.2"))
LLM_TIMEOUT_ANTHROPIC = int(os.getenv("ISSUEFORGE_LLM_TIMEOUT_ANTHROPIC", "120"))
LLM_TIMEOUT_GEMINI = int(os.getenv("ISSUEFORGE_LLM_TIMEOUT_GEMINI", "120"))
LLM_TIMEOUT_OPENAI = int(os.getenv("ISSUEFORGE_LLM_TIMEOUT_OPENAI", "60"))

# ---------------------------------------------------------------------------
# Drupal.org API
# ---------------------------------------------------------------------------

DRUPAL_API_BASE_URL = "https://www.drupal.org/api-d7"
DRUPAL_API_RETRIES = int(os.getenv("ISSUEFORGE_API_RETRIES", "5"))
DRUPAL_API_BACKOFF_BASE = int(os.getenv("ISSUEFORGE_API_BACKOFF", "1"))
DRUPAL_API_USER_AGENT = "IssueForge/1.0"

# ---------------------------------------------------------------------------
# Environment provisioner
# ---------------------------------------------------------------------------

ENVIRONMENTS_DIR = os.getenv(
    "ISSUEFORGE_ENVIRONMENTS_DIR",
    os.path.join(os.path.dirname(__file__), "environments"),
)
PROVISIONER_COMMAND_TIMEOUT = int(
    os.getenv("ISSUEFORGE_PROVISIONER_TIMEOUT", "600")
)  # seconds per command
PROVISIONER_REUSE_EXISTING = (
    os.getenv("ISSUEFORGE_REUSE_ENV", "true").lower() == "true"
)

# ---------------------------------------------------------------------------
# Reproduction scripts
# ---------------------------------------------------------------------------

REPRODUCTION_MAX_ATTEMPTS = int(
    os.getenv("ISSUEFORGE_REPRODUCTION_MAX_ATTEMPTS", "3")
)
REPRODUCTION_SCRIPT_TIMEOUT = int(
    os.getenv("ISSUEFORGE_REPRODUCTION_SCRIPT_TIMEOUT", "120")
)
REPRODUCTION_SYNTAX_TIMEOUT = int(
    os.getenv("ISSUEFORGE_REPRODUCTION_SYNTAX_TIMEOUT", "30")
)

# ---------------------------------------------------------------------------
# Git / GitLab credentials
# ---------------------------------------------------------------------------

# GitLab Personal Access Token (git.drupalcode.org → Settings → Access Tokens)
# Scope needed: read_api  (read_repository optional — public repos work without it)
# Optional: if absent, MR detection falls back to comment-scanning only.
GITLAB_TOKEN = os.getenv("GITLAB_TOKEN", "")

# Git identity used for commits/branches in the provisioned environment.
# These appear as the PR author when the user pushes from the env.
GIT_USER_NAME = os.getenv("GIT_USER_NAME", "")
GIT_USER_EMAIL = os.getenv("GIT_USER_EMAIL", "")

# ---------------------------------------------------------------------------
# Provisioner — git clone
# ---------------------------------------------------------------------------

# Depth for git clone in the provisioned environment.
# 1 = fastest but can't push branches. 50 = small overhead, enables PR workflow.
PROVISIONER_CLONE_DEPTH = int(os.getenv("ISSUEFORGE_CLONE_DEPTH", "50"))

# Branch name pattern for working branches created in the environment.
PROVISIONER_BRANCH_PATTERN = os.getenv(
    "ISSUEFORGE_BRANCH_PATTERN", "issue-{issue_id}-work"
)

# ---------------------------------------------------------------------------
# MR detection
# ---------------------------------------------------------------------------

GITLAB_API_BASE = "https://git.drupalcode.org/api/v4"
GITLAB_HOST = "git.drupalcode.org"
MR_DETECTION_MAX_COMMENTS = int(os.getenv("ISSUEFORGE_MR_MAX_COMMENTS", "50"))

# ---------------------------------------------------------------------------
# Regression checker
# ---------------------------------------------------------------------------

REGRESSION_PHPUNIT_TIMEOUT = int(os.getenv("ISSUEFORGE_PHPUNIT_TIMEOUT", "300"))
REGRESSION_HEALTH_TIMEOUT = int(os.getenv("ISSUEFORGE_HEALTH_TIMEOUT", "30"))

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

LOG_LEVEL_CONSOLE = os.getenv("ISSUEFORGE_LOG_LEVEL_CONSOLE", "WARNING")
LOG_LEVEL_FILE = os.getenv("ISSUEFORGE_LOG_LEVEL_FILE", "DEBUG")
LOG_FILE = os.getenv(
    "ISSUEFORGE_LOG_FILE",
    os.path.join(os.path.dirname(__file__), "logs", "issueforge.log"),
)
LOG_ROTATION_DAYS = int(os.getenv("ISSUEFORGE_LOG_ROTATION_DAYS", "7"))
