"""
CheckRunner — deterministic pass/fail + failure-signature primitive backing
the bounded fix/verify loop (TDD test-pass, PHPStan-clean, reviewer-critique
gates in the issueforge.md workflow).

There is no LLM call anywhere in this module. "The AI" in IssueForge is
Claude Code itself, driven by the .claude/commands/issueforge.md protocol —
this module's only job is to give it a cheap, comparable signal so it can
follow a bounded retry loop instead of guessing whether an attempt made
progress:

    result1 = CheckRunner.run_phpunit_test(env_path, test_file)
    ... apply a fix ...
    result2 = CheckRunner.run_phpunit_test(env_path, test_file)
    if result2["passed"]: done
    elif result2["signature"] == result1["signature"]: stuck — escalate, don't retry blindly
    else: real progress — one more bounded attempt is worth it

A "signature" is a short, stable, order-independent summary of what failed
(failing test method names; file:line:message triples) — NOT raw output,
which varies between runs (timings, temp paths) even when the underlying
failure is identical.
"""

import json
import logging
import os
import re
import shlex
import subprocess
from typing import Dict, List

from config import CHECK_PHPSTAN_TIMEOUT
from services.regression_checker import RegressionChecker, _strip_noise

logger = logging.getLogger("IssueForge.CheckRunner")

_PHPUNIT_FAILURE_HEADER = re.compile(r"^\d+\)\s+(\S+::\S+)", re.MULTILINE)


class CheckRunner:

    @staticmethod
    def run_phpunit_test(env_path: str, test_file: str) -> Dict:
        """
        Run a single PHPUnit test file/class and return pass/fail plus a
        signature of which test methods failed. Reuses RegressionChecker's
        env-var-aware runner rather than duplicating subprocess handling.
        """
        result = RegressionChecker.run_phpunit(env_path, [test_file])
        test_result = (result.get("test_results") or [{}])[0]
        output = test_result.get("output", "")
        signature = sorted(set(_PHPUNIT_FAILURE_HEADER.findall(output)))
        return {
            "passed": bool(test_result.get("passed")),
            "signature": signature,
            "output": output,
        }

    @staticmethod
    def run_phpstan(env_path: str, changed_files: List[str]) -> Dict:
        """
        Run PHPStan against only the given PHP files, using the project's
        own config (core/phpstan.neon.dist, falling back to a contrib
        module's own phpstan.neon if present). Returns pass/fail plus a
        signature of {file}:{line}:{message} triples.
        """
        php_files = [f for f in changed_files if f.endswith(".php")]
        if not php_files:
            return {"passed": True, "skipped": True, "reason": "No PHP files changed.", "signature": []}

        config_path = CheckRunner._find_phpstan_config(env_path, php_files)
        if not config_path:
            return {
                "passed": True,
                "skipped": True,
                "reason": "No phpstan.neon(.dist) found — skipping static analysis.",
                "signature": [],
            }

        quoted_files = " ".join(shlex.quote(f) for f in php_files)
        cmd = (
            f"cd /var/www/html && vendor/bin/phpstan analyze "
            f"--configuration={shlex.quote(config_path)} --error-format=json --no-progress "
            f"{quoted_files}"
        )
        try:
            proc = subprocess.run(
                ["ddev", "exec", "sh", "-c", cmd],
                cwd=env_path,
                capture_output=True,
                text=True,
                timeout=CHECK_PHPSTAN_TIMEOUT,
            )
        except subprocess.TimeoutExpired:
            return {
                "passed": False,
                "timed_out": True,
                "signature": [],
                "output": f"PHPStan timed out after {CHECK_PHPSTAN_TIMEOUT}s",
            }

        return CheckRunner._parse_phpstan_json(proc.stdout)

    @staticmethod
    def _find_phpstan_config(env_path: str, php_files: List[str]) -> str:
        """
        Prefer a contrib module's own phpstan.neon if the changed files are
        entirely within one contrib module; otherwise fall back to core's.
        Returns a path relative to the Drupal root, or "" if none exist.
        """
        contrib_dirs = {
            f.split("/src/")[0] for f in php_files if f.startswith("modules/contrib/")
        }
        if len(contrib_dirs) == 1:
            module_dir = next(iter(contrib_dirs))
            for name in ("phpstan.neon", "phpstan.neon.dist"):
                candidate = f"{module_dir}/{name}"
                if os.path.exists(os.path.join(env_path, candidate)):
                    return candidate

        for candidate in ("core/phpstan.neon.dist", "core/phpstan.neon"):
            if os.path.exists(os.path.join(env_path, candidate)):
                return candidate
        return ""

    @staticmethod
    def _parse_phpstan_json(raw_stdout: str) -> Dict:
        try:
            data = json.loads(raw_stdout)
        except (ValueError, TypeError):
            return {
                "passed": False,
                "signature": [],
                "output": _strip_noise(raw_stdout)[-2000:],
                "parse_error": True,
            }

        signature = []
        for file_path, file_result in data.get("files", {}).items():
            for message in file_result.get("messages", []):
                signature.append(f"{file_path}:{message.get('line')}: {message.get('message')}")
        signature.sort()

        total_errors = data.get("totals", {}).get("file_errors", 0)
        return {
            "passed": total_errors == 0,
            "signature": signature,
            "error_count": total_errors,
        }

    @staticmethod
    def same_signature(a: Dict, b: Dict) -> bool:
        """True if two check results represent the same failure (no progress)."""
        return a.get("signature", []) == b.get("signature", [])
