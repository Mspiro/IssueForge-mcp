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
After running, read the slim summary (avoids loading the full multi-KB JSON):
```
! python {{ISSUEFORGE_DIR}}/scripts/slim_plan.py env_plan_<ID>.json
```
From the slim JSON, read: `llm_analysis.root_cause`, `environment_plan` (project_name, checkout_ref, php_version, contrib_modules), `reproduction_steps`, `detected_mrs`, `detected_subsystems`, and `suggested_fix_strategies`.

Then show the user:
- **Root cause**: what was detected
- **Environment**: Drupal branch, PHP version, contrib modules to install
- **Reproduction steps**: Write these yourself based on your understanding of the issue — do NOT just copy raw text from the issue. Write clear, numbered, developer-friendly steps. Each step should be a concrete action (e.g. "Go to /admin/structure/types, click Add content type, fill in Name = 'Test', save"). If the issue involves a code path or a specific trigger, name it explicitly.

Then ask: proceed to provision + reproduce [y], or different issue [n]?

### Step 3 — Provision environment
```
! python {{ISSUEFORGE_DIR}}/scripts/provision_env.py <ISSUE_ID> env_plan_<ID>.json
```
Clones Drupal, starts DDEV, installs modules. Takes 3-5 minutes.

After provisioning succeeds, get a one-time login link:
```
! cd {{ISSUEFORGE_DIR}}/environments/env_<ID> && ddev drush uli
```
Show the user:
- Site URL: `https://env-<ID>.ddev.site`
- Login link: the URL from `ddev drush uli` (valid for 1 hour, logs in as admin)

### Step 4 — Reproduce the bug
Write a PHP Drush script (`repro_<ID>.php`) that programmatically triggers the bug — based on your reproduction steps from Step 2. Then run it:
```
! python {{ISSUEFORGE_DIR}}/scripts/reproduce_with_healing.py <ISSUE_ID> repro_<ID>.php \
    --issue-title "<TITLE>" --env-plan env_plan_<ID>.json
```
After the script runs, tell the user exactly what to look for in the site to observe the bug (specific URL, UI element, error message, or log entry).

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
Each run: applies diff → regression check (health + PHPUnit + compatibility) → shows diff stat → prints NEXT STEPS block.

After the script finishes, read the NEXT STEPS block and ask the user:
- Do you want to submit this as a **Merge Request**?
- Or save it as a **patch file**?

If they choose Merge Request:
1. Tell them to open the issue page and click **"Get push access"** in the Merge Requests section (this creates their issue fork on git.drupalcode.org)
2. Ask them to confirm once done, then run the git commands from the NEXT STEPS block using `!`:
   ```
   ! git -C <env_path> add -A
   ! git -C <env_path> commit -m "Apply fix for #<ISSUE_ID>"
   ! git -C <env_path> push issue HEAD:<branch>
   ```
3. Tell them the MR link to open once pushed.

If they choose patch: run the patch save command from NEXT STEPS and show them the file path.

### Step 6 — Generate issue comment

Once the user has finished their session (tested, fixed, or reproduced), generate a comment they can post on the Drupal.org issue page.

First, identify which scenario applies based on what happened in this session:

**Scenario A — User tested an existing patch or MR**
They ran `apply_mr.py` with someone else's patch/MR ID and reviewed the results.
Comment should cover: what was tested (MR !N or patch ID), branch + PHP version, whether the bug reproduced first, whether the fix resolved it, regression check outcome.

**Scenario B — User submitted their own fix (new MR or patch)**
They wrote code changes, committed, and either pushed a new MR or exported a patch.
Before writing the comment, ask: "What is the MR number or patch file ID that was created?" (they'll have this from the git.drupalcode.org URL or the drupal.org file upload).
Comment should cover: "Created MR !N / uploaded patch #ID that fixes this by [brief description of what was changed]", branch + PHP, regression results.

**Scenario C — User only confirmed reproduction (no fix applied)**
They ran through Steps 1–4 but did not apply or submit a fix.
Comment should cover: confirmed the bug reproduces on branch + PHP version, exact trigger observed, any additional detail not already in the thread.

**Scenario D — User could not reproduce**
Comment should cover: steps attempted, environment, what was observed instead, any version-specific nuance.

---

For all scenarios, the comment must:
- Be concise — 3–8 sentences, no padding
- State the environment explicitly: Drupal branch (e.g. `11.1.x`), PHP version
- State the outcome clearly: reproduces / fixed / cannot reproduce
- Add one concrete observation if it adds value (edge case, related code path, etc.)
- NOT repeat what other commenters already said (check RECENT_COMMENTS from Step 1)
- NOT use filler phrases ("Great work!", "Thanks for the patch", "Hope this helps")
- Follow Drupal.org style: plain prose, no markdown headers, use `backticks` only for function names or file paths

Present the comment in a copyable block. Then ask: "Anything to adjust before you post this?"

---

## Credentials
Stored in `~/.issueforge/credentials`. Run once to configure:
```
! python {{ISSUEFORGE_DIR}}/scripts/setup.py
```

## Troubleshooting
- DDEV port conflict → run `! ddev poweroff`
- Patch won't apply → `apply_mr.py` tries 4 strategies automatically
