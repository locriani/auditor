"""Tests for Git provenance probes and worktree detection."""

from __future__ import annotations

import subprocess
from pathlib import Path

from conftest import RunProbe


def init_git_repo(target: Path) -> None:
    subprocess.run(["git", "init", "-b", "main"], cwd=target, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Audit Test"], cwd=target, check=True)
    subprocess.run(["git", "config", "user.email", "audit@test.local"], cwd=target, check=True)
    (target / "README.md").write_text("# Test Repo\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=target, check=True)
    subprocess.run(
        ["git", "commit", "-m", "Initial commit"], cwd=target, check=True, capture_output=True
    )


def test_git_repo_root_detection(temp_target: Path, run_probe: RunProbe) -> None:
    init_git_repo(temp_target)

    manifest = run_probe(temp_target)
    assert manifest.status("git-commit-count") == "ok"
    assert manifest.out_content("git-commit-count").strip() == "1"

    env_text = (manifest.bundle_dir / "env.txt").read_text(encoding="utf-8")
    assert "git scope:  repo root" in env_text

    # git-status must be gated by default
    assert manifest.status("git-status") == "error"
    assert "target-supplied toolchain config can execute code" in manifest.note("git-status")


def test_git_status_runs_with_toolchains(temp_target: Path, run_probe: RunProbe) -> None:
    init_git_repo(temp_target)

    manifest = run_probe(temp_target, "--run-toolchains")
    # git-status should run and be empty (clean worktree)
    assert manifest.status("git-status") == "empty"


def test_git_subdirectory_scope(temp_target: Path, run_probe: RunProbe) -> None:
    init_git_repo(temp_target)
    subdir = temp_target / "packages" / "subpkg"
    subdir.mkdir(parents=True)
    (subdir / "file.txt").write_text("content", encoding="utf-8")

    manifest = run_probe(subdir)
    env_text = (manifest.bundle_dir / "env.txt").read_text(encoding="utf-8")
    assert "git scope:  subdirectory of" in env_text
