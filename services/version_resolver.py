import re
from typing import Dict


class VersionResolver:
    """
    Resolves a Drupal issue's target version into:
      - git checkout_ref  (e.g. "11.x", "10.3.x")
      - DDEV project_type (e.g. "drupal11")
      - PHP version       (e.g. "8.2")
      - contrib_branch    (only for contrib issues)

    Contrib branch detection
    ─────────────────────────
    When the issue belongs to a contrib module, the version field looks like:
      "8.x-2.7", "3.x-dev", "2.0.0", "4.0.x-dev (D10)", "4.0.x-dev"

    We detect the compatible Drupal core version by:
    1. Explicit hint in parentheses — "(D9)", "(D10)", "(D11)", "(Drupal 10)"
    2. Module major version → Drupal core mapping heuristics:
       - branch prefix "8.x-*" historically targets D7/D8/D9 → default to current stable D11
         unless an explicit hint says otherwise
    3. Fall back to D11 if nothing found.
    """

    VERSION_MAP = {
        "11": ("drupal11", "8.3"),
        "10": ("drupal10", "8.3"),
        "9":  ("drupal9",  "8.1"),
        "8":  ("drupal",   "8.1"),
    }

    # Maps legacy "8.x-N.x" style major to likely Drupal core range.
    # These are heuristics only — explicit D-hints in the version string win.
    CONTRIB_LEGACY_CORE_DEFAULT = "11"

    @staticmethod
    def normalize_branch(version: str) -> str:
        """Convert a Drupal issue version string to a git branch name."""
        if not version:
            return "11.x"

        version = version.lower().strip()

        if version in ("main", ""):
            return "11.x"

        if version.endswith("-dev"):
            return version[:-4]  # "11.x-dev" → "11.x"

        # Strip parenthetical annotations e.g. "4.0.x-dev (D10)" → "4.0.x-dev"
        version = re.sub(r"\s*\(.*?\)\s*$", "", version).strip()
        if version.endswith("-dev"):
            return version[:-4]

        return version

    @staticmethod
    def detect_major(version: str) -> str:
        if not version:
            return "11"
        return version.split(".")[0]

    @staticmethod
    def _detect_core_from_contrib_version(raw_version: str) -> str:
        """
        Extract the compatible Drupal core major version from a contrib
        module version string.

        Returns a string like "10" or "11".
        """
        if not raw_version:
            return VersionResolver.CONTRIB_LEGACY_CORE_DEFAULT

        v = raw_version.strip()

        # 1. Explicit D-hint: "(D10)", "(Drupal 10)", "(D11)", etc.
        hint = re.search(r"\(D(?:rupal\s*)?(\d+)\)", v, re.IGNORECASE)
        if hint:
            return hint.group(1)

        # 2. Semver-style contrib version with core prefix like "10.x-3.x-dev"
        #    Some projects use "10.x-N.x" to signal D10 compatibility.
        semver_prefix = re.match(r"^(\d+)\.x-", v)
        if semver_prefix:
            prefix_major = semver_prefix.group(1)
            if prefix_major in VersionResolver.VERSION_MAP:
                return prefix_major

        # 3. Plain semver "2.x", "3.0.0" — no core signal, use latest stable.
        return VersionResolver.CONTRIB_LEGACY_CORE_DEFAULT

    @staticmethod
    def resolve(metadata: Dict) -> Dict:
        project_name = metadata.get("project_name", "drupal")
        raw_version = metadata.get("version", "main")

        if project_name != "drupal":
            core_major = VersionResolver._detect_core_from_contrib_version(raw_version)
            project_type, php_version = VersionResolver.VERSION_MAP.get(
                core_major, ("drupal11", "8.3")
            )
            core_branch = f"{core_major}.x"
            contrib_branch = VersionResolver.normalize_branch(raw_version)
            return {
                "checkout_ref": core_branch,
                "project_type": project_type,
                "php_version": php_version,
                "contrib_branch": contrib_branch,
            }

        checkout_ref = VersionResolver.normalize_branch(raw_version)
        major = VersionResolver.detect_major(checkout_ref)
        project_type, php_version = VersionResolver.VERSION_MAP.get(
            major, ("drupal11", "8.3")
        )
        return {
            "checkout_ref": checkout_ref,
            "project_type": project_type,
            "php_version": php_version,
        }
