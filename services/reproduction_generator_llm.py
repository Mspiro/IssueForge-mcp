import logging
from typing import Dict, List, Optional
from services.llm_client import LlmClient

logger = logging.getLogger("IssueForge.ReproductionGeneratorLlm")

# Static Drupal API constraints — sent as a cached system prompt so they are
# not re-tokenised on every call and do not dilute the issue-specific context.
_DRUPAL_SYSTEM_PROMPT = """You are a senior Drupal core developer and automation expert.

Your task is to write standalone Drupal PHP scripts executed via `ddev drush scr`.

## Hard rules — violation causes fatal errors

### Module checks
- ALWAYS use `\\Drupal::moduleHandler()->moduleExists('name')`.
- NEVER use `isEnabled()`, `getAllModuleData()`, or similar non-existent methods.

### Module installation
- `\\Drupal::service('module_installer')->install(['name'])` returns a boolean, NOT an array.
- NEVER pass its return value to `implode()` or iterate over it.

### Paragraphs
- To create paragraph types: ALWAYS use `\\Drupal\\paragraphs\\Entity\\ParagraphsType::create([...])->save();`
- To check existence: `\\Drupal\\paragraphs\\Entity\\ParagraphsType::load('bundle_name')`
- Use `ParagraphsType` (plural). `ParagraphType` (singular) does not exist.
- NEVER use `NodeType::create()` for paragraph types.

### Paragraph fields
- Field type MUST be `entity_reference_revisions` (NOT `entity_reference_paragraphs`).
- In field storage settings: `'target_type' => 'paragraph'`.

### Views
- For complex views, define in a YAML heredoc and import via:
  `\\Drupal\\Core\\Serialization\\Yaml::decode($yaml)` + `View::create($values)->save();`

### Text formats
- Only use core filter plugins: `filter_html`, `filter_align`, `filter_caption`,
  `filter_html_image_secure`, `filter_autop`, `filter_htmlcorrector`,
  `filter_html_escape`, `filter_url`, `filter_null`.
- NEVER reference external module filters (e.g. `filter_linkit`) unless explicitly requested.

### Layout Builder
- Enable on view display: `$display->setThirdPartySetting('layout_builder', 'enabled', TRUE)->save();`
- Check if enabled: `$display->getThirdPartySetting('layout_builder', 'enabled')`
- NEVER use `getRenderer()` or `setComponent('layout_builder', ...)`.

## Output requirements
- Return ONLY raw PHP starting with `<?php`.
- NEVER wrap output in markdown code blocks (no ```php).
- Always guard against duplicate creation: check existence before `create()`.
- Add `echo "[OK] ..."` lines so the caller can confirm progress.
"""


class ReproductionGeneratorLlm:
    """
    Generates a Drupal Drush/PHP reproduction setup script using the LlmClient.
    """

    @staticmethod
    def generate_script(
        issue_title: str,
        problem_summary: str,
        reproduction_steps: List[str],
        detected_subsystems: List[str],
        modified_files: List[str],
    ) -> str:
        """
        Generate a reproduction PHP script for the given issue.
        Returns raw PHP code or empty string on failure.
        """
        steps_str = (
            "\n".join(f"- {step}" for step in reproduction_steps)
            if reproduction_steps
            else "No explicit steps provided — infer from the problem summary."
        )

        user_prompt = f"""Write a standalone Drupal PHP script (`ddev drush scr`) that programmatically
sets up the exact database state (content types, fields, content, views, configs) needed
to reproduce the bug described below.

### Issue
- **Title**: {issue_title}
- **Subsystems**: {", ".join(detected_subsystems)}
- **Affected Files**: {", ".join(modified_files)}

### Problem
{problem_summary}

### Steps to reproduce
{steps_str}

### Script requirements
1. Use Drupal 10/11-compatible APIs.
2. Check existence before creating every entity, field, view, or config.
3. Use exposed view path `/issue-{issue_title[:30].lower().replace(" ", "-")}-test` (unique).
4. Print `[OK] <action>` for each major step so output is verifiable.
5. Return ONLY raw PHP starting with `<?php` — no markdown, no explanation.
"""

        generated = LlmClient.generate(user_prompt, system=_DRUPAL_SYSTEM_PROMPT)

        if not generated:
            return ""

        return ReproductionGeneratorLlm._clean_output(generated)

    @staticmethod
    def fix_script(
        broken_script: str,
        error_output: str,
        issue_title: str,
        attempt: int,
    ) -> str:
        """
        Feed a broken script + its error output back to the LLM to get a fixed version.
        Called by the self-healing loop in reproduce_with_healing.py.
        """
        user_prompt = f"""The following Drupal PHP script (for issue: "{issue_title}") failed on attempt {attempt}.

### Error output
```
{error_output.strip()[:3000]}
```

### Broken script
```php
{broken_script.strip()[:6000]}
```

Fix the script so it runs without errors under `ddev drush scr`.
Apply the Drupal API rules from your system prompt.
Return ONLY the corrected raw PHP starting with `<?php`.
"""
        fixed = LlmClient.generate(user_prompt, system=_DRUPAL_SYSTEM_PROMPT)
        if not fixed:
            return ""
        return ReproductionGeneratorLlm._clean_output(fixed)

    @staticmethod
    def _clean_output(code: str) -> str:
        lines = code.splitlines()
        cleaned = [
            line for line in lines
            if not line.strip().startswith("```")
        ]
        return "\n".join(cleaned).strip()

    # ------------------------------------------------------------------
    # Verification guide
    # ------------------------------------------------------------------

    _GUIDE_SYSTEM_PROMPT = """\
You are a senior Drupal developer writing a step-by-step guide to help a developer
see a bug in their browser after the test environment has been set up.

Rules:
- Write numbered steps. Each step has: URL (if navigating), Action (what to do),
  Observe (what the bug looks like — be specific: error text, missing element, wrong value).
- Use the EXACT site URL provided — include it in every navigation step.
- Include admin login credentials: username admin, password admin.
- Include at least one step pointing to /admin/reports/dblog (Drupal error log).
- Include a terminal command tip for checking watchdog logs via Drush.
- If the issue involves JavaScript, mention opening DevTools → Console.
- Keep each step to 3-4 lines. No padding or generic advice.
- Plain text output only — no markdown headers, no bullet symbols, numbered steps only."""

    @staticmethod
    def generate_verification_guide(
        issue_id: str,
        issue_title: str,
        site_url: str,
        reproduction_steps: List[str],
        subsystems: Optional[List[str]] = None,
        problem_summary: Optional[str] = None,
    ) -> str:
        """
        Generate a numbered, browser-ready guide showing exactly how to see the bug.

        Args:
            issue_id: Drupal issue ID (for display).
            issue_title: Human-readable issue title.
            site_url: Full DDEV site URL, e.g. https://env-12345.ddev.site
            reproduction_steps: Raw steps extracted from the issue.
            subsystems: Involved Drupal subsystems (e.g. ['views', 'paragraphs']).
            problem_summary: Short description of what the bug is.

        Returns:
            Formatted multi-line guide string, or a minimal fallback if LLM fails.
        """
        steps_text = (
            "\n".join(f"{i+1}. {s}" for i, s in enumerate(reproduction_steps))
            if reproduction_steps
            else "No explicit steps provided — infer from the issue description."
        )
        subs = ", ".join(subsystems) if subsystems else "general"

        prompt = (
            f"Issue #{issue_id}: {issue_title}\n"
            f"Subsystems: {subs}\n"
            f"Problem: {problem_summary or issue_title}\n\n"
            f"Site URL: {site_url}\n"
            f"Admin credentials: admin / admin\n\n"
            f"Reproduction steps from the issue:\n{steps_text}\n\n"
            "Write a numbered guide (5-8 steps) showing exactly where to go and what to "
            "look at in the browser to observe the bug. Include log-checking steps."
        )

        guide = LlmClient.generate(prompt, system=ReproductionGeneratorLlm._GUIDE_SYSTEM_PROMPT)
        if guide:
            return guide

        # Minimal fallback when LLM is unavailable
        lines = [
            f"1. Open {site_url}/user/login and log in as admin / admin",
            f"2. Follow the reproduction steps below:",
        ]
        for i, step in enumerate(reproduction_steps, 3):
            lines.append(f"   {i-2}. {step}")
        lines += [
            f"{len(reproduction_steps)+3}. Check {site_url}/admin/reports/dblog for PHP errors",
            "   Terminal: cd <env_path> && ddev drush watchdog:show --count=20",
        ]
        return "\n".join(lines)

    @staticmethod
    def format_verification_guide(
        issue_id: str,
        issue_title: str,
        site_url: str,
        guide_text: str,
        env_path: str = "",
    ) -> str:
        """Wrap the LLM guide in a terminal-friendly box."""
        W = 65
        sep = "=" * W
        lines = [
            "",
            sep,
            f"  HOW TO VERIFY THE BUG  —  #{issue_id}",
            sep,
            f"",
            f"  Site   : {site_url}",
            f"  Login  : admin / admin",
            f"  Logs   : {site_url}/admin/reports/dblog",
        ]
        if env_path:
            lines.append(
                f"  Drush  : cd {env_path} && ddev drush watchdog:show --count=20"
            )
        lines += ["", "  Steps:", ""]

        for line in guide_text.splitlines():
            lines.append(f"  {line}")

        lines += ["", sep]
        return "\n".join(lines)
