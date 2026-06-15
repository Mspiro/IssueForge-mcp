"""
Regression checker — runs after a patch or MR is applied.

Three levels of confidence:

Level 1 — Health check (always runs, ~5s)
  `drush status` confirms Drupal still bootstraps and the DB is reachable.

Level 2 — PHPUnit tests (runs when test files are discoverable, ~30-300s)
  Discovers test classes that correspond to the changed source files and runs
  them via `ddev exec vendor/bin/phpunit`.

Level 3 — Module compatibility (runs when specific modules are installed)
  A PHP script checks that Layout Builder, Paragraphs, and SDC APIs
  still behave correctly after the change.
"""

import logging
import os
import re
import subprocess
from typing import Dict, List, Optional

from config import REGRESSION_PHPUNIT_TIMEOUT, REGRESSION_HEALTH_TIMEOUT

logger = logging.getLogger("IssueForge.RegressionChecker")

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
        Run all three levels and return a consolidated result.
        """
        results = {}

        # Level 1: health check
        results["health"] = RegressionChecker.run_health_check(env_path)

        # Level 2: PHPUnit (only if Drupal is healthy)
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

        # Level 3: module compatibility
        results["compatibility"] = RegressionChecker.run_module_compatibility(env_path)

        results["overall_passed"] = (
            results["health"]["passed"]
            and results.get("phpunit", {}).get("passed", True)
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
    def discover_test_files(env_path: str, changed_files: List[str]) -> List[str]:
        """
        Discover test files that correspond to the changed source files.

        Patterns (relative to env_path):
        - core/lib/Drupal/X/Y.php → core/tests/Drupal/Tests/X/YTest.php (Unit)
        - core/modules/FOO/src/Y.php → core/modules/FOO/tests/src/Unit/YTest.php
        - modules/contrib/FOO/src/Y.php → modules/contrib/FOO/tests/src/Unit/YTest.php
        """
        found = []
        for f in changed_files:
            candidates = RegressionChecker._candidate_test_paths(f)
            for candidate in candidates:
                full = os.path.join(env_path, candidate)
                if os.path.exists(full):
                    found.append(candidate)
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

        # Pattern 3: modules/contrib/FOO/src/Bar.php → similar
        m2 = re.match(r"(modules/contrib/[^/]+)/src/(.+)\.php", f)
        if m2:
            candidates.append(f"{m2.group(1)}/tests/src/Unit/{m2.group(2)}Test.php")
            candidates.append(f"{m2.group(1)}/tests/src/Kernel/{m2.group(2)}Test.php")

        return candidates

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
            full_path = os.path.join(env_path, test_file)
            logger.info("Running PHPUnit for %s", test_file)
            try:
                proc = subprocess.run(
                    [
                        "ddev", "exec",
                        "vendor/bin/phpunit",
                        f"--configuration=core/phpunit.xml.dist",
                        full_path,
                        "--no-coverage",
                    ],
                    cwd=env_path,
                    capture_output=True,
                    text=True,
                    timeout=REGRESSION_PHPUNIT_TIMEOUT,
                )
                passed = proc.returncode == 0
                overall = overall and passed
                output = proc.stdout + proc.stderr
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
