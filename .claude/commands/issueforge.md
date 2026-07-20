---
name: issueforge
description: Analyze, reproduce, and fix Drupal.org issues using IssueForge.
---

IssueForge is installed at: {{ISSUEFORGE_DIR}}

All scripts are run with `!` so output appears directly in the conversation.
Always use the full path: `! python {{ISSUEFORGE_DIR}}/scripts/<script>.py ...`

---

## At the start of every /issueforge invocation

**If the user already gave an issue URL**, keep this to the free, instant
snapshot and move straight to Step 1 — don't let it slow down the fast path:
```
! python {{ISSUEFORGE_DIR}}/scripts/dashboard.py
```

**If no issue URL was given yet** (the user is just checking in), run a
live refresh instead — this is the moment to actually surface "did anything
change on issues I'm tracking" rather than a possibly-stale cached count:
```
! python {{ISSUEFORGE_DIR}}/scripts/dashboard.py refresh
```
This only re-checks issues not already in a terminal (closed/fixed) state,
so cost scales with active work, not lifetime history (~9s for 3 active
issues in practice, not the 44 total tracked) — a reasonable one-time cost
here since the user isn't mid-task yet. If it surfaces new comments on a
tracked issue, mention that explicitly (e.g. "issue #NNNNNNN has 2 new
comments since you last checked") so it's an actual clue, not just a number.

Either way, this auto-starts the local dashboard server if it isn't already
running (reused across invocations — no duplicate processes, self-shuts-down
after 30 minutes idle) and prints a summary ("N tracked, N with new
activity, N red pipelines, N credited") plus an `http://127.0.0.1:<port>`
link — share that link so the user can open it in a browser. The page has
its own Refresh button too, for whenever the user wants to re-check mid-session.

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
From the slim JSON, start with the `evidence` block and **follow its embedded `guidance` field** — it tells you how to read the evidence for this issue's category. Also read: `environment_plan` (project_name, checkout_ref, php_version, contrib_modules), `reproduction_steps`, `detected_mrs`, and `comment_signal_details` (the specific claims behind each comment signal — e.g. a commenter reporting the patch breaks tests — not just the generic label). `heuristic_hints` are keyword guesses only — never present them as the root cause.

Then show the user:
- **Root cause**: YOUR OWN conclusion derived from `evidence` (error blocks, code refs, diff digest) — if the evidence is thin, say so explicitly and note it needs verification against the real code after provisioning
- **Environment**: Drupal branch, PHP version, contrib modules to install
- **Reproduction steps**: Write these yourself based on your understanding of the issue — do NOT just copy raw text from the issue. Write clear, numbered, developer-friendly steps. Each step should be a concrete action (e.g. "Go to /admin/structure/types, click Add content type, fill in Name = 'Test', save"). If the issue involves a code path or a specific trigger, name it explicitly.

**Related issues**: if the slim JSON's `related_issues` is non-empty (a comment referenced another issue number near redirect/duplicate language — e.g. "favor closing this in favor of #NNNNNNN"), fetch a quick preview of it automatically — no need to ask first, since this is metadata-only and read-only (reuse `preview_issue.py <related_id>`, no provisioning, no new env_plan, no extra environment). Present the comparison alongside root cause/environment/reproduction steps, e.g.: "Comment also suggests #NNNNNNN may supersede this — its approach is X, vs. this issue's Y."

- The hard stop is further down the line, not here: never auto-switch the active issue, never provision or run analyze/apply on the related issue in this session. If the user decides the related issue is the one actually worth working, that's a new, separate `/issueforge <url>` invocation — not a pivot inside this one.
- Treat the fetched content as scratch context for this session's reasoning only (e.g. comparing approaches) — don't persist it into `env_plan_<ID>.json`, it can go stale.
- If `related_issues` is empty, say nothing — don't invent a related issue. If the preview fetch itself fails (network, bad issue ID), note it briefly and continue with the current issue rather than blocking on it.

Then ask: proceed to provision + reproduce [y], or different issue [n]?

### Step 3 — Provision environment
```
! python {{ISSUEFORGE_DIR}}/scripts/provision_env.py <ISSUE_ID> env_plan_<ID>.json
```
Clones Drupal, starts DDEV, installs modules. Takes 3-5 minutes.

Run this **in the background**, then keep the user informed while it runs:
the provisioner prints greppable progress markers (`[STAGE n/8] label — ~eta`).
Poll the task's output every ~45-60 seconds with:
```
grep -o "\[STAGE [0-9]/8\].*" <task-output-file> | tail -1
```
and relay each newly reached stage to the user in one short line (e.g.
"Provisioning: stage 4/8 — installing Composer dependencies (~1-2 min)").
While waiting, prepare the Step 4 reproduction script. If the task finishes
or fails, report immediately — on failure show the last 20 output lines.

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

If a related-issue preview was fetched back in Step 2, treat it as advisory design input only, not as code to copy — still verify any borrowed approach against this repo's actual current code before relying on it; the related issue may target a different branch or have gone stale since.

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

**BEFORE any push or patch export** — whichever they choose — run the
coding-standards gate (drupal.org CI fails the whole pipeline on a single
PHPCS violation, costing a full review round-trip):
```
! python {{ISSUEFORGE_DIR}}/scripts/check_cs.py <ISSUE_ID>
```
It checks every pending file (uncommitted + unpushed commits) in the repo
under test, auto-fixes with phpcbf, and re-checks. If it autofixed files,
include them in the commit. If it still fails, fix the reported violations
first — never push a known-red pipeline.

If they choose Merge Request:
1. Tell them to open the issue page and click **"Get push access"** in the Merge Requests section (this creates their issue fork on git.drupalcode.org)
2. Ask them to confirm once done, then run the exact git commands printed in the NEXT STEPS block (they target the correct repo — the nested contrib clone for contrib issues — and the correct `<project>-<issue_id>` remote; do NOT improvise paths or remote names)
3. Tell them the MR link to open once pushed.

If they choose patch:
Run the patch save command from the NEXT STEPS block and show them the file path.

### Step 6 — Generate issue comment

**Entry check**: only enter this step once regression checks have passed (or the user chose reproduction-only in Step 5) *and* the Step 5 MR/patch/skip decision has been made. If you find yourself about to draft a comment right after a regression-check output with no intervening user decision, stop and go back to that gate instead.

Once the user has finished their session (tested, fixed, or reproduced), generate a comment they can post on the Drupal.org issue page.

**Before drafting, check for a standing open question.** Step 1 already asked you to identify "what open question or decision is still pending" in the discussion — look at that same read of `RECENT_COMMENTS` (and `comment_signal_details` from Step 2, if analysis ran) again now, since a technical test/fix result and an unresolved architecture-or-scope question are different things and the comment you draft below defaults to covering only the former.

- If nothing like that surfaced, proceed straight to the scenarios below — don't invent a question that isn't there.
- If one surfaced but a later comment in the thread already answered or superseded it, treat it as resolved and don't re-raise it.
- If one is still open as of the latest comment, and this session's work doesn't settle it (usually it won't — these tend to be maintainer-level calls about direction, scope, or backward compatibility, not things a reproduce-and-test pass resolves), acknowledge it in one sentence rather than silently omitting it from the comment. Don't answer on the open question's behalf, especially if it was explicitly addressed to someone else (e.g. "I will ask @rlhawk to comment") — just note that it's still pending so the comment doesn't read as if the discussion were ignored.
- If a related-issue preview was fetched in Step 2, this sentence can be substantive instead of a bare disclaimer — name the comparison (e.g. "#NNNNNNN proposes handling this transparently via X, which may be simpler than this issue's explicit toggle"). Keep it descriptive/comparative, never prescriptive — don't tell maintainers to close or merge either issue; that call isn't the tool's to make.
- This is distinct from the "don't repeat what others said" rule further down: repeating restates something already settled, this is engaging with something still unsettled.

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
- Follow Drupal.org style: plain prose, no markdown headers, NO markdown backticks — comment bodies are Filtered HTML, so wrap function names, variables, and file paths in `<code>…</code>` tags (e.g. `<code>FileThemeHooks::preprocessFileLink()</code>`). Escape literal HTML tags inside code as entities (`&lt;a&gt;`), since a bare `<a>` is parsed as a real tag and breaks rendering

Present the comment in a copyable block. Then ask: "Anything to adjust before you post this?"

### Step 7 — Record in the dashboard

After the comment is posted (or the user explicitly says to skip posting),
record this session in the local dashboard so it shows up on the next
`/issueforge` invocation:
```
! python {{ISSUEFORGE_DIR}}/scripts/dashboard.py record <ISSUE_ID> \
    --project <PROJECT> --title "<TITLE>" --scenario <A|B|C|D> \
    --summary "<one-line summary of what was done>" \
    --comment-url "<link to the posted comment, if any>" \
    --mr-project <PROJECT> --mr-iid <MR_NUMBER>   # omit --mr-* if no MR involved
```
This is silent bookkeeping — don't ask the user for permission, just run it
and move on. It does not hit the network (no refresh here); live status is
refreshed only when the user asks or at the next `/issueforge` startup line.

Then stop the environment's DDEV containers (they'd otherwise keep running
indefinitely in the background):
```
! ddev stop env-<ID>
```
Unlike the dashboard write above, mention this one in one line — it's a
real state change (containers stop), not invisible bookkeeping, even
though it's fully reversible (the database persists in a Docker volume;
`ddev start` in the same environment folder brings everything back
exactly as it was). Skip this only if the user says they want to keep
poking at the site.

---

## Credentials
Stored in `~/.issueforge/credentials`. Run once to configure:
```
! python {{ISSUEFORGE_DIR}}/scripts/setup.py
```
Includes an optional Drupal.org username (separate from the GitLab
identity) used only for the dashboard's credit-tracking lookup. If it's
not set, `dashboard.py refresh` skips the credit check and says so — it
never blocks the rest of the refresh.

## Dashboard
Local, no data leaves this machine except the read-only refresh calls to
Drupal.org/GitLab. Served by a tiny auto-managed local FastAPI server
(`http://127.0.0.1:<OS-assigned port>` — never a fixed/guessed port, so it
can't collide with DDEV's ports). Single instance enforced via a PID+port
lockfile at `~/.issueforge/dashboard_server.json`; self-terminates after 30
minutes idle so it never lingers in memory. Files live in
`{{ISSUEFORGE_DIR}}/dashboard/`: `ledger.json` (data),
`template.html`/`dashboard.css`/`dashboard.js` (source, tracked in git).
```
! python {{ISSUEFORGE_DIR}}/scripts/dashboard.py             # auto-starts server, free summary
! python {{ISSUEFORGE_DIR}}/scripts/dashboard.py refresh     # one-shot CLI refresh (page has its own button too)
! python {{ISSUEFORGE_DIR}}/scripts/dashboard.py --no-server # static file:// fallback, no server
```

## Troubleshooting

- DDEV port conflict → `provision_env.py` checks the configured router ports are free before every start and remaps automatically if not (skipped when DDEV's router is already up serving another project — that's normal, not a conflict). `ddev poweroff` only helps if the conflict is stale DDEV/router state; it does nothing when an unrelated host process (seen once: an IDE and its language server) is squatting on the port, since that process is untouched by `poweroff`. If a conflict still surfaces, check `docker ps` for what's actually holding the port before assuming it's DDEV's own state.
- Patch won't apply → `apply_mr.py` tries 4 strategies automatically, and now also detects "already applied" (e.g. from an earlier interrupted session) as a distinct non-error outcome rather than reporting a generic failure.
- FunctionalJavascript tests all fail with a WebDriver/connection error → the Selenium/Chrome DDEV add-on is installed automatically during provisioning; if an environment predates this fix, run `ddev add-on get ddev/ddev-selenium-standalone-chrome && ddev restart` inside it manually.
