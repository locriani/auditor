"""mutations.py — domain-specific mutation testing suite for auditor.

Each mutation is a literal, count-checked substitution in the Python source code
that breaks one specific behaviour. A mutant the test suite still passes is a
behaviour no test pins.

    uv run python dev/mutations.py run [-j JOBS] [ID ...]
    uv run python dev/mutations.py list

Numbering:
  m01–m58 are the core contract & regression mutations
  n01–n03 are the security gate mutations
  r01–r11 are Rust target mutations
  s01–s13 are Swift target mutations
  d01–d17 are nested-manifest and scanner report-check mutations
"""

from __future__ import annotations

import argparse
import concurrent.futures
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src" / "auditor"

# (id, description, file_rel, [(old, new, count)], requires, equivalent)
M: list[tuple[str, str, str, list[tuple[str, str, int]], str, str]] = [
    (
        "m01",
        "TRUNCATED at exactly the cap",
        "bundle.py",
        [
            (
                "if cap is not None and total_lines > cap:",
                "if cap is not None and total_lines >= cap:",
                1,
            )
        ],
        "",
        "",
    ),
    (
        "m02",
        "capped file keeps cap-1 lines",
        "bundle.py",
        [
            (
                'capped_text = "".join(stdout_lines[:cap])',
                'capped_text = "".join(stdout_lines[:cap - 1])',
                1,
            )
        ],
        "",
        "",
    ),
    (
        "m04",
        "TRUNCATED note misreports the population",
        "bundle.py",
        [
            (
                'f"TRUNCATED: {cap} of {total_lines} lines shown',
                'f"TRUNCATED: {cap} of {cap} lines shown',
                1,
            )
        ],
        "",
        "",
    ),
    (
        "m05",
        "bytes and lines columns swapped",
        "models.py",
        [("{self.bytes}\\t{self.lines}", "{self.lines}\\t{self.bytes}", 1)],
        "",
        "",
    ),
    (
        "m06",
        "exit column always 0",
        "bundle.py",
        [("exit=str(rc),", 'exit="0",', 1)],
        "",
        "",
    ),
    (
        "m07",
        "valid_pat check disabled",
        "bundle.py",
        [
            (
                "elif valid_pat and not re.search(valid_pat, output.stdout):",
                "elif False and valid_pat:",
                1,
            )
        ],
        "",
        "",
    ),
    (
        "m08",
        "npm report pattern accepts an error object",
        "probes/dependencies.py",
        [
            (
                r'"(auditReportVersion|vulnerabilities)"\s*:',
                r'"(auditReportVersion|vulnerabilities|error)"\s*:',
                1,
            )
        ],
        "",
        "",
    ),
    (
        "m10",
        "TIMED OUT branch disabled",
        "bundle.py",
        [("if output.timed_out:", "if False and output.timed_out:", 1)],
        "",
        "",
    ),
    (
        "m11",
        "error note no longer quotes stderr",
        "bundle.py",
        [("note = cleaned_err", 'note = ""', 1)],
        "",
        "",
    ),
    (
        "m12",
        "stderr column always no",
        "bundle.py",
        [
            (
                'has_err: Literal["yes", "no"] = "yes" if output.stderr else "no"',
                'has_err: Literal["yes", "no"] = "no"',
                1,
            )
        ],
        "",
        "",
    ),
    (
        "m14",
        "output status collapsed into error",
        "bundle.py",
        [("status = ProbeStatus.OUTPUT", "status = ProbeStatus.ERROR", 1)],
        "",
        "",
    ),
    (
        "m15",
        "empty status collapsed into ok",
        "bundle.py",
        [("status = ProbeStatus.EMPTY", "status = ProbeStatus.OK", 2)],
        "",
        "",
    ),
    (
        "m16",
        "default ok_exits widened to 0 1",
        "bundle.py",
        [
            (
                "ok_codes = [0] if ok_exits is None else ok_exits",
                "ok_codes = [0, 1] if ok_exits is None else ok_exits",
                1,
            )
        ],
        "",
        "",
    ),
    (
        "m20",
        "--timeout 0 treated as enabled",
        "bundle.py",
        [("if self.timeout == 0:", "if False and self.timeout == 0:", 1)],
        "",
        "",
    ),
    (
        "m21",
        "empty --timeout accepted",
        "cli.py",
        [("if not cleaned or not cleaned.isdigit():", "if False:", 1)],
        "",
        "",
    ),
    (
        "m24",
        "refusal exits 0",
        "bundle.py",
        [("sys.exit(2)\n\n        resolved_target", "sys.exit(0)\n\n        resolved_target", 1)],
        "",
        "",
    ),
    (
        "m25",
        "unmarked non-empty dir refused only if it has out/",
        "bundle.py",
        [
            (
                "if not marker_file.is_file():",
                'if not marker_file.is_file() and (bundle_path / "out").exists():',
                1,
            )
        ],
        "",
        "",
    ),
    (
        "m26",
        "-o naming a regular file no longer refused",
        "bundle.py",
        [("if bundle_path.exists() and not bundle_path.is_dir():", "if False:", 1)],
        "",
        "",
    ),
    (
        "m27",
        "skip list drops node_modules",
        "probes/base.py",
        [('"node_modules",', "", 1)],
        "",
        "",
    ),
    (
        "m28",
        "skip list drops .git",
        "probes/base.py",
        [('".git",', "", 1)],
        "",
        "",
    ),
    (
        "m30",
        "secret-scan no longer skips node_modules",
        "probes/secrets.py",
        [
            (
                'SECRET_PRUNE_DIRS = {".git", "node_modules", "vendor"}',
                'SECRET_PRUNE_DIRS = {".git"}',
                1,
            )
        ],
        "",
        "",
    ),
    (
        "m38",
        "secret-scan no longer looks for password/passwd",
        "probes/secrets.py",
        [("password|passwd|secret|", "secret|", 2)],
        "",
        "",
    ),
    (
        "m39",
        "secret-scan minimum literal length 6 -> 16",
        "probes/secrets.py",
        [("{6,}", "{16,}", 2)],
        "",
        "",
    ),
    (
        "m42",
        "minified files, maps and lockfiles scanned again",
        "probes/base.py",
        [
            (
                'EXCLUDED_FILE_PATTERNS: list[str] = [\n    "*.min.js",\n    "*.min.css",\n    "*.map",\n    "*-lock.json",\n    "*.lock",\n]',
                "EXCLUDED_FILE_PATTERNS: list[str] = []",
                1,
            )
        ],
        "",
        "",
    ),
    (
        "m43",
        "empty secret-scan note reverts to empty string",
        "probes/secrets.py",
        [
            (
                'empty_note = (\n        "the pattern matched nothing in the file types listed in env.txt. "',
                'empty_note = "" # (',
                1,
            )
        ],
        "",
        "",
    ),
    (
        "m46",
        "git-log asks for 40, so truncation is never visible",
        "probes/git.py",
        [('"-41"', '"-40"', 1)],
        "",
        "",
    ),
    (
        "m47",
        "git detection back to simple directory check",
        "probes/git.py",
        [
            (
                'if not has_command("git"):',
                'if not has_command("git") or not (target / ".git").is_dir():',
                1,
            )
        ],
        "",
        "",
    ),
    (
        "m48",
        "git scope always reports subdirectory",
        "probes/git.py",
        [("if git_root == target_resolved:", "if False:", 1)],
        "",
        "",
    ),
    (
        "m56",
        "host-container gate removed",
        "probes/runtime.py",
        [("if not host_containers:", "if False:", 1)],
        "",
        "",
    ),
    (
        "m58",
        "placeholder filter stops dropping changeme",
        "probes/secrets.py",
        [("changeme|", "", 1)],
        "",
        "",
    ),
    (
        "n01",
        "toolchains run by default",
        "cli.py",
        [("] = False,\n    host_containers:", "] = True,\n    host_containers:", 1)],
        "",
        "",
    ),
    (
        "u01",
        "Care Team storage reverts to patient_data",
        "ui_path/analyzer.py",
        [('table="care_teams"', 'table="patient_data"', 1)],
        "",
        "",
    ),
    (
        "u02",
        "Care Team mismatch file:line citation stripped to bare filename",
        "ui_path/analyzer.py",
        [
            (
                'ui_evidence="src/Services/CareTeamService.php:565"',
                'ui_evidence="CareTeamService.php"',
                1,
            )
        ],
        "",
        "",
    ),
    (
        "u03",
        "AJAX fragment Immunizations table corrupted",
        "ui_path/analyzer.py",
        [
            (
                'table="immunizations",\n                    columns=["id", "immunization_id"',
                'table="lists",\n                    columns=["id", "immunization_id"',
                1,
            )
        ],
        "",
        "",
    ),
    (
        "u04",
        "MRN drops identifier type v2-0203|PT",
        "ui_path/analyzer.py",
        [("v2-0203|PT", "generic_mrn", 1)],
        "",
        "",
    ),
    (
        "u05",
        "observed flag elevation disabled",
        "ui_path/analyzer.py",
        [("confidence = ConfidenceLevel.OBSERVED if self.observed else", "confidence =", 5)],
        "",
        "",
    ),
    (
        "r01",
        "cargo-audit accepts an error as a report",
        "probes/dependencies.py",
        [(r"""valid_pat = r'"vulnerabilities"\s*:'""", "valid_pat = None", 1)],
        "",
        "",
    ),
    (
        "r07",
        "cargo-audit runs without a Cargo.lock",
        "probes/dependencies.py",
        [('if not (d / "Cargo.lock").is_file():', "if False:", 1)],
        "",
        "",
    ),
    (
        "r08",
        "cargo-licenses lists the target's own crates",
        "probes/compliance.py",
        [('        if pkg["id"] in own:\n            continue\n', "", 1)],
        "",
        "",
    ),
    (
        "r09",
        "crate with no license reads as licensed",
        "probes/compliance.py",
        [('else "NO LICENSE DECLARED"', 'else "MIT"', 1)],
        "",
        "",
    ),
    (
        "r10",
        "cargo metadata runs without a Cargo.lock",
        "probes/compliance.py",
        [('elif not (d / "Cargo.lock").is_file():', "elif False:", 1)],
        "",
        "",
    ),
    (
        "r11",
        "unparseable cargo metadata reads ok",
        "probes/compliance.py",
        [("out = ProbeOutput(1, out.stdout,", "out = ProbeOutput(0, out.stdout,", 1)],
        "",
        "",
    ),
    (
        "r02",
        "cargo-audit runs without --json",
        "probes/dependencies.py",
        [('["cargo-audit", "audit", "--json"]', '["cargo-audit", "audit"]', 1)],
        "",
        "",
    ),
    (
        "r03",
        "Rust tests/ directory files not counted",
        "probes/testing.py",
        [('"tests" in rel_path.parts[:-1]', "False", 1)],
        "",
        "",
    ),
    (
        "r04",
        "inline #[cfg(test)] modules not counted",
        "probes/testing.py",
        [("cfg\\(test\\)|", "", 1)],
        "",
        "",
    ),
    (
        "r05",
        "marker counts include test paths",
        "probes/standards.py",
        [('if "test" in str(rel_path).lower():\n                continue\n', "", 1)],
        "",
        "",
    ),
    (
        "r06",
        "unsafe blocks not counted",
        "probes/standards.py",
        [("(\\{|fn\\b|impl\\b|trait\\b)", "(fn\\b|impl\\b|trait\\b)", 1)],
        "",
        "",
    ),
    (
        "s01",
        "Pods/ not pruned",
        "probes/base.py",
        [('    "Pods",\n', "", 1)],
        "",
        "",
    ),
    (
        "s02",
        "SwiftPM .build/ not pruned",
        "probes/base.py",
        [('    ".build",\n', "", 1)],
        "",
        "",
    ),
    (
        "s03",
        "one-line empty catch {} missed",
        "probes/observability.py",
        [("if EMPTY_CATCH_REGEX.search(line):", "if False:", 1)],
        "",
        "",
    ),
    (
        "s04",
        "catch without parenthesis missed",
        "probes/observability.py",
        [
            (
                'CATCH_REGEX = re.compile(r"\\bcatch\\b")',
                'CATCH_REGEX = re.compile(r"catch\\s*\\(")',
                1,
            )
        ],
        "",
        "",
    ),
    (
        "s05",
        "Swift/Xcode Tests dirs missed",
        "probes/testing.py",
        [(' or d.endswith("Tests")', "", 1)],
        "",
        "",
    ),
    (
        "s06",
        "Package.swift without pins reads as nothing to scan",
        "probes/dependencies.py",
        [('if name == "swift-audit" and (d / "Package.swift").is_file():', "if False:", 1)],
        "",
        "",
    ),
    (
        "s11",
        "trivy runs inside the target, reading its trivy.yaml and .trivyignore",
        "probes/dependencies.py",
        [
            (
                "out = run_command(cmd, cwd=bundle.bundle_dir,",
                "out = run_command(cmd, cwd=target,",
                1,
            )
        ],
        "",
        "",
    ),
    (
        "s12",
        "trivy report without Results reads ok",
        "probes/dependencies.py",
        [(r"""out, valid_pat=r'"Results"\s*:')""", "out)", 1)],
        "",
        "",
    ),
    (
        "s13",
        "dependency scanners run without --run-toolchains",
        "probes/dependencies.py",
        [
            (
                "    if not run_toolchains:\n        bundle.record_gated(probe, AXIS)\n    elif not_run:",
                "    if not_run:",
                1,
            )
        ],
        "",
        "",
    ),
    (
        "s07",
        "xcconfig not secret-scanned",
        "probes/secrets.py",
        [(" *.xcconfig", "", 1)],
        "",
        "",
    ),
    (
        "s09",
        "one-line catch with a body read as swallowed",
        "probes/observability.py",
        [(' and line.rstrip().endswith("{")', "", 1)],
        "",
        "",
    ),
    (
        "s10",
        "route verb matched inside a word",
        "probes/surface.py",
        [(r'r"(\b(GET|', 'r"((GET|', 1)],
        "",
        "",
    ),
    (
        "s08",
        "try? not counted",
        "probes/standards.py",
        [('re.compile(r"\\btry\\?")', 're.compile(r"\\btry\\?NEVER")', 1)],
        "",
        "",
    ),
    (
        "d01",
        "a nested project with its own lock is dropped as a workspace member",
        "probes/base.py",
        [("if not (index[d] & locks) and any(", "if any(", 1)],
        "",
        "",
    ),
    (
        "d02",
        "workspace members without a lock become projects of their own",
        "probes/base.py",
        [
            (
                "any(p in d.parents for p in projects):\n            continue",
                "any(p in d.parents for p in projects):\n            pass",
                1,
            )
        ],
        "",
        "",
    ),
    (
        "d03",
        "manifests below the target root are not indexed",
        "probes/base.py",
        [
            (
                "if rel_path.name in names:",
                'if rel_path.name in names and rel_path.parent == Path("."):',
                1,
            )
        ],
        "",
        "",
    ),
    (
        "d04",
        "nested probe names written into subdirectories of out/",
        "bundle.py",
        [('stem = name.replace("/", "__")', "stem = name", 1)],
        "",
        "",
    ),
    (
        "d05",
        "nested npm project audited from the target root",
        "probes/dependencies.py",
        [
            (
                "        out = run_command(cmd, cwd=d, timeout=timeout)\n        valid_pat = r'\"(auditReportVersion",
                "        out = run_command(cmd, cwd=d.parent, timeout=timeout)\n        valid_pat = r'\"(auditReportVersion",
                1,
            )
        ],
        "",
        "",
    ),
    (
        "d06",
        "composer audits installed packages instead of the lock",
        "probes/dependencies.py",
        [('            "--locked",\n', "", 1)],
        "",
        "",
    ),
    (
        "d07",
        "composer audits the target dir, reading its config",
        "probes/dependencies.py",
        [
            (
                "out = run_command(cmd, cwd=work, timeout=timeout)",
                "out = run_command(cmd, cwd=d, timeout=timeout)",
                1,
            )
        ],
        "",
        "",
    ),
    (
        "d08",
        "composer.json config block (advisory ignores) kept in the audited copy",
        "probes/dependencies.py",
        [('data.pop("config", None)', "pass", 1)],
        "",
        "",
    ),
    (
        "d09",
        "composer failure without a report reads as a result",
        "probes/dependencies.py",
        [("ok_exits=[0, 1, 2, 3], valid_pat=r'\"advisories\"\\s*:')", "ok_exits=[0, 1, 2, 3])", 1)],
        "",
        "",
    ),
    (
        "d10",
        "composer runs without a lock",
        "probes/dependencies.py",
        [('if not (d / "composer.lock").is_file():', "if False:", 1)],
        "",
        "",
    ),
    (
        "d11",
        "govulncheck report without SBOM reads as a scan",
        "probes/dependencies.py",
        [("out, valid_pat=r'\"SBOM\"\\s*:')", "out)", 1)],
        "",
        "",
    ),
    (
        "d12",
        "govulncheck runs in text mode",
        "probes/dependencies.py",
        [('"govulncheck", "-format", "json", "./..."', '"govulncheck", "./..."', 1)],
        "",
        "",
    ),
    (
        "d13",
        "bundler-audit reads the target's .bundler-audit.yml",
        "probes/dependencies.py",
        [('"--format", "json", "--config", str(config)]', '"--format", "json"]', 1)],
        "",
        "",
    ),
    (
        "d14",
        "garbage Gemfile.lock audited and reported clean",
        "probes/dependencies.py",
        [('elif "specs:" not in _read(lock):', "elif False:", 1)],
        "",
        "",
    ),
    (
        "d15",
        "bundler-audit failure without a report reads as a result",
        "probes/dependencies.py",
        [("ok_exits=[0, 1], valid_pat=r'\"results\"\\s*:')", "ok_exits=[0, 1])", 1)],
        "",
        "",
    ),
    (
        "d16",
        "nested Xcode Package.resolved is not a Swift project",
        "probes/dependencies.py",
        [
            (
                '    {"Package.swift", "Package.resolved", "Podfile.lock"},\n',
                '    {"Package.swift", "Podfile.lock"},\n',
                1,
            )
        ],
        "",
        "",
    ),
    (
        "d17",
        "nested npm license rows all named for the root",
        "probes/compliance.py",
        [('project_probe("dep-licenses", proj)', '"dep-licenses"', 1)],
        "",
        "",
    ),
]


def apply_mutation(file_path: Path, subs: list[tuple[str, str, int]]) -> str:
    """Read file, apply count-checked substitutions, write, and return original content."""
    original = file_path.read_text(encoding="utf-8")
    mutated = original
    for old, new, expected_count in subs:
        actual_count = mutated.count(old)
        if actual_count != expected_count:
            raise ValueError(
                f"Substitution count mismatch in {file_path.name}: "
                f"expected {expected_count} occurrence(s) of '{old[:30]}...', found {actual_count}"
            )
        mutated = mutated.replace(old, new, expected_count)
    file_path.write_text(mutated, encoding="utf-8")
    return original


def run_one_mutant(
    m_id: str,
    desc: str,
    file_rel: str,
    subs: list[tuple[str, str, int]],
    env_overrides: dict[str, str] | None = None,
) -> tuple[str, str, str]:
    """Test one mutant in an isolated copy of src."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_src = Path(tmp_dir) / "src"
        shutil.copytree(ROOT / "src", tmp_src)
        target_file = tmp_src / "auditor" / file_rel

        try:
            apply_mutation(target_file, subs)
        except Exception as e:
            return m_id, "ERROR", f"{desc} (failed to apply: {e})"

        # Run pytest with PYTHONPATH pointing to mutated src
        env = os.environ.copy()
        env["PYTHONPATH"] = str(tmp_src)
        if env_overrides:
            env.update(env_overrides)

        res = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "--tb=no"],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

        if res.returncode != 0:
            return m_id, "killed", desc
        else:
            return m_id, "SURVIVED", desc


def cmd_list() -> None:
    for m_id, desc, _, _, req, eq in M:
        print(f"{m_id:<8} {req:<12} {eq:<12} {desc}")


def cmd_run(jobs: int = 6, filter_ids: list[str] | None = None) -> int:
    print("control: unmutated suite")
    ctrl = subprocess.run(
        [sys.executable, "-m", "pytest", "-q"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if ctrl.returncode != 0:
        print("  the unmutated suite fails — fix that first:")
        print(ctrl.stdout)
        print(ctrl.stderr)
        return 1
    print(f"  {ctrl.stdout.strip().splitlines()[-1]}")

    unknown = sorted(set(filter_ids or []) - {m[0] for m in M})
    if unknown:
        print(f"  no such mutant: {' '.join(unknown)}")
        return 2
    mutants_to_run = [m for m in M if not filter_ids or m[0] in filter_ids]
    print(f"running {len(mutants_to_run)} mutants, {jobs} at a time\n")

    results: list[tuple[str, str, str]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=jobs) as pool:
        futures = {
            pool.submit(run_one_mutant, m[0], m[1], m[2], m[3]): m[0] for m in mutants_to_run
        }
        for fut in concurrent.futures.as_completed(futures):
            results.append(fut.result())

    # Sort results matching M order
    order = {m[0]: idx for idx, m in enumerate(M)}
    results.sort(key=lambda r: order.get(r[0], 999))

    killed = sum(1 for _, res, _ in results if res == "killed")
    survived = sum(1 for _, res, _ in results if res == "SURVIVED")
    errors = sum(1 for _, res, _ in results if res == "ERROR")

    print(f"{'mutant':<10} {'result':<12} description")
    for m_id, res, desc in results:
        print(f"{m_id:<10} {res:<12} {desc}")

    print(f"\nkilled {killed} · survived {survived} · errors {errors}")
    if survived > 0 or errors > 0:
        return 1
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Auditor mutation testing harness.")
    subparsers = parser.add_subparsers(dest="cmd")

    subparsers.add_parser("list", help="List all mutations")

    run_parser = subparsers.add_parser("run", help="Run mutation testing")
    run_parser.add_argument("-j", "--jobs", type=int, default=6, help="Parallel jobs (default: 6)")
    run_parser.add_argument("ids", nargs="*", help="Optional mutant IDs to run")

    args = parser.parse_args()
    if args.cmd == "list":
        cmd_list()
    elif args.cmd == "run":
        sys.exit(cmd_run(jobs=args.jobs, filter_ids=args.ids))
    else:
        parser.print_help()
        sys.exit(2)


if __name__ == "__main__":
    main()
