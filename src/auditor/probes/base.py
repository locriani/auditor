"""Base utilities, pruning logic, and execution wrappers for auditor probes."""

from __future__ import annotations

import fnmatch
import os
import shutil
import subprocess
from collections.abc import Iterator
from pathlib import Path

from auditor.models import ProbeOutput

PRUNE_DIRS: set[str] = {
    ".git",
    "node_modules",
    "vendor",
    "dist",
    "build",
    "coverage",
    ".venv",
    "venv",
    "__pycache__",
    "third_party",
    "bower_components",
    "target",
    ".build",
    "Pods",
    "Carthage",
    "DerivedData",
    "jquery",
}

EXCLUDED_FILE_PATTERNS: list[str] = [
    "*.min.js",
    "*.min.css",
    "*.map",
    "*-lock.json",
    "*.lock",
]


def has_command(cmd: str) -> bool:
    """Check if command executable exists on PATH."""
    return shutil.which(cmd) is not None


def is_file_excluded(filename: str, patterns: list[str] = EXCLUDED_FILE_PATTERNS) -> bool:
    """Check if a filename matches any of the exclude patterns."""
    return any(fnmatch.fnmatch(filename, pattern) for pattern in patterns)


def walk_target_files(
    target_dir: Path,
    prune_dirs: set[str] = PRUNE_DIRS,
    exclude_patterns: list[str] | None = None,
    include_extensions: set[str] | None = None,
) -> Iterator[tuple[Path, Path]]:
    """Walk target directory, pruning ignored directories at any depth.

    Yields (relative_path, absolute_path).
    """
    patterns = EXCLUDED_FILE_PATTERNS if exclude_patterns is None else exclude_patterns
    target_resolved = target_dir.resolve()

    for root, dirs, files in os.walk(target_resolved, topdown=True, followlinks=False):
        # Prune directories in place
        dirs[:] = [d for d in dirs if d not in prune_dirs]

        root_path = Path(root)
        for f in files:
            if patterns and is_file_excluded(f, patterns):
                continue
            if include_extensions is not None:
                # check extension
                suffix = Path(f).suffix
                if suffix not in include_extensions:
                    continue
            full_path = root_path / f
            try:
                rel_path = full_path.relative_to(target_resolved)
            except ValueError:
                rel_path = full_path
            yield rel_path, full_path


def run_command(
    cmd: str | list[str],
    cwd: Path,
    timeout: int | None = 120,
    env: dict[str, str] | None = None,
) -> ProbeOutput:
    """Execute a command in target directory with timeout and output capture."""
    exec_env = os.environ.copy()
    if env:
        exec_env.update(env)

    use_shell = isinstance(cmd, str)
    # Ensure unsetting CDPATH
    exec_env.pop("CDPATH", None)

    try:
        proc = subprocess.Popen(
            cmd,
            cwd=cwd,
            shell=use_shell,
            executable="/bin/bash" if use_shell else None,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=exec_env,
        )
        effective_timeout = None if (timeout == 0 or timeout is None) else timeout
        stdout, stderr = proc.communicate(timeout=effective_timeout)
        return ProbeOutput(
            exit_code=proc.returncode,
            stdout=stdout or "",
            stderr=stderr or "",
            timed_out=False,
        )
    except subprocess.TimeoutExpired:
        proc.kill()
        stdout, stderr = proc.communicate()
        return ProbeOutput(
            exit_code=124,
            stdout=stdout or "",
            stderr=stderr or "",
            timed_out=True,
        )
    except Exception as e:
        return ProbeOutput(
            exit_code=1,
            stdout="",
            stderr=str(e),
            timed_out=False,
        )


def manifest_index(target_dir: Path, names: set[str]) -> dict[Path, set[str]]:
    """Map each directory (relative to the target) to which of `names` it holds, at any depth."""
    index: dict[Path, set[str]] = {}
    for rel_path, _ in walk_target_files(target_dir, exclude_patterns=[]):
        if rel_path.name in names:
            index.setdefault(rel_path.parent, set()).add(rel_path.name)
    return index


def find_projects(index: dict[Path, set[str]], manifests: set[str], locks: set[str]) -> list[Path]:
    """Directories holding one of `manifests`, shallowest first.

    A directory with no lock of its own beneath one already found is a workspace member
    whose dependencies the ancestor's lock pins, so it is not a project of its own.
    """
    # ponytail: nearest-lock heuristic; a nested project that relies on a lock two levels up
    # of a *different* workspace would be dropped
    candidates = sorted(
        (d for d, held in index.items() if held & manifests),
        key=lambda d: (len(d.parts), str(d)),
    )
    projects: list[Path] = []
    for d in candidates:
        if not (index[d] & locks) and any(p in d.parents for p in projects):
            continue
        projects.append(d)
    return projects


def project_probe(name: str, project: Path) -> str:
    """`name` for the target root, `name@rel/dir` for a nested project."""
    return name if project == Path(".") else f"{name}@{project}"
