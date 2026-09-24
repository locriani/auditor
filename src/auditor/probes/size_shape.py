"""Size and shape probes (repo size, largest files, total file count)."""

from __future__ import annotations

import subprocess
from pathlib import Path

from auditor.bundle import BundleManager
from auditor.models import ProbeAxis, ProbeOutput
from auditor.probes.base import walk_target_files


def run_size_shape_probes(bundle: BundleManager, target: Path) -> None:
    """Execute repo-size, largest-files, and file-count probes."""
    # 1. repo-size
    du_proc = subprocess.run(
        ["du", "-sh", "."],
        cwd=target,
        capture_output=True,
        text=True,
        check=False,
    )
    if du_proc.returncode == 0 and du_proc.stdout.strip():
        size_str = du_proc.stdout.split()[0]
        repo_size_out = ProbeOutput(0, f"{size_str}\n", "")
    else:
        # Fallback calculate total bytes
        total_bytes = 0
        try:
            for p in target.rglob("*"):
                if p.is_file():
                    total_bytes += p.stat().st_size
            repo_size_out = ProbeOutput(0, f"{total_bytes}\n", "")
        except Exception as e:
            repo_size_out = ProbeOutput(1, "", str(e))

    bundle.record_probe("repo-size", ProbeAxis.PERFORMANCE.value, repo_size_out)

    # 2. largest-files & 3. file-count
    file_list: list[tuple[int, str]] = []
    for rel_path, full_path in walk_target_files(target):
        try:
            sz = full_path.stat().st_size
            file_list.append((sz, f"./{rel_path}"))
        except Exception:
            pass

    # Sort largest files descending
    file_list.sort(key=lambda item: item[0], reverse=True)
    largest_lines = [f"{sz} {name}" for sz, name in file_list[:15]]
    largest_out = "\n".join(largest_lines) + ("\n" if largest_lines else "")
    bundle.record_probe(
        "largest-files", ProbeAxis.PERFORMANCE.value, ProbeOutput(0, largest_out, ""), cap=15
    )

    # file-count
    bundle.record_probe(
        "file-count",
        ProbeAxis.PERFORMANCE.value,
        ProbeOutput(0, f"{len(file_list)}\n", ""),
    )
