# IssueForge

**Give Claude Code a Drupal.org issue link. Get back a reproduced bug, a tested fix, and a comment ready to post — with a human deciding every step that matters.**

![Python](https://img.shields.io/badge/python-3.8%2B-3776AB?logo=python&logoColor=white)
![Drupal](https://img.shields.io/badge/drupal-7%20%E2%80%93%2012-0678BE?logo=drupal&logoColor=white)
![FastAPI](https://img.shields.io/badge/dashboard-FastAPI-009485?logo=fastapi&logoColor=white)
![DDEV](https://img.shields.io/badge/environments-DDEV%20%2F%20Docker-1565C0?logo=docker&logoColor=white)

---

## What this actually is

Working a Drupal.org issue is mostly setup, not code: read a sprawling comment thread, figure out which core version and PHP version and contrib modules the bug even needs, stand up a disposable site to watch it happen, and only *then* start on a fix — before getting it past CI on the first try.

IssueForge is a [Claude Code](https://claude.com/claude-code) skill that automates everything except the judgment calls. It runs as `/issueforge <issue-url>`, and it drives a real pipeline:

```
preview → analyze → provision → reproduce → fix → comment → track
```

At every step where a real decision has to be made — test an existing patch or write a new one, open a merge request or save a patch file, post this comment or not — it stops and asks. It never guesses on your behalf.

## Why it's built this way

IssueForge used to have its own LLM wired in. It doesn't anymore.

Early on, the tool tried to *be* the AI: a bundled LLM client generated reproduction scripts and fixes directly. Keeping that model's output correct turned into a losing game of prompt patches — one commit log shows eight separate fixes in a single day, each one forbidding another wrong pattern the model kept producing. Three days later, the whole LLM layer was deleted in one commit: *"Remove all LLM code — Claude Code skill handles AI reasoning."*

That's the architecture today, and it's the whole design philosophy in one line:

> **Deterministic Python owns the verdict. Claude owns the reasoning. You own the decision.**

Concretely:
- **Python fetches, parses, provisions, and verifies.** It never guesses at meaning — a heuristic classifier's output is explicitly labeled a *hint*, never a conclusion, and downstream code is required to say so.
- **Claude reads the evidence and writes the fix.** Root-cause analysis, the reproduction script, the patch, the drupal.org comment — all reasoning, none of it faked by a keyword match.
- **You approve every consequential move.** Whether to provision at all, which fix strategy to try, merge request vs. patch file, whether to post the comment — six explicit gates, never auto-continued.

Nowhere is that division clearer than in the tool's own quality gates: they exist so a claim the model makes about its own fix is *proven*, not trusted. A patch either passes a real PHPUnit run, a real PHPStan pass, and a real regression sweep against the whole affected module — or it doesn't ship.

## The pipeline

| Step | Script | What happens |
|---|---|---|
| **1. Preview** | `preview_issue.py` | Free, instant look — title, status, patches, MRs, and a synthesis of where the discussion actually stands. No environment, no downloads. |
| **2. Analyze** | `analyze_issue.py` → `slim_plan.py` | Builds the full reasoning payload: root-cause evidence (ranked, budget-capped, never invented), environment requirements, detected merge requests, related issues. |
| **3. Provision** | `provision_env.py` | Clones the right Drupal core branch (or a full distribution like Drupal CMS), starts DDEV, installs contrib dependencies — a real, disposable site in 3–5 minutes. |
| **4. Reproduce** | `reproduce_with_healing.py` | Runs a Drush script that actually triggers the bug against the provisioned site. |
| **5. Fix** | `apply_mr.py`, `run_check.py`, `check_regression.py`, `check_cs.py` | Tests an existing patch, or writes one test-first — then proves it: unit tests, static analysis, a full regression sweep, coding standards. |
| **6. Comment** | *(drafted by Claude)* | A concise, drupal.org-styled write-up of what was found or fixed — never auto-posted. |
| **7. Track** | `dashboard.py` | Silent bookkeeping to the local dashboard, then the environment's containers are stopped. |

Every one of those scripts is invoked directly and its output — JSON, a progress marker, a pass/fail report — is what Claude actually reads. There is no hidden state between them.

## Under the hood

```
scripts/       one entry point per pipeline step (CLI, argparse-thin)
services/      the real logic: API clients, provisioning, patch application, verification, dashboard
classifiers/   keyword heuristics — explicitly downstream of "hint," never "conclusion"
tools/         MCP-style tool wrapper around the same analysis core
dashboard/     the local tracking UI (template + built output)
tests/         32 test files covering the client, provisioning, patch, and dashboard layers
```

A few decisions worth knowing about before you go digging:

- **The evidence bundle is deliberately lossy, and says so.** `services/evidence_extractor.py` ranks and byte-caps what reaches the model — roughly 5.5 KB out of patches that can run past 175 KB — and when something is dropped, it's replaced with a literal `"[N more block(s) omitted for budget]"` entry instead of vanishing silently.
- **Verification is brute-force on purpose.** A full-module regression sweep runs the *entire* affected module's test suite, not just the files a patch touched, because a heuristic can't find a regression in a test it never looked at. It costs Docker minutes, not model tokens — the trade the whole tool is built around.
- **Retries are bounded and comparison-based, not vibes-based.** Two check runs are reduced to a normalized "failure signature" (sorted, deduplicated, timing-independent) and compared with `==`. Same signature twice means the loop isn't converging, and it stops rather than guessing again.
- **Contrib issues have two git repositories in one directory tree**, and the tool is careful about which one every operation targets — the outer core checkout for DDEV, the nested contrib clone for the actual diff, commit, and push.

## Installation

Requires `git`, `python3` (3.8+), and [`ddev`](https://ddev.com/) on your PATH.

```bash
curl -fsSL https://raw.githubusercontent.com/Mspiro/IssueForge-mcp/main/install.py | python3
```

This clones the repo, creates a virtualenv, walks you through one-time credential setup, and registers `/issueforge` as a Claude Code slash command. Restart Claude Code afterward.

To install from a local clone instead:

```bash
git clone https://github.com/Mspiro/IssueForge-mcp.git
cd IssueForge-mcp
python3 install.py
```

### Credentials

One secret is required — a [GitLab personal access token](https://git.drupalcode.org/-/user_settings/personal_access_tokens) (`read_api` scope) for `git.drupalcode.org`. Your git identity is derived from it automatically. Re-run setup any time:

```bash
python3 scripts/setup.py --force
```

An optional drupal.org username can also be added, used only to look up your own contribution credit on the dashboard.

## Usage

```
/issueforge https://www.drupal.org/project/drupal/issues/1234567
```

Claude previews the issue, asks whether you want the full flow or analysis only, provisions an environment in the background while keeping you posted on progress, reproduces the bug, and stops before touching any code to ask how you want to fix it. Nothing gets pushed, patched, or posted without an explicit yes.

Running `/issueforge` with no URL gives you a live status check instead — how many tracked issues have new activity, and a link to the local dashboard.

## The dashboard

A small local FastAPI app (`http://127.0.0.1:8420` by default, auto-starting and self-terminating after 30 minutes idle) tracks every issue you've worked through the tool: status, merge request state and CI pipeline result, comment activity, and drupal.org credit — alongside your full historical contribution record, imported once on first run. Nothing leaves your machine except the read-only refresh calls to drupal.org and GitLab.

```bash
python scripts/dashboard.py           # summary + link, auto-starts the server
python scripts/dashboard.py refresh   # re-check live status for active issues
python scripts/dashboard.py --no-server   # static file:// fallback, no server
```

## Troubleshooting

- **DDEV port conflicts** are checked and remapped automatically before every provision; if one still surfaces, check `docker ps` for what's actually holding the port before assuming it's stale DDEV state.
- **FunctionalJavascript tests failing with a WebDriver error** almost always means the Selenium/Chromium DDEV add-on is missing from an environment provisioned before it was added — `ddev add-on get ddev/ddev-selenium-standalone-chrome && ddev restart` inside that environment fixes it.
- **A patch that won't apply** is tried against four `git apply` strategies automatically, including detection of "already applied" as a distinct, non-error outcome.

## Requirements

```
requests · pydantic · fastapi · uvicorn · python-dotenv · httpx
```

Supports Drupal core 7 through the current development branch, plus known distributions (Drupal CMS today, with room to register more).
