"""
Fix generator — uses LLM to produce a structured fix plan and code changes.

Two-phase design:
  1. generate_plan()  — analyses issue context + source files → JSON plan
  2. generate_code_for_file() — generates complete new file content per plan entry

The LLM receives the real source files so it can produce targeted, minimal diffs
rather than guessing at file structure.
"""

import json
import logging
import os
import re
from typing import Dict, List, Optional

from services.llm_client import LlmClient

logger = logging.getLogger("IssueForge.FixGenerator")

# Caps to avoid overwhelming the LLM context window
_MAX_FILE_CHARS = 8000
_MAX_FILES_IN_PROMPT = 12

_PLAN_SYSTEM = """\
You are an expert Drupal developer fixing reported issues.
Analyse the provided issue context and source files, then output a structured JSON fix plan.

Rules:
- Only fix what the issue describes. Do not refactor unrelated code.
- Prefer minimal, targeted changes to reduce regression risk.
- Follow Drupal coding standards (PSR-4, hook naming, service injection).
- Set confidence to "high" only when the root cause is clear from the code.
- Your ENTIRE response must be valid JSON — no prose, no markdown fences.

Output schema (all keys required):
{
  "fix_summary": "One sentence describing what the fix does",
  "root_cause": "What causes the reported bug",
  "approach": "The fix strategy at a high level",
  "confidence": "high|medium|low",
  "files": [
    {
      "path": "relative/path/from/drupal-root.php",
      "reason": "Why this file must change",
      "changes": "Precise description of what to add/remove/modify",
      "risk": "low|medium|high"
    }
  ],
  "new_files": [
    {
      "path": "relative/path/from/drupal-root.php",
      "reason": "Why this new file is needed",
      "content_hint": "What it should contain"
    }
  ],
  "potential_side_effects": ["possible regression 1", "possible regression 2"],
  "test_guidance": "How to manually verify the fix works"
}
"""

_CODE_SYSTEM = """\
You are an expert Drupal developer generating PHP/YAML code to fix a bug.

Rules:
- Write the COMPLETE file content — never truncate or use placeholder comments.
- Follow Drupal coding standards: PSR-4 namespaces, dependency injection, hooks.
- Return raw PHP/YAML/JSON only — no markdown fences, no prose before or after.
- Do not add comments explaining what the fix does; only add comments for non-obvious WHY.
- Target Drupal 10+ APIs; avoid deprecated functions.
- When fixing validation errors from a previous attempt, address each error exactly.
"""


class FixGenerator:

    # ------------------------------------------------------------------
    # Plan generation
    # ------------------------------------------------------------------

    @staticmethod
    def _read_module_files(env_path: str, module_rel_path: str) -> Dict[str, str]:
        """Walk module directory and return {rel_path: content} for PHP/YAML files."""
        module_abs = os.path.join(env_path, module_rel_path)
        files: Dict[str, str] = {}

        if not os.path.isdir(module_abs):
            logger.warning("Module directory not found: %s", module_abs)
            return files

        php_exts = {".php", ".module", ".inc", ".install", ".theme", ".profile"}

        for root, dirs, filenames in os.walk(module_abs):
            dirs[:] = [d for d in dirs if d not in ("vendor", "node_modules", ".git")]
            for fname in sorted(filenames):
                ext = os.path.splitext(fname)[1]
                if ext not in php_exts and not fname.endswith(".yml"):
                    continue
                full = os.path.join(root, fname)
                rel = os.path.relpath(full, env_path)
                try:
                    with open(full, encoding="utf-8", errors="replace") as f:
                        content = f.read()
                    if len(content) > _MAX_FILE_CHARS:
                        content = content[:_MAX_FILE_CHARS] + f"\n[...truncated at {_MAX_FILE_CHARS} chars]"
                    files[rel] = content
                except Exception as e:
                    logger.debug("Could not read %s: %s", full, e)

        return files

    @staticmethod
    def generate_plan(
        env_path: str,
        issue_context: Dict,
        module_rel_path: str,
    ) -> Optional[Dict]:
        """
        Generate a structured fix plan for the issue.

        Args:
            env_path: Absolute path to the provisioned environment directory.
            issue_context: Dict built from env_plan.json (title, root_cause, etc.)
            module_rel_path: Module path relative to env_path (e.g. modules/contrib/mymod)

        Returns:
            Parsed plan dict or None if the LLM failed.
        """
        source_files = FixGenerator._read_module_files(env_path, module_rel_path)

        file_sections = []
        for i, (path, content) in enumerate(sorted(source_files.items())):
            if i >= _MAX_FILES_IN_PROMPT:
                file_sections.append(
                    f"[...{len(source_files) - i} more files omitted...]"
                )
                break
            file_sections.append(f"=== {path} ===\n{content}")

        files_block = "\n\n".join(file_sections) if file_sections else "(no source files found)"

        prompt = (
            f"Issue #{issue_context.get('issue_id', '?')}: {issue_context.get('title', 'Unknown')}\n"
            f"Project : {issue_context.get('project_name', 'unknown')}\n"
            f"Status  : {issue_context.get('status', 'Unknown')}\n"
            f"Drupal  : {issue_context.get('drupal_version', '10')}\n"
            f"Module path: {module_rel_path}\n\n"
            f"Root cause: {issue_context.get('root_cause', issue_context.get('analysis', 'Not specified'))}\n"
            f"Fix approach suggested: {issue_context.get('fix_approach', 'Not specified')}\n"
            f"Subsystems: {', '.join(issue_context.get('subsystems', [])) or 'Not specified'}\n\n"
            f"Current module source files:\n\n{files_block}\n\n"
            "Generate the JSON fix plan."
        )

        response = LlmClient.generate(prompt, system=_PLAN_SYSTEM)
        if not response:
            logger.error("LLM returned empty response for fix plan.")
            return None

        # Strip accidental markdown fences
        clean = re.sub(r"^```(?:json)?\s*", "", response.strip())
        clean = re.sub(r"\s*```$", "", clean)

        try:
            plan = json.loads(clean)
        except json.JSONDecodeError as exc:
            logger.error("Could not parse LLM fix plan JSON: %s\nResponse: %.500s", exc, response)
            return None

        plan.setdefault("new_files", [])
        plan.setdefault("potential_side_effects", [])
        plan.setdefault("confidence", "medium")
        plan.setdefault("test_guidance", "")
        return plan

    # ------------------------------------------------------------------
    # Code generation
    # ------------------------------------------------------------------

    @staticmethod
    def generate_code_for_file(
        file_rel_path: str,
        current_content: str,
        change_instructions: str,
        issue_context: Dict,
        validation_errors: Optional[List[Dict]] = None,
        attempt: int = 1,
    ) -> str:
        """
        Generate complete new content for a single file.

        Args:
            file_rel_path: Path relative to the Drupal webroot.
            current_content: Existing file content (empty string for new files).
            change_instructions: What needs to change, from the plan entry.
            issue_context: Issue metadata.
            validation_errors: PHPCS/PHPStan errors from a previous attempt.
            attempt: Attempt number (1 = first, >1 = self-healing retry).

        Returns:
            Complete file content as a string.
        """
        errors_block = ""
        if validation_errors:
            lines = []
            for err in validation_errors[:20]:
                checker = err.get("type", "error").upper()
                lines.append(
                    f"  [{checker}] Line {err.get('line', '?')}: {err.get('message', '')} "
                    f"({err.get('source', '')})"
                )
            errors_block = (
                f"\nValidation errors to fix (attempt {attempt}):\n"
                + "\n".join(lines)
                + "\n"
            )

        is_new = not current_content.strip()
        action = "Create new file" if is_new else "Modify existing file"

        prompt = (
            f"{action}: {file_rel_path}\n\n"
            f"Issue #{issue_context.get('issue_id', '?')}: {issue_context.get('title', '')}\n"
            f"Project: {issue_context.get('project_name', 'unknown')} "
            f"(Drupal {issue_context.get('drupal_version', '10')})\n\n"
            f"Required changes:\n{change_instructions}\n"
            f"{errors_block}\n"
        )

        if is_new:
            prompt += "This is a new file — write it from scratch.\n"
        else:
            prompt += f"Current content:\n{current_content}\n"

        prompt += "\nWrite the complete file content. Raw PHP/YAML/JSON only — no markdown."

        return LlmClient.generate(prompt, system=_CODE_SYSTEM)

    # ------------------------------------------------------------------
    # Display
    # ------------------------------------------------------------------

    @staticmethod
    def format_plan(plan: Dict) -> str:
        """Format a fix plan for terminal display."""
        conf = plan.get("confidence", "medium")
        conf_icon = {"high": "✓", "medium": "~", "low": "?"}.get(conf, "~")

        lines = [
            "",
            "=" * 65,
            "  FIX PLAN",
            "=" * 65,
            f"\n  Summary    : {plan.get('fix_summary', 'N/A')}",
            f"  Root cause : {plan.get('root_cause', 'N/A')}",
            f"  Approach   : {plan.get('approach', 'N/A')}",
            f"  Confidence : {conf_icon} {conf.upper()}",
        ]

        files = plan.get("files", [])
        new_files = plan.get("new_files", [])

        if files:
            lines.append(f"\n  Files to modify ({len(files)}):")
            for f in files:
                risk = f.get("risk", "medium")
                risk_icon = {"high": "⚠", "medium": "•", "low": "○"}.get(risk, "•")
                lines.append(f"\n  {risk_icon} {f.get('path')}")
                lines.append(f"      Why    : {f.get('reason', '')}")
                lines.append(f"      Changes: {f.get('changes', '')}")

        if new_files:
            lines.append(f"\n  New files ({len(new_files)}):")
            for f in new_files:
                lines.append(f"\n  + {f.get('path')}")
                lines.append(f"      Reason : {f.get('reason', '')}")

        side_effects = plan.get("potential_side_effects", [])
        if side_effects:
            lines.append("\n  Potential side effects:")
            for se in side_effects:
                lines.append(f"    ⚠  {se}")

        guidance = plan.get("test_guidance", "")
        if guidance:
            lines.append(f"\n  Test guidance: {guidance}")

        lines.append("\n" + "=" * 65)
        return "\n".join(lines)
