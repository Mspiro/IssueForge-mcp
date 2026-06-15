"""
Code validator — runs PHPCS, PHPCBF, PHPStan, and PHPUnit against a module.

All tools run inside the DDEV container via `ddev exec -d /var/www/html`.
The working directory is always env_path so DDEV picks up the right project.
"""

import json
import logging
import os
import subprocess
from typing import Dict, List, Optional

logger = logging.getLogger("IssueForge.CodeValidator")

_PHPCS_TIMEOUT = int(os.getenv("ISSUEFORGE_PHPCS_TIMEOUT", "120"))
_PHPCBF_TIMEOUT = int(os.getenv("ISSUEFORGE_PHPCBF_TIMEOUT", "120"))
_PHPSTAN_TIMEOUT = int(os.getenv("ISSUEFORGE_PHPSTAN_TIMEOUT", "180"))
_PHPUNIT_TIMEOUT = int(os.getenv("ISSUEFORGE_PHPUNIT_FIX_TIMEOUT", "300"))


class CodeValidator:

    @staticmethod
    def run_phpcs(env_path: str, module_rel_path: str) -> Dict:
        """
        Run PHPCS against the module.  Returns dict with passed, errors list,
        error_count, warning_count.
        """
        try:
            result = subprocess.run(
                [
                    "ddev", "exec", "-d", "/var/www/html",
                    "vendor/bin/phpcs",
                    "--standard=Drupal,DrupalPractice",
                    "--extensions=php,module,inc,install,test,profile,theme,yml",
                    "--report=json",
                    module_rel_path,
                ],
                cwd=env_path,
                capture_output=True,
                text=True,
                timeout=_PHPCS_TIMEOUT,
            )
            try:
                data = json.loads(result.stdout)
            except json.JSONDecodeError:
                return {
                    "passed": False,
                    "errors": [],
                    "error_count": 0,
                    "warning_count": 0,
                    "output": (result.stdout + result.stderr).strip(),
                    "parse_error": True,
                }

            totals = data.get("totals", {})
            error_count = totals.get("errors", 0)
            warning_count = totals.get("warnings", 0)

            file_errors = []
            for file_path, file_data in data.get("files", {}).items():
                for msg in file_data.get("messages", []):
                    if msg.get("type") == "ERROR":
                        file_errors.append({
                            "file": file_path,
                            "line": msg.get("line"),
                            "column": msg.get("column"),
                            "message": msg.get("message"),
                            "source": msg.get("source"),
                            "type": "phpcs",
                        })

            return {
                "passed": error_count == 0,
                "error_count": error_count,
                "warning_count": warning_count,
                "errors": file_errors,
                "output": result.stdout,
            }
        except subprocess.TimeoutExpired:
            return {"passed": False, "errors": [], "error_count": 0,
                    "warning_count": 0, "output": "PHPCS timed out."}
        except Exception as e:
            return {"passed": False, "errors": [], "error_count": 0,
                    "warning_count": 0, "output": str(e)}

    @staticmethod
    def run_phpcbf(env_path: str, module_rel_path: str) -> Dict:
        """
        Run PHPCBF to auto-fix coding standard violations.
        Exit codes: 0 = nothing fixed, 1 = fixed, 2 = unfixable errors remain.
        """
        try:
            result = subprocess.run(
                [
                    "ddev", "exec", "-d", "/var/www/html",
                    "vendor/bin/phpcbf",
                    "--standard=Drupal,DrupalPractice",
                    "--extensions=php,module,inc,install,test,profile,theme,yml",
                    module_rel_path,
                ],
                cwd=env_path,
                capture_output=True,
                text=True,
                timeout=_PHPCBF_TIMEOUT,
            )
            return {
                "ran": True,
                "fixed_something": result.returncode == 1,
                "has_unfixable": result.returncode == 2,
                "output": (result.stdout + result.stderr).strip(),
            }
        except subprocess.TimeoutExpired:
            return {"ran": False, "fixed_something": False,
                    "has_unfixable": False, "output": "PHPCBF timed out."}
        except Exception as e:
            return {"ran": False, "fixed_something": False,
                    "has_unfixable": False, "output": str(e)}

    @staticmethod
    def run_phpstan(env_path: str, module_rel_path: str) -> Dict:
        """
        Run PHPStan static analysis.  Returns dict with passed, errors list.
        """
        try:
            result = subprocess.run(
                [
                    "ddev", "exec", "-d", "/var/www/html",
                    "vendor/bin/phpstan", "analyse",
                    "--no-progress",
                    "--error-format=json",
                    module_rel_path,
                ],
                cwd=env_path,
                capture_output=True,
                text=True,
                timeout=_PHPSTAN_TIMEOUT,
            )
            try:
                data = json.loads(result.stdout)
            except json.JSONDecodeError:
                return {
                    "passed": result.returncode == 0,
                    "errors": [],
                    "error_count": 0,
                    "output": (result.stdout + result.stderr).strip(),
                    "parse_error": True,
                }

            totals = data.get("totals", {})
            error_count = totals.get("errors", 0)
            file_errors = []
            for file_path, file_data in data.get("files", {}).items():
                for msg in file_data.get("messages", []):
                    file_errors.append({
                        "file": file_path,
                        "line": msg.get("line"),
                        "message": msg.get("message"),
                        "ignorable": msg.get("ignorable", False),
                        "type": "phpstan",
                    })

            return {
                "passed": error_count == 0,
                "error_count": error_count,
                "errors": file_errors,
                "output": result.stdout,
            }
        except subprocess.TimeoutExpired:
            return {"passed": False, "errors": [], "error_count": 0,
                    "output": "PHPStan timed out."}
        except Exception as e:
            return {"passed": False, "errors": [], "error_count": 0,
                    "output": str(e)}

    @staticmethod
    def run_phpunit_for_module(env_path: str, module_rel_path: str) -> Dict:
        """
        Run PHPUnit tests for the module if a tests/ directory exists.
        """
        tests_dir = os.path.join(env_path, module_rel_path, "tests")
        if not os.path.exists(tests_dir):
            return {
                "skipped": True,
                "passed": True,
                "reason": f"No tests/ directory at {module_rel_path}",
            }

        phpunit_xml = os.path.join(env_path, "core", "phpunit.xml.dist")
        if not os.path.exists(phpunit_xml):
            return {
                "skipped": True,
                "passed": True,
                "reason": "phpunit.xml.dist not found",
            }

        try:
            result = subprocess.run(
                [
                    "ddev", "exec",
                    "vendor/bin/phpunit",
                    "--configuration=core/phpunit.xml.dist",
                    f"{module_rel_path}/tests/",
                    "--no-coverage",
                ],
                cwd=env_path,
                capture_output=True,
                text=True,
                timeout=_PHPUNIT_TIMEOUT,
            )
            passed = result.returncode == 0
            output = (result.stdout + result.stderr).strip()
            return {
                "passed": passed,
                "skipped": False,
                "output": output[-3000:],
            }
        except subprocess.TimeoutExpired:
            return {"passed": False, "skipped": False,
                    "output": f"PHPUnit timed out after {_PHPUNIT_TIMEOUT}s."}
        except Exception as e:
            return {"passed": False, "skipped": False, "output": str(e)}

    @staticmethod
    def run_all(env_path: str, module_rel_path: str) -> Dict:
        """
        Run PHPCBF (auto-fix), then PHPCS, PHPStan, PHPUnit.
        Returns consolidated results dict.
        """
        results = {}

        # Auto-fix first, before checking
        results["phpcbf"] = CodeValidator.run_phpcbf(env_path, module_rel_path)
        results["phpcs"] = CodeValidator.run_phpcs(env_path, module_rel_path)
        results["phpstan"] = CodeValidator.run_phpstan(env_path, module_rel_path)
        results["phpunit"] = CodeValidator.run_phpunit_for_module(env_path, module_rel_path)

        results["overall_passed"] = (
            results["phpcs"].get("passed", False)
            and results["phpstan"].get("passed", False)
            and results["phpunit"].get("passed", True)
        )

        return results

    @staticmethod
    def collect_errors_by_file(results: Dict) -> Dict[str, List[Dict]]:
        """
        Extract PHPCS and PHPStan errors keyed by the container-side file path.
        Used to feed errors back to the LLM for self-healing.
        """
        by_file: Dict[str, List[Dict]] = {}
        for checker in ("phpcs", "phpstan"):
            for err in results.get(checker, {}).get("errors", []):
                key = err.get("file", "unknown")
                by_file.setdefault(key, []).append(err)
        return by_file

    @staticmethod
    def format_report(results: Dict) -> str:
        lines = ["", "=" * 60, "  CODE VALIDATION REPORT", "=" * 60]

        cbf = results.get("phpcbf", {})
        if cbf.get("ran"):
            msg = "Fixed some issues" if cbf.get("fixed_something") else "Nothing to fix"
            if cbf.get("has_unfixable"):
                msg += " (some errors remain)"
            lines.append(f"\n[PHPCBF]  Auto-fix : {msg}")

        cs = results.get("phpcs", {})
        lines.append(f"\n[PHPCS]   Coding standards : {'PASS' if cs.get('passed') else 'FAIL'}")
        if not cs.get("passed"):
            lines.append(f"  Errors: {cs.get('error_count', 0)},  Warnings: {cs.get('warning_count', 0)}")
            for err in cs.get("errors", [])[:10]:
                lines.append(f"  Line {err.get('line', '?')}: {str(err.get('message', ''))[:120]}")
            if len(cs.get("errors", [])) > 10:
                lines.append(f"  ... and {len(cs['errors']) - 10} more")

        stan = results.get("phpstan", {})
        lines.append(f"\n[PHPStan] Static analysis : {'PASS' if stan.get('passed') else 'FAIL'}")
        if not stan.get("passed"):
            lines.append(f"  Errors: {stan.get('error_count', 0)}")
            for err in stan.get("errors", [])[:10]:
                lines.append(f"  Line {err.get('line', '?')}: {str(err.get('message', ''))[:120]}")
            if len(stan.get("errors", [])) > 10:
                lines.append(f"  ... and {len(stan['errors']) - 10} more")

        pu = results.get("phpunit", {})
        if pu.get("skipped"):
            lines.append(f"\n[PHPUnit] Tests : SKIPPED — {pu.get('reason', 'no tests')}")
        else:
            lines.append(f"\n[PHPUnit] Tests : {'PASS' if pu.get('passed') else 'FAIL'}")
            if not pu.get("passed"):
                lines.append(f"\n{pu.get('output', '')[-600:]}")

        overall = results.get("overall_passed", False)
        lines.append(f"\n{'✔  ALL CHECKS PASSED' if overall else '✘  CHECKS FAILED — fix required'}")
        lines.append("=" * 60)

        return "\n".join(lines)
