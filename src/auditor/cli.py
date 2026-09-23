"""Auditor CLI entry point using Typer."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Annotated

import typer

from auditor.runner import AuditRunner

app = typer.Typer(
    name="auditor-probe",
    help="One-pass evidence collection for a codebase audit.",
    add_completion=False,
)


def validate_timeout(timeout_str: str) -> int:
    """Validate timeout string matching probe.sh rules."""
    cleaned = timeout_str.strip()
    if not cleaned or not cleaned.isdigit():
        sys.stderr.write(f"invalid --timeout: '{timeout_str}' (whole seconds, or 0 to disable)\n")
        sys.exit(2)

    # Strip leading zeros
    stripped = cleaned.lstrip("0") or "0"
    if len(stripped) > 6:
        sys.stderr.write("invalid --timeout: more than 999999 seconds\n")
        sys.exit(2)

    return int(stripped)


@app.command()
def main(
    target: Annotated[
        str | None,
        typer.Argument(
            help="Target directory to audit.",
            metavar="<target-dir>",
        ),
    ] = None,
    output: Annotated[
        str | None,
        typer.Option(
            "-o",
            "--output",
            help="New or empty directory you own outside the target, or a bundle created before.",
            metavar="<dir>",
        ),
    ] = None,
    run_toolchains: Annotated[
        bool,
        typer.Option(
            "--run-toolchains",
            help="Also run dependency scanners (composer, npm, pip-audit, govulncheck, cargo-audit, bundler-audit).",
        ),
    ] = False,
    host_containers: Annotated[
        bool,
        typer.Option(
            "--host-containers",
            help="Also inspect running containers on this host (off by default).",
        ),
    ] = False,
    timeout: Annotated[
        str,
        typer.Option(
            "--timeout",
            help="Whole seconds per probe, default 120, 0 disables.",
            metavar="N",
        ),
    ] = "120",
) -> None:
    """Run one-pass evidence collection across 9 axes on <target-dir>."""
    if target is None:
        sys.stderr.write(
            "probe.sh <target-dir> [-o <bundle-dir>] [--run-toolchains] [--host-containers] [--timeout N]\n"
        )
        sys.exit(2)

    target_path = Path(target)
    if not target_path.exists() or not target_path.is_dir():
        sys.stderr.write(f"not a directory: {target}\n")
        sys.exit(2)

    timeout_seconds = validate_timeout(timeout)
    bundle_path = Path(output) if output else None

    try:
        runner = AuditRunner(
            target_dir=target_path,
            bundle_dir=bundle_path,
            run_toolchains=run_toolchains,
            host_containers=host_containers,
            timeout=timeout_seconds,
        )
        final_bundle = runner.run()

        # Print summary to stderr
        summary_text = (final_bundle / "summary.txt").read_text(encoding="utf-8")
        sys.stderr.write(summary_text)

        # Print bundle path to stdout
        sys.stdout.write(f"{final_bundle}\n")
        sys.exit(0)
    except SystemExit:
        raise
    except Exception as e:
        sys.stderr.write(f"error: {e}\n")
        sys.exit(1)


if __name__ == "__main__":
    app()
