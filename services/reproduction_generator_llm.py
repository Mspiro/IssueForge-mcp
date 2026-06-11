import logging
from typing import Dict, List
from services.llm_client import LlmClient

logger = logging.getLogger("IssueForge.ReproductionGeneratorLlm")


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
        Dynamically generates a Drupal PHP script to set up the reproduction environment.
        """

        steps_str = "\n".join([f"- {step}" for step in reproduction_steps])
        subsystems_str = ", ".join(detected_subsystems)
        files_str = ", ".join(modified_files)

        prompt = f"""You are a senior Drupal core developer and automation expert.
Your task is to write a standalone Drupal PHP script (to be executed via `ddev drush scr setup_reproduction.php`) that programmatically sets up the exact database configuration, content types, vocabularies, fields, mock content, and Views required to reproduce the bug described below.

### Issue Information:
- **Title**: {issue_title}
- **Subsystems**: {subsystems_str}
- **Affected Files**: {files_str}
- **Problem Summary**: {problem_summary}

### Reproduction Steps:
{steps_str}

### Instructions for the PHP script:
1. Write standard Drupal API code (compatible with Drupal 10/11) to create nodes, fields, content types, views, taxonomies, or configs needed to reproduce this issue.
2. Use standard Drupal APIs (e.g., `NodeType::create()`, `FieldStorageConfig::create()`, `FieldConfig::create()`, `Node::create()`, `View::create()`).
3. Always verify if entities/views/fields already exist before creating them to avoid duplicate creation errors.
4. For Paragraphs: To create paragraph types/bundles, do NOT use `NodeType::create()`. Instead, use `\Drupal\paragraphs\Entity\ParagraphsType::create(['id' => 'bundle_name', 'label' => 'Bundle Name'])->save();`. Check if they exist using `\Drupal\paragraphs\Entity\ParagraphsType::load('bundle_name')`.
5. For Paragraph fields: The field type must be `entity_reference_revisions` (NOT `entity_reference_paragraphs` which does not exist). In the field storage config settings, set `'target_type' => 'paragraph'`.
6. To check if a module is installed/enabled, use `\Drupal::moduleHandler()->moduleExists('module_name')` (do NOT use `isEnabled()` or other non-existent ModuleHandler methods).
7. For complex configurations like Views, define them in a YAML heredoc and import them via `\Drupal\Core\Serialization\Yaml::decode($yaml_content)` and `View::create($values)->save()`.
8. The view configuration should expose filters, configure sorting, display mode, or whatever is specified in the steps. Make sure the exposed path is unique (e.g. `/issue-test-view`).
9. Do NOT include any markdown code blocks (like ```php or ```) in your output.
10. Return ONLY the raw PHP code starting with `<?php`.

Generate the complete PHP script below:
"""

        generated_code = LlmClient.generate(prompt)

        # Post-process to remove markdown formatting if the LLM still wraps it
        if not generated_code:
            return ""

        # Remove leading/trailing markdown wrapper lines if present
        lines = generated_code.splitlines()
        cleaned_lines = []
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("```php") or stripped.startswith("```"):
                continue
            cleaned_lines.append(line)

        return "\n".join(cleaned_lines).strip()
