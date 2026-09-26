"""Declared standards and syntax checking probes."""

from __future__ import annotations

import collections
import concurrent.futures
import fnmatch
import re
import subprocess
from pathlib import Path

from auditor.bundle import BundleManager
from auditor.models import ProbeAxis, ProbeOutput
from auditor.probes.base import has_command, walk_target_files

LINT_CONFIG_PATTERNS = [
    ".editorconfig",
    ".eslintrc*",
    "eslint.config.*",
    ".prettierrc*",
    "phpcs.xml*",
    ".php-cs-fixer*",
    "psalm.xml*",
    "phpstan.neon*",
    "ruff.toml",
    ".flake8",
    "setup.cfg",
    "tox.ini",
    "rustfmt.toml",
    ".rustfmt.toml",
    "clippy.toml",
    ".clippy.toml",
    "deny.toml",
    ".swiftlint.yml",
    ".swiftlint.yaml",
    ".swiftformat",
    ".swift-format",
    ".golangci.yml",
    ".golangci.yaml",
    ".rubocop.yml",
]

# Escape hatches from each language's safety guarantees. Counts point at files to read;
# a count is not a finding.
LANG_MARKERS: dict[str, tuple[str, list[tuple[str, re.Pattern[str]]]]] = {
    "rust-markers": (
        ".rs",
        [
            ("unsafe", re.compile(r"\bunsafe\s*(\{|fn\b|impl\b|trait\b)")),
            (".unwrap()", re.compile(r"\.unwrap\(\)")),
            (".expect(", re.compile(r"\.expect\(")),
            ("panic!", re.compile(r"\bpanic!")),
            ("todo!/unimplemented!", re.compile(r"\b(todo|unimplemented)!")),
            ("let _ = (result discarded)", re.compile(r"\blet\s+_\s*=")),
            (".ok(); (error discarded)", re.compile(r"\.ok\(\)\s*;")),
            ("#[allow(", re.compile(r"#!?\[allow\(")),
        ],
    ),
    "swift-markers": (
        ".swift",
        [
            ("try!", re.compile(r"\btry!")),
            ("try? (error discarded)", re.compile(r"\btry\?")),
            ("as!", re.compile(r"\bas!")),
            ("fatalError(", re.compile(r"\bfatalError\(")),
            ("unowned", re.compile(r"\bunowned\b")),
            ("@unchecked Sendable", re.compile(r"@unchecked\s+Sendable\b")),
            ("nonisolated(unsafe)", re.compile(r"\bnonisolated\(unsafe\)")),
            ("Unsafe*Pointer", re.compile(r"\bUnsafe(Mutable)?(Raw)?(Buffer)?Pointer\b")),
            ("swiftlint:disable", re.compile(r"swiftlint:disable")),
        ],
    ),
}


def run_standards_probes(
    bundle: BundleManager,
    target: Path,
    checker_jobs: int = 4,
    timeout: int = 120,
) -> None:
    """Execute lint-config, lang-census, language marker, php-syntax, and shell lint probes."""
    # 1. lint-config (root directory only)
    lint_configs: list[str] = []
    for entry in target.iterdir():
        for pat in LINT_CONFIG_PATTERNS:
            if fnmatch.fnmatch(entry.name, pat):
                lint_configs.append(f"./{entry.name}")
                break
    lint_configs.sort()
    lint_out = "\n".join(lint_configs) + ("\n" if lint_configs else "")
    bundle.record_probe("lint-config", ProbeAxis.CODE_QUALITY.value, ProbeOutput(0, lint_out, ""))

    # 2. lang-census
    ext_counter: collections.Counter[str] = collections.Counter()
    for rel_path, _ in walk_target_files(target):
        name = rel_path.name
        if "." in name and not name.startswith("."):
            ext = name.rsplit(".", 1)[-1]
            if ext:
                ext_counter[ext] += 1
        elif name.count(".") > 1:
            ext = name.rsplit(".", 1)[-1]
            if ext:
                ext_counter[ext] += 1

    ext_lines = [f"{count:>7} {ext}" for ext, count in ext_counter.most_common()]
    lang_out = "\n".join(ext_lines) + ("\n" if ext_lines else "")
    bundle.record_probe(
        "lang-census", ProbeAxis.CODE_QUALITY.value, ProbeOutput(0, lang_out, ""), cap=20
    )

    # 3. rust-markers / swift-markers
    for probe, (ext, markers) in LANG_MARKERS.items():
        files = list(walk_target_files(target, include_extensions={ext}))
        if not files:
            bundle.record_skip(probe, ProbeAxis.CODE_QUALITY.value, f"no {ext} files")
            continue
        counts: collections.Counter[str] = collections.Counter()
        for rel_path, full_path in files:
            if "test" in str(rel_path).lower():
                continue
            content = full_path.read_text(encoding="utf-8", errors="replace")
            for label, pattern in markers:
                counts[label] += len(pattern.findall(content))
        marker_lines = [f"{count:>7} {label}" for label, count in counts.most_common() if count]
        marker_out = "\n".join(marker_lines) + ("\n" if marker_lines else "")
        bundle.record_probe(
            probe,
            ProbeAxis.CODE_QUALITY.value,
            ProbeOutput(0, marker_out, ""),
            empty_note="no marker matched outside paths containing 'test'",
        )

    # 4. php-syntax
    has_composer = (target / "composer.json").is_file()
    if has_composer and has_command("php"):
        php_files = [
            full_path
            for rel_path, full_path in walk_target_files(target)
            if rel_path.suffix == ".php"
        ]
        if not php_files:
            bundle.record_probe(
                "php-syntax", ProbeAxis.CODE_QUALITY.value, ProbeOutput(0, "", ""), cap=40
            )
        else:
            errors: list[str] = []
            rc = 0

            def check_php(p: Path) -> tuple[int, str]:
                res = subprocess.run(
                    ["php", "-l", str(p)],
                    cwd=target,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    check=False,
                )
                return res.returncode, res.stdout

            with concurrent.futures.ThreadPoolExecutor(max_workers=checker_jobs) as executor:
                results = executor.map(check_php, php_files)
                for code, output in results:
                    # In php -l, 0 or 255 are standard exit codes (0 = no error, 255 = syntax error)
                    if code not in (0, 255):
                        rc = 1
                    filtered = [
                        line
                        for line in output.splitlines()
                        if not line.startswith("No syntax errors detected in")
                    ]
                    errors.extend(filtered)

            php_out = "\n".join(errors) + ("\n" if errors else "")
            bundle.record_probe(
                "php-syntax", ProbeAxis.CODE_QUALITY.value, ProbeOutput(rc, php_out, ""), cap=40
            )
    else:
        bundle.record_skip(
            "php-syntax", ProbeAxis.CODE_QUALITY.value, "no composer.json, or php not on PATH"
        )

    # 5. shell-lint / shell-syntax-only
    sh_files = [
        str(rel_path) for rel_path, _ in walk_target_files(target) if rel_path.suffix == ".sh"
    ]

    if has_command("shellcheck"):
        if not sh_files:
            bundle.record_probe(
                "shell-lint", ProbeAxis.CODE_QUALITY.value, ProbeOutput(0, "", ""), cap=60
            )
        else:
            res = subprocess.run(
                ["shellcheck", "-f", "gcc", *sh_files],
                cwd=target,
                capture_output=True,
                text=True,
                check=False,
            )
            # shellcheck exit 0 = no issues, 1 = issues found, >1 = could not run/syntax error
            out_rc = 0 if res.returncode <= 1 else res.returncode
            bundle.record_probe(
                "shell-lint",
                ProbeAxis.CODE_QUALITY.value,
                ProbeOutput(out_rc, res.stdout, res.stderr),
                cap=60,
            )
    else:
        if not sh_files:
            bundle.record_probe(
                "shell-syntax-only", ProbeAxis.CODE_QUALITY.value, ProbeOutput(0, "", ""), cap=40
            )
        else:
            syntax_rc = 0
            syntax_errors: list[str] = []
            for f in sh_files:
                chk = subprocess.run(
                    ["bash", "-n", f],
                    cwd=target,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                if chk.returncode > 2:
                    syntax_rc = 1
                if chk.stderr:
                    syntax_errors.append(chk.stderr.strip())

            syn_out = "\n".join(syntax_errors) + ("\n" if syntax_errors else "")
            bundle.record_probe(
                "shell-syntax-only",
                ProbeAxis.CODE_QUALITY.value,
                ProbeOutput(syntax_rc, syn_out, ""),
                cap=40,
            )
        bundle.record_skip(
            "shell-lint",
            ProbeAxis.CODE_QUALITY.value,
            "shellcheck NOT installed — only bash -n syntax checking ran; style and quoting defects were NOT looked for",
        )
