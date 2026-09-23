"""Runtime probes (docker container inspection)."""

from __future__ import annotations

import subprocess
from pathlib import Path

from auditor.bundle import BundleManager
from auditor.models import ProbeAxis, ProbeOutput
from auditor.probes.base import has_command, run_command


def run_runtime_probes(
    bundle: BundleManager, target: Path, timeout: int, host_containers: bool
) -> None:
    """Execute host container runtime probes."""
    if not host_containers:
        bundle.record_skip(
            "docker-ps",
            ProbeAxis.OBSERVABILITY.value,
            "host container inspection is opt-in; pass --host-containers",
        )
        bundle.record_skip(
            "db-clients",
            ProbeAxis.DATA_QUALITY.value,
            "host container inspection is opt-in; pass --host-containers",
        )
        return

    if not has_command("docker"):
        bundle.record_skip(
            "docker-ps",
            ProbeAxis.OBSERVABILITY.value,
            "host container inspection is opt-in; pass --host-containers",
        )
        bundle.record_skip(
            "db-clients",
            ProbeAxis.DATA_QUALITY.value,
            "host container inspection is opt-in; pass --host-containers",
        )
        return

    # docker-ps
    out = run_command(
        ["docker", "ps", "--format", "{{.Names}}\t{{.Status}}\t{{.Image}}\t{{.Ports}}"],
        cwd=target,
        timeout=timeout,
    )
    bundle.record_probe("docker-ps", ProbeAxis.OBSERVABILITY.value, out)

    # db-clients
    # Check docker ps first
    ps_proc = subprocess.run(
        ["docker", "ps", "--format", "{{.Names}}"],
        cwd=target,
        capture_output=True,
        text=True,
        check=False,
    )
    if ps_proc.returncode != 0:
        db_out = ProbeOutput(
            exit_code=ps_proc.returncode,
            stdout="",
            stderr=ps_proc.stderr,
        )
        bundle.record_probe("db-clients", ProbeAxis.DATA_QUALITY.value, db_out)
        return

    containers = [c.strip() for c in ps_proc.stdout.splitlines() if c.strip()]
    if not containers:
        bundle.record_probe("db-clients", ProbeAxis.DATA_QUALITY.value, ProbeOutput(0, "", ""))
        return

    rc = 0
    stdout_lines: list[str] = []
    stderr_lines: list[str] = []
    db_binaries = ["mariadb", "mysql", "psql", "mongosh", "sqlite3", "redis-cli"]

    for c in containers:
        exec_test = subprocess.run(
            ["docker", "exec", c, "true"],
            cwd=target,
            capture_output=True,
            check=False,
        )
        if exec_test.returncode == 0:
            sh_cmd = (
                f"for b in {' '.join(db_binaries)}; do "
                "command -v $b >/dev/null 2>&1 && echo $b; "
                "done; true"
            )
            inspect_proc = subprocess.run(
                ["docker", "exec", c, "sh", "-c", sh_cmd],
                cwd=target,
                capture_output=True,
                text=True,
                check=False,
            )
            for found_bin in inspect_proc.stdout.splitlines():
                if found_bin.strip():
                    stdout_lines.append(f"{c}: {found_bin.strip()}")
        else:
            stderr_lines.append(f"{c}: docker exec failed — which clients it has is unknown")
            rc = 1

    stdout_text = "\n".join(stdout_lines) + ("\n" if stdout_lines else "")
    stderr_text = "\n".join(stderr_lines) + ("\n" if stderr_lines else "")
    bundle.record_probe(
        "db-clients",
        ProbeAxis.DATA_QUALITY.value,
        ProbeOutput(exit_code=rc, stdout=stdout_text, stderr=stderr_text),
    )
