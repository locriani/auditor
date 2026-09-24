"""Secret scanning, env files, and published ports probes."""

from __future__ import annotations

import fnmatch
import os
import re
from pathlib import Path

from auditor.bundle import BundleManager
from auditor.models import ProbeAxis, ProbeOutput
from auditor.probes.base import (
    EXCLUDED_FILE_PATTERNS,
    is_file_excluded,
    walk_target_files,
)

SECRET_GLOBS = (
    "*.y*ml *.env* *.json *.ini *.conf *.cfg *.toml *.xml *.properties *.tf *.tfvars "
    "*.sh *.php *.ts *.tsx *.js *.jsx *.mjs *.cjs *.vue *.py *.rb *.go *.java *.kt "
    "*.kts *.scala *.gradle *.cs *.rs *.swift *.c *.cc *.cpp *.h *.hpp *.md Dockerfile* Makefile"
)

# Convert SECRET_GLOBS to list of patterns
SECRET_GLOB_PATTERNS = [g for g in SECRET_GLOBS.split() if g]

# Directory exclusions for secret-scan (only .git, node_modules, vendor)
SECRET_PRUNE_DIRS = {".git", "node_modules", "vendor"}

SECRET_MATCH_REGEX = re.compile(
    r"((password|passwd|secret|token|api[_-]?key|access[_-]?key|private[_-]?key)"
    r"([_-]?key|[_-][a-z0-9_-]*)?"
    r"(['\"]?\s*(:|=>?)\s*['\"]?|['\"]\s*,\s*['\"])"
    r"[A-Za-z0-9_./+=-]{6,}|"
    r"[a-z][a-z0-9+.-]*://[^/:@\s'\"]+:[^/@\s'\"]{6,}@)",
    re.IGNORECASE,
)

SECRET_FILTER_REGEX = re.compile(
    r"(example|sample|placeholder|changeme|your[_-]|xxx|csrf|jquery|function|typeof|prototype|"
    r"(password|passwd|secret|token|api[_-]?key|access[_-]?key|private[_-]?key)"
    r"([_-]?key|[_-][a-z0-9_-]*)?['\"]?\s*(:|=>?)\s*[A-Za-z_][A-Za-z0-9_.]*\()",
    re.IGNORECASE,
)

PORT_REGEX = re.compile(r"^\s*-\s*\"?[0-9]{2,5}:[0-9]{2,5}")


def matches_secret_glob(filename: str) -> bool:
    for pat in SECRET_GLOB_PATTERNS:
        # Match y*ml pattern properly
        if pat == "*.y*ml":
            if fnmatch.fnmatch(filename, "*.yml") or fnmatch.fnmatch(filename, "*.yaml"):
                return True
        elif fnmatch.fnmatch(filename, pat):
            return True
    return False


def run_secret_probes(bundle: BundleManager, target: Path) -> None:
    """Execute secret-scan, env-files, and published-ports probes."""
    target_resolved = target.resolve()

    # 1. secret-scan
    matches: list[str] = []
    unreadable_tree = False
    stderr_msgs: list[str] = []

    for root, dirs, files in os.walk(target_resolved, topdown=True, followlinks=False):
        dirs[:] = [d for d in dirs if d not in SECRET_PRUNE_DIRS]

        root_path = Path(root)
        for f in files:
            if is_file_excluded(f, EXCLUDED_FILE_PATTERNS):
                continue
            if not matches_secret_glob(f):
                continue

            full_path = root_path / f
            try:
                rel_path = full_path.relative_to(target_resolved)
            except ValueError:
                rel_path = full_path

            try:
                # Read file content safely
                with open(full_path, encoding="utf-8", errors="replace") as fh:
                    for line_no, line in enumerate(fh, start=1):
                        clean_line = line.rstrip("\r\n")
                        if SECRET_MATCH_REGEX.search(clean_line):
                            # Check filter regex
                            if not SECRET_FILTER_REGEX.search(clean_line):
                                matches.append(f"./{rel_path}:{line_no}:{clean_line}")
            except (OSError, PermissionError) as e:
                unreadable_tree = True
                stderr_msgs.append(f"./{rel_path}: {e}")

    secret_out = "\n".join(matches) + ("\n" if matches else "")
    secret_err = "\n".join(stderr_msgs) + ("\n" if stderr_msgs else "")

    if unreadable_tree and not matches:
        # An unreadable tree with no match is an error, not an empty result
        secret_rc = 2
    else:
        secret_rc = 0 if matches else 1

    empty_note = (
        "the pattern matched nothing in the file types listed in env.txt. "
        "It finds one-line assignments and URL credentials only (SKILL.md, "
        "What auditor-probe does not guarantee) — this is not evidence of no secrets"
    )

    bundle.record_probe(
        "secret-scan",
        ProbeAxis.SECURITY.value,
        ProbeOutput(secret_rc, secret_out, secret_err),
        ok_exits=[0, 1],
        cap=40,
        empty_note=empty_note,
    )

    # 2. env-files
    env_matches: list[str] = []
    for rel_path, _ in walk_target_files(target):
        if fnmatch.fnmatch(rel_path.name, ".env*"):
            env_matches.append(f"./{rel_path}")

    env_out = "\n".join(env_matches) + ("\n" if env_matches else "")
    bundle.record_probe("env-files", ProbeAxis.SECURITY.value, ProbeOutput(0, env_out, ""), cap=20)

    # 3. published-ports
    compose_patterns = [
        "docker-compose*.yml",
        "docker-compose*.yaml",
        "compose*.yml",
        "compose*.yaml",
    ]
    port_matches: list[str] = []
    for rel_path, full_path in walk_target_files(target):
        fname = rel_path.name
        if any(fnmatch.fnmatch(fname, pat) for pat in compose_patterns):
            try:
                with open(full_path, encoding="utf-8", errors="replace") as fh:
                    for line in fh:
                        if PORT_REGEX.match(line):
                            port_matches.append(line.rstrip("\r\n"))
            except Exception:
                pass

    ports_out = "\n".join(port_matches) + ("\n" if port_matches else "")
    ports_rc = 0 if port_matches else 1
    bundle.record_probe(
        "published-ports",
        ProbeAxis.SECURITY.value,
        ProbeOutput(ports_rc, ports_out, ""),
        ok_exits=[0, 1],
        cap=40,
    )
