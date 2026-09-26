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
        content = cargo_toml.read_text(encoding="utf-8", errors="replace")
        bundle.record_probe(
            "cargo-manifest", ProbeAxis.SUPPLY_CHAIN.value, ProbeOutput(0, content, "")
        )
        if not run_toolchains:
            bundle.record_gated("cargo-audit", ProbeAxis.SUPPLY_CHAIN.value)
        elif not (target / "Cargo.lock").is_file():
            # cargo-audit would run `cargo generate-lockfile`: it writes into the target and
            # audits versions resolved today, not the ones the target ships.
            bundle.record_skip(
                "cargo-audit",
                ProbeAxis.SUPPLY_CHAIN.value,
                "Cargo.toml present but no Cargo.lock — not run: cargo-audit would generate one "
                "in the target and audit today's resolution, not the shipped versions",
            )
        elif has_command("cargo-audit"):
            cmd = ["cargo-audit", "audit", "--json"]
            out = run_command(cmd, cwd=target, timeout=timeout)
            # exit 1 is both "vulnerabilities found" and "could not load Cargo.lock"
            valid_pat = r'"vulnerabilities"\s*:'
            bundle.record_probe(
                "cargo-audit",
                ProbeAxis.SUPPLY_CHAIN.value,
                out,
                ok_exits=[0, 1],
                valid_pat=valid_pat,
            )
        else:
            bundle.record_skip(
                "cargo-audit",
                ProbeAxis.SUPPLY_CHAIN.value,
                "Cargo.toml present but cargo-audit not installed",
            )

    # Swift: Package.swift is Swift code SwiftPM compiles and runs to resolve, so it is only
    # read. trivy scans the pins in Package.resolved and Podfile.lock against GHSA.
    swift_files = {
        "swiftpm-manifest": "Package.swift",
        "swiftpm-resolved": "Package.resolved",
        "cocoapods-lockfile": "Podfile.lock",
    }
    for probe, fname in swift_files.items():
        path = target / fname
        if path.is_file():
            deps_found = True
            content = path.read_text(encoding="utf-8", errors="replace")
            bundle.record_probe(probe, ProbeAxis.SUPPLY_CHAIN.value, ProbeOutput(0, content, ""))

    swift_scans = {"swift-audit": "Package.resolved", "cocoapods-audit": "Podfile.lock"}
    for probe, fname in swift_scans.items():
        path = target / fname
        if not path.is_file():
            if probe == "swift-audit" and (target / "Package.swift").is_file():
                bundle.record_skip(
                    probe,
                    ProbeAxis.SUPPLY_CHAIN.value,
                    "Package.swift present but no Package.resolved — not run: the pins are "
                    "unknown, and resolving them executes Package.swift",
                )
            continue
        if not run_toolchains:
            bundle.record_gated(probe, ProbeAxis.SUPPLY_CHAIN.value)
        elif has_command("trivy"):
            cmd = [
                "trivy",
                "fs",
                "--scanners",
                "vuln",
                "--pkg-types",
                "library",
                "--format",
                "json",
                "--skip-version-check",
                "--quiet",
                str(path.resolve()),
            ]
            # trivy reads trivy.yaml and .trivyignore from its cwd; one shipped by the target
            # can hide every finding, so it runs from the bundle directory.
            out = run_command(cmd, cwd=bundle.bundle_dir, timeout=timeout)
            # an unparseable lockfile still exits 0 with a report, but one with no Results
            valid_pat = r'"Results"\s*:'
            bundle.record_probe(probe, ProbeAxis.SUPPLY_CHAIN.value, out, valid_pat=valid_pat)
        else:
            bundle.record_skip(
                probe,
                ProbeAxis.SUPPLY_CHAIN.value,
                f"{fname} present but trivy not installed — Swift dependencies were NOT "
                "checked for known vulnerabilities",
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
