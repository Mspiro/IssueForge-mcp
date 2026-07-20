# IssueForge Session Report — Issue #3392735

**Issue:** [layout_paragraphs] "in_preview not passed correctly causing wrong display in edit"
**Fix tested:** MR !139 ("Utilize layout preview mode")
**Date:** 2026-07-20
**Outcome:** Fix confirmed correct and regression-clean; comment drafted, not yet posted.

> **A note on precision before you read this:** I do not have access to any per-call
> token-usage metering, and most tool output isn't wall-clock-stamped. Where a
> timestamp appears below, it's copied verbatim from a log line IssueForge itself
> printed. Everywhere else, "time spent" is a qualitative read of how much back-and-forth
> a step took, not a stopwatch figure. Token figures are a relative *effort proxy*
> (tool-call count, data volume moved) — not actual token counts. I flag this instead of
> inventing numbers that would look precise but wouldn't be real.

---

## 1. What got done, end to end

| Step | Result |
|---|---|
| 1. Preview issue | Clean, first try |
| 2. Analyze issue | Clean, first try — but evidence was thin (`has_error_signal: false`, confidence: low) |
| 3. Provision environment | **Failed twice**, succeeded on 3rd attempt (DDEV port conflict, root-caused manually) |
| 4. Reproduce bug | **Failed twice**, succeeded on 3rd attempt (missing content type, then render-context error) |
| 5a. Apply MR !139 | Reported failure — **false negative**, patch was already applied by an earlier interrupted session |
| 5b. Regression check | **Failed repeatedly** across multiple root causes (see §3) before giving a trustworthy signal |
| 6. Draft comment | Done, presented to you, not yet posted |

Net result: the fix is correct, matches MR !139 exactly, and the only failing checks are
pre-existing test-suite issues unrelated to the patch (proven by reproducing the identical
failure on the unpatched baseline).

---

## 2. Timeline (measured where timestamped, estimated otherwise)

| Time | Event |
|---|---|
| 15:54:14 | Provisioning attempt #1 starts |
| 15:54:44 | Attempt #1 fails — `ddev start` fails, port 33000 already in use |
| ~15:55–15:57 | Diagnosed as DDEV router conflict; ran `ddev poweroff` (per IssueForge's own troubleshooting doc) |
| 15:57:20 | Provisioning attempt #2 starts |
| 15:57:47 | Attempt #2 fails — **identical** port-33000 conflict; `ddev poweroff` did not fix it |
| ~15:58–16:00 | Root-caused properly: port 33000 was held by an unrelated **host** process (an IDE + its language server), not by Docker/DDEV at all. Set DDEV's global router ports to 33010/33011. |
| ~16:00 | Provisioning attempt #3 starts — succeeds through all 8 stages |
| ~16:06 | Repro script written; attempt #1 fails (`page` content type missing) |
| ~16:07 | Attempt #2 fails (Renderer "render context empty" error) |
| ~16:08 | Attempt #3 succeeds — bug reproduced, root cause confirmed against real source |
| 16:09:00 | *(discovered retroactively)* `LayoutParagraphsBuilder.php` already modified on disk — meaning a **prior, now-summarized-away session** had already applied MR !139 before this stretch of work began |
| 16:13:29 | `apply_mr.py` downloads MR !139 diff, attempts apply, reports false failure (file already patched) |
| ~16:14–16:20 | Diagnosed the false failure; found `check_regression.py` also targets the wrong repo for contrib issues; ran regression manually against the correct nested repo — revealed missing Selenium/WebDriver in the environment entirely |
| ~16:24:26 | Selenium add-on installed, DDEV restarted (containers come up fresh) |
| ~16:25 onward | Selenium networking debugging: wrong webdriver capability format (my own mistake), then found the add-on's correct built-in env vars |
| (untimed) | Isolated a **genuine** test failure, unrelated to infra; used `git stash` to test the unpatched baseline — **`git stash` itself failed** ("Cannot save the current status", cause undetermined) |
| (untimed) | Worked around via `git diff > file` + `git checkout --`; confirmed identical failure on baseline (proves pre-existing) |
| (untimed) | Mid-process, **all three containers crashed** ("service web has exited") — restarted DDEV, hit the same project-root/symlink issue again |
| (untimed) | Reapplying the saved diff via `git apply` **corrupted the source file to 0 bytes** — caught immediately, restored via `git checkout --` (git's object store was untouched, so no real data loss), then manually re-created the exact 3-file diff via direct edits |
| (untimed) | Final regression run confirms: health PASS, module-compatibility PASS, FunctionalJavascript failures reproduce identically on baseline (pre-existing) |
| (untimed) | Comment drafted and presented |

Rough total elapsed wall-clock from first timestamp to last: **at least ~35–40 minutes**
of visible logged activity, plus an unknown amount of untimed work after 16:25 that,
by tool-call volume, looks comparable to or larger than the timed portion — so a
realistic estimate for the whole session is **60–90 minutes**, the majority of it spent
fighting the regression-check path rather than the actual fix.

---

## 3. Where IssueForge itself failed, and why

These are gaps in the **IssueForge tool**, not in the Drupal fix being tested.

### 3.1 Environment provisioning: DDEV port conflict (2 failed attempts)
- **What happened:** `provision_env.py` let DDEV auto-select a fallback router port
  (33000) when port 80 was unavailable, with no check that the fallback port was
  actually free.
- **Why it failed:** Port 33000 was already held by an unrelated host process (looked
  like an IDE and its language server) — nothing to do with Docker or DDEV state.
- **Misleading step:** IssueForge's own troubleshooting doc says "DDEV port conflict →
  run `ddev poweroff`." I followed it first since it's the documented fix, and it
  didn't help — because the conflict wasn't DDEV's own stale state, it was a foreign
  process. That troubleshooting entry is correct for *some* port conflicts but not this
  class of it, and cost one full retry cycle to rule out.
- **Fix applied this session:** Set DDEV's global `router-http-port`/`router-https-port`
  to a confirmed-free pair (33010/33011).
- **Not fixed in the tool:** `provision_env.py` still doesn't proactively check port
  availability before calling `ddev start`, so this will recur on any machine where
  33000 (or 80) is occupied by something else.

### 3.2 `apply_mr.py`: false-negative on an already-applied patch
- **What happened:** `apply_mr.py` reported `[FAIL] Could not apply: Patch cannot be
  applied cleanly with any strategy.` — but the file on disk already contained the
  exact fix.
- **Why it failed:** A patch that's already applied will always fail `git apply
  --check` (the "before" context in the diff no longer matches). The tool doesn't
  distinguish "already applied" from "genuinely conflicting" — both produce the same
  generic failure message.
- **Downstream effect:** because `apply_result["success"]` was `False`, the script's
  final summary fell back to reporting the **outer Drupal core repo's** git state
  (branch `11.x`, core commits) instead of the nested `modules/contrib/layout_paragraphs`
  repo where the change actually lives — which is confusing and looks like the tool
  patched the wrong repo entirely, when it actually just never got that far.
- **Not fixed in the tool:** `PatchApplier.apply_patch_file()` doesn't pre-check "is
  this diff already present in the working tree" before returning a generic failure.

### 3.3 `check_regression.py` / `RegressionChecker`: wrong repo root for contrib issues
- **What happened:** Running `check_regression.py 3392735` reported "PHPUnit: SKIPPED
  — No matching test files found," even though the actual changed files (3 files
  inside `modules/contrib/layout_paragraphs/`) very much have matching tests.
- **Why it failed:** The script always calls `GitWorkspaceManager.get_status(env_path)`
  — the **outer** Drupal core checkout — never the nested contrib repo. For contrib
  issues, all real changes live in the nested clone, so the script sees only
  composer.json/composer.lock noise and concludes nothing meaningful changed.
- **Contrast:** `apply_mr.py` gets this right (`apply_and_check()` correctly uses
  `target_root` from `PatchApplier._get_apply_cwd()`), but `check_regression.py` was
  apparently never updated to match — this is the same class of bug the memory notes
  say was fixed in the provisioner/`apply_mr.py` on 2026-07-17, but the fix didn't
  reach `check_regression.py`.
- **Workaround used this session:** invoked `RegressionChecker.run_all()` directly with
  the correct `target_root`/`env_relative_files`, bypassing the script.
- **Not fixed in the tool:** `check_regression.py` still has this gap for any future
  contrib issue.

### 3.4 No Selenium/WebDriver in provisioned environments
- **What happened:** All of `layout_paragraphs`'s tests are `FunctionalJavascript`
  (browser-driven) — there are no Kernel or plain Functional tests in this module at
  all. The provisioned DDEV environment had no WebDriver service, so every single test
  failed with `Could not connect to server` on port 4444.
- **Why it matters beyond this issue:** any contrib module whose test suite is
  JavaScript-only will get a **false "all tests fail"** signal from IssueForge as
  provisioned today, with no indication that the cause is "no browser," not "broken
  code."
- **Fix applied this session:** installed the `ddev/ddev-selenium-standalone-chrome`
  add-on and restarted DDEV.
- **Not fixed in the tool:** `provision_env.py` doesn't install this by default or
  detect that a module's tests require it.

### 3.5 `RegressionChecker`'s hardcoded `SIMPLETEST_BASE_URL`
- **What happened:** Even after Selenium was installed and working (confirmed via a
  manual, correctly-configured `ddev exec` run), re-running the check **through**
  `RegressionChecker.run_all()` still showed 53 errors.
- **Why it failed:** the checker's own PHPUnit invocation hardcodes
  `SIMPLETEST_BASE_URL=http://127.0.0.1` on the command line, which **overrides** the
  Selenium add-on's correct container-level default (`http://web`) — Chrome, running
  inside its own container, can't reach `127.0.0.1` (that's itself, not the web
  container).
- **Not fixed in the tool:** this means **no** browser-based regression check run
  through the official script path can currently succeed in a Selenium-enabled
  environment, regardless of the code under test. This is the single largest
  contributor to wasted effort in this session.

### 3.6 `git stash` failure (cause undetermined)
- **What happened:** `git stash` and `git stash push -m test` both failed with the
  generic message "Cannot save the current status" inside the nested contrib repo.
- **Investigated:** git identity was configured correctly, no stale `.git/index.lock`,
  and disk had 89G free — none of the usual causes applied. Root cause not identified;
  worked around with `git diff > file` + `git checkout --` instead.
- **This is a git/environment anomaly, not necessarily an IssueForge bug** — flagging
  it because it directly caused §3.7 below.

### 3.7 Working-tree file corruption during manual diff replay
- **What happened:** After proving the baseline also fails (via the stash workaround),
  reapplying the saved diff (`git apply /tmp/mr139.diff`) wiped
  `LayoutParagraphsBuilder.php` to **0 bytes**.
- **Why it happened:** the diff file itself was bad — `git diff > /tmp/mr139.diff` had
  captured the file already in a corrupted (empty) state, most likely due to the DDEV
  container crash (§Timeline, "all three containers crashed") interacting badly with
  the bind-mounted working tree at that exact moment. Root cause not fully confirmed.
- **No permanent damage:** git's object database was untouched, so `git checkout --`
  restored the file to its correct 651-line baseline immediately.
- **What had to be recreated by hand:** since the diff file itself was now
  untrustworthy, I did not reuse it. I re-applied the fix by directly editing all 3
  files (the 1-line production fix + the 2 test-file additions from MR !139), then
  verified the resulting `git diff` was byte-for-byte identical (same blob hash,
  `30a4aef`) to what had been confirmed correct earlier.

### 3.8 DDEV project-root vs. symlink path mismatch (recurred twice)
- **What happened:** `ddev restart` / `ddev start` failed with "project root is already
  set to `/home/.../IssueForge/...`, refusing to change it to
  `/home/.../.issueforge/current/...`".
- **Why it failed:** `$HOME/.issueforge/current` is a symlink to the real project
  directory. DDEV resolves and stores the literal path used at `ddev config` time; if
  a later command is run via the symlink instead of the canonical path, DDEV treats it
  as a different (conflicting) project root.
- **Workaround:** always `cd` to the canonical (non-symlinked) path before any `ddev`
  command. This tripped me twice in this session because IssueForge's own path
  convention (`$HOME/.issueforge/current/...`) is the symlinked form.

---

## 4. Retry / attempt counts

| Check | Attempts | Converged? |
|---|---|---|
| Environment provisioning | 3 | Yes — root cause (port conflict) fixed, not a code issue |
| Bug reproduction script | 3 | Yes — two setup bugs in my own script, fixed |
| Apply MR !139 | 1 (reported failure, but was already applied) | N/A — false negative |
| Regression check (raw, no Selenium) | 1 | Failed — infra gap, not a retry-fixable failure |
| Regression check (with Selenium, wrong driver args) | 1 | Failed — my own config mistake |
| Regression check (with Selenium, correct args, manual) | 1 | Succeeded in getting real signal |
| Baseline comparison (proving pre-existing failure) | 1 | Succeeded |
| Fix re-application after corruption | 1 | Succeeded, verified byte-identical |
| Final official regression check (`RegressionChecker.run_all`) | 1 | Still shows FAIL due to §3.5 (tool bug, not a real failure) |

No step exceeded the bounded-retry protocol's cap of 3 attempts. The repeated failures
were concentrated in **infrastructure/tooling gaps**, not in code-fix convergence — the
actual one-line fix was correct on the first reproduction and never needed rework.

---

## 5. Token / effort proxy (not real telemetry — see caveat at top)

I can't report real token counts. As a rough relative proxy, by number of tool calls
and data volume moved:

- **Heaviest phase by far:** the regression-check saga (§3.3–§3.7) — repeated
  multi-hundred-line PHPUnit output captures, multiple full DDEV restarts (each pulling
  container images), and several rounds of source reading to diagnose each failure.
  This was easily the majority of the session's total effort.
- **Second heaviest:** provisioning retries (§3.1) — each failed attempt re-cloned
  Drupal core (depth 50) and the contrib module from scratch before failing at the
  `ddev start` step, so the wasted work per attempt was non-trivial (a full core clone),
  not just a quick failed command.
- **Lightest phases:** Steps 1–2 (preview/analyze) and drafting the final comment —
  both single-shot, no retries, minimal data volume.

---

## 6. Overall tool performance assessment

**What worked well:**
- The core workflow (preview → analyze → provision → reproduce → apply → regress →
  comment) is sound and got to a correct, verified conclusion.
- `apply_mr.py`'s contrib-repo path resolution (`_get_apply_cwd`) is correct and was
  the one part of the patch-application pipeline that worked as designed.
- The bounded-retry discipline meant no time was wasted over-iterating on the actual
  code fix — once reproduced, the fix was right immediately.

**What needs fixing in IssueForge, in priority order:**
1. **`RegressionChecker`'s hardcoded `SIMPLETEST_BASE_URL=http://127.0.0.1`** — this
   alone makes every browser-test regression check unreliable in any Selenium-enabled
   environment. Highest priority; affects every future contrib issue with JS tests.
2. **`check_regression.py` targeting the wrong repo for contrib issues** — silent
   "SKIPPED, no matching tests" is worse than an explicit error, since it looks like a
   pass.
3. **No Selenium/WebDriver in provisioned environments by default** — should either be
   installed automatically, or the tool should detect JS-only test suites and say so
   explicitly rather than reporting connection-refused as a generic failure.
4. **`apply_mr.py` should detect "already applied"** as a distinct, non-error outcome.
5. **Provisioner should verify the fallback router port is actually free**, not just
   that the primary (80) is busy.
6. **Troubleshooting doc's `ddev poweroff` advice** should be narrowed or given a
   fallback, since it doesn't address foreign-process port conflicts.

**Net assessment:** the actual Drupal-side investigation (root-causing the bug,
confirming the fix, proving the remaining failures are pre-existing) went cleanly and
converged fast. Nearly all of the session's friction came from IssueForge's own
environment/regression tooling having gaps specific to **contrib** issues with
**JavaScript-only** test suites — a combination this session happened to hit, and one
that will recur for other contrib modules until §6 items 1–3 are addressed.
