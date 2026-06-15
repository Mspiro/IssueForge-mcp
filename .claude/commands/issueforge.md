---
name: issueforge
description: Analyze, reproduce, and fix Drupal.org issues using IssueForge.
---

IssueForge is installed at: {{ISSUEFORGE_DIR}}

All scripts are run with `!` so output appears directly in the conversation.
Always use the full path: `! python {{ISSUEFORGE_DIR}}/scripts/<script>.py ...`

---

## When the user gives a Drupal issue URL or ID

### Step 1 — Preview the issue
```
! python {{ISSUEFORGE_DIR}}/scripts/preview_issue.py <URL_OR_ID>
```
Shows: title, status, patches, MRs, discussion summary.
Then ask the user: proceed with full flow [y], analysis only [a], or different issue [n]?

### Step 2 — Analyze (writes env_plan_<ID>.json)
```
! python {{ISSUEFORGE_DIR}}/scripts/analyze_issue.py <URL> > env_plan_<ID>.json
```

### Step 3 — Provision environment
```
! python {{ISSUEFORGE_DIR}}/scripts/provision_env.py <ISSUE_ID> env_plan_<ID>.json
```
Clones Drupal, starts DDEV, installs modules. Takes 3-5 minutes.

### Step 4 — Reproduce the bug
```
! python {{ISSUEFORGE_DIR}}/scripts/reproduce_with_healing.py <ISSUE_ID> setup_reproduction.php \
    --issue-title "<TITLE>" --env-plan env_plan_<ID>.json
```
After success, prints a step-by-step browser guide showing where to go to see the bug.

### Step 5 — Apply and validate a patch or MR

Apply an MR:
```
! python {{ISSUEFORGE_DIR}}/scripts/apply_mr.py <ISSUE_ID> --mr-url <MR_URL>
```
Apply a patch by ID:
```
! python {{ISSUEFORGE_DIR}}/scripts/apply_mr.py <ISSUE_ID> --patch-id <PATCH_ID>
```
Apply all MRs from the plan:
```
! python {{ISSUEFORGE_DIR}}/scripts/apply_mr.py <ISSUE_ID> --from-plan env_plan_<ID>.json
```
Each run: applies diff → regression check (health + PHPUnit + compatibility) → shows diff stat → offers push or patch upload.

### Step 6 — Generate a fix (when issue is unresolved)
```
! python {{ISSUEFORGE_DIR}}/scripts/generate_fix.py <ISSUE_ID> env_plan_<ID>.json
```
Generates a fix plan, shows it to the user, applies code changes, runs PHPCS/PHPStan/PHPUnit with self-healing, then offers to submit.

---

## Credentials
Stored in `~/.issueforge/credentials`. Run once to configure:
```
! python {{ISSUEFORGE_DIR}}/scripts/setup.py
```

## Troubleshooting
- DDEV port conflict → run `! ddev poweroff`
- PHP syntax error in reproduction script → `reproduce_with_healing.py` auto-corrects via LLM
- Patch won't apply → `apply_mr.py` tries 4 strategies automatically
