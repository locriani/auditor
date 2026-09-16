---
name: codebase-audit
description: Use when a codebase someone else wrote has to be assessed before work is built on top of it — inheriting a service, forking an open-source project, technical due diligence, an AUDIT.md gate, "what are we walking into" — because the findings that matter come from operating the system and expire the moment they are asserted without evidence. Do NOT use for reviewing a diff you or the team just wrote.
---

# Codebase Audit

An audit is not a code review. A review reads a change against the intent of the person who made it. An audit asks a different question — **what risk do I inherit by building on this?** — about a system whose authors are unavailable, whose intent is undocumented, and whose defects have had time to become load-bearing.

That difference decides the method. You cannot review your way to the answer, because the most expensive defects in an inherited system are not visible in the source. They are visible in what the system *does*.

## The one rule that governs everything

**Operate the system, cite what it did, and name what each finding forbids you to build.**

```
always:  run(system) → observe → cite → constrain
never:   finding without evidence          = ✗   an assertion is a liability
never:   finding without downstream        = ✗   an audit that changes nothing is decoration
never:   exit_status(probe) = 0 ⊨ correct  = ✗   this is the class you are hunting
```

## The five rules

### 1. Run it before you read it

Boot it. Log in. Import something. Break something on purpose. Watch what it writes while you do.

Reading finds what the authors wrote down. Operating finds what they did not — the timeout that truncates, the queue that half-drains, the config that validates and does the wrong thing. You will not think to grep for a defect you have no reason to suspect, and the system will show you one in ten minutes of use.

If the system cannot be run, that is the first finding, and everything downstream of it is `Confidence: Probable` at best. Say so rather than quietly proceeding.

### 2. Evidence or it doesn't ship

Every finding cites `path:line`, command output, or a measured number.

This is not pedantry about rigor. An audit gets read by someone who will ask *"how do you know?"*, and a finding that cannot survive that question damages every finding next to it. One unsupported claim makes a reader re-examine the twelve supported ones.

The pressure this creates is real: you will find things that matter and cannot prove tonight. Do not drop them and do not overstate them — ship them labelled `Confidence: Unverified` and say in the appendix what verifying would take. **Overstating is the failure that actually costs you.**

### 3. Hunt the silent-success class specifically

A defect where exit status says success and only the output reveals the problem.

Set this as its own pass, because every tool you have reads exit codes and is therefore blind to it. Nothing will hand you these. The named patterns, and what each looks like in the wild:

| Pattern | Shape |
|---|---|
| Empty-Result Ambiguity | one return value carries two meanings — "no rows" and "the query failed" |
| Swallowed Exceptions | caught, logged at debug, never escalated |
| Success Codes on Failed Work | HTTP 200 because routing worked; the work inside threw |
| Unchecked Output | N rows written, N never confirmed correct |
| Missing Expected Metrics | zero orders at noon — nothing errored, nothing arrived |
| Default Values Masking Loss | absent field replaced by `""`, `0`, `null`, indistinguishable from real |
| Best-Effort Writes Unverified | async write, no read-after-write |
| Async Work Without Completion Signal | job enqueued, completion never confirmed |
| Agent Claims Unverified | a self-report treated as the result |

Probes that find them: **synthetic probe** (send a known input, verify arrival), **after-load assertion** (check the invariant that should hold once the operation claims success), **absence alert** (look for the signal that should be there rather than the error that isn't), **paired-write divergence** (count table A against table B where every A demands a B).

### 4. Every finding names what it constrains downstream

One line: *because this is true, the thing you build on top cannot do X / must do Y.*

An audit that changes no subsequent decision is decoration, however accurate. This line is also the one a reader remembers, and the one an interviewer asks about. If you cannot write it, the finding is an observation and belongs in the appendix, not a section.

### 5. State what was NOT audited

A stated boundary is more credible than implied total coverage.

Every audit is partial. The reader knows this. An audit that does not say where it stopped invites the assumption that it stopped wherever the author got bored — so naming the edge is worth more than the coverage you would have bought with the same time.

## The nine axes

Read only the axis you are working. Each file opens with the one question whose answer changes the design.

| # | Axis | The decisive question | Read |
|---|---|---|---|
| 1 | Security | At what layer is authorization enforced — UI, service, or data? | [references/security.md](references/security.md) |
| 2 | Supply Chain | Does the build produce *your* code, from sources you can name? | [references/supply-chain.md](references/supply-chain.md) |
| 3 | Performance | What limit governs the path that actually serves traffic? | [references/performance.md](references/performance.md) |
| 4 | Architecture | What is the read/write asymmetry, per resource, per verb? | [references/architecture.md](references/architecture.md) |
| 5 | Code Quality | Does the code meet the standard *it declares* — and is one declared? | [references/code-quality.md](references/code-quality.md) |
| 6 | Testing | What would have to break for a test to notice? | [references/testing.md](references/testing.md) |
| 7 | Observability | When it fails at 3am, what tells you, and how fast? | [references/observability.md](references/observability.md) |
| 8 | Data Quality | Is a field absent because there is none, or because it was never captured? | [references/data-quality.md](references/data-quality.md) |
| 9 | Compliance | What lands in logs — and is encoding being mistaken for encryption? | [references/compliance.md](references/compliance.md) |

Standards identifiers for tagging findings: [references/standards-map.md](references/standards-map.md).

**An axis that does not apply is reported as inapplicable, with the reason.** A markdown repo has no data-quality axis and saying so takes one line. Inventing a finding to fill the slot is worse than the empty slot, and a reader can tell.

## Collect the evidence first

```sh
bash ${CLAUDE_PLUGIN_ROOT}/skills/codebase-audit/scripts/probe.sh <target-dir> [-o <bundle>] \
     [--host-containers] [--timeout N]
```

Runs once, detects the stack rather than assuming it, and writes an evidence bundle plus `manifest.tsv`. Run it **before** the axis walk so nine axes do not re-derive the same twelve facts.

Read `manifest.tsv` first. Five outcomes, and the difference between them is what you are allowed to conclude:

```
ok       ran, found something        → read the output file; do not trust that it succeeded
empty    ran clean, found nothing    → a lead toward "no X found" — run the checks below first
n/a      does not apply to this stack→ expected, not a gap
error    could not run               → you know NOTHING here; say so explicitly
output   exited nonzero AND produced output → READ IT
```

`output` exists because vulnerability scanners signal *findings* with a nonzero exit. `npm audit` exiting 1 with 1,700 lines of JSON is the best evidence in the bundle, and treating exit status as the verdict would discard it.

`empty` and `error` are meant never to be the same value. Collapsing them is Empty-Result Ambiguity, the first pattern in the list above, and v1.0.0 of this script committed it. The status column is still the collector's opinion; the output file is the fact. What the probe cannot promise is listed in [What probe.sh does not guarantee](#what-probesh-does-not-guarantee) — read it once before relying on any `empty`.

Two things the probe deliberately will not do without being asked: inspect host containers (`--host-containers`, because a `Dockerfile` in the target is not consent to enumerate the machine) and run unbounded (`--timeout N`).

**Check four things before writing a negative conclusion:** any `error` rows in that area; any `stderr = yes` rows; any `TRUNCATED` note, whose complete output is in `out/<probe>.full.txt`; and the `timeout:` line in `env.txt`, which says `NONE ENFORCED` when no probe was bounded. Each one narrows what the bundle actually covers.

The bundle is evidence, not findings — and it holds raw config and possible secrets, so delete it when the audit is written.

## Severity is derived, never asserted

Grade impact and likelihood, then read the cell. State the cell in the finding so a reader can disagree with the inputs rather than the verdict.

| | **Likelihood: Default** | **Likelihood: Common** | **Likelihood: Conditional** |
|---|---|---|---|
| **Impact: Severe** — data loss, PHI/PII exposure, full auth bypass | Critical | Critical | High |
| **Impact: Major** — constrains the design with no workaround, or corrupts a subset | Critical | High | Medium |
| **Impact: Moderate** — costs real time, has a workaround | High | Medium | Low |
| **Impact: Minor** — worth recording, not worth acting on | Medium | Low | Info |

*Default* = true out of the box, no configuration required. *Common* = true in ordinary use. *Conditional* = needs a specific combination to fire.

**Then apply the detectability bump.** A finding graded `Detectability: SILENT` moves up one level.

```
Info < Low < Medium < High < Critical

detectability(f) = SILENT  →  severity(f) := next level up; Critical stays Critical
```

The reasoning: a loud defect is bounded by the time it takes someone to notice. A silent one is not bounded at all — it accrues damage until an unrelated investigation happens to surface it, and the cost of that gap has no ceiling. Two defects with identical impact are not equally dangerous when one of them announces itself.

**The bump is a default, not an assignment.** Decline it when something outside the defect bounds the silence — a warning printed on every run, a neighbouring output that contradicts the wrong one at a glance, a check the reader cannot avoid making. Write the reason into the Severity line: `High (Moderate × Default = High; SILENT bump declined — <why>)`. A declined bump with a stated reason is a judgment the reader can check. A skipped bump with no reason is an error.

**Do not count silence twice.** Grade Impact as though the defect were noticed the moment it fired. "Nobody would notice, so it spreads" is the detectability argument; putting it in Impact as well moves the finding up two levels for one property. Test: if the Impact sentence would change when the defect became loud, it holds detectability reasoning that belongs in the bump.

## The finding format

```
**<Title>**

- **What** — the defect in one sentence.
- **Evidence** — `path:line`, command output, or a measured number.
- **Impact** — blast radius if it fires.
- **Likelihood** — Default | Common | Conditional.
- **Severity** — <level> (Impact × Likelihood = <cell>; +1 bump if SILENT).
- **Confidence** — Confirmed (reproduced or measured) | Probable (strong static evidence) | Unverified.
- **Detectability** — Loud | Quiet | SILENT.
- **Class** — one of the nine silent-failure patterns, or "loud".
- **Refs** — CWE / OWASP / CVE where one applies; omit the line where none does.
- **Downstream** — what this forbids or forces in what gets built next.
- **Delta** — re-audits only: new | unchanged | relocated | regressed, naming the prior finding.
```

`Delta` exists because severity cannot express a fix that moves a defect instead of removing it. **new** — not present before. **unchanged** — same defect, same place. **relocated** — the old path is fixed and the same defect now appears through another one; graded afresh it can read as "no progress" when the population it affects has changed. **regressed** — introduced by a remediation. Findings that were fixed outright go in the appendix's remediation table, not in a section.

Worked example:

```
**The published image is built from upstream, not from this fork**

- **What** — the release Dockerfile git-clones the upstream project, so a build of
  "your fork" ships code the fork never contained.
- **Evidence** — `docker/release/Dockerfile:162`: `git clone https://github.com/openemr/openemr.git`
- **Impact** — every fork change is absent from the deployed artifact. Severe: the
  deliverable is not the audited system.
- **Likelihood** — Default. No configuration is needed to hit this; it is the build path.
- **Severity** — Critical (Severe × Default = Critical; already at ceiling, bump absorbed).
- **Confidence** — Confirmed. Build produced an image whose
  `org.opencontainers.image.source` label pointed at upstream.
- **Detectability** — SILENT. The build succeeds, the image runs, the app works.
- **Class** — Unchecked Output.
- **Refs** — CWE-1104 (use of unmaintained third-party components); A08:2021.
- **Downstream** — no deployment claim can be made until the build is verified to
  contain fork code. Pin an identity label and assert it in CI before anything ships.
```

## Output structure

```markdown
# AUDIT.md

## Summary            ~500 words, written LAST
## 1. Security        ## 2. Performance      ## 3. Architecture
## 4. Data Quality    ## 5. Compliance & Regulatory
## 6. Supply Chain & Dependencies    ## 7. Code Quality & Language Idiom
## 8. Testing & Verifiability        ## 9. Observability & Operability
## Appendix           method, tooling, standards mapping, what was NOT audited
```

Order is deliberate where a brief demands five specific axes: put those five first so compliance is unmistakable, then the rest. Where no brief constrains you, order by severity of what you found.

**The summary is written last and is a judgment, not a digest.** Not "section 1 found three things, section 2 found five." It answers: what is the single most important thing here, what would someone have missed by only reading the code, and what does this change about the plan. A summary that could be regenerated by concatenating the section headings has not been written yet.

## What probe.sh does not guarantee

Known limits at this version. Each is a place where a status can be wrong without the bundle saying so.

- **Only `npm audit` has its output checked for a scanner that did not run.** `composer audit`, `pip-audit`, `govulncheck`, `cargo audit` and `bundle audit` accept their "found something" exit, so if they fail with that exit and print an error, the row reads `ok`. Open the file.
- **`secret-scan` is a regex over a list of file types**, named in `env.txt`. It matches `key = literal` on one line. Files outside the list, multi-line secrets, and encoded values are not read. It is a lead, not a secret scanner.
- **`test-file-count` knows eight naming conventions.** It misses `.bats`, `*Test.java`, `*Tests.cs`, `*.spec.ts`, `*_test.py` and others, and it reports `0` as `ok`. Never write "no tests" from it.
- **A syntax checker that fails on one file** files `output`. For `php-syntax` and `shell-syntax-only` its message sits in the output file beside real findings, not in `stderr`; `shell-lint` keeps shellcheck's own errors in `stderr`.
- **A grep that could not read part of the tree but matched elsewhere files `output`.** That is correct, and it reads like a finding. Check `stderr`.
- **Timeouts** are enforced only where `timeout` or `gtimeout` exists. On stock macOS nothing is bounded. The test suite uses a stand-in; real GNU `timeout` was checked by hand, not by the suite.
- **`repo-size` is `du` without pruning**, so it includes `.git` and vendored trees. **`largest-files`** splits a filename containing a newline across two lines.
- **Pruning is by directory name at any depth** — `.git`, `node_modules`, `vendor`. First-party code in a directory named `vendor` is not counted.
- **Surface probes are keyword greps.** `route-tables`, `health-endpoints`, `log-surface` and `telemetry` point at files to read; they are not maps of the system.
- **`php-syntax` and `shell-lint` are pinned by the suite only against stand-ins** that follow php's and shellcheck's exit conventions. The real tools were checked by hand at 1.3.0 — php 8.3, shellcheck 0.10.0 and GNU coreutils 9.7 in a Debian container — and matched, but nothing re-checks them when either tool changes its exit codes.

## Red flags — the inference that fails

| Thought | Checksum | Reality |
|---|---|---|
| "The command exited 0, so it worked." | `exit(0) ⊬ correct(output)` | The entire silent-success class lives in this gap. Read the output. |
| "`ini_get()` says the limit is 0, so there is no limit." | `limit(CLI) ⊬ limit(server)` | You measured the wrong SAPI. Check the one that serves traffic. |
| "The query returned no rows, so there is no problem." | `∅ ⊬ clean` | Empty means "none" or "the probe failed". Distinguish before concluding. |
| "It's base64, so it's protected." | `encoded ⊬ encrypted` | Base64 is a transport encoding. Decode it, then judge what you see. |
| "The API exists, so I can write through it." | `readable(r) ⊬ writable(r)` | Map verbs per resource. Read/write asymmetry is invisible until enumerated. |
| "CI is green." | `green(badge) ⊬ tested(repo)` | Confirm CI runs against *this* repo and that a failure would actually block. |
| "The ACL check passed, so the model is enforced." | `pass(check) ⊬ enforced(layer)` | Find where it is enforced. UI-layer checks are bypassed by any direct query. |
| "Nothing looked wrong while I clicked around." | `¬observed ⊬ ¬present` | Absence of an alarm is not evidence when nothing is wired to alarm. |
| "The sample data looks clean." | `clean(synthetic) ⊬ clean(production)` | Synthetic data understates quality problems by construction. Say so. |
