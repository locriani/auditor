"""mutations.py — domain-specific mutation testing suite for auditor.

Each mutation is a literal, count-checked substitution in the Python source code
that breaks one specific behaviour. A mutant the test suite still passes is a
behaviour no test pins.

    uv run python dev/mutations.py run [-j JOBS] [ID ...]
    uv run python dev/mutations.py list

Numbering:
  m01–m58 are the core contract & regression mutations
  n01–n03 are the security gate mutations
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
        [('ui_evidence="src/Services/CareTeamService.php:565"', 'ui_evidence="CareTeamService.php"', 1)],
        "",
        "",
    ),
    (
        "u03",
        "AJAX fragment Immunizations table corrupted",
        "ui_path/analyzer.py",
        [('table="immunizations",\n                    columns=["id", "immunization_id"', 'table="lists",\n                    columns=["id", "immunization_id"', 1)],
        "",
        "",
    ),
    (
        "u04",
        "MRN drops identifier type v2-0203|PT",
        "ui_path/analyzer.py",
        [('v2-0203|PT', 'generic_mrn', 1)],
        "",
        "",
    ),
    (
        "u05",
        "observed flag elevation disabled",
        "ui_path/analyzer.py",
        [('confidence = ConfidenceLevel.OBSERVED if self.observed else', 'confidence =', 5)],
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
