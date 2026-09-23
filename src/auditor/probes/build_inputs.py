"""Build input probes (Dockerfiles, compose files, and remote fetches)."""

from __future__ import annotations

import fnmatch
import re
from pathlib import Path

from auditor.bundle import BundleManager
from auditor.models import ProbeAxis, ProbeOutput
from auditor.probes.base import walk_target_files

DOCKER_PATTERNS = ["Dockerfile*", "*.Dockerfile", "*.dockerfile", "Containerfile*"]
COMPOSE_PATTERNS = ["docker-compose*.yml", "docker-compose*.yaml", "compose.yml", "compose.yaml"]

FETCH_REGEX = re.compile(
    r"(git clone|curl|wget|ADD\s+https?://|"
    r"^\s*FROM(\s+--\S+)*\s+\S+:latest(\s|$)|"
    r"^\s*FROM(\s+--\S+)*\s+[^:@\s]+(\s+AS\s+\S+)?\s*$)",
    re.IGNORECASE | re.MULTILINE,
)


def run_build_input_probes(bundle: BundleManager, target: Path) -> None:
    """Execute build input probes."""
    docker_files: list[tuple[Path, Path]] = []
    compose_files: list[str] = []

    for rel_path, full_path in walk_target_files(target):
        fname = rel_path.name
        if any(fnmatch.fnmatch(fname, pat) for pat in DOCKER_PATTERNS):
            docker_files.append((rel_path, full_path))
        if any(fnmatch.fnmatch(fname, pat) for pat in COMPOSE_PATTERNS):
            compose_files.append(f"./{rel_path}")

    # dockerfiles
    docker_lines = [f"./{rel}" for rel, _ in docker_files]
    docker_out = "\n".join(docker_lines) + ("\n" if docker_lines else "")
    bundle.record_probe(
        "dockerfiles", ProbeAxis.SUPPLY_CHAIN.value, ProbeOutput(0, docker_out, ""), cap=20
    )

    # dockerfile-fetches
    fetch_lines: list[str] = []
    for rel_path, full_path in docker_files:
        try:
            content = full_path.read_text(encoding="utf-8", errors="replace")
            for line_no, line in enumerate(content.splitlines(), start=1):
                if FETCH_REGEX.search(line):
                    fetch_lines.append(f"./{rel_path}:{line_no}:{line}")
        except Exception:
            pass

    fetch_out = "\n".join(fetch_lines) + ("\n" if fetch_lines else "")
    fetch_rc = 0 if fetch_lines else 1
    bundle.record_probe(
        "dockerfile-fetches",
        ProbeAxis.SUPPLY_CHAIN.value,
        ProbeOutput(fetch_rc, fetch_out, ""),
        ok_exits=[0, 1],
    )

    # compose-files
    compose_out = "\n".join(compose_files) + ("\n" if compose_files else "")
    bundle.record_probe(
        "compose-files", ProbeAxis.SUPPLY_CHAIN.value, ProbeOutput(0, compose_out, ""), cap=20
    )
