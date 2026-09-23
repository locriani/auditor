"""Bundle directory management, safety gates, and manifest generation."""

from __future__ import annotations

import datetime
import os
import platform
import re
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Literal

from auditor.models import ProbeOutput, ProbeRecord, ProbeStatus

MARKER = ".codebase-audit-bundle"
MARKER_TEXT = "created by codebase-audit probe.sh; safe for probe.sh to clear on reuse\n"

MANIFEST_HEADER = "probe\taxis\tstatus\texit\tbytes\tlines\tstderr\tfile\tnote\n"


def resolve_canonical_path(path: Path) -> Path:
    """Resolve symlinks through the deepest ancestor that exists."""
    p = path.resolve() if path.is_absolute() else (Path.cwd() / path).resolve()
    # If path exists, resolve fully
    if p.exists():
        return p.resolve()
    # Otherwise climb to existing ancestor
    parts: list[str] = []
    curr = p
    while not curr.exists() and curr != curr.parent:
        parts.insert(0, curr.name)
        curr = curr.parent
    return curr.resolve().joinpath(*parts)


class BundleManager:
    def __init__(
        self,
        target_dir: Path,
        bundle_dir: Path | None = None,
        timeout: int = 120,
        run_toolchains: bool = False,
        host_containers: bool = False,
        checker_jobs: int = 4,
    ) -> None:
        self.target_dir = target_dir.resolve()
        self.requested_bundle_dir = bundle_dir
        self.timeout = timeout
        self.run_toolchains = run_toolchains
        self.host_containers = host_containers
        self.checker_jobs = checker_jobs

        self.bundle_dir = self._init_bundle_dir(bundle_dir)
        self.out_dir = self.bundle_dir / "out"
        self.manifest_file = self.bundle_dir / "manifest.tsv"
        self.env_file = self.bundle_dir / "env.txt"
        self.summary_file = self.bundle_dir / "summary.txt"

        self.records: list[ProbeRecord] = []

    def _init_bundle_dir(self, requested: Path | None) -> Path:
        """Validate and initialize bundle directory with strict safety checks."""
        os.umask(0o077)

        if requested is None:
            ts = datetime.datetime.now(datetime.UTC).strftime("%Y%m%d-%H%M%S")
            prefix = f"codebase-audit-{self.target_dir.name}-{ts}."
            tmp_root = os.environ.get("TMPDIR", "/tmp")
            bundle_path = Path(tempfile.mkdtemp(prefix=prefix, dir=tmp_root))
        else:
            bundle_path = (
                requested.resolve()
                if requested.is_absolute()
                else (Path.cwd() / requested).resolve()
            )

        if bundle_path.exists() and not bundle_path.is_dir():
            sys.stderr.write(
                f"refusing: bundle path exists and is not a directory: {bundle_path}\n"
            )
            sys.exit(2)

        resolved_target = str(resolve_canonical_path(self.target_dir))
        resolved_bundle = str(resolve_canonical_path(bundle_path))

        # Check if bundle is inside target or target is bundle
        if resolved_bundle == resolved_target or resolved_bundle.startswith(
            resolved_target + os.sep
        ):
            sys.stderr.write(
                f"refusing: bundle {bundle_path} is inside the target {self.target_dir}. Nothing was modified.\n"
            )
            sys.exit(2)

        if bundle_path.exists():
            stat_info = bundle_path.stat()
            # Check ownership (unless root)
            if hasattr(os, "getuid") and os.getuid() != 0 and stat_info.st_uid != os.getuid():
                sys.stderr.write(
                    f"refusing: {bundle_path} is owned by another account. Nothing was modified.\n"
                )
                sys.exit(2)

            # Check if directory has contents
            has_entries = any(bundle_path.iterdir())
            marker_file = bundle_path / MARKER
            if has_entries:
                if not marker_file.is_file():
                    sys.stderr.write(
                        f"refusing: {bundle_path} is not empty and was not created by probe.sh\n"
                        f"          (no {MARKER} marker). Nothing was modified. Choose an empty\n"
                        f"          or new directory for -o.\n"
                    )
                    sys.exit(2)
                # Safe reuse: clear out/ directory
                out_dir = bundle_path / "out"
                if out_dir.exists():
                    shutil.rmtree(out_dir)
        else:
            bundle_path.mkdir(parents=True, exist_ok=True)

        os.chmod(bundle_path, 0o700)
        (bundle_path / "out").mkdir(parents=True, exist_ok=True)
        (bundle_path / MARKER).write_text(MARKER_TEXT, encoding="utf-8")

        # Initialize manifest
        (bundle_path / "manifest.tsv").write_text(MANIFEST_HEADER, encoding="utf-8")
        return bundle_path

    def write_env(self, secret_globs: str, git_scope: str | None = None) -> None:
        """Write env.txt metadata."""
        uname_str = f"{platform.system()} {platform.release()} {platform.machine()}"
        py_ver = sys.version.split()[0]

        if self.timeout == 0:
            timeout_desc = "none — disabled with --timeout 0"
        else:
            timeout_desc = f"{self.timeout}s per probe, enforced by Python asyncio/subprocess"

        toolchains_desc = (
            "run (--run-toolchains) — scanners honoured the target's own config"
            if self.run_toolchains
            else "NOT RUN — dependency scanners and git-status were withheld; see their error rows"
        )

        content = [
            f"target:     {self.target_dir}",
            f"collected:  {datetime.datetime.now(datetime.UTC).strftime('%Y-%m-%dT%H:%M:%SZ')}",
            f"host:       {uname_str}",
            f"python:     {py_ver}",
            f"host-containers: {1 if self.host_containers else 0}",
            f"toolchains: {toolchains_desc}",
            f"timeout:    {timeout_desc}",
            f"secret-scan reads: {secret_globs}",
            f"checker jobs: {self.checker_jobs}",
        ]
        if git_scope:
            content.append(f"git scope:  {git_scope}")

        self.env_file.write_text("\n".join(content) + "\n", encoding="utf-8")

    def record_probe(
        self,
        name: str,
        axis: str,
        output: ProbeOutput,
        ok_exits: list[int] | None = None,
        cap: int | None = None,
        valid_pat: str | None = None,
        empty_note: str | None = None,
    ) -> ProbeRecord:
        """Process probe output, write files into out/, classify status, and append to manifest."""
        ok_codes = [0] if ok_exits is None else ok_exits
        out_file = self.out_dir / f"{name}.txt"
        full_file = self.out_dir / f"{name}.full.txt"
        err_file = self.out_dir / f"{name}.err"

        # Handle stderr
        has_err: Literal["yes", "no"] = "yes" if output.stderr else "no"
        if output.stderr:
            err_file.write_text(output.stderr, encoding="utf-8")
        elif err_file.exists():
            err_file.unlink()

        # Handle stdout and line capping
        stdout_lines = output.stdout.splitlines(keepends=True)
        total_lines = len(stdout_lines)
        truncated = False

        if cap is not None and total_lines > cap:
            truncated = True
            # Write full output
            full_file.write_text(output.stdout, encoding="utf-8")
            # Write capped output
            capped_text = "".join(stdout_lines[:cap])
            out_file.write_text(capped_text, encoding="utf-8")
        else:
            out_file.write_text(output.stdout, encoding="utf-8")
            if full_file.exists():
                full_file.unlink()

        out_bytes = out_file.stat().st_size
        out_lines = len(out_file.read_text(encoding="utf-8", errors="replace").splitlines())

        rc = output.exit_code
        expected = rc in ok_codes

        # Status classification matching probe.sh lines 192-228
        if output.timed_out:
            status = ProbeStatus.ERROR
            note = f"TIMED OUT after {self.timeout}s — the output file holds only what arrived before the kill"
        elif valid_pat and not re.search(valid_pat, output.stdout):
            status = ProbeStatus.ERROR
            # Extract error summary message
            said_match = re.search(r'"(message|code|summary)"\s*:\s*"([^"]+)"', output.stdout)
            if said_match:
                said = said_match.group(0)
            else:
                combined = (output.stdout + "\n" + output.stderr).splitlines()
                non_empty = [
                    line.strip()
                    for line in combined
                    if line.strip() and line.strip() not in ("{", "}")
                ]
                said = non_empty[0] if non_empty else ""
            said = re.sub(r"[\t\n]", " ", said)[:120]
            note = f"exited {rc} and printed no report ({said}) — out/{name}.txt holds its error, not results"
        elif expected:
            if out_bytes == 0 and has_err == "yes":
                status = ProbeStatus.EMPTY
                note = f"produced no output, but wrote stderr — read out/{name}.err before concluding none"
                if empty_note:
                    note += f". {empty_note}"
            elif out_bytes == 0:
                status = ProbeStatus.EMPTY
                note = empty_note if empty_note else "ran clean, produced no output"
            else:
                status = ProbeStatus.OK
                note = "see output file"
        elif out_bytes > 0:
            status = ProbeStatus.OUTPUT
            note = f"exited {rc} and produced output — read it, do not discard"
        else:
            status = ProbeStatus.ERROR
            if output.stderr:
                cleaned_err = re.sub(r"\s+", " ", output.stderr.strip()[:160])
                note = cleaned_err
            else:
                note = f"exited {rc} with no stderr"

        if truncated:
            note = (
                f"TRUNCATED: {cap} of {total_lines} lines shown, all in out/{name}.full.txt. {note}"
            )
        if has_err == "yes" and status != ProbeStatus.EMPTY:
            note = f"{note} [stderr present: out/{name}.err]"

        record = ProbeRecord(
            probe=name,
            axis=axis,
            status=status,
            exit=str(rc),
            bytes=out_bytes,
            lines=out_lines,
            stderr=has_err,
            file=f"out/{name}.txt",
            note=note,
        )
        self.records.append(record)
        with open(self.manifest_file, "a", encoding="utf-8") as f:
            f.write(record.to_tsv_row() + "\n")
        return record

    def record_skip(self, name: str, axis: str, reason: str) -> ProbeRecord:
        """Record an inapplicable probe."""
        record = ProbeRecord(
            probe=name,
            axis=axis,
            status=ProbeStatus.NA,
            exit="-",
            bytes=0,
            lines=0,
            stderr="no",
            file="-",
            note=reason,
        )
        self.records.append(record)
        with open(self.manifest_file, "a", encoding="utf-8") as f:
            f.write(record.to_tsv_row() + "\n")
        return record

    def record_gated(self, name: str, axis: str) -> ProbeRecord:
        """Record a gated probe withheld because target configuration can execute code."""
        reason = (
            "not run: target-supplied toolchain config can execute code — "
            "pass --run-toolchains, inside a disposable container over a copy"
        )
        record = ProbeRecord(
            probe=name,
            axis=axis,
            status=ProbeStatus.ERROR,
            exit="-",
            bytes=0,
            lines=0,
            stderr="no",
            file="-",
            note=reason,
        )
        self.records.append(record)
        with open(self.manifest_file, "a", encoding="utf-8") as f:
            f.write(record.to_tsv_row() + "\n")
        return record

    def write_summary(self) -> str:
        """Generate and write summary.txt."""
        status_counts: dict[str, int] = {}
        for r in self.records:
            status_counts[r.status.value] = status_counts.get(r.status.value, 0) + 1

        truncated_count = sum(1 for r in self.records if r.note.startswith("TRUNCATED"))
        stderr_count = sum(1 for r in self.records if r.stderr == "yes")
        output_count = sum(1 for r in self.records if r.status == ProbeStatus.OUTPUT)

        lines = ["auditor-probe summary", ""]
        for s in sorted(status_counts.keys()):
            lines.append(f"  {s:<7} {status_counts[s]}")
        lines.append("")
        lines.append(f"  total   {len(self.records)}")

        if truncated_count > 0:
            lines.append(
                f"  WARN    {truncated_count} probe(s) exceeded their line cap — full output in out/*.full.txt"
            )
        if stderr_count > 0:
            lines.append(f"  WARN    {stderr_count} probe(s) wrote stderr — see out/*.err")
        if output_count > 0:
            lines.append(
                f"  NOTE    {output_count} probe(s) exited nonzero WITH output — read them, do not discard"
            )

        lines.append("")
        lines.append("  bundle holds raw config and possible secrets — delete it when done.")
        summary_text = "\n".join(lines) + "\n"
        self.summary_file.write_text(summary_text, encoding="utf-8")
        return summary_text
