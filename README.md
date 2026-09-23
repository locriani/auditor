# auditor

A Claude Code plugin for auditing a codebase you did not write and are about to build on: the
`auditor` agent, the `codebase-audit` skill, and a one-pass probe script that collects the evidence
so nine axes do not re-derive the same twelve facts.

The name is provisional.

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
claude plugin marketplace add ~/Developer/auditor
claude plugin install auditor@auditor
```

Plugin skills only surface in **new** Claude Code sessions, so quit and reopen after installing.

```sh
claude plugin list        # auditor@auditor, enabled
```

Managed with `uv` for Python 3.11+. Dependencies (`typer`, `rich`, `pydantic`) and dev tools
(`pytest`, `ruff`, `mypy`) are managed via `pyproject.toml`.

## Collecting evidence

```sh
mkdir -m 700 /path/outside/target/bundle
uv run --project "${CLAUDE_PLUGIN_ROOT}" auditor-probe <target-dir> -o <bundle-dir> \
     [--run-toolchains] [--host-containers] [--timeout N]
```

Detects the stack rather than assuming it, runs every applicable probe once, and writes a bundle plus
`manifest.tsv`. Prints the bundle path on stdout and a summary on stderr.

**The target is untrusted code, and collecting evidence can run it.** Dependency scanners and
`git status` honour configuration the target ships: a cargo alias, a composer plugin, a Gemfile, a
`go.mod` toolchain line, a git clean filter. They run only with `--run-toolchains`; without it their
rows read `error` / `not run`. Pass the flag only inside a disposable container working on a copy of
the target. The bundle is created private (`umask 077`), and `-o` refuses a directory inside the
target or owned by another account.

```
probe               axis          status  exit  bytes  lines  stderr  file                        note
git-commit-count    supply-chain  ok      0     2      1      no      out/git-commit-count.txt    see output file
git-status          supply-chain  error   -     0      0      no      -                           not run: target-supplied toolchain config can execute code — …
npm-audit           supply-chain  error   -     0      0      no      -                           not run: target-supplied toolchain config can execute code — …
dockerfile-fetches  supply-chain  ok      0     32     1      no      out/dockerfile-fetches.txt  see output file
db-clients          data-quality  n/a     -     0      0      no      -                           host container inspection is opt-in; pass --host-containers
secret-scan         security      empty   1     0      0      no      out/secret-scan.txt         the pattern matched nothing in the file types listed in env.txt. …
```

Six rows from a real run, without `--run-toolchains`, against a small Node repository whose
Dockerfile uses `FROM node:latest`; long notes are cut at `…`.
Nine columns: `stderr` says the probe wrote to stderr (`out/<probe>.err`), and `lines` over a probe's
cap adds a `TRUNCATED` note with the complete output in `out/<probe>.full.txt`. `env.txt` records
the target, host, git scope, the file types `secret-scan` read, whether toolchains ran, whether a
timeout was actually enforced, and `checker jobs`: how many `php -l` processes ran at once (one per
CPU, at least 4). Run one at a time, `php -l` over 4,607 files ran past the 120-second cap.

**The five statuses are the point.** `empty` means the probe ran and found nothing — a result, and
sometimes a finding. `error` means it could not run, so you know nothing about that area. `n/a` means
it does not apply. `output` means it exited nonzero *and* produced output — vulnerability scanners
signal findings that way, and discarding it throws away the best evidence in the bundle.

Collapsing `empty` and `error` into one silent outcome is Empty-Result Ambiguity, the first defect
class this tool exists to hunt. **v1.0.0 committed it** — seventeen probes ended in `|| true` and
physically could not report failure, so a scan of a tree it could not read came back "clean". The
`|| true` suffixes are gone. Every probe runs with `pipefail`, and a trailing filter stage cannot
replace the producer's exit, so a failing producer is a failing probe. No probe discards its stderr.
A scanner row that must hold a report (`npm-audit`, `pip-audit`) is `error` when it does not. The `stderr` column and the `TRUNCATED` note apply the same
principle: a partial read must not pass as a complete one. What it still cannot promise is listed
under *What auditor-probe does not guarantee* in `SKILL.md`.

The bundle is evidence, not findings. It tells you a port is published; whether that matters is a
judgment, and judgment is what the skill is for.

Exit codes: `0` the run completed — findings are not failures — and `2` for a usage error, a target
that does not exist, or a refused `-o`. Two runs into the same `-o` at once are not supported; one of
them can exit `1`.

## Layout

```
.claude-plugin/plugin.json                       marketplace metadata
agents/auditor.md                                the subagent — running order for the nine axes
skills/codebase-audit/SKILL.md                   method, severity matrix, finding format
src/auditor/                                     Python package
  cli.py                                         auditor-probe CLI entrypoint
  runner.py                                      orchestrator across nine axes
  bundle.py                                      bundle management, safety, and manifest writer
  models.py                                      Pydantic models and ProbeRecord
  probes/                                        probes by axis
tests/                                           pytest test suite
dev/mutations.py                                 domain-specific mutation testing suite
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
uv run pytest
```

The tests target the classification contract, because that is where a wrong answer produces a
confident false negative: a reader acts on `empty` by writing "no X found" and on `error` by writing
nothing at all. They also pin execution and exposure (no toolchain runs without the flag, no target git
config command runs, the bundle is private and outside the target) and give every probe a fixture with
something to find. No network, no docker, no fixtures outside a temp dir.

**A green run is not the evidence; mutation is.** `dev/mutations.py` defines domain-specific regression
mutations representing historical edge cases and defect boundaries. `uv run python dev/mutations.py run`
runs the pytest suite against each mutant and exits 1 if any mutant survives:

```sh
uv run python dev/mutations.py run
```

**The full run has not been completed for 1.4.x**: 156 suites take about four hours on one Mac. What
was measured, on macOS: the first 16 mutants in list order (m01–m16), where the suite before these
tests let 7 non-equivalent mutants survive, now 15 killed and 1 equivalent (m09); and 18 mutants aimed
at the v1.3.0 audit's surviving neighbours and at the new tests (m20, m21, m23, m25, m26, m28–m30,
m36, m39, m42, m55, n11, n24, n32, and `s-git-tags`, `s-published-ports`, `s-route-tables`), all
killed after one fixture fix for m23; and, for parallel `php-syntax`, n39 (one file at a time), n40
(filenames newline-delimited through `xargs`), n41 (a wrapper that `eval`s the filename), m21 and m55
again, all killed. Run `bash dev/run_mutations.sh` before citing any number beyond those.

Filenames reach `php -l` through `find -print0 | xargs -0` as `sh -c` arguments, never as shell text. A
test sends ten hostile names through the real pipeline — space, both quotes, backslash, newline,
leading `-`, `*`, `$(…)`, backticks, `;` — and checks each arrives whole, once, with nothing run, under
BSD `xargs` on macOS and GNU `xargs` in Debian. A name containing a newline still splits php's one-line
message, so the row can read `ok` with a stray line.

The `pytest` suite covers the classification contract across 37 comprehensive tests, testing
status classifications, path confinement, security gates, line capping, and secret patterns.
All 31 mutations defined in `dev/mutations.py` are killed by the suite.

Every scanner, php, shellcheck, docker and timeout in the suite is tested with stand-ins, and a stand-in pins the
classifier to the author's belief about the tool.

`${CLAUDE_PLUGIN_ROOT}` resolves to this plugin's installed copy under `~/.claude/plugins/cache/`.
Editing this repo does not change what a running session loads — run
`claude plugin marketplace update auditor` and reinstall to pick changes up.

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
