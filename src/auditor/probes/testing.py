"""Testing probes (inventory, file counts, CI configurations, and badges)."""

from __future__ import annotations

import fnmatch
import os
import re
from pathlib import Path

from auditor.bundle import BundleManager
from auditor.models import ProbeAxis, ProbeOutput
from auditor.probes.base import PRUNE_DIRS, walk_target_files

TEST_DIR_NAMES = {"test", "tests", "spec", "__tests__"}
TEST_FILE_PATTERNS = [
    "*test*.php",
    "*_test.go",
    "*.test.js",
    "*.test.ts",
    "test_*.py",
    "*_spec.rb",
    "test_*.sh",
    "*_test.sh",
    "*Tests.swift",
    "*Test.swift",
]
# Rust tests carry no naming convention: they live under tests/ or inline behind these.
RUST_TEST_ATTR = re.compile(r"#\[(cfg\(test\)|(\w+::)?test\b)")

CI_CONFIG_PATTERNS = [
    ".github/workflows/*",
    ".gitlab-ci.yml",
    ".circleci/*",
    "Jenkinsfile",
    ".travis.yml",
    "azure-pipelines.yml",
]

BADGE_REGEX = re.compile(
    r"!\[[^]]*\]\(https://[^)]*(badge|shield|workflow|actions)[^)]*\)", re.IGNORECASE
)


def run_testing_probes(bundle: BundleManager, target: Path) -> None:
    """Execute test-inventory, test-file-count, ci-config, and ci-badges probes."""
    target_resolved = target.resolve()

    # 1. test-inventory
    test_dirs: list[str] = []
    for root, dirs, _ in os.walk(target_resolved, topdown=True, followlinks=False):
        dirs[:] = [d for d in dirs if d not in PRUNE_DIRS]
        for d in dirs:
            # SwiftPM uses Tests/, Xcode targets end in Tests/UITests
            if d in TEST_DIR_NAMES or d.endswith("Tests"):
                full_d = Path(root) / d
                try:
                    rel_d = full_d.relative_to(target_resolved)
                except ValueError:
                    rel_d = full_d
                test_dirs.append(f"./{rel_d}")

    test_dirs.sort()
    test_inv_out = "\n".join(test_dirs) + ("\n" if test_dirs else "")
    bundle.record_probe(
        "test-inventory", ProbeAxis.TESTING.value, ProbeOutput(0, test_inv_out, ""), cap=20
    )

    # 2. test-file-count
    test_file_count = 0
    for rel_path, full_path in walk_target_files(target):
        fname = rel_path.name
        if any(fnmatch.fnmatch(fname, pat) for pat in TEST_FILE_PATTERNS):
            test_file_count += 1
        elif rel_path.suffix == ".rs" and (
            "tests" in rel_path.parts[:-1]
            or RUST_TEST_ATTR.search(full_path.read_text(encoding="utf-8", errors="replace"))
        ):
            test_file_count += 1

    bundle.record_probe(
        "test-file-count",
        ProbeAxis.TESTING.value,
        ProbeOutput(0, f"{test_file_count}\n", ""),
    )

    # 3. ci-config (maxdepth 3)
    ci_matches: list[str] = []
    for root, dirs, files in os.walk(target_resolved, topdown=True, followlinks=False):
        dirs[:] = [d for d in dirs if d not in PRUNE_DIRS]
        rel_root = Path(root).relative_to(target_resolved)
        depth = len(rel_root.parts)
        if depth >= 3:
            dirs.clear()
            continue

        for f in files:
            full_f = Path(root) / f
            rel_f = full_f.relative_to(target_resolved)
            rel_str = str(rel_f)
            for pat in CI_CONFIG_PATTERNS:
                if fnmatch.fnmatch(rel_str, pat):
                    ci_matches.append(f"./{rel_str}")
                    break

    ci_matches.sort()
    ci_out = "\n".join(ci_matches) + ("\n" if ci_matches else "")
    bundle.record_probe("ci-config", ProbeAxis.TESTING.value, ProbeOutput(0, ci_out, ""))

    # 4. ci-badges
    badges: list[str] = []
    for rel_path, full_path in walk_target_files(target):
        if rel_path.suffix == ".md":
            try:
                with open(full_path, encoding="utf-8", errors="replace") as fh:
                    for line in fh:
                        for m in BADGE_REGEX.finditer(line):
                            badges.append(m.group(0))
            except Exception:
                pass

    badges_out = "\n".join(badges) + ("\n" if badges else "")
    badge_rc = 0 if badges else 1
    bundle.record_probe(
        "ci-badges",
        ProbeAxis.TESTING.value,
        ProbeOutput(badge_rc, badges_out, ""),
        ok_exits=[0, 1],
        cap=20,
    )
