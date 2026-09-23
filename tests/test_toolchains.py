"""Tests for toolchain execution gates and scanner output validation."""

from __future__ import annotations

from pathlib import Path


def test_toolchains_gated_by_default(temp_target: Path, run_probe) -> None:
    # Create all manifests
    (temp_target / "composer.json").write_text("{}", encoding="utf-8")
    (temp_target / "package.json").write_text("{}", encoding="utf-8")
    (temp_target / "requirements.txt").write_text("requests==2.0.0\n", encoding="utf-8")
    (temp_target / "go.mod").write_text("module test\n", encoding="utf-8")
    (temp_target / "Cargo.toml").write_text("[package]\nname='test'\n", encoding="utf-8")
    (temp_target / "Gemfile").write_text("source 'https://rubygems.org'\n", encoding="utf-8")

    manifest = run_probe(temp_target)

    gated_probes = [
        "composer-audit",
        "npm-audit",
        "pip-audit",
        "go-vulncheck",
        "cargo-audit",
        "bundler-audit",
        "dep-licenses",
    ]
    for p in gated_probes:
        assert manifest.status(p) == "error", f"Probe {p} should be error when gated"
        assert "target-supplied toolchain config can execute code" in manifest.note(p)

    env_text = (manifest.bundle_dir / "env.txt").read_text(encoding="utf-8")
    assert "toolchains: NOT RUN" in env_text


def test_npm_audit_enolock_is_error(temp_target: Path, mock_bin_dir: Path, run_probe) -> None:
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


def test_npm_audit_findings_is_ok(temp_target: Path, mock_bin_dir: Path, run_probe) -> None:
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
