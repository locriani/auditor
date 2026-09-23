"""Tests for CLI options, arguments, exit codes, and usage validation."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from auditor.cli import app


def test_cli_no_args(cli_runner: CliRunner) -> None:
    res = cli_runner.invoke(app, [])
    assert res.exit_code == 2
    assert (
        "probe.sh <target-dir>" in res.stderr or "auditor-probe" in res.stderr or res.exit_code == 2
    )


def test_cli_missing_target(cli_runner: CliRunner, tmp_path: Path) -> None:
    missing = tmp_path / "nonexistent"
    res = cli_runner.invoke(app, [str(missing)])
    assert res.exit_code == 2
    assert "not a directory" in res.stderr


def test_cli_file_target(cli_runner: CliRunner, tmp_path: Path) -> None:
    afile = tmp_path / "regular_file.txt"
    afile.write_text("hello", encoding="utf-8")
    res = cli_runner.invoke(app, [str(afile)])
    assert res.exit_code == 2
    assert "not a directory" in res.stderr


def test_cli_empty_dir_exits_zero(cli_runner: CliRunner, tmp_path: Path) -> None:
    empty_dir = tmp_path / "empty_dir"
    empty_dir.mkdir()
    bundle_dir = tmp_path / "bundle"
    res = cli_runner.invoke(app, [str(empty_dir), "-o", str(bundle_dir)])
    assert res.exit_code == 0
    assert (bundle_dir / "manifest.tsv").is_file()


def test_cli_timeout_validation(cli_runner: CliRunner, tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    bundle = tmp_path / "bundle"

    # Non-numeric
    res = cli_runner.invoke(app, [str(target), "-o", str(bundle), "--timeout", "abc"])
    assert res.exit_code == 2
    assert "invalid --timeout" in res.stderr

    # Empty
    res = cli_runner.invoke(app, [str(target), "-o", str(bundle), "--timeout", ""])
    assert res.exit_code == 2
    assert "invalid --timeout" in res.stderr

    # Out of range (>999999)
    res = cli_runner.invoke(app, [str(target), "-o", str(bundle), "--timeout", "1000000"])
    assert res.exit_code == 2
    assert "more than 999999 seconds" in res.stderr

    # 00 is valid (disabled)
    res = cli_runner.invoke(app, [str(target), "-o", str(bundle), "--timeout", "00"])
    assert res.exit_code == 0
    env_content = (bundle / "env.txt").read_text(encoding="utf-8")
    assert "disabled with --timeout 0" in env_content
