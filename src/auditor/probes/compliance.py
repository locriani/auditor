"""Compliance probes (license files and dependency licenses)."""

from __future__ import annotations

import fnmatch
import json
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
from auditor.probes.dependencies import CARGO, NPM

LICENSE_PATTERNS = ["LICENSE*", "COPYING*", "NOTICE*"]


def run_compliance_probes(
    bundle: BundleManager,
    target: Path,
    timeout: int = 120,
    run_toolchains: bool = False,
) -> None:
    """Execute license-files, dep-licenses, and cargo-licenses probes."""
    # 1. license-files (root directory only)
    licenses: list[str] = []
    for entry in target.iterdir():
        for pat in LICENSE_PATTERNS:
            if fnmatch.fnmatch(entry.name, pat):
                licenses.append(f"./{entry.name}")
                break
    licenses.sort()
    lic_out = "\n".join(licenses) + ("\n" if licenses else "")
    bundle.record_probe("license-files", ProbeAxis.COMPLIANCE.value, ProbeOutput(0, lic_out, ""))

    # 2. dep-licenses / 3. cargo-licenses, per project anywhere in the tree
    index = manifest_index(target, NPM[0] | NPM[1] | CARGO[0] | CARGO[1])
    for proj in find_projects(index, *NPM):
        _npm_licenses(
            bundle, target / proj, project_probe("dep-licenses", proj), run_toolchains, timeout
        )
    for proj in find_projects(index, *CARGO):
        _cargo_licenses(
            bundle, target / proj, project_probe("cargo-licenses", proj), run_toolchains, timeout
        )


def _npm_licenses(
    bundle: BundleManager, d: Path, probe: str, run_toolchains: bool, timeout: int
) -> None:
    if not run_toolchains:
        bundle.record_gated(probe, ProbeAxis.COMPLIANCE.value)
    elif has_command("npm"):
        out = run_command(["npm", "ls", "--json", "--depth=0"], cwd=d, timeout=timeout)
        bundle.record_probe(probe, ProbeAxis.COMPLIANCE.value, out, ok_exits=[0, 1])
    else:
        bundle.record_skip(probe, ProbeAxis.COMPLIANCE.value, "npm not on PATH")


def _cargo_licenses(
    bundle: BundleManager, d: Path, probe: str, run_toolchains: bool, timeout: int
) -> None:
    if not run_toolchains:
        bundle.record_gated(probe, ProbeAxis.COMPLIANCE.value)
    elif not (d / "Cargo.lock").is_file():
        bundle.record_skip(
            probe,
            ProbeAxis.COMPLIANCE.value,
            "Cargo.toml present but no Cargo.lock — not run: the licenses would be for "
            "today's resolution, not the shipped versions",
        )
    elif has_command("cargo"):
        out = run_command(
            ["cargo", "metadata", "--format-version", "1", "--locked"],
            cwd=d,
            timeout=timeout,
        )
        if out.exit_code == 0 and not out.timed_out:
            try:
                out = ProbeOutput(0, _cargo_license_lines(out.stdout), out.stderr)
            except (ValueError, KeyError, TypeError):
                # keep the raw output, and let the row say it is not a license list
                out = ProbeOutput(1, out.stdout, out.stderr or "unparseable cargo metadata")
        bundle.record_probe(probe, ProbeAxis.COMPLIANCE.value, out, cap=60)
    else:
        bundle.record_skip(
            probe, ProbeAxis.COMPLIANCE.value, "Cargo.toml present but cargo not on PATH"
        )


def _cargo_license_lines(metadata_json: str) -> str:
    """One `license<TAB>crate version` line per third-party crate, grouped by license."""
    meta = json.loads(metadata_json)
    own = set(meta["workspace_members"])
    rows = []
    for pkg in meta["packages"]:
        if pkg["id"] in own:
            continue
        lic = pkg["license"] or (
            f"license-file: {pkg['license_file']}" if pkg["license_file"] else "NO LICENSE DECLARED"
        )
        rows.append(f"{lic}\t{pkg['name']} {pkg['version']}")
    rows.sort()
    return "\n".join(rows) + ("\n" if rows else "")
