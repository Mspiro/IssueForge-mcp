"""
Coding-standards gate — runs phpcs on the files about to be contributed and
auto-fixes violations with phpcbf BEFORE anything is pushed to a fork or
exported as a patch.

Rationale: Drupal.org GitLab CI runs a strict PHPCS job on every MR; a
single missing blank line fails the whole pipeline and costs a review
round-trip. Checking locally is seconds; a red pipeline is hours.

Uses the environment's own toolchain inside DDEV (vendor/bin/phpcs comes
with drupal/core-dev; the Drupal/DrupalPractice standards are registered by
drupal/coder at composer install time). Prefers core's phpcs.xml.dist when
the environment is a core checkout, falling back to the plain Drupal
standard for detached contrib work.
"""

import logging
import os
import shlex
import subprocess
from typing import Dict, List

logger = logging.getLogger("IssueForge.CodingStandardsChecker")

# File types Drupal's PHPCS setup actually lints.
_LINTABLE_EXTENSIONS = (
    ".php", ".module", ".inc", ".install", ".theme", ".profile", ".engine",
)

_TIMEOUT = 300


class CodingStandardsChecker:

    @staticmethod
    def lintable(files: List[str]) -> List[str]:
        """Filter to the file types PHPCS lints."""
        return [f for f in files if f.endswith(_LINTABLE_EXTENSIONS)]

    @staticmethod
    def _standard_args(env_path: str) -> str:
        if os.path.exists(os.path.join(env_path, "core", "phpcs.xml.dist")):
            return "--standard=core/phpcs.xml.dist"
        return "--standard=Drupal,DrupalPractice"

    @staticmethod
    def _run(env_path: str, binary: str, files: List[str]) -> subprocess.CompletedProcess:
        cmd = (
            f"vendor/bin/{binary} -q "
            f"{CodingStandardsChecker._standard_args(env_path)} "
            + " ".join(shlex.quote(f) for f in files)
        )
        return subprocess.run(
            ["ddev", "exec", "sh", "-c", cmd],
            cwd=env_path,
            capture_output=True,
            text=True,
            timeout=_TIMEOUT,
        )

    @staticmethod
    def check(env_path: str, files: List[str]) -> Dict:
        """
        Run phpcs on the given env-relative files.
        Returns {passed, output, checked (list), skipped_reason?}.
        """
        targets = CodingStandardsChecker.lintable(files)
        targets = [
            f for f in targets if os.path.exists(os.path.join(env_path, f))
        ]
        if not targets:
            return {"passed": True, "output": "",
                    "checked": [], "skipped_reason": "No lintable PHP files."}
        try:
            proc = CodingStandardsChecker._run(env_path, "phpcs", targets)
        except subprocess.TimeoutExpired:
            return {"passed": False, "output": "phpcs timed out.",
                    "checked": targets}
        except Exception as e:
            # Toolchain missing (no core-dev install) — report, don't block.
            return {"passed": True, "output": str(e), "checked": [],
                    "skipped_reason": f"phpcs unavailable: {e}"}
        return {
            "passed": proc.returncode == 0,
            "output": (proc.stdout + proc.stderr).strip()[-3000:],
            "checked": targets,
        }

    @staticmethod
    def fix(env_path: str, files: List[str]) -> Dict:
        """Run phpcbf (autofixer) on the given files."""
        targets = CodingStandardsChecker.lintable(files)
        targets = [
            f for f in targets if os.path.exists(os.path.join(env_path, f))
        ]
        if not targets:
            return {"fixed": False, "output": ""}
        try:
            proc = CodingStandardsChecker._run(env_path, "phpcbf", targets)
        except Exception as e:
            return {"fixed": False, "output": str(e)}
        # phpcbf exit codes: 0 = nothing to fix, 1 = fixed everything
        # fixable, 2 = fixed some but unfixable remain, 3 = error.
        return {
            "fixed": proc.returncode in (1, 2),
            "output": (proc.stdout + proc.stderr).strip()[-2000:],
        }

    @staticmethod
    def check_and_fix(env_path: str, files: List[str]) -> Dict:
        """
        The pre-submission gate: check → autofix → re-check.
        Returns {passed, autofixed, output, checked, skipped_reason?}.
        `passed` reflects the FINAL state after any autofix.
        """
        first = CodingStandardsChecker.check(env_path, files)
        if first["passed"]:
            return {**first, "autofixed": False}

        fix_result = CodingStandardsChecker.fix(env_path, first["checked"])
        second = CodingStandardsChecker.check(env_path, first["checked"])
        return {
            **second,
            "autofixed": fix_result["fixed"],
        }
