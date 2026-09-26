"""Tests for toolchain execution gates and scanner output validation."""

from __future__ import annotations

from pathlib import Path

from conftest import RunProbe


def test_toolchains_gated_by_default(temp_target: Path, run_probe: RunProbe) -> None:
    # Create all manifests
    (temp_target / "composer.json").write_text("{}", encoding="utf-8")
    (temp_target / "package.json").write_text("{}", encoding="utf-8")
    (temp_target / "requirements.txt").write_text("requests==2.0.0\n", encoding="utf-8")
    (temp_target / "go.mod").write_text("module test\n", encoding="utf-8")
    (temp_target / "Cargo.toml").write_text("[package]\nname='test'\n", encoding="utf-8")
    (temp_target / "Gemfile").write_text("source 'https://rubygems.org'\n", encoding="utf-8")
    (temp_target / "Package.resolved").write_text('{"pins": []}\n', encoding="utf-8")
    (temp_target / "Podfile.lock").write_text("PODS:\n", encoding="utf-8")

    manifest = run_probe(temp_target)

    gated_probes = [
        "composer-audit",
        "npm-audit",
        "pip-audit",
        "go-vulncheck",
        "cargo-audit",
        "cargo-licenses",
        "swift-audit",
        "cocoapods-audit",
        "bundler-audit",
        "dep-licenses",
    ]
    for p in gated_probes:
        assert manifest.status(p) == "error", f"Probe {p} should be error when gated"
        assert "target-supplied toolchain config can execute code" in manifest.note(p)

    env_text = (manifest.bundle_dir / "env.txt").read_text(encoding="utf-8")
    assert "toolchains: NOT RUN" in env_text


def test_npm_audit_enolock_is_error(
    temp_target: Path, mock_bin_dir: Path, run_probe: RunProbe
) -> None:
    (temp_target / "package.json").write_text("{}", encoding="utf-8")

    # Create mock npm that outputs ENOLOCK
    mock_npm = mock_bin_dir / "npm"
    mock_npm.write_text(
        '#!/bin/sh\nprintf \'{"error": {"code": "ENOLOCK", "summary": "No lockfile"}}\'\nexit 1\n',
        encoding="utf-8",
    )
    mock_npm.chmod(0o755)

    manifest = run_probe(temp_target, "--run-toolchains")
    assert manifest.status("npm-audit") == "error"
    assert "printed no report" in manifest.note("npm-audit")


def test_npm_audit_findings_is_ok(
    temp_target: Path, mock_bin_dir: Path, run_probe: RunProbe
) -> None:
    (temp_target / "package.json").write_text("{}", encoding="utf-8")

    # Create mock npm that outputs vulnerability report with exit 1
    mock_npm = mock_bin_dir / "npm"
    mock_npm.write_text(
        '#!/bin/sh\nprintf \'{"auditReportVersion": 2, "vulnerabilities": {"lodash": {}}}\'\nexit 1\n',
        encoding="utf-8",
    )
    mock_npm.chmod(0o755)

    manifest = run_probe(temp_target, "--run-toolchains")
    assert manifest.status("npm-audit") == "ok"


def test_host_containers_gated_by_default(
    temp_target: Path, mock_bin_dir: Path, run_probe: RunProbe
) -> None:
    # A docker stand-in that leaves a footprint whenever it runs.
    footprint = mock_bin_dir / "docker.called"
    mock_docker = mock_bin_dir / "docker"
    mock_docker.write_text(
        f"#!/bin/sh\ntouch '{footprint}'\nprintf 'web\\tUp\\tnginx\\t80/tcp\\n'\n",
        encoding="utf-8",
    )
    mock_docker.chmod(0o755)

    manifest = run_probe(temp_target)
    for p in ("docker-ps", "db-clients"):
        assert manifest.status(p) == "n/a", f"{p} must not run without --host-containers"
        assert "pass --host-containers" in manifest.note(p)
    assert not footprint.exists(), "docker ran without --host-containers"

    manifest = run_probe(temp_target, "--host-containers")
    assert footprint.exists()
    assert manifest.status("docker-ps") == "ok"
    assert "nginx" in manifest.out_content("docker-ps")
