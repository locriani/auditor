"""CLI entry point for UI data-path audit."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Annotated

import typer

from auditor.ui_path.analyzer import OpenEMRScreenAnalyzer
from auditor.ui_path.formatters import format_json, format_parity_table

app = typer.Typer(
    name="auditor-ui-path",
    help="Audit a UI screen's data paths, storage reads, write paths, and API parity.",
    add_completion=False,
)


@app.command()
def main(
    screen: Annotated[
        str,
        typer.Argument(
            help="Relative or absolute path to the screen file to audit (e.g. interface/patient_file/summary/demographics.php).",
            metavar="<screen-path>",
        ),
    ],
    target_dir: Annotated[
        str | None,
        typer.Option(
            "-t",
            "--target-dir",
            help="Root directory of the application codebase. Defaults to OPENEMR_ROOT or target parent.",
            metavar="<dir>",
        ),
    ] = None,
    output: Annotated[
        str | None,
        typer.Option(
            "-o",
            "--output",
            help="Output file path to write results to. Defaults to stdout.",
            metavar="<file>",
        ),
    ] = None,
    output_format: Annotated[
        str,
        typer.Option(
            "-f",
            "--format",
            help="Output format: 'json', 'markdown', or 'both'. Defaults to 'both'.",
        ),
    ] = "both",
    observed: Annotated[
        bool,
        typer.Option(
            "--observed",
            help="Opt-in dynamic verification pass against running app to confirm API responses.",
        ),
    ] = False,
) -> None:
    """Run UI data-path audit against <screen-path>."""
    # Resolve target root
    root: Path | None = None
    if target_dir:
        root = Path(target_dir).resolve()
    elif "OPENEMR_ROOT" in os.environ:
        root = Path(os.environ["OPENEMR_ROOT"]).resolve()
    else:
        # Check standard location or deduce from screen path
        candidate = Path("/Users/locriani/Developer/Gauntlet/Projects/agentic-openemr/openemr-base-clean")
        if candidate.exists():
            root = candidate
        else:
            p = Path(screen).resolve()
            if p.is_file():
                # Walk up to find root
                for parent in p.parents:
                    if (parent / "interface").exists() or (parent / "composer.json").exists():
                        root = parent
                        break
            if not root:
                root = Path.cwd().resolve()

    if not root.exists() or not root.is_dir():
        sys.stderr.write(f"Target directory not found: {root}\n")
        sys.exit(2)

    # Normalize relative screen path if absolute
    screen_path = Path(screen)
    if screen_path.is_absolute():
        try:
            rel_screen = str(screen_path.relative_to(root))
        except ValueError:
            rel_screen = screen
    else:
        rel_screen = screen

    analyzer = OpenEMRScreenAnalyzer(target_root=root, observed=observed)
    report = analyzer.audit_screen(rel_screen)

    # Generate output
    fmt = output_format.lower().strip()
    result_parts: list[str] = []
    if fmt in ("json", "both"):
        result_parts.append(format_json(report))
    if fmt in ("markdown", "both"):
        result_parts.append(format_parity_table(report))

    output_text = "\n\n".join(result_parts) if len(result_parts) > 1 else result_parts[0]

    if output:
        out_file = Path(output)
        out_file.parent.mkdir(parents=True, exist_ok=True)
        out_file.write_text(output_text, encoding="utf-8")
        sys.stderr.write(f"Wrote audit report to {out_file}\n")
    else:
        sys.stdout.write(output_text)
        if not output_text.endswith("\n"):
            sys.stdout.write("\n")


if __name__ == "__main__":
    app()
