"""
Regression checker — runs after a patch or MR is applied.

Four levels of confidence:

Level 1 — Health check (always runs, ~5s)
  `drush status` confirms Drupal still bootstraps and the DB is reachable.

Level 2 — Targeted PHPUnit (runs when test files are discoverable, ~30-300s)
  Runs test files that are either (a) changed/added directly by the patch
  itself, or (b) heuristically matched by source-file naming convention.

Level 2b — Full module suite (runs when a module's non-test source changed)
  File-name heuristics cannot find a regression in a pre-existing test file
  the patch never touched — that requires actually running the affected
  module's full tests/src directory. This is the safety net that catches
  behavioral regressions Level 2 structurally cannot see. It costs
  wall-clock time, not LLM tokens, since no model is involved in running it.

Level 3 — Module compatibility (runs when specific modules are installed)
  A PHP script checks that Layout Builder, Paragraphs, and SDC APIs
  still behave correctly after the change.
"""

import logging
import os
import re
import shlex
import subprocess
from typing import Dict, List, Optional

from config import (
    REGRESSION_PHPUNIT_TIMEOUT,
    REGRESSION_HEALTH_TIMEOUT,
    REGRESSION_FULL_SUITE_TIMEOUT,
    REGRESSION_SIMPLETEST_BASE_URL,
    REGRESSION_SIMPLETEST_DB,
    REGRESSION_BROWSERTEST_OUTPUT_DIR,
)

logger = logging.getLogger("IssueForge.RegressionChecker")

# Lines PHPUnit/Drupal print per-test when BROWSERTEST_OUTPUT_DIRECTORY is
# set — one per functional test, purely informational. They add nothing
# useful to a failure summary and can add hundreds of lines to output that
# gets fed back into an LLM context, so they're filtered out before capture.
_BROWSER_OUTPUT_LINE = re.compile(r"^https?://\S+/sites/simpletest/browser_output/")


def _strip_noise(output: str) -> str:
    return "\n".join(
        line for line in output.splitlines() if not _BROWSER_OUTPUT_LINE.match(line)
    )


def _phpunit_env_prefix() -> str:
    """Shell env-var prefix so functional (BrowserTestBase) tests can bootstrap."""
    return (
        f"SIMPLETEST_BASE_URL={shlex.quote(REGRESSION_SIMPLETEST_BASE_URL)} "
        f"SIMPLETEST_DB={shlex.quote(REGRESSION_SIMPLETEST_DB)} "
        f"BROWSERTEST_OUTPUT_DIRECTORY={shlex.quote(REGRESSION_BROWSERTEST_OUTPUT_DIR)} "
    )

# Modules whose compatibility we check if installed
_COMPAT_MODULES = ["layout_builder", "paragraphs", "sdc"]

# PHP script that exercises Layout Builder / Paragraphs / SDC APIs
_COMPAT_SCRIPT = """\
<?php
$results = [];
$modules = ['layout_builder', 'paragraphs', 'sdc'];
foreach ($modules as $module) {
  if (!\\Drupal::moduleHandler()->moduleExists($module)) {
    continue;
  }
  $ok = TRUE;
  try {
    switch ($module) {
      case 'layout_builder':
        \\Drupal::service('plugin.manager.core.layout')->getDefinitions();
        break;
      case 'paragraphs':
        \\Drupal\\paragraphs\\Entity\\ParagraphsType::loadMultiple();
        break;
      case 'sdc':
        \\Drupal::service('plugin.manager.sdc')->getDefinitions();
        break;
    }
  } catch (\\Exception $e) {
    $ok = FALSE;
    echo "[FAIL] $module compatibility: " . $e->getMessage() . "\\n";
  }
  if ($ok) {
    echo "[PASS] $module compatibility OK\\n";
  }
}
"""


class RegressionChecker:

    @staticmethod
    def run_all(env_path: str, changed_files: List[str]) -> Dict:
        """
        Run all levels and return a consolidated result.
        """
        results = {}

        # Level 1: health check
        results["health"] = RegressionChecker.run_health_check(env_path)

        # Level 2 / 2b: PHPUnit (only if Drupal is healthy)
        if results["health"]["passed"]:
            test_files = RegressionChecker.discover_test_files(env_path, changed_files)
            if test_files:
                results["phpunit"] = RegressionChecker.run_phpunit(env_path, test_files)
            else:
                results["phpunit"] = {
                    "skipped": True,
                    "reason": "No matching test files found for changed source files.",
                    "changed_files": changed_files,
                }

            affected_modules = RegressionChecker.extract_affected_modules(changed_files)
            if affected_modules:
                results["full_suite"] = RegressionChecker.run_full_module_suite(
                    env_path, affected_modules
                )
            else:
                results["full_suite"] = {
                    "skipped": True,
                    "reason": "No module source files changed — nothing to sweep.",
                }

        # Level 3: module compatibility
        results["compatibility"] = RegressionChecker.run_module_compatibility(env_path)

        results["overall_passed"] = (
            results["health"]["passed"]
            and results.get("phpunit", {}).get("passed", True)
            and results.get("full_suite", {}).get("passed", True)
            and results["compatibility"]["passed"]
        )

        return results

    # ------------------------------------------------------------------
    # Level 1: Health check
    # ------------------------------------------------------------------

    @staticmethod
    def run_health_check(env_path: str) -> Dict:
        """
        Run `drush status` to confirm Drupal bootstraps correctly.
        """
        try:
            result = subprocess.run(
                ["ddev", "drush", "status", "--format=json"],
                cwd=env_path,
                capture_output=True,
                text=True,
                timeout=REGRESSION_HEALTH_TIMEOUT,
            )
            passed = result.returncode == 0
            output = result.stdout + result.stderr
            if passed:
                logger.info("Health check passed.")
            else:
                logger.warning("Health check failed: %s", output[:500])
            return {"passed": passed, "output": output.strip()[:1000]}
        except subprocess.TimeoutExpired:
            return {"passed": False, "output": "Health check timed out."}
        except Exception as e:
            return {"passed": False, "output": str(e)}

    # ------------------------------------------------------------------
    # Level 2: PHPUnit
    # ------------------------------------------------------------------

    @staticmethod
    def is_test_file(path: str) -> bool:
        """True if this path is itself a PHPUnit test class."""
        f = path.lstrip("/")
        return "/tests/src/" in f and f.endswith("Test.php")

    @staticmethod
    def discover_test_files(env_path: str, changed_files: List[str]) -> List[str]:
        """
        Discover test files to run for this patch.

        Two sources, both added directly (no naming heuristic needed):
        1. Self-match — any changed/added file that IS ALREADY a test file
           (new test added by the patch, or an existing test it modified).
           This is exact and catches every test the patch itself touches.
        2. Heuristic guess — for changed non-test source files, guess a
           same-named test file by convention:
           - core/lib/Drupal/X/Y.php → core/tests/Drupal/Tests/X/YTest.php (Unit)
           - core/modules/FOO/src/Y.php → core/modules/FOO/tests/src/{Unit,Kernel}/YTest.php
           - modules/contrib/FOO/src/Y.php → same, under modules/contrib/FOO

        Note: (2) only finds tests that happen to share the source class's
        name. It cannot find a regression in an unrelated, pre-existing test
        — that's what the Level 2b full-module sweep in run_all() is for.
        """
        found = []
        seen = set()

        for f in changed_files:
            if RegressionChecker.is_test_file(f):
                full = os.path.join(env_path, f.lstrip("/"))
                if os.path.exists(full) and f not in seen:
                    found.append(f)
                    seen.add(f)
                    logger.debug("Self-matched test file: %s", f)

        for f in changed_files:
            if RegressionChecker.is_test_file(f):
                continue
            candidates = RegressionChecker._candidate_test_paths(f)
            for candidate in candidates:
                full = os.path.join(env_path, candidate)
                if os.path.exists(full) and candidate not in seen:
                    found.append(candidate)
                    seen.add(candidate)
                    logger.debug("Found test file: %s", candidate)
                    break  # take first match per source file

        logger.info(
            "Discovered %d test file(s) for %d changed file(s).",
            len(found), len(changed_files),
        )
        return found

    @staticmethod
    def _candidate_test_paths(source_file: str) -> List[str]:
        """Return likely test file paths for a given source file path."""
        candidates = []
        f = source_file.lstrip("/")

        # Pattern 1: core/lib/Drupal/Core/... → core/tests/Drupal/Tests/Core/...Test.php
        if f.startswith("core/lib/Drupal/"):
            rel = f[len("core/lib/Drupal/"):]  # e.g. "Core/Entity/Element/EntityAutocomplete.php"
            test_rel = rel[:-4] + "Test.php"   # → "Core/Entity/Element/EntityAutocompleteTest.php"
            candidates.append(f"core/tests/Drupal/Tests/{test_rel}")

        # Pattern 2: core/modules/FOO/src/Bar.php → core/modules/FOO/tests/src/Unit/BarTest.php
        m = re.match(r"(core/modules/[^/]+)/src/(.+)\.php", f)
        if m:
            candidates.append(f"{m.group(1)}/tests/src/Unit/{m.group(2)}Test.php")
            candidates.append(f"{m.group(1)}/tests/src/Kernel/{m.group(2)}Test.php")
            candidates.append(f"{m.group(1)}/tests/src/Functional/{m.group(2)}Test.php")

        # Pattern 3: modules/contrib/FOO/src/Bar.php → similar
        m2 = re.match(r"(modules/contrib/[^/]+)/src/(.+)\.php", f)
        if m2:
            candidates.append(f"{m2.group(1)}/tests/src/Unit/{m2.group(2)}Test.php")
            candidates.append(f"{m2.group(1)}/tests/src/Kernel/{m2.group(2)}Test.php")
            candidates.append(f"{m2.group(1)}/tests/src/Functional/{m2.group(2)}Test.php")

        return candidates

    # ------------------------------------------------------------------
    # Level 2b: Full module suite
    # ------------------------------------------------------------------

    @staticmethod
    def extract_affected_modules(changed_files: List[str]) -> List[Dict[str, str]]:
        """
        Return the modules whose *non-test* source changed, each as
        {"label": "layout_builder", "test_dir": "core/modules/layout_builder/tests/src"}.

        Only source changes trigger this — if a patch only touches test
        files, Level 2's self-match already runs them directly and a full
        sweep adds nothing. It's specifically behavioral (src/) changes that
        heuristics can't safety-net, because the regression can land in any
        pre-existing test in the module, not just a same-named one.
        """
        modules = {}
        for f in changed_files:
            if RegressionChecker.is_test_file(f):
                continue
            ff = f.lstrip("/")
            m = re.match(r"(core/modules/([^/]+))/src/", ff) or re.match(
                r"(modules/contrib/([^/]+))/src/", ff
            )
            if m:
                module_dir, label = m.group(1), m.group(2)
                modules[module_dir] = label

        return [
            {"label": label, "module_dir": module_dir, "test_dir": f"{module_dir}/tests/src"}
            for module_dir, label in modules.items()
        ]

    @staticmethod
    def run_full_module_suite(env_path: str, affected_modules: List[Dict[str, str]]) -> Dict:
        """
        Run each affected module's entire tests/src directory (Kernel +
        Functional + Unit together, since PHPUnit discovers by directory).

        Bounded by REGRESSION_FULL_SUITE_TIMEOUT per module — if a module's
        suite is too large to finish in time, that is reported explicitly
        as timed_out rather than silently skipped or reported as a pass.
        """
        phpunit_xml = os.path.join(env_path, "core", "phpunit.xml.dist")
        if not os.path.exists(phpunit_xml):
            return {
                "passed": True,
                "skipped": True,
                "reason": "phpunit.xml.dist not found — skipping full-suite sweep.",
            }

        results = []
        overall = True

        for module in affected_modules:
            test_dir = module["test_dir"]
            full_test_dir = os.path.join(env_path, test_dir)
            if not os.path.isdir(full_test_dir):
                results.append({
                    "module": module["label"],
                    "test_dir": test_dir,
                    "passed": True,
                    "skipped": True,
                    "reason": "Module has no tests/src directory.",
                })
                continue

            logger.info("Running full suite sweep for module %s (%s)", module["label"], test_dir)
            cmd = (
                f"cd /var/www/html && {_phpunit_env_prefix()}"
                f"vendor/bin/phpunit --configuration=core/phpunit.xml.dist "
                f"{shlex.quote(test_dir)} --no-coverage"
            )
            try:
                proc = subprocess.run(
                    ["ddev", "exec", "sh", "-c", cmd],
                    cwd=env_path,
                    capture_output=True,
                    text=True,
                    timeout=REGRESSION_FULL_SUITE_TIMEOUT,
                )
                passed = proc.returncode == 0
                overall = overall and passed
                output = _strip_noise(proc.stdout + proc.stderr)
                results.append({
                    "module": module["label"],
                    "test_dir": test_dir,
                    "passed": passed,
                    # Keep only the tail — PHPUnit puts the failure summary
                    # at the end; the dot-progress line at the top is noise.
                    "output": output.strip()[-4000:],
                })
                logger.info("Full suite %s: %s", module["label"], "PASS" if passed else "FAIL")
            except subprocess.TimeoutExpired:
                overall = False
                results.append({
                    "module": module["label"],
                    "test_dir": test_dir,
                    "passed": False,
                    "timed_out": True,
                    "output": (
                        f"Timed out after {REGRESSION_FULL_SUITE_TIMEOUT}s — "
                        f"this module's suite could not be fully verified. "
                        f"Not a pass: treat as unverified, not clean."
                    ),
                })

        return {
            "passed": overall,
            "module_results": results,
            "modules_run": len(results),
        }

    @staticmethod
    def run_phpunit(env_path: str, test_files: List[str]) -> Dict:
        """
        Run PHPUnit for the given test files.
        """
        phpunit_xml = os.path.join(env_path, "core", "phpunit.xml.dist")
        if not os.path.exists(phpunit_xml):
            return {
                "passed": True,
                "skipped": True,
                "reason": "phpunit.xml.dist not found — skipping PHPUnit.",
            }

        results = []
        overall = True

        for test_file in test_files:
            logger.info("Running PHPUnit for %s", test_file)
            try:
                cmd = (
                    f"cd /var/www/html && {_phpunit_env_prefix()}"
                    f"vendor/bin/phpunit --configuration=core/phpunit.xml.dist "
                    f"{shlex.quote(test_file)} --no-coverage"
                )
                proc = subprocess.run(
                    ["ddev", "exec", "sh", "-c", cmd],
                    cwd=env_path,
                    capture_output=True,
                    text=True,
                    timeout=REGRESSION_PHPUNIT_TIMEOUT,
                )
                passed = proc.returncode == 0
                overall = overall and passed
                output = _strip_noise(proc.stdout + proc.stderr)
                results.append({
                    "test_file": test_file,
                    "passed": passed,
                    "output": output.strip()[-2000:],  # last 2000 chars
                })
                logger.info("PHPUnit %s: %s", test_file, "PASS" if passed else "FAIL")
            except subprocess.TimeoutExpired:
                overall = False
                results.append({
                    "test_file": test_file,
                    "passed": False,
                    "output": f"Timed out after {REGRESSION_PHPUNIT_TIMEOUT}s",
                })

        return {
            "passed": overall,
            "test_results": results,
            "tests_run": len(results),
        }

    # ------------------------------------------------------------------
    # Level 3: Module compatibility
    # ------------------------------------------------------------------

    @staticmethod
    def run_module_compatibility(env_path: str) -> Dict:
        """
        Run a PHP script inside DDEV to verify Layout Builder, Paragraphs,
        and SDC APIs are intact.  Only checks modules that are actually installed.
        """
        script_path = os.path.join(env_path, "_compat_check.php")
        try:
            with open(script_path, "w") as f:
                f.write(_COMPAT_SCRIPT)

            result = subprocess.run(
                ["ddev", "drush", "scr", "_compat_check.php"],
                cwd=env_path,
                capture_output=True,
                text=True,
                timeout=60,
            )
            output = result.stdout + result.stderr
            failures = [line for line in output.splitlines() if "[FAIL]" in line]
            passes = [line for line in output.splitlines() if "[PASS]" in line]

            passed = result.returncode == 0 and not failures

            if failures:
                logger.warning("Module compatibility failures: %s", failures)

            return {
                "passed": passed,
                "passes": passes,
                "failures": failures,
                "output": output.strip(),
            }
        except subprocess.TimeoutExpired:
            return {"passed": False, "failures": ["Compatibility check timed out."], "passes": []}
        except Exception as e:
            return {"passed": False, "failures": [str(e)], "passes": []}
        finally:
            # Clean up temp script
            if os.path.exists(script_path):
                os.remove(script_path)

    # ------------------------------------------------------------------
    # Formatting helper
    # ------------------------------------------------------------------

    @staticmethod
    def format_report(results: Dict) -> str:
        lines = ["", "=" * 60, "  REGRESSION CHECK REPORT", "=" * 60]

        # Health
        h = results.get("health", {})
        lines.append(f"\n[Level 1] Health check: {'PASS' if h.get('passed') else 'FAIL'}")
        if not h.get("passed"):
            lines.append(f"  {h.get('output', '')[:200]}")

        # PHPUnit
        p = results.get("phpunit", {})
        if p.get("skipped"):
            lines.append(f"\n[Level 2] PHPUnit: SKIPPED — {p.get('reason')}")
        elif p:
            lines.append(f"\n[Level 2] PHPUnit: {'PASS' if p.get('passed') else 'FAIL'} "
                         f"({p.get('tests_run', 0)} test file(s))")
            for tr in p.get("test_results", []):
                status = "PASS" if tr["passed"] else "FAIL"
                lines.append(f"  [{status}] {tr['test_file']}")
                if not tr["passed"]:
                    lines.append(f"  {tr['output'][-300:]}")

        # Full module suite
        fs = results.get("full_suite", {})
        if fs.get("skipped"):
            lines.append(f"\n[Level 2b] Full module suite: SKIPPED — {fs.get('reason')}")
        elif fs:
            lines.append(f"\n[Level 2b] Full module suite: {'PASS' if fs.get('passed') else 'FAIL'} "
                         f"({fs.get('modules_run', 0)} module(s) swept)")
            for mr in fs.get("module_results", []):
                if mr.get("skipped"):
                    lines.append(f"  [SKIP] {mr['module']} — {mr.get('reason')}")
                    continue
                status = "PASS" if mr["passed"] else ("TIMEOUT" if mr.get("timed_out") else "FAIL")
                lines.append(f"  [{status}] {mr['module']} ({mr['test_dir']})")
                if not mr["passed"]:
                    lines.append(f"  {mr['output'][-500:]}")

        # Compatibility
        c = results.get("compatibility", {})
        lines.append(f"\n[Level 3] Module compatibility: {'PASS' if c.get('passed') else 'FAIL'}")
        for line in c.get("passes", []):
            lines.append(f"  {line}")
        for line in c.get("failures", []):
            lines.append(f"  {line}")

        # Overall
        overall = results.get("overall_passed", False)
        lines.append(f"\n{'✔  ALL CHECKS PASSED' if overall else '✘  SOME CHECKS FAILED'}")
        lines.append("=" * 60)

        return "\n".join(lines)
