import re
import subprocess
from typing import Dict, List, Optional


class VersionResolver:
    """
    Resolves a Drupal issue's target version into:
      - git checkout_ref  (e.g. "11.x", "10.3.x")
      - DDEV project_type (e.g. "drupal11")
      - PHP version       (e.g. "8.2")
      - contrib_branch    (only for contrib issues)

    Contrib core-version detection, in priority order:
    1. The module's own `core_version_requirement` in its info.yml, fetched
       from git.drupalcode.org for the resolved contrib branch. This is the
       authoritative signal — it's what Drupal itself enforces at install.
    2. Explicit hint in parentheses — "(D9)", "(D10)", "(D11)", "(Drupal 10)"
    3. Fall back to the current stable core (D11).

    The chosen core major is then mapped to a branch that actually exists on
    the core repository: only "11.x" exists as a bare-major branch; D10/D9/D8
    development happens on "N.M.x" branches (10.6.x, 9.5.x, …), so the major
    must be resolved against `git ls-remote` (with a static fallback) rather
    than naively formatted as "N.x".
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

    CORE_REPO = "https://git.drupalcode.org/project/drupal.git"

    # Used when `git ls-remote` is unavailable (offline/timeout). Latest
    # stable branch per major as of 2026-07; only majors without a real
    # bare "N.x" branch need an entry — 11.x exists and needs none.
    FALLBACK_CORE_BRANCHES = {
        "11": "11.x",
        "10": "10.6.x",
        "9": "9.5.x",
        "8": "8.9.x",
    }

    # Populated lazily by _list_core_branches(); one network call per process.
    _core_branches_cache: Optional[List[str]] = None

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
        #    "8.x-N.x" is excluded: it's the pre-D9 legacy branch naming
        #    scheme (predates per-core-version prefixes) and does not mean
        #    "requires Drupal 8 core" — treating it as a literal match used
        #    to resolve checkout_ref to "8.x", a branch that doesn't exist
        #    in Drupal core (core's last 8-series branch was "8.9.x"), which
        #    made cloning fail outright for any "8.x-*" contrib module.
        semver_prefix = re.match(r"^(\d+)\.x-", v)
        if semver_prefix:
            prefix_major = semver_prefix.group(1)
            if prefix_major != "8" and prefix_major in VersionResolver.VERSION_MAP:
                return prefix_major

        # 3. Plain semver "2.x", "3.0.0" — no core signal, use latest stable.
        return VersionResolver.CONTRIB_LEGACY_CORE_DEFAULT

    @staticmethod
    def _fetch_core_requirement(project_name: str, contrib_branch: str) -> Optional[str]:
        """
        Fetch the module's `core_version_requirement` from its info.yml on
        git.drupalcode.org. Returns the raw requirement string (e.g.
        "^10.3 || ^11") or None when unavailable (offline, wrong branch,
        module without info.yml at the repo root).
        """
        import requests
        url = (
            f"https://git.drupalcode.org/project/{project_name}/-/raw/"
            f"{contrib_branch}/{project_name}.info.yml"
        )
        try:
            resp = requests.get(url, timeout=8)
            if resp.status_code != 200:
                return None
            m = re.search(
                r"^core_version_requirement:\s*['\"]?([^'\"\n]+)",
                resp.text, re.MULTILINE,
            )
            return m.group(1).strip() if m else None
        except Exception:
            return None

    @staticmethod
    def _pick_core_major_from_requirement(requirement: str) -> Optional[str]:
        """
        Choose the newest supported core major out of a composer-style
        requirement like "^9.5 || ^10 || ^11". Returns None when no major
        in the requirement is one we can provision.
        """
        majors = {
            m for m in re.findall(r"(\d+)(?:\.\d+)*", requirement)
            if m in VersionResolver.VERSION_MAP
        }
        return max(majors, key=int) if majors else None

    @staticmethod
    def _list_core_branches() -> List[str]:
        """All branch names on the core repo, cached for the process."""
        if VersionResolver._core_branches_cache is not None:
            return VersionResolver._core_branches_cache
        try:
            result = subprocess.run(
                ["git", "ls-remote", "--heads", VersionResolver.CORE_REPO],
                capture_output=True, text=True, timeout=30,
            )
            branches = [
                line.split("refs/heads/", 1)[1].strip()
                for line in result.stdout.splitlines()
                if "refs/heads/" in line
            ] if result.returncode == 0 else []
        except Exception:
            branches = []
        VersionResolver._core_branches_cache = branches
        return branches

    @staticmethod
    def _resolve_core_branch(core_major: str) -> str:
        """
        Map a core major ("10") to a branch that actually exists on the core
        repo. Only "11.x" exists as a bare-major branch; other majors live on
        "N.M.x" branches, so pick the highest one for that major. Falls back
        to a static table when the branch list can't be fetched.
        """
        branches = VersionResolver._list_core_branches()
        bare = f"{core_major}.x"
        if bare in branches:
            return bare
        minor_branches = [
            b for b in branches
            if re.fullmatch(rf"{core_major}\.\d+\.x", b)
        ]
        if minor_branches:
            return max(minor_branches, key=lambda b: int(b.split(".")[1]))
        return VersionResolver.FALLBACK_CORE_BRANCHES.get(core_major, "11.x")

    @staticmethod
    def resolve(metadata: Dict) -> Dict:
        project_name = metadata.get("project_name", "drupal")
        raw_version = metadata.get("version", "main")

        if project_name != "drupal":
            contrib_branch = VersionResolver.normalize_branch(raw_version)

            # Authoritative: the module's own core_version_requirement.
            core_major = None
            requirement = VersionResolver._fetch_core_requirement(
                project_name, contrib_branch
            )
            if requirement:
                core_major = VersionResolver._pick_core_major_from_requirement(
                    requirement
                )
            if core_major is None:
                core_major = VersionResolver._detect_core_from_contrib_version(
                    raw_version
                )

            project_type, php_version = VersionResolver.VERSION_MAP.get(
                core_major, ("drupal11", "8.3")
            )
            return {
                "checkout_ref": VersionResolver._resolve_core_branch(core_major),
                "project_type": project_type,
                "php_version": php_version,
                "contrib_branch": contrib_branch,
                "core_version_requirement": requirement,
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
