"""
Central configuration for IssueForge.

All magic values (timeouts, retry counts) live here so they
are easy to find, change, and override via environment variables.
"""

import os

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

_BASE_DIR = os.path.dirname(os.path.realpath(__file__))

ENVIRONMENTS_DIR = os.getenv(
    "ISSUEFORGE_ENVIRONMENTS_DIR",
    os.path.join(_BASE_DIR, "environments"),
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

# Full-module regression sweep: runs a module's entire tests/src directory
# (Kernel + Functional + Unit) when a non-test source file in that module
# changed, since single-file heuristics can't find regressions in test
# files the patch never touched (e.g. a behavioral change breaking an
# unrelated, pre-existing functional test). This only costs wall-clock time
# — no LLM call is involved in running it.
REGRESSION_FULL_SUITE_TIMEOUT = int(os.getenv("ISSUEFORGE_FULL_SUITE_TIMEOUT", "900"))

# Functional PHPUnit tests (BrowserTestBase) require these to bootstrap.
# "web" (not "127.0.0.1") because PHPUnit runs via `ddev exec`, which executes
# inside the web container — but FunctionalJavascript tests drive a separate
# WebDriver/Chrome container that must reach the site over DDEV's internal
# network. "127.0.0.1" from that container's point of view is itself, not
# the web container, so every JS test fails with a WebDriver connection
# error regardless of the code under test. "web" resolves correctly from
# any container on the network, including the web container itself, so one
# value covers plain Functional and FunctionalJavascript tests alike — same
# convention SIMPLETEST_DB below already uses ("db", not "127.0.0.1").
REGRESSION_SIMPLETEST_BASE_URL = os.getenv("ISSUEFORGE_SIMPLETEST_BASE_URL", "http://web")
REGRESSION_SIMPLETEST_DB = os.getenv("ISSUEFORGE_SIMPLETEST_DB", "mysql://db:db@db/db")
REGRESSION_BROWSERTEST_OUTPUT_DIR = os.getenv("ISSUEFORGE_BROWSERTEST_OUTPUT_DIR", "/tmp")

# ---------------------------------------------------------------------------
# Check runner (bounded fix/verify loop primitive)
# ---------------------------------------------------------------------------

# PHPStan uses the project's own config (core/phpstan.neon.dist, or a
# contrib module's own if present) rather than a fixed --level=max — core's
# baseline already tunes out pre-existing noise unrelated to any given
# change; running at max level blind would surface thousands of unrelated
# baseline errors and make the gate impossible to satisfy.
CHECK_PHPSTAN_TIMEOUT = int(os.getenv("ISSUEFORGE_PHPSTAN_TIMEOUT", "180"))
CHECK_BOUNDED_RETRY_MAX_ATTEMPTS = int(os.getenv("ISSUEFORGE_CHECK_MAX_ATTEMPTS", "3"))

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

LOG_LEVEL_CONSOLE = os.getenv("ISSUEFORGE_LOG_LEVEL_CONSOLE", "WARNING")
LOG_LEVEL_FILE = os.getenv("ISSUEFORGE_LOG_LEVEL_FILE", "DEBUG")
LOG_FILE = os.getenv(
    "ISSUEFORGE_LOG_FILE",
    os.path.join(_BASE_DIR, "logs", "issueforge.log"),
)
LOG_ROTATION_DAYS = int(os.getenv("ISSUEFORGE_LOG_ROTATION_DAYS", "7"))
