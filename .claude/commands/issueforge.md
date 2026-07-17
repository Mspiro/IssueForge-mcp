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
From the slim JSON, read: `llm_analysis.root_cause`, `environment_plan` (project_name, checkout_ref, php_version, contrib_modules), `reproduction_steps`, `detected_mrs`, `detected_subsystems`, `suggested_fix_strategies`, and `comment_signal_details` (the specific claims behind each comment signal — e.g. a commenter reporting the patch breaks tests — not just the generic label).

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

### Step 5 — Apply existing fix OR Generate AI Fix

**Before touching any code**, explain the issue to the user in your own words (root cause + what the fix needs to do — reuse your Step 2 explanation) and ask explicitly whether they want to resolve it now, and how:

- [1] Test an existing MR/patch from the plan
- [2] Generate an AI fix (no existing patch, or existing one rejected)
- [3] Skip fixing — reproduction only

Do not auto-apply an MR/patch just because one exists in the plan. The user chooses.

If they choose to test an existing MR or patch:
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
Each run: applies diff → regression check (health check + targeted PHPUnit + full-module test sweep + module compatibility) → shows diff stat → prints NEXT STEPS block. The full-module sweep runs the entire affected module's test suite whenever a non-test source file changed, not just files the patch happened to touch — this is what catches a patch breaking an unrelated, pre-existing test.

If there are NO existing patches or MRs, or if the user requests an AI Fix, follow this loop rather than editing straight from a guess — an unstructured pass tends to only solve the happy path and miss edge cases or break unrelated behavior:

1. **Edge-case check.** Grep the affected module's existing tests for assertions related to the issue's own keywords, e.g.:
   ```
   ! grep -rn "<keyword>" {{ISSUEFORGE_DIR}}/environments/env_<ID>/core/modules/<module>/tests
   ```
   If an existing assertion encodes exactly the behavior this issue is changing, note it now — it will need a matching update, not a surprise failure discovered after the fact.
2. **Write a failing test first**, in the module's existing test style (Kernel or Functional) — this defines the bug's boundary before you write a fix for it, not after. Skip this step only when there's no reproducible code path (e.g. a pure architecture/discussion issue with nothing to test yet). Confirm it fails for the right reason:
   ```
   ! python {{ISSUEFORGE_DIR}}/scripts/run_check.py <ISSUE_ID> phpunit <test_file>
   ```
3. Review the `root_cause` and `suggested_fix_strategies` from Step 2, then implement the fix in `{{ISSUEFORGE_DIR}}/environments/env_<ID>/`.
4. **Verify the new test now passes** with the same `run_check.py phpunit` command. Apply the bounded retry protocol below if it doesn't.
5. **Static analysis gate.** Run PHPStan against every file you changed:
   ```
   ! python {{ISSUEFORGE_DIR}}/scripts/run_check.py <ISSUE_ID> phpstan <file1> <file2> ...
   ```
   Apply the bounded retry protocol to any errors reported.
6. **Regression sweep.** Run the full regression check against your uncommitted changes:
   ```
   ! python {{ISSUEFORGE_DIR}}/scripts/check_regression.py <ISSUE_ID>
   ```
7. **Reviewer pass** — only when the diff touches core behavioral logic (not a one-line change) *and* step 1 found no existing test already covering it. Re-read your own diff as a skeptic: does the fix apply narrowly, or did it remove/alter behavior beyond what the issue actually asked for? (This exact mistake — removing more than the issue asked for — is what produced 5 failing tests when validating MR !13200 against #3115759.)
8. Once everything passes, use `! git -C {{ISSUEFORGE_DIR}}/environments/env_<ID> diff` to show the user the changes.

**Bounded retry protocol** (steps 4–6): if a check fails, make one fix attempt, then re-run the *same* check.
- Passes now → continue.
- Fails with the exact same signature as before → stop. This isn't converging — don't keep guessing. Tell the user what's stuck and what you tried.
- Fails with a *different* signature → real progress was made, one more attempt is justified. Cap at 3 total attempts per check regardless of outcome, then stop and report to the user rather than continuing to iterate.

**Gate: do not proceed to Step 6 yet.** After a fix is applied (either from an MR or generated by you) and it passes regression, stop and ask the user:
- Do you want to submit this as a **Merge Request**?
- Or save it as a **patch file**?

Step 6 (the drupal.org comment) only happens after this choice is made and acted on — or after the user explicitly says to skip it. Never draft the comment as an automatic continuation of a passing regression check.

If they choose Merge Request:
1. Tell them to open the issue page and click **"Get push access"** in the Merge Requests section (this creates their issue fork on git.drupalcode.org)
2. Ask them to confirm once done, then run the git commands to commit and push using `!`:
   ```
   ! git -C {{ISSUEFORGE_DIR}}/environments/env_<ID> add -A
   ! git -C {{ISSUEFORGE_DIR}}/environments/env_<ID> commit -m "Issue #<ISSUE_ID>: Applied fix"
   ! git -C {{ISSUEFORGE_DIR}}/environments/env_<ID> push issue HEAD:<branch>
   ```
3. Tell them the MR link to open once pushed.

If they choose patch: 
Run the patch save command and show them the file path:
`! git -C {{ISSUEFORGE_DIR}}/environments/env_<ID> diff > {{ISSUEFORGE_DIR}}/environments/env_<ID>/fix_<ISSUE_ID>.patch`

### Step 6 — Generate issue comment

**Entry check**: only enter this step once regression checks have passed (or the user chose reproduction-only in Step 5) *and* the Step 5 MR/patch/skip decision has been made. If you find yourself about to draft a comment right after a regression-check output with no intervening user decision, stop and go back to that gate instead.

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
