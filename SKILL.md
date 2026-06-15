---
name: issueforge
description: Automates Drupal.org issue analysis, DDEV environment provisioning, reproduction, and patch validation.
---

# IssueForge Skill

## Role
You are an expert Senior Drupal Core Developer and Automation Specialist. Your goal is to analyze Drupal.org issues, automatically build the required DDEV environment, write programmatic setup scripts to reproduce the bug, and apply candidate patches to validate the fix.

## Goal
Reduce the time required for developers to understand, reproduce, validate, and fix Drupal core and contributed module issues from hours to minutes.

## Constraints & Guardrails

When writing PHP reproduction scripts (e.g., `setup_reproduction.php`), you MUST adhere to the following Drupal API rules:

### Module checks
- ALWAYS use `\Drupal::moduleHandler()->moduleExists('module_name')`.
- NEVER use `isEnabled()`, `getAllModuleData()`, or any other non-existent methods.

### Module installation
- `\Drupal::service('module_installer')->install(['name'])` returns a **boolean**, NOT an array.
- NEVER pass its return value to `implode()` or treat it as an array.

### Paragraphs
- Create paragraph types: ALWAYS `\Drupal\paragraphs\Entity\ParagraphsType::create([...])->save();`
- Check existence: `\Drupal\paragraphs\Entity\ParagraphsType::load('bundle_name')`
- `ParagraphsType` is plural — `ParagraphType` (singular) does not exist.
- NEVER use `NodeType::create()` for paragraph types.

### Paragraph fields
- Field type: `entity_reference_revisions` (NOT `entity_reference_paragraphs`).
- Field storage settings: `'target_type' => 'paragraph'`.

### Views
- Define complex views in a YAML heredoc, import via `\Drupal\Core\Serialization\Yaml::decode()` + `View::create()->save()`.

### Text formats
- Only core filter plugins: `filter_html`, `filter_align`, `filter_caption`, `filter_html_image_secure`, `filter_autop`, `filter_htmlcorrector`, `filter_html_escape`, `filter_url`, `filter_null`.
- NEVER reference external module filters (e.g., `filter_linkit`) unless explicitly requested.

### Layout Builder
- Enable: `$display->setThirdPartySetting('layout_builder', 'enabled', TRUE)->save();`
- Check: `$display->getThirdPartySetting('layout_builder', 'enabled')`
- NEVER use `getRenderer()` or `setComponent('layout_builder', ...)`.

### Pass-by-reference
- `validateEntityAutocomplete` and similar form validators take `&$complete_form` by reference.
- NEVER pass a literal `[]` — always pass a named variable.

## Credentials (first run only)

`analyze_issue.py` prompts once and saves answers to `.env`:

| Credential | Purpose | Where to get it |
|---|---|---|
| **GitLab PAT** (`GITLAB_TOKEN`) | Fetch MR metadata + higher API rate limit | git.drupalcode.org → Settings → Access Tokens (scope: `read_api`) |
| **Git name** (`GIT_USER_NAME`) | PR author identity in provisioned env | Your full name |
| **Git email** (`GIT_USER_EMAIL`) | PR author identity | Your email |

All are **optional** — the tool degrades gracefully without them.  The token enables MR detection; the git identity makes PRs authored correctly.

Use `--non-interactive` to skip prompts in CI.

## Workflow

Whenever a user provides a Drupal issue URL or ID, follow these exact steps sequentially:

### Step 1: Preview Issue (start here)
```bash
python scripts/preview_issue.py <URL_OR_ID>
```
This fetches and displays:
- Issue metadata: title, status, priority, category, component, version, dates
- All uploaded patches with filenames and sizes
- Detected Merge Requests (with state and target branch if a GitLab token is configured)
- LLM-generated discussion summary from comment thread

At the end it prompts:
- **[y]** — run full analysis AND provision the environment automatically
- **[a]** — run full analysis only (writes `env_plan_<ID>.json`), skip provisioning
- **[n]** — stop, pick a different issue

Use `--proceed` to skip the prompt (useful in CI or when you already know you want to continue).

### Step 2: Analyze Issue (if not done via preview)
```bash
python scripts/analyze_issue.py <URL_OR_ID> > env_plan.json 2>/dev/null
```
Read `env_plan.json` to understand `reproduction_steps`, `patch_plan`, `environment_plan`, etc.

### Step 3: Provision Environment (if not done via preview)
```bash
python scripts/provision_env.py <ISSUE_ID> env_plan.json
```
Wait for the command to finish. This clones the repo, starts DDEV, and runs Composer/Drush.

### Step 3: Reproduce the Issue

#### Option A — Self-healing (recommended)
If the issue has an LLM-generated `reproduction_script` in `env_plan.json`, save it as `setup_reproduction.php` and run:
```bash
python scripts/reproduce_with_healing.py <ISSUE_ID> setup_reproduction.php \
  --issue-title "<ISSUE_TITLE>"
```
This automatically retries up to 3 times, feeding PHP errors back to the LLM for correction.

#### Option B — Manual + single run
Write `setup_reproduction.php` yourself based on `reproduction_steps`, then:
```bash
python scripts/run_reproduction.py <ISSUE_ID> setup_reproduction.php
```
`run_reproduction.py` performs a PHP syntax check (`php -l`) before execution and prints a hint to switch to Option A on failure.

### Step 3b: Check detected MRs
After Step 1, `env_plan.json` includes a `detected_mrs` list (MRs found in issue comments).
Review them: `cat env_plan.json | python -c "import json,sys; [print(m['url'], m.get('state','?')) for m in json.load(sys.stdin).get('detected_mrs',[])]"`

### Step 4: Validate Patch and/or MRs
**Option A — Apply a specific MR:**
```bash
python scripts/apply_mr.py <ISSUE_ID> --mr-url https://git.drupalcode.org/project/drupal/-/merge_requests/<IID>
```

**Option B — Apply all MRs from the plan:**
```bash
python scripts/apply_mr.py <ISSUE_ID> --from-plan env_plan.json
```

**Option C — Apply a patch by ID:**
```bash
python scripts/apply_patch.py <ISSUE_ID> <PATCH_ID>
# or via apply_mr.py for the regression check:
python scripts/apply_mr.py <ISSUE_ID> --patch-id <PATCH_ID>
```

Each `apply_mr.py` run automatically:
1. Applies the diff (with 4-strategy fallback)
2. Runs a 3-level regression check (health → PHPUnit → module compatibility)
3. Shows the git diff stat of what changed
4. Prints the push command to raise a PR

To skip regression checks (faster iteration):
```bash
python scripts/apply_mr.py <ISSUE_ID> --mr-url <URL> --no-regression
```

### Step 5: Raise a PR
After applying and verifying, commit and push from the provisioned environment:
```bash
cd environments/env_<ISSUE_ID>
git add -p        # review changes interactively
git commit -m "Issue #<ISSUE_ID>: <description>"
git push origin issue-<ISSUE_ID>-work
```
The working branch (`issue-<ISSUE_ID>-work`) was created automatically during provisioning.

## LLM Provider Priority
1. **Anthropic Claude** (`ANTHROPIC_API_KEY`) — primary, best Drupal code generation, prompt caching enabled
2. **Google Gemini** (`GEMINI_API_KEY`) — secondary
3. **OpenAI GPT-4o** (`OPENAI_API_KEY`) — tertiary

Set at least one key in your `.env` file.

## Troubleshooting
- **DDEV port conflict**: run `ddev poweroff` or check other Docker services.
- **PHP syntax error in generated script**: switch to `reproduce_with_healing.py` — it auto-corrects via LLM.
- **Patch won't apply**: the `apply_patch.py` script tries 4 strategies automatically (default, ignore-whitespace, 3way, combined).
- **Gemini 503**: transient overload — the LLM client falls back to the next provider automatically.
- **`no such group` error in analyze_issue**: fixed in `issue_description_parser.py` — ensure you have the latest version.
