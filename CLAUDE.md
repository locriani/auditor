# Project: auditor

A Claude Code plugin that ships the `auditor` agent (`agents/auditor.md`) and the
`codebase-audit` skill (`skills/codebase-audit/`), plus the `reviewer` agent (`agents/reviewer.md`)
and the `pr-review` skill (`skills/pr-review/`), which share its evidence discipline. It assesses a codebase somebody else
wrote, before work gets built on top of it.

**The name is provisional.** Zach, 2026-09-19: *"just call it Auditor for now."* Repo,
marketplace, and plugin id all say `auditor`; the skill keeps its functional name.

## Rules

- **Operate the system, cite what it did, name what each finding forbids.** The skill's own
  rule, and it governs this repo's development too: a claim about the probe is checked by
  running the probe, not by reading it.
- **The target is untrusted.** `auditor-probe` never executes configuration the target ships
  unless `--run-toolchains` says so, and never enumerates the host unless `--host-containers`
  does. A change that widens either default is a behaviour change, not a fix.
- **Exit status is not a verdict.** The silent-success class is what this tool hunts, so it
  is also the bug class most likely to be in the tool. `dev/mutations.py` exists to prove the
  tests fail when the code is wrong.
- **No shell scripts.** Auditor is a Python 3.11+ project managed with `uv`, strictly typed with
  `mypy`, formatted/linted with `ruff`, and tested with `pytest`. Run `uv run auditor-probe` for
  evidence collection, `uv run pytest` for tests, and `uv run python dev/mutations.py run` for
  mutation testing.
- **Referenced from `~/Developer/ai-additions`** (`SETUP-LIST.md`, Referenced table). That
  repo's approval gate governs enabling; this one holds the code.

## Install

```sh
claude plugin marketplace add ~/Developer/auditor
claude plugin install auditor@auditor
```

The installed copy is a version-stamped snapshot under `~/.claude/plugins/cache/`. Editing
this tree does not change what a running session loads — that takes
`claude plugin marketplace update auditor` and a reinstall.
