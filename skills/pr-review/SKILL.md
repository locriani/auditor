---
name: pr-review
description: Use when a pull request somebody else wrote has to be reviewed before a human decides what to do with the findings, because a review needs orthogonal axes dispatched in parallel, tests-that-lie triaged first, and every finding cited or dropped. Produces findings, not fixes. Do NOT use to assess an inherited codebase (that is codebase-audit), or to fix what the review finds.
---

# PR Review

A review reads a change against the intent of the person who made it, and it produces findings. What
happens to each finding is the user's call: **file**, **keep**, **fix**, or **discard**. The reviewer
suggests one, and the user decides. There is no fix loop here. Fixing is the implementer's job, after
triage.

## Hard rules

- **Build before reviewing.** Never dispatch reviewers against a change that doesn't compile.
- **One persona per agent.** Never bundle two lenses into one agent. Bundled prompts dilute focus and
  produce shallow reports.
- **Self-contained prompts.** Each agent gets absolute paths, the base and head shas, the contract
  restated, numbered checks, a demand for skepticism, severity-tagged output, and a 600-word cap. See
  `CODE_REVIEW.md` next to this file.
- **All axes in one message.**
- **Evidence or it doesn't ship.** A finding cites `file:line` and the evidence: the line, the
  command and its output, or the test that shows it. Without both, drop it.
- **Confidence is never rounded up.** `Confirmed` means reproduced or run. `Probable` means strong
  static evidence. `Unverified` means neither, and says what would settle it.
- **An axis that doesn't apply gets one line** saying why. Never invent a finding to fill it.

## Axes

Each axis is one subagent, dispatched as `general-purpose` unless noted.

| Axis | Agent | Brief |
|---|---|---|
| Correctness | Senior Staff Engineer (persona 2) | Build the prompt from `code-reviewer.md`, and add persona 2's checks from `CODE_REVIEW.md` |
| Security / edge cases | Chaos Demon (persona 5) | Persona 5's checks. It also reads `../codebase-audit/references/security.md` |
| Over-engineering | ponytail reviewer | Invoke the `ponytail:ponytail-review` skill on the diff. Output as below |
| Architecture compliance | compliance grader | Grade the diff against the canonical document named in the workspace `## Architecture` block, section by section. A gap cites the section and the `file:line`. A stale document is not a code gap, so report it as `Minor`, with the suggestion `file` |
| SOLID | Sandi Metz (persona 10) | Persona 10's checks |
| Clean Architecture | Uncle Bob (persona 11) | Persona 11's checks, as Clean Architecture. If the repo declares another style, name the persona after it and say so |
| Tests that lie | tests-that-lie hunter | For every test the diff adds or touches, ask: what's the smallest change that should fail this test but won't? It also reads `../codebase-audit/references/testing.md` |
| Test run | suite runner | Run the repo's suite in the detached worktree at the head sha. Report pass/fail, the counts, and the command. Missing tests for new behaviour are findings |

## Severity

Subagents report `Critical / High / Medium / Low / Nit`. Map them as follows:

- Critical and High become **Critical**.
- Medium becomes **Important**.
- Low and Nit become **Minor**.

**Tests that lie come first**, whatever their severity. Green means ship, and you ship the bug.

## Finding row

```
R<n> | axis | severity | confidence | file:line | what | evidence | suggested: fix/file/keep/discard
```

A suggestion is a recommendation to the user:
- `fix` means fix it in this PR.
- `file` means open an issue for later.
- `keep` means accept the code as it is, for a stated reason.
- `discard` means you doubt the finding yourself.

## Report

Both the PR comment and the report to the coordinator use this format:

```
Reviewer pass: <full|verify> @ <head sha>
PR: <url>
Tests: <pass|fail> — <counts> — `<command>`
Axes not examined: <axis: reason>, or none

R1 | ...
R2 | ...

Assessment: <one line on the change; no merge verdict>
Dispositions are the user's: file / keep / fix / discard.
```
