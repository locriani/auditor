"""Compliance probes (license files and dependency licenses)."""

from __future__ import annotations

import fnmatch
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
    """Execute license-files and dep-licenses probes."""
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
