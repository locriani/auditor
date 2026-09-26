"""Compliance probes (license files and dependency licenses)."""

from __future__ import annotations

import fnmatch
import json
from pathlib import Path

from auditor.bundle import BundleManager
from auditor.models import ProbeAxis, ProbeOutput
from auditor.probes.base import has_command, run_command

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

    # 2. dep-licenses
    has_package_json = (target / "package.json").is_file()
    if has_package_json:
        if not run_toolchains:
            bundle.record_gated("dep-licenses", ProbeAxis.COMPLIANCE.value)
        elif has_command("npm"):
            out = run_command(["npm", "ls", "--json", "--depth=0"], cwd=target, timeout=timeout)
            bundle.record_probe("dep-licenses", ProbeAxis.COMPLIANCE.value, out, ok_exits=[0, 1])
        else:
            bundle.record_skip(
                "dep-licenses",
                ProbeAxis.COMPLIANCE.value,
                "no package.json, or npm not on PATH",
            )

    # 3. cargo-licenses
    if (target / "Cargo.toml").is_file():
        if not run_toolchains:
            bundle.record_gated("cargo-licenses", ProbeAxis.COMPLIANCE.value)
        elif not (target / "Cargo.lock").is_file():
            bundle.record_skip(
                "cargo-licenses",
                ProbeAxis.COMPLIANCE.value,
                "Cargo.toml present but no Cargo.lock — not run: the licenses would be for "
                "today's resolution, not the shipped versions",
            )
        elif has_command("cargo"):
            out = run_command(
                ["cargo", "metadata", "--format-version", "1", "--locked"],
                cwd=target,
                timeout=timeout,
            )
            if out.exit_code == 0 and not out.timed_out:
                try:
                    out = ProbeOutput(0, _cargo_license_lines(out.stdout), out.stderr)
                except (ValueError, KeyError, TypeError):
                    # keep the raw output, and let the row say it is not a license list
                    out = ProbeOutput(1, out.stdout, out.stderr or "unparseable cargo metadata")
            bundle.record_probe("cargo-licenses", ProbeAxis.COMPLIANCE.value, out, cap=60)
        else:
            bundle.record_skip(
                "cargo-licenses",
                ProbeAxis.COMPLIANCE.value,
                "Cargo.toml present but cargo not on PATH",
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
