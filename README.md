# codebase-audit

A Claude Code skill for auditing a codebase you did not write and are about to build on, plus a
one-pass probe script that collects the evidence so nine axes do not re-derive the same twelve facts.

## Why

A code review reads a change against the intent of the person who made it. An audit asks a different
question — *what risk do I inherit by building on this?* — about a system whose authors are gone,
whose intent is undocumented, and whose defects have had years to become load-bearing.

That difference decides the method, because the expensive defects in an inherited system are not in
the source. They are in what the system does: the timeout that truncates, the queue that half-drains,
the config that validates and does the wrong thing, the build that succeeds and ships someone else's
code. You will not grep for a defect you have no reason to suspect, and the system will show you one
in ten minutes of use.

So the skill encodes five rules — run it before you read it, evidence or it doesn't ship, hunt the
silent-success class on its own pass, name what every finding forbids downstream, and state what was
not audited — across nine axes, with severity derived from a published matrix rather than felt.

## Install

```sh
claude plugin marketplace add locriani/ai-additions
claude plugin install codebase-audit@ai-additions
```

Plugin skills only surface in **new** Claude Code sessions, so quit and reopen after installing.

```sh
claude plugin list        # codebase-audit@ai-additions, enabled
```

No external dependencies. `probe.sh` is bash 3.2 compatible and uses whatever is already on the
machine — it degrades to `n/a` rather than failing when a tool is absent.

## Collecting evidence

```sh
bash "${CLAUDE_PLUGIN_ROOT}"/skills/codebase-audit/scripts/probe.sh <target-dir> [-o <bundle-dir>] \
     [--host-containers] [--timeout N]
```

Detects the stack rather than assuming it, runs every applicable probe once, and writes a bundle plus
`manifest.tsv`. Prints the bundle path on stdout and a summary on stderr.

```
probe               axis          status  exit  bytes  lines  stderr  file                        note
git-commit-count    supply-chain  ok      0     2      1      no      out/git-commit-count.txt    see output file
npm-audit           supply-chain  error   1     240    7      yes     out/npm-audit.txt           exited 1; output says the tool did not run ("code": "ENOLOCK") — …
dockerfile-fetches  supply-chain  ok      0     74     1      no      out/dockerfile-fetches.txt  see output file
db-clients          data-quality  n/a     -     0      0      no      -                           host container inspection is opt-in; pass --host-containers
secret-scan         security      empty   1     0      0      no      out/secret-scan.txt         no assigned literal in the file types listed in env.txt — …
```

Six rows from a real run against a small Node fixture with no lockfile; long notes are cut at `…`.
Nine columns: `stderr` says the probe wrote to stderr (`out/<probe>.err`), and `lines` over a probe's
cap adds a `TRUNCATED` note with the complete output in `out/<probe>.full.txt`. `env.txt` records
the target, host, git scope, the file types `secret-scan` read, and whether a timeout was actually
enforced.

**The five statuses are the point.** `empty` means the probe ran and found nothing — a result, and
sometimes a finding. `error` means it could not run, so you know nothing about that area. `n/a` means
it does not apply. `output` means it exited nonzero *and* produced output — vulnerability scanners
signal findings that way, and discarding it throws away the best evidence in the bundle.

Collapsing `empty` and `error` into one silent outcome is Empty-Result Ambiguity, the first defect
class this tool exists to hunt. **v1.0.0 committed it** — seventeen probes ended in `|| true` and
physically could not report failure, so a scan of a tree it could not read came back "clean". The
`|| true` suffixes are gone, every probe runs with `pipefail` so a failing producer is a failing
probe, and none discards its stderr. The `stderr` column and the `TRUNCATED` note apply the same
principle: a partial read must not pass as a complete one. What it still cannot promise is listed
under *What probe.sh does not guarantee* in `SKILL.md`.

The bundle is evidence, not findings. It tells you a port is published; whether that matters is a
judgment, and judgment is what the skill is for.

Exit codes: `0` the run completed — findings are not failures — and `2` for a usage error or a target
that does not exist.

## Layout

```
.claude-plugin/plugin.json                       marketplace metadata
agents/auditor.md                                the subagent — running order for the nine axes
skills/codebase-audit/SKILL.md                   method, severity matrix, finding format
skills/codebase-audit/scripts/probe.sh           one-pass evidence collection
skills/codebase-audit/scripts/test_probe.sh      its tests — status classification,
                                                 scope containment, awkward paths
skills/codebase-audit/references/security.md         at what layer is authorization enforced?
skills/codebase-audit/references/supply-chain.md     does the build produce your code?
skills/codebase-audit/references/performance.md      what limit governs the serving path?
skills/codebase-audit/references/architecture.md     read/write asymmetry, per resource, per verb
skills/codebase-audit/references/code-quality.md     does it meet the standard it declares?
skills/codebase-audit/references/testing.md          what would have to break for a test to notice?
skills/codebase-audit/references/observability.md    when it fails at 3am, what tells you?
skills/codebase-audit/references/data-quality.md     absent because none, or never captured?
skills/codebase-audit/references/compliance.md       what lands in logs, and is it actually encrypted?
skills/codebase-audit/references/standards-map.md    OWASP / ASVS / CWE identifiers, offline
```

```sh
bash skills/codebase-audit/scripts/test_probe.sh
```

The tests target the classification contract, because that is where a wrong answer produces a
confident false negative: a reader acts on `empty` by writing "no X found" and on `error` by writing
nothing at all. No network, no docker, no fixtures outside a temp dir.

**A green run was not proof in v1.2.0**, and the evidence that it is now is mutation, not the pass
count. Against v1.2.0, four of eleven deliberate breakages left the suite all-pass: deleting the
`TRUNCATED` flag, the bundle-reuse clearing, the `error` status, or the `output` status. The suite
was rebuilt around those, and each of 35 mutations of `probe.sh` fails at least one of its 52 tests,
in every case the test aimed at that behaviour:

```
status contract  TRUNCATED flag · no flag under the cap · no flag exactly at it · complete output kept
                 out/ clearing · error · output · empty · per-probe ok_exits · stderr column
                 stderr note · npm failure-content check · TIMED OUT status
safety           -o marker guard · --timeout validation · host-container gate
exit status      pipefail · find accepting exit 1 · `ls … 2>/dev/null` for license files
                 dockerfile-fetches via xargs · shell syntax via xargs · shellcheck and php -l exit mapping
collection       git detection · placeholder filter · root-anchored prune · largest-files split on spaces
                 file-count by newline · secret-scan file types · secret-scan empty note
                 include globs expanded in the caller's directory · shell test-file glob
reporting        env.txt effective timeout · timeout via eval · usage by line number
```

Writing the tests found two defects the mutation list did not anticipate: the include globs expanded
against whatever directory `probe.sh` was launched from — run beside a `CLAUDE.md`, the scan read that
file instead of every `.md` — and BSD `xargs` reports a checker's findings as exit 1, the same as an
unreadable tree. Both are fixed and both are in the list above.

`output`, npm, docker, `timeout`, `php` and `shellcheck` are stub binaries put first on `PATH`;
`error` uses a commitless repository. The suite does not reach real GNU `timeout`, real `php` or
`shellcheck`, or the five scanners with no failure-content check. The first three were checked by hand
at 1.3.0 in a Debian container (php 8.3.33, shellcheck 0.10.0, GNU coreutils 9.7, non-root): parse
errors and lint findings file `ok`, clean trees `empty`, an unreadable directory `error`, and a hung
probe `TIMED OUT` at exit 124. The suite itself also passes there, 51 of 51 with the macOS-only
no-timeout test skipped.

`${CLAUDE_PLUGIN_ROOT}` resolves to this plugin's installed copy under `~/.claude/plugins/cache/`.
Editing this repo does not change what a running session loads — run
`claude plugin marketplace update ai-additions` and reinstall to pick changes up.

## The nine axes

Five of them are the conventional set that most audit briefs ask for. Four were added because they
had no home and kept producing the highest-impact findings anyway:

**Supply chain** is not a security bug and not an architecture flaw — it is the question of whether
the artifact you deploy contains the code you audited, and it is its own discipline. **Code quality
and language idiom** is where the per-language toolchain lives, governed by one rule: audit against
the standard the project *declares*, because imposing your own produces noise rather than findings.
**Testing** asks what would have to break for a test to notice, which is a different question from
coverage. **Observability** asks what tells you at 3am, and the honest answer is usually "a user, the
next morning" — which is the baseline anything you add has to beat.

## Scope

Assessment only. The skill records what is true and what it constrains; it does not fix anything,
and remediation is deliberately out of scope — an audit that edits the system it is measuring has
destroyed its own baseline.

It is not a penetration test, not a load test, and not a substitute for the ecosystem's own security
tooling. It runs those tools and reads their output; it does not replace them.

It is also not a code review. Reviewing a diff you just wrote is a different task with a different
method — use `code-review` for that.
