# IssueForge — Organizational Proposal

**Tool:** IssueForge  
**Author:** Meeninath Dhobale  
**Organization:** QED42  
**Date:** June 2026  
**Status:** Proposal for internal adoption

---

## Executive Summary

IssueForge is an AI-powered developer tool that automates the most time-consuming parts of Drupal open source contribution — environment setup, bug reproduction, patch validation, and submission. Built as a Claude Code skill, it integrates directly into a developer's existing workflow and reduces the time to complete a Drupal.org issue from several hours to under 30 minutes.

This document proposes the adoption of IssueForge as a standard tool for QED42's Drupal contribution program.

---

## 1. Problem Statement

### The Cost of Open Source Contribution

Contributing to Drupal.org is one of the most valuable things a Drupal agency can do — for reputation, for client outcomes, and for the community. However, the actual mechanics of contribution are slow, error-prone, and deeply repetitive.

Every time a developer picks up a Drupal.org issue, they face the same series of manual steps:

**Environment Setup (1–3 hours)**
- Identify the correct Drupal version from the issue
- Clone the repository and check out the right branch
- Configure DDEV, run `composer install`, set up Drush
- Install the Drupal site with the correct profile
- Install any contrib modules or themes the issue depends on
- Configure git identity and set up the issue fork remote

**Bug Reproduction (30 min – 2 hours)**
- Read and interpret the issue description
- Figure out what "Steps to reproduce" actually means in code
- Write a PHP script or follow manual browser steps to trigger the bug
- Verify the bug is actually reproducible in this environment

**Patch/MR Validation (30 min – 1 hour)**
- Identify the correct patch or MR to test
- Apply it (dealing with whitespace issues, wrong base branches, git conflicts)
- Run PHPUnit tests
- Verify no regressions in related modules
- Commit and push to the issue fork, or generate a patch file

**Total per issue: 3–6 hours of mechanical work before any real thinking begins.**

### The Org-Level Impact

At QED42, multiple developers contribute to Drupal core and contrib. If each developer spends even 3 hours on setup per issue, and contributes 2 issues per week:

| Developers | Issues/week | Hours lost to setup/week | Hours lost/year |
|---|---|---|---|
| 5 | 10 | 30 hrs | 1,560 hrs |
| 10 | 20 | 60 hrs | 3,120 hrs |

That is thousands of hours per year spent on work that adds zero intellectual value — time that could go into actually fixing bugs, reviewing architecture, writing tests, or taking on more issues.

### The Expertise Barrier

Junior and mid-level developers who want to contribute often cannot because:
- Setting up a Drupal contribution environment is intimidating
- Reading a complex issue and understanding what to test requires deep Drupal knowledge
- Dealing with patch apply failures, wrong branches, and PHPUnit configuration discourages them from trying again

This creates a bottleneck where only senior developers contribute, further limiting throughput.

---

## 2. What IssueForge Solves

IssueForge removes the mechanical overhead of Drupal contribution entirely. A developer types one command:

```
/issueforge https://www.drupal.org/project/drupal/issues/3593581
```

And the tool handles everything else.

### Problem → Solution Mapping

| Problem | IssueForge Solution |
|---|---|
| Manual environment setup (DDEV, composer, drush, modules) | Fully automated — provisions a complete, issue-specific environment in one command |
| Reading the issue to understand what to test | Analyzes the issue, identifies root cause, writes developer-friendly reproduction steps |
| Writing a PHP reproduction script | Claude writes the script based on its understanding of the issue |
| Patch apply failures (whitespace, wrong base, conflicts) | Tries 4 application strategies automatically, selects the one that works |
| Running PHPUnit — config, paths, test discovery | Auto-discovers relevant tests, runs them with correct configuration |
| Setting up git identity and issue fork | Automated: creates branch, adds remote, provides push command |
| Finding the right patch/MR to test | Detects all patches and MRs from the issue page, selects most recent |
| Getting push access and submitting | Guides through "Get push access" flow, provides exact git commands |

---

## 3. How It Works

IssueForge is a **Claude Code skill** — it runs inside Claude Code (the AI coding assistant) and uses a combination of Python scripts and Claude's intelligence to automate contribution.

### Architecture Overview

```
Developer types: /issueforge <drupal-issue-url>
        │
        ▼
┌─────────────────────────────────────────────────────────┐
│                    Claude Code (AI Layer)                │
│  Reads issue, synthesizes summary, writes repro script, │
│  guides the developer through each decision             │
└────────────────────┬────────────────────────────────────┘
                     │ calls
        ┌────────────▼───────────────┐
        │    Python Scripts Layer    │
        │  (Mechanical Automation)   │
        └────────────┬───────────────┘
                     │
    ┌────────────────┼────────────────────┐
    ▼                ▼                    ▼
Drupal.org API   GitLab API            DDEV
(issue data,     (MR metadata,         (Docker-based
 patches)         MR diffs)             Drupal env)
```

### The 5-Step Workflow

**Step 1 — Preview**
Fetches issue metadata, patches, MRs, and recent comments. Claude presents a concise summary: what the bug is, current status, what's available to test, and what the community is currently discussing — not raw comment text, but the intent and open questions.

**Step 2 — Analyze**
Runs a 14-stage analysis pipeline:
- Identifies the correct Drupal branch and PHP version
- Detects which subsystems are involved (Views, Entity API, Layout Builder, etc.)
- Identifies the root cause signal from modified functions and file paths
- Detects all patches and MRs, selects the most recent
- Extracts or derives structured reproduction steps
- Generates an environment plan (modules, themes, install profile)

Claude reads the output and presents: root cause, detailed reproduction steps it wrote itself, environment details.

**Step 3 — Provision**
Creates a complete, isolated Drupal environment:
- Clones Drupal at the exact branch the issue targets
- Configures DDEV (Docker-based local Drupal environment)
- Runs `composer install`, installs Drush, runs site-install
- Downloads and enables any required contrib modules or themes
- Verifies each module exists on drupal.org before attempting install
- Configures git identity, creates working branch
- Runs `ddev drush uli` → gives the developer a one-time login link

**Step 4 — Reproduce**
Claude writes a PHP Drush script that programmatically triggers the bug, then runs it against the live DDEV site. Tells the developer exactly what to look for.

**Step 5 — Apply & Validate**
Downloads and applies the patch or MR. Tries 4 application strategies automatically. Runs:
- Health check (confirms Drupal bootstraps)
- PHPUnit tests (auto-discovered for modified files)
- Module compatibility check (Layout Builder, Paragraphs, SDC)

Prints the exact git commands to push to the issue fork or save as a patch file. Walks the developer through "Get push access" on the issue page.

---

## 4. Time Impact

### Time Comparison: Manual vs. IssueForge

| Task | Manual | With IssueForge |
|---|---|---|
| Environment setup | 1–3 hours | ~5 minutes (automated) |
| Bug reproduction | 30 min – 2 hours | ~10 minutes (Claude writes script, runs it) |
| Patch validation | 30 min – 1 hour | ~5 minutes (automated apply + regression) |
| Submission (push / patch) | 15–30 minutes | ~2 minutes (guided commands) |
| **Total** | **3–6 hours** | **20–30 minutes** |

### What This Means in Practice

A developer who previously could contribute **1–2 issues per week** can now contribute **8–12 issues per week** — the same intellectual effort, but the mechanical barrier is gone.

For an organization with 5 contributing developers:

| Metric | Manual | With IssueForge | Improvement |
|---|---|---|---|
| Issues contributed/week | 10 | 50–60 | 5–6x |
| Developer hours on setup/week | 30 hrs | 3 hrs | 90% reduction |
| Issues junior devs can tackle | Low | High | Significant |

---

## 5. Impact on Organization Growth

### 5.1 Reputation on Drupal.org

Drupal.org tracks contribution credit — commits, patch reviews, issue comments, MR approvals — and displays it publicly on organization pages. More issues contributed per week directly translates to higher visibility in the Drupal community.

High contribution scores signal expertise, attract enterprise clients who evaluate vendors by community standing, and increase the likelihood of being invited to Drupal governance and working groups.

### 5.2 Technical Depth Across the Team

When environment setup is automated:
- Junior developers can work on real Drupal issues without senior hand-holding
- Mid-level developers can contribute to core, not just contrib modules
- Senior developers spend time on architectural decisions, not setup scripts

This creates a contribution culture across seniority levels rather than a bottleneck at senior level.

### 5.3 Client Project Quality

Bugs fixed in Drupal core and contrib directly improve the quality of client projects built on that code. Developers who regularly reproduce and fix upstream bugs develop:
- Deeper understanding of Drupal internals
- Faster debugging skills on client projects
- Awareness of known issues before clients hit them

### 5.4 Talent Attraction and Retention

Developers who contribute to open source build public portfolios. A workplace that provides tooling to make contribution easy and rewarding is more attractive to Drupal engineers. It also gives developers meaningful work beyond delivery projects.

### 5.5 Reduced Reliance on External Fixes

When client projects hit Drupal bugs, the typical path is: file issue → wait weeks for community fix → apply patch manually. With IssueForge and a contributing team, QED42 developers can fix the bug themselves, validate the fix, and submit — giving clients a resolution in days rather than weeks.

---

## 6. Scenarios Where IssueForge Helps

### Scenario 1: Client hits a bug in Drupal core

A client reports that Layout Builder is throwing an exception on their production site. The bug is a known Drupal.org issue with an open MR.

**Without IssueForge:** Developer spends 2–3 hours setting up an environment to reproduce the issue, another hour applying and testing the MR, then manually patches the client site. Total: 4–5 hours.

**With IssueForge:** `/issueforge <issue-url>` provisions the environment, applies the MR, runs regression checks, and gives the developer a validated patch in under 30 minutes. The MR is also submitted upstream, credited to QED42.

---

### Scenario 2: Contribution Sprint

The team is participating in a Drupal contribution sprint. 5 developers, 1 day, goal: as many issues as possible.

**Without IssueForge:** Each developer spends the first 1–2 hours setting up. By lunch, they have maybe 2–3 issues done collectively.

**With IssueForge:** Each developer starts contributing within 10 minutes. By end of day, the team has worked through 15–25 issues.

---

### Scenario 3: Junior developer wants to contribute

A junior developer with 1 year of Drupal experience wants to contribute but doesn't know how to set up a Drupal contribution environment or what "steps to reproduce" means in terms of actual code.

**Without IssueForge:** Requires senior mentoring, hours of guidance, likely abandons the effort.

**With IssueForge:** Junior types the issue URL. IssueForge explains the bug in plain language, generates reproduction steps, provisions the environment, and walks through every step. Junior contributes independently.

---

### Scenario 4: Reviewing a patch for a security issue

A critical security patch needs validation before it can be committed to Drupal core. The reviewer needs to reproduce the vulnerability, confirm the patch fixes it without regression.

**Without IssueForge:** Setting up a secure test environment, writing a PoC, running tests manually — 3–4 hours minimum.

**With IssueForge:** Environment provisioned with the exact branch. Patch applied with regression checks. Reviewer focuses on reading the code, not running infrastructure.

---

### Scenario 5: Staying current on a long-running issue

An issue has been active for 6 months with 40+ comments, 8 patch iterations, and 3 competing MRs. A developer needs to understand the current state and test the latest MR.

**Without IssueForge:** Reading all 40 comments, identifying which MR is current, setting up environment from scratch.

**With IssueForge:** Preview step shows the discussion intent (what's still open, what's decided), automatically identifies the latest MR, provisions and applies it in one flow.

---

## 7. Technical Solution

### Technology Stack

| Component | Technology | Purpose |
|---|---|---|
| AI layer | Claude Code (claude-sonnet-4-6) | Issue interpretation, step synthesis, decision guidance |
| Automation scripts | Python 3.8+ | API calls, environment orchestration, patch application |
| Local environment | DDEV + Docker | Reproducible, isolated Drupal environments |
| Issue data | Drupal.org REST API | Metadata, patches, comments |
| MR data | GitLab API (git.drupalcode.org) | Merge request detection and diff download |
| Dependency management | Python venv + pip | Isolated Python dependencies |
| Credential storage | `~/.issueforge/credentials` | Secure, never in project directory |

### Design Principles

**AI does the thinking, scripts do the mechanics.**
Claude reads and understands issues, writes reproduction steps, synthesizes discussion intent, and guides the developer. Python scripts handle deterministic operations: API calls, DDEV commands, git operations, file I/O. No AI inference in the scripts — this keeps them fast, predictable, and debuggable.

**One-prompt credential setup.**
The only credential needed is a GitLab Personal Access Token. The installer derives name, email, and username from the token automatically. No configuration files to edit.

**Non-interactive scripts.**
All Python scripts print output and exit. No `input()` calls, no blocking prompts. Claude Code handles the conversation with the developer — it reads the output and asks the right questions.

**Graceful degradation.**
If a module doesn't exist on drupal.org, it's skipped (not a crash). If git fetch times out, it's caught gracefully. If PHPUnit has no relevant tests, that level is skipped. The tool continues as far as it can.

**Smart environment reuse.**
If an environment already exists and is running on the correct branch, the provisioner skips cloning and just proceeds to the next step. No redundant 5-minute setup for repeat testing.

### Installation

Single command:
```bash
curl -fsSL https://raw.githubusercontent.com/Mspiro/IssueForge-mcp/main/install.py | python3
```

Or, if you want to control the install directory:
```bash
mkdir ~/my-issueforge && cd ~/my-issueforge
curl -fsSL .../install.py -o install.py
python install.py
```

The installer:
1. Clones the repository
2. Creates a Python virtual environment
3. Installs dependencies
4. Prompts for GitLab token (one question)
5. Registers the `/issueforge` slash command in Claude Code
6. Adds auto-allow rules so DDEV and git commands don't require repeated approval

### Prerequisites

- Claude Code (claude.ai/code or VS Code extension)
- DDEV installed and running
- Python 3.8+
- Git

---

## 8. Current Capabilities

### What It Can Do Today

- [x] Preview any Drupal.org issue: metadata, patches, MRs, discussion intent
- [x] Analyze issues: root cause detection, subsystem identification, fix strategies
- [x] Provision complete DDEV environments for Drupal 7, 9, 10, 11
- [x] Provision contrib module environments (separate clone + enable)
- [x] Verify contrib modules exist before attempting install (no false failures)
- [x] Auto-detect and download the most recent patch or MR
- [x] Apply patches with 4 fallback strategies
- [x] Run regression checks: health, PHPUnit, module compatibility
- [x] Generate one-time login link via `ddev drush uli`
- [x] Guide submission: push to issue fork or save as patch file
- [x] Walk developer through "Get push access" on Drupal.org
- [x] Smart environment reuse (skip re-provisioning when branch matches)
- [x] One-prompt credential setup (token → name/email auto-derived)
- [x] Auto-allow rules for Claude Code bash permissions

### Supported Drupal Versions

| Version | Branch | PHP |
|---|---|---|
| Drupal 11 | 11.x | 8.3 |
| Drupal 10 | 10.3.x | 8.2 |
| Drupal 9 | 9.5.x | 8.1 |
| Drupal 7 | 7.x | 7.4 |

---

## 9. Risks and Mitigations

| Risk | Mitigation |
|---|---|
| DDEV environment conflicts | `ddev poweroff` + cleanup on failure; each issue gets isolated env |
| Wrong Drupal branch detected | Branch shown to developer before provisioning; can override |
| Patch apply fails on all strategies | Clear error message; developer can apply manually |
| GitLab token expires | Setup re-prompts on failure; `setup.py --force` to refresh |
| Docker/DDEV not available | Installer checks prerequisites before starting |
| Environment takes too long | Smart reuse avoids re-provisioning existing environments |

---

## 10. Proposal Ask

### Phase 1 — Pilot (1 month)
- 3–5 developers use IssueForge during normal contribution work
- Track: issues completed per week, time to first working environment, developer satisfaction
- Identify gaps in the tool for QED42-specific workflows

### Phase 2 — Standardize (month 2)
- Add IssueForge to QED42's developer onboarding guide
- Integrate into contribution sprint workflow
- Contribute any QED42-specific improvements back to the open source repo

### Phase 3 — Scale (month 3+)
- Enable junior developers to contribute independently
- Set contribution targets per team (e.g., 5 issues/developer/week)
- Track and showcase QED42's Drupal.org contribution metrics

### What Is Needed

- **From developers:** Install IssueForge, use it for one real issue, provide feedback
- **From leadership:** 1 hour of time to review this proposal; endorsement of pilot
- **Infrastructure:** None — runs on each developer's machine using existing DDEV setup

### Cost

IssueForge is open source. The only cost is Claude Code usage (API tokens), which is already in use at QED42.

---

## 11. Conclusion

Drupal contribution is valuable — for the community, for client outcomes, and for QED42's reputation. But the mechanical overhead of contribution has made it slow and exclusive to senior developers.

IssueForge removes that overhead entirely. A developer types one command and gets a working environment, a clear bug reproduction, and a validated patch — in under 30 minutes instead of 3–6 hours.

At 5 developers contributing with IssueForge, QED42 could contribute 5–6x more issues per week with the same team, expand contribution access to junior developers, and build a faster, deeper feedback loop between upstream Drupal and client projects.

The tool is built, tested, and ready to use. The only step remaining is adoption.

---

## Appendix: Repository

**GitHub:** https://github.com/Mspiro/IssueForge-mcp  
**Install:** `curl -fsSL https://raw.githubusercontent.com/Mspiro/IssueForge-mcp/main/install.py | python3`  
**Skill command:** `/issueforge <drupal-issue-url>`

---

*Prepared by Meeninath Dhobale, QED42 — June 2026*
