"""Additional edge case tests ported from test_probe.sh."""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import RunProbe


def test_secret_scan_file_types_and_minified(temp_target: Path, run_probe: RunProbe) -> None:
    # Minified files and lockfiles should be excluded
    (temp_target / "app.min.js").write_text('api_key = "secret_in_minified";\n', encoding="utf-8")
    (temp_target / "package-lock.json").write_text(
        '{"token": "secret_in_lockfile"}\n', encoding="utf-8"
    )
    (temp_target / "app.map").write_text('api_key = "secret_in_map";\n', encoding="utf-8")

    manifest = run_probe(temp_target)
    assert manifest.status("secret-scan") == "empty"

    # Valid supported file types: .env, .php, .toml, .tf, .sh, .py, Dockerfile
    (temp_target / "deploy.tf").write_text('token = "secret_in_tf1234";\n', encoding="utf-8")
    manifest = run_probe(temp_target)
    assert manifest.status("secret-scan") == "ok"
    assert "secret_in_tf1234" in manifest.out_content("secret-scan")


def test_git_log_truncation(temp_target: Path, run_probe: RunProbe) -> None:
    # Create git repo with 45 commits
    import subprocess

    subprocess.run(["git", "init", "-b", "main"], cwd=temp_target, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=temp_target, check=True)
    subprocess.run(["git", "config", "user.email", "test@test.local"], cwd=temp_target, check=True)

    for i in range(45):
        (temp_target / "commit.txt").write_text(f"commit {i}\n", encoding="utf-8")
        subprocess.run(["git", "add", "commit.txt"], cwd=temp_target, check=True)
        subprocess.run(
            ["git", "commit", "-m", f"commit {i}"], cwd=temp_target, check=True, capture_output=True
        )

    manifest = run_probe(temp_target)
    assert manifest.status("git-log") == "ok"
    assert "TRUNCATED: 40 of" in manifest.note("git-log")
    assert (manifest.bundle_dir / "out" / "git-log.full.txt").is_file()


def test_timeout_execution(
    temp_target: Path, monkeypatch: pytest.MonkeyPatch, run_probe: RunProbe
) -> None:
    # Test that a probe that hangs hits the timeout and classifies as error
    import auditor.probes.git as git_probe
    from auditor.models import ProbeOutput

    def mock_run_command(*args: object, **kwargs: object) -> ProbeOutput:
        return ProbeOutput(exit_code=124, stdout="", stderr="", timed_out=True)

    monkeypatch.setattr(git_probe, "run_command", mock_run_command)

    # Make target a git repo so git probes run
    import subprocess

    subprocess.run(["git", "init", "-b", "main"], cwd=temp_target, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=temp_target, check=True)
    subprocess.run(["git", "config", "user.email", "test@test.local"], cwd=temp_target, check=True)
    (temp_target / "file.txt").write_text("ok", encoding="utf-8")
    subprocess.run(["git", "add", "file.txt"], cwd=temp_target, check=True)
    subprocess.run(
        ["git", "commit", "-m", "init"], cwd=temp_target, check=True, capture_output=True
    )

    manifest = run_probe(temp_target, "--timeout", "1")
    assert manifest.status("git-remotes") == "error"
    assert "TIMED OUT" in manifest.note("git-remotes")
