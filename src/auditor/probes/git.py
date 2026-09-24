"""Git provenance probes for auditor."""

from __future__ import annotations

import collections
import subprocess
from pathlib import Path

from auditor.bundle import BundleManager
from auditor.models import ProbeAxis, ProbeOutput
from auditor.probes.base import has_command, run_command

GIT_BASE_CMD = ["git", "-c", "core.fsmonitor=false", "-c", "log.showSignature=false"]


def check_git_worktree(target: Path) -> tuple[bool, str | None]:
    """Check if target is inside a git work tree and determine git scope."""
    if not has_command("git"):
        return False, None
    try:
        res = subprocess.run(
            [*GIT_BASE_CMD, "rev-parse", "--is-inside-work-tree"],
            cwd=target,
            capture_output=True,
            text=True,
            check=False,
        )
        if res.returncode != 0:
            return False, None

        root_res = subprocess.run(
            [*GIT_BASE_CMD, "rev-parse", "--show-toplevel"],
            cwd=target,
            capture_output=True,
            text=True,
            check=False,
        )
        if root_res.returncode == 0:
            git_root = Path(root_res.stdout.strip()).resolve()
            target_resolved = target.resolve()
            if git_root == target_resolved:
                return True, "repo root"
            return True, f"subdirectory of {git_root}"
        return True, "unknown"
    except Exception:
        return False, None


def run_git_probes(
    bundle: BundleManager, target: Path, timeout: int, run_toolchains: bool
) -> str | None:
    """Execute git probes and record results in bundle.

    Returns git_scope string if inside git work tree, else None.
    """
    is_git, git_scope = check_git_worktree(target)

    if not is_git:
        git_probes = [
            "git-remotes",
            "git-log",
            "git-commit-count",
            "git-authors",
            "git-status",
            "git-staged",
            "git-untracked",
            "git-tracked",
            "git-tags",
            "git-submodules",
        ]
        for p in git_probes:
            bundle.record_skip(
                p, ProbeAxis.SUPPLY_CHAIN.value, "not inside a git work tree, or git not installed"
            )
        bundle.record_skip("git-churn", ProbeAxis.CODE_QUALITY.value, "no git history to mine")
        return None

    # git-remotes
    out = run_command([*GIT_BASE_CMD, "remote", "-v"], cwd=target, timeout=timeout)
    bundle.record_probe("git-remotes", ProbeAxis.SUPPLY_CHAIN.value, out)

    # git-log (cap 40, requests 41)
    out = run_command(
        [*GIT_BASE_CMD, "log", "--oneline", "-41", "--", "."], cwd=target, timeout=timeout
    )
    bundle.record_probe("git-log", ProbeAxis.SUPPLY_CHAIN.value, out, ok_exits=[0], cap=40)

    # git-commit-count
    out = run_command(
        [*GIT_BASE_CMD, "rev-list", "--count", "HEAD", "--", "."], cwd=target, timeout=timeout
    )
    bundle.record_probe("git-commit-count", ProbeAxis.SUPPLY_CHAIN.value, out)

    # git-authors
    out = run_command(
        [*GIT_BASE_CMD, "shortlog", "-sne", "HEAD", "--", "."], cwd=target, timeout=timeout
    )
    bundle.record_probe("git-authors", ProbeAxis.SUPPLY_CHAIN.value, out)

    # git-status
    if run_toolchains:
        out = run_command(
            [*GIT_BASE_CMD, "status", "--short", "--", "."], cwd=target, timeout=timeout
        )
        bundle.record_probe("git-status", ProbeAxis.SUPPLY_CHAIN.value, out)
    else:
        bundle.record_gated("git-status", ProbeAxis.SUPPLY_CHAIN.value)

    # git-staged
    out = run_command(
        [*GIT_BASE_CMD, "diff-index", "--cached", "--name-status", "HEAD", "--", "."],
        cwd=target,
        timeout=timeout,
    )
    bundle.record_probe("git-staged", ProbeAxis.SUPPLY_CHAIN.value, out, ok_exits=[0], cap=40)

    # git-untracked
    out = run_command(
        [*GIT_BASE_CMD, "ls-files", "--others", "--exclude-standard", "--", "."],
        cwd=target,
        timeout=timeout,
    )
    bundle.record_probe("git-untracked", ProbeAxis.SUPPLY_CHAIN.value, out, ok_exits=[0], cap=40)

    # git-tracked
    out = run_command([*GIT_BASE_CMD, "ls-files", "--", "."], cwd=target, timeout=timeout)
    bundle.record_probe("git-tracked", ProbeAxis.SUPPLY_CHAIN.value, out, ok_exits=[0], cap=40)

    # git-tags
    out = run_command([*GIT_BASE_CMD, "tag", "--list"], cwd=target, timeout=timeout)
    bundle.record_probe("git-tags", ProbeAxis.SUPPLY_CHAIN.value, out, ok_exits=[0], cap=40)

    # git-submodules
    submodules_file = target / ".gitmodules"
    if submodules_file.is_file():
        out = ProbeOutput(
            exit_code=0,
            stdout=submodules_file.read_text(encoding="utf-8", errors="replace"),
            stderr="",
        )
    else:
        out = ProbeOutput(exit_code=1, stdout="", stderr="")
    bundle.record_probe("git-submodules", ProbeAxis.SUPPLY_CHAIN.value, out, ok_exits=[0, 1])

    # git-churn
    log_out = run_command(
        [*GIT_BASE_CMD, "log", "--format=format:", "--name-only", "--", "."],
        cwd=target,
        timeout=timeout,
    )
    if log_out.exit_code == 0:
        counts: collections.Counter[str] = collections.Counter()
        for line in log_out.stdout.splitlines():
            name = line.strip()
            if name:
                counts[name] += 1
        lines = [f"{count:>7} {fname}" for fname, count in counts.most_common()]
        churn_text = "\n".join(lines) + ("\n" if lines else "")
        churn_out = ProbeOutput(exit_code=0, stdout=churn_text, stderr=log_out.stderr)
    else:
        churn_out = log_out
    bundle.record_probe(
        "git-churn", ProbeAxis.CODE_QUALITY.value, churn_out, ok_exits=[0, 1], cap=25
    )

    return git_scope
