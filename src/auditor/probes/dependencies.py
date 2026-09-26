"""Dependency manifest and vulnerability scanner probes.

Every ecosystem is audited wherever its manifest sits in the tree, one row per project:
`npm-audit` for the target root, `npm-audit@packages/web` for a nested one.
"""

from __future__ import annotations

import json
import shutil
import tempfile
from collections.abc import Callable
from pathlib import Path

from auditor.bundle import BundleManager
from auditor.models import ProbeAxis, ProbeOutput
from auditor.probes.base import (
    find_projects,
    has_command,
    manifest_index,
    project_probe,
    run_command,
)

AXIS = ProbeAxis.SUPPLY_CHAIN.value

# (manifests, locks): a directory holding a manifest is a project unless it has no lock of
# its own and sits inside another project, whose lock then pins it.
COMPOSER = ({"composer.json"}, {"composer.lock"})
NPM = (
    {"package.json"},
    {"package-lock.json", "npm-shrinkwrap.json", "yarn.lock", "pnpm-lock.yaml"},
)
PYTHON = ({"requirements.txt", "pyproject.toml"}, {"requirements.txt", "uv.lock", "poetry.lock"})
GO = ({"go.mod"}, {"go.sum"})
CARGO = ({"Cargo.toml"}, {"Cargo.lock"})
SWIFT = (
    {"Package.swift", "Package.resolved", "Podfile.lock"},
    {"Package.resolved", "Podfile.lock"},
)
RUBY = ({"Gemfile"}, {"Gemfile.lock"})
ECOSYSTEMS = (COMPOSER, NPM, PYTHON, GO, CARGO, SWIFT, RUBY)
MANIFEST_NAMES = set().union(*(m | locks for m, locks in ECOSYSTEMS))


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _scanner(
    bundle: BundleManager,
    probe: str,
    run_toolchains: bool,
    tool: str,
    missing: str,
    run: Callable[[], None],
    not_run: str | None = None,
) -> None:
    """Gate, then refuse on `not_run`, then skip when `tool` is absent, else `run`."""
    if not run_toolchains:
        bundle.record_gated(probe, AXIS)
    elif not_run:
        bundle.record_skip(probe, AXIS, not_run)
    elif not has_command(tool):
        bundle.record_skip(probe, AXIS, missing)
    else:
        run()


def run_dependency_probes(
    bundle: BundleManager, target: Path, timeout: int, run_toolchains: bool
) -> None:
    """Execute dependency probes against every package manifest in the target."""
    index = manifest_index(target, MANIFEST_NAMES)
    composer, npm, python, go, cargo, swift, ruby = (find_projects(index, *e) for e in ECOSYSTEMS)

    with tempfile.TemporaryDirectory(dir=bundle.bundle_dir) as tmp:
        work = Path(tmp)
        for n, proj in enumerate(composer):
            _composer(bundle, target / proj, proj, run_toolchains, timeout, work / f"c{n}")
        for proj in npm:
            _npm(bundle, target / proj, proj, run_toolchains, timeout)
        for proj in python:
            _python(bundle, target / proj, proj, run_toolchains, timeout)
        for proj in go:
            _go(bundle, target / proj, proj, run_toolchains, timeout)
        for proj in cargo:
            _cargo(bundle, target / proj, proj, run_toolchains, timeout)
        for proj in swift:
            _swift(bundle, target / proj, proj, run_toolchains, timeout)
        for proj in ruby:
            _ruby(bundle, target / proj, proj, run_toolchains, timeout, work)

    if not any((composer, npm, python, go, cargo, swift, ruby)):
        bundle.record_skip(
            "dependency-audit", AXIS, "no recognised package manifest anywhere in the target"
        )


def _composer(
    bundle: BundleManager, d: Path, proj: Path, run_toolchains: bool, timeout: int, work: Path
) -> None:
    manifest = _read(d / "composer.json")
    bundle.record_probe(
        project_probe("composer-manifest", proj), AXIS, ProbeOutput(0, manifest, "")
    )
    probe = project_probe("composer-audit", proj)

    def run() -> None:
        # composer.json's config.policy.advisories.ignore hid all 14 advisories in a real
        # run, and no flag overrides it, so the audit reads a copy without the config block.
        work.mkdir()
        try:
            data = json.loads(manifest)
            if isinstance(data, dict):
                data.pop("config", None)
            manifest_copy = json.dumps(data)
        except ValueError:
            manifest_copy = manifest
        (work / "composer.json").write_text(manifest_copy, encoding="utf-8")
        shutil.copyfile(d / "composer.lock", work / "composer.lock")
        cmd = [
            "composer",
            "audit",
            "--locked",
            "--format=json",
            "--no-interaction",
            "--no-plugins",
            "--no-scripts",
        ]
        out = run_command(cmd, cwd=work, timeout=timeout)
        bundle.record_probe(probe, AXIS, out, ok_exits=[0, 1, 2, 3], valid_pat=r'"advisories"\s*:')

    not_run = None
    if not (d / "composer.lock").is_file():
        not_run = (
            "composer.json present but no composer.lock — not run: without a lock, composer "
            "audits installed packages, not the versions that ship"
        )
    _scanner(
        bundle,
        probe,
        run_toolchains,
        "composer",
        "composer.json present but composer not on PATH",
        run,
        not_run,
    )


def _npm(bundle: BundleManager, d: Path, proj: Path, run_toolchains: bool, timeout: int) -> None:
    bundle.record_probe(
        project_probe("npm-manifest", proj), AXIS, ProbeOutput(0, _read(d / "package.json"), "")
    )
    probe = project_probe("npm-audit", proj)

    def run() -> None:
        cmd = ["npm", "audit", "--json", "--registry=https://registry.npmjs.org/"]
        out = run_command(cmd, cwd=d, timeout=timeout)
        valid_pat = r'"(auditReportVersion|vulnerabilities)"\s*:'
        bundle.record_probe(probe, AXIS, out, ok_exits=[0, 1], valid_pat=valid_pat)

    _scanner(bundle, probe, run_toolchains, "npm", "package.json present but npm not on PATH", run)


def _python(bundle: BundleManager, d: Path, proj: Path, run_toolchains: bool, timeout: int) -> None:
    probe = project_probe("pip-audit", proj)

    def run() -> None:
        if (d / "requirements.txt").is_file():
            cmd = ["pip-audit", "-r", "requirements.txt", "-f", "json", "--progress-spinner", "off"]
        else:
            cmd = ["pip-audit", "-f", "json", "--progress-spinner", "off", "."]
        out = run_command(cmd, cwd=d, timeout=timeout)
        valid_pat = r'"dependencies"\s*:'
        bundle.record_probe(probe, AXIS, out, ok_exits=[0, 1], valid_pat=valid_pat)

    _scanner(
        bundle,
        probe,
        run_toolchains,
        "pip-audit",
        "python manifest present but pip-audit not installed",
        run,
    )


def _go(bundle: BundleManager, d: Path, proj: Path, run_toolchains: bool, timeout: int) -> None:
    probe = project_probe("go-vulncheck", proj)

    def run() -> None:
        cmd = ["govulncheck", "-format", "json", "./..."]
        out = run_command(cmd, cwd=d, timeout=timeout, env={"GOTOOLCHAIN": "local"})
        # a go.mod that fails to load still prints the config header; SBOM follows only a
        # successful package load. JSON mode exits 0 whatever it finds.
        bundle.record_probe(probe, AXIS, out, valid_pat=r'"SBOM"\s*:')

    _scanner(
        bundle,
        probe,
        run_toolchains,
        "govulncheck",
        "go.mod present but govulncheck not installed",
        run,
    )


def _cargo(bundle: BundleManager, d: Path, proj: Path, run_toolchains: bool, timeout: int) -> None:
    bundle.record_probe(
        project_probe("cargo-manifest", proj), AXIS, ProbeOutput(0, _read(d / "Cargo.toml"), "")
    )
    probe = project_probe("cargo-audit", proj)

    def run() -> None:
        out = run_command(["cargo-audit", "audit", "--json"], cwd=d, timeout=timeout)
        # exit 1 is both "vulnerabilities found" and "could not load Cargo.lock"
        valid_pat = r'"vulnerabilities"\s*:'
        bundle.record_probe(probe, AXIS, out, ok_exits=[0, 1], valid_pat=valid_pat)

    not_run = None
    if not (d / "Cargo.lock").is_file():
        # cargo-audit would run `cargo generate-lockfile`: it writes into the target and
        # audits versions resolved today, not the ones the target ships.
        not_run = (
            "Cargo.toml present but no Cargo.lock — not run: cargo-audit would generate one "
            "in the target and audit today's resolution, not the shipped versions"
        )
    _scanner(
        bundle,
        probe,
        run_toolchains,
        "cargo-audit",
        "Cargo.toml present but cargo-audit not installed",
        run,
        not_run,
    )


def _swift(bundle: BundleManager, d: Path, proj: Path, run_toolchains: bool, timeout: int) -> None:
    # Package.swift is Swift code SwiftPM compiles and runs to resolve, so it is only read;
    # trivy scans the pins in Package.resolved and Podfile.lock against GHSA.
    rows = {
        "swiftpm-manifest": "Package.swift",
        "swiftpm-resolved": "Package.resolved",
        "cocoapods-lockfile": "Podfile.lock",
    }
    for name, fname in rows.items():
        if (d / fname).is_file():
            bundle.record_probe(
                project_probe(name, proj), AXIS, ProbeOutput(0, _read(d / fname), "")
            )

    for name, fname in {
        "swift-audit": "Package.resolved",
        "cocoapods-audit": "Podfile.lock",
    }.items():
        probe = project_probe(name, proj)
        path = d / fname
        if not path.is_file():
            if name == "swift-audit" and (d / "Package.swift").is_file():
                bundle.record_skip(
                    probe,
                    AXIS,
                    "Package.swift present but no Package.resolved — not run: the pins are "
                    "unknown, and resolving them executes Package.swift",
                )
            continue

        def run(probe: str = probe, path: Path = path) -> None:
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
            bundle.record_probe(probe, AXIS, out, valid_pat=r'"Results"\s*:')

        _scanner(
            bundle,
            probe,
            run_toolchains,
            "trivy",
            f"{fname} present but trivy not installed — Swift dependencies were NOT checked "
            "for known vulnerabilities",
            run,
        )


def _ruby(
    bundle: BundleManager, d: Path, proj: Path, run_toolchains: bool, timeout: int, work: Path
) -> None:
    probe = project_probe("bundler-audit", proj)

    def run() -> None:
        # bundler-audit reads .bundler-audit.yml from the audited directory, and a target's
        # ignore list hid advisories in a real run; an explicit empty config overrides it.
        config = work / "bundler-audit.yml"
        config.write_text("--- {}\n", encoding="utf-8")
        cmd = ["bundler-audit", "check", "--update", "--format", "json", "--config", str(config)]
        out = run_command(cmd, cwd=d, timeout=timeout)
        bundle.record_probe(probe, AXIS, out, ok_exits=[0, 1], valid_pat=r'"results"\s*:')

    not_run = None
    lock = d / "Gemfile.lock"
    if not lock.is_file():
        not_run = "Gemfile present but no Gemfile.lock — not run: bundler-audit needs the lock"
    elif "specs:" not in _read(lock):
        # a garbage Gemfile.lock exits 0 with "No vulnerabilities found" and an empty report
        not_run = (
            "Gemfile.lock lists no gems (no specs: section) — not run: bundler-audit reports "
            "an unreadable lock as clean"
        )
    _scanner(
        bundle,
        probe,
        run_toolchains,
        "bundler-audit",
        "Gemfile present but bundler-audit not installed",
        run,
        not_run,
    )
