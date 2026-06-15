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
After running, present the issue to the user like this:

**Brief summary** (2–3 sentences): What is the issue about? What is the current status?

**Patches / MRs**: List what is available (IDs, titles, states).

**Discussion**: Read the `RECENT_COMMENTS` block at the bottom of the output.
Do NOT repeat the raw comment text. Instead, in 2–4 sentences, explain:
- What is the current state of the conversation?
- What open question or decision is still pending?
- What is blocking resolution (if anything)?

Then ask the user:
- [y] Full flow — analyze + provision environment + reproduce
- [a] Analysis only — see detailed plan first, then decide
- [n] Different issue

### Step 2 — Analyze (writes env_plan_<ID>.json)
```
! python {{ISSUEFORGE_DIR}}/scripts/analyze_issue.py <URL> 2>/dev/null > env_plan_<ID>.json
```

### Step 3 — Provision environment
```
! python {{ISSUEFORGE_DIR}}/scripts/provision_env.py <ISSUE_ID> env_plan_<ID>.json
```
Clones Drupal, starts DDEV, installs modules. Takes 3-5 minutes.

### Step 4 — Reproduce the bug
Write a PHP reproduction script based on the env_plan analysis, then run it:
```
! python {{ISSUEFORGE_DIR}}/scripts/reproduce_with_healing.py <ISSUE_ID> <script.php> \
    --issue-title "<TITLE>" --env-plan env_plan_<ID>.json
```
On success: site is at `https://env-<ID>.ddev.site` (admin / admin).
Tell the user exactly where to go and what to look for to observe the bug.

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

---

## Credentials
Stored in `~/.issueforge/credentials`. Run once to configure:
```
! python {{ISSUEFORGE_DIR}}/scripts/setup.py
```

## Troubleshooting
- DDEV port conflict → run `! ddev poweroff`
- Patch won't apply → `apply_mr.py` tries 4 strategies automatically
