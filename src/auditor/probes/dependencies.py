"""Dependency manifest and vulnerability scanner probes."""

from __future__ import annotations

from pathlib import Path

from auditor.bundle import BundleManager
from auditor.models import ProbeAxis, ProbeOutput
from auditor.probes.base import has_command, run_command


def run_dependency_probes(
    bundle: BundleManager, target: Path, timeout: int, run_toolchains: bool
) -> None:
    """Execute dependency probes against package manifests at target root."""
    deps_found = False

    # Composer
    composer_file = target / "composer.json"
    if composer_file.is_file():
        deps_found = True
        content = composer_file.read_text(encoding="utf-8", errors="replace")
        bundle.record_probe(
            "composer-manifest", ProbeAxis.SUPPLY_CHAIN.value, ProbeOutput(0, content, "")
        )
        if not run_toolchains:
            bundle.record_gated("composer-audit", ProbeAxis.SUPPLY_CHAIN.value)
        elif has_command("composer"):
            cmd = [
                "composer",
                "audit",
                "--format=plain",
                "--no-interaction",
                "--no-plugins",
                "--no-scripts",
            ]
            out = run_command(cmd, cwd=target, timeout=timeout)
            bundle.record_probe(
                "composer-audit", ProbeAxis.SUPPLY_CHAIN.value, out, ok_exits=[0, 1, 2]
            )
        else:
            bundle.record_skip(
                "composer-audit",
                ProbeAxis.SUPPLY_CHAIN.value,
                "composer.json present but composer not on PATH",
            )

    # NPM
    package_file = target / "package.json"
    if package_file.is_file():
        deps_found = True
        content = package_file.read_text(encoding="utf-8", errors="replace")
        bundle.record_probe(
            "npm-manifest", ProbeAxis.SUPPLY_CHAIN.value, ProbeOutput(0, content, "")
        )
        if not run_toolchains:
            bundle.record_gated("npm-audit", ProbeAxis.SUPPLY_CHAIN.value)
        elif has_command("npm"):
            cmd = ["npm", "audit", "--json", "--registry=https://registry.npmjs.org/"]
            out = run_command(cmd, cwd=target, timeout=timeout)
            valid_pat = r'"(auditReportVersion|vulnerabilities)"\s*:'
            bundle.record_probe(
                "npm-audit", ProbeAxis.SUPPLY_CHAIN.value, out, ok_exits=[0, 1], valid_pat=valid_pat
            )
        else:
            bundle.record_skip(
                "npm-audit",
                ProbeAxis.SUPPLY_CHAIN.value,
                "package.json present but npm not on PATH",
            )

    # Python
    req_file = target / "requirements.txt"
    pyproject_file = target / "pyproject.toml"
    if req_file.is_file() or pyproject_file.is_file():
        deps_found = True
        if not run_toolchains:
            bundle.record_gated("pip-audit", ProbeAxis.SUPPLY_CHAIN.value)
        elif not has_command("pip-audit"):
            bundle.record_skip(
                "pip-audit",
                ProbeAxis.SUPPLY_CHAIN.value,
                "python manifest present but pip-audit not installed",
            )
        elif req_file.is_file():
            cmd = ["pip-audit", "-r", "requirements.txt", "-f", "json", "--progress-spinner", "off"]
            out = run_command(cmd, cwd=target, timeout=timeout)
            valid_pat = r'"dependencies"\s*:'
            bundle.record_probe(
                "pip-audit", ProbeAxis.SUPPLY_CHAIN.value, out, ok_exits=[0, 1], valid_pat=valid_pat
            )
        else:
            cmd = ["pip-audit", "-f", "json", "--progress-spinner", "off", "."]
            out = run_command(cmd, cwd=target, timeout=timeout)
            valid_pat = r'"dependencies"\s*:'
            bundle.record_probe(
                "pip-audit", ProbeAxis.SUPPLY_CHAIN.value, out, ok_exits=[0, 1], valid_pat=valid_pat
            )

    # Go
    go_mod = target / "go.mod"
    if go_mod.is_file():
        deps_found = True
        if not run_toolchains:
            bundle.record_gated("go-vulncheck", ProbeAxis.SUPPLY_CHAIN.value)
        elif has_command("govulncheck"):
            cmd = ["govulncheck", "./..."]
            out = run_command(cmd, cwd=target, timeout=timeout, env={"GOTOOLCHAIN": "local"})
            bundle.record_probe("go-vulncheck", ProbeAxis.SUPPLY_CHAIN.value, out, ok_exits=[0, 3])
        else:
            bundle.record_skip(
                "go-vulncheck",
                ProbeAxis.SUPPLY_CHAIN.value,
                "go.mod present but govulncheck not installed",
            )

    # Cargo
    cargo_toml = target / "Cargo.toml"
    if cargo_toml.is_file():
        deps_found = True
        if not run_toolchains:
            bundle.record_gated("cargo-audit", ProbeAxis.SUPPLY_CHAIN.value)
        elif has_command("cargo-audit"):
            cmd = ["cargo-audit", "audit"]
            out = run_command(cmd, cwd=target, timeout=timeout)
            bundle.record_probe("cargo-audit", ProbeAxis.SUPPLY_CHAIN.value, out, ok_exits=[0, 1])
        else:
            bundle.record_skip(
                "cargo-audit",
                ProbeAxis.SUPPLY_CHAIN.value,
                "Cargo.toml present but cargo-audit not installed",
            )

    # Bundler
    gemfile = target / "Gemfile"
    if gemfile.is_file():
        deps_found = True
        if not run_toolchains:
            bundle.record_gated("bundler-audit", ProbeAxis.SUPPLY_CHAIN.value)
        elif has_command("bundler-audit"):
            cmd = ["bundler-audit", "check", "--update"]
            out = run_command(cmd, cwd=target, timeout=timeout)
            bundle.record_probe("bundler-audit", ProbeAxis.SUPPLY_CHAIN.value, out, ok_exits=[0, 1])
        else:
            bundle.record_skip(
                "bundler-audit",
                ProbeAxis.SUPPLY_CHAIN.value,
                "Gemfile present but bundler-audit not installed",
            )

    if not deps_found:
        bundle.record_skip(
            "dependency-audit",
            ProbeAxis.SUPPLY_CHAIN.value,
            "no recognised package manifest at the target root",
        )
