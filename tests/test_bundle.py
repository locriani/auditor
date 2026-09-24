"""Tests for bundle directory security, marker files, and path confinement."""

from __future__ import annotations

import stat
from pathlib import Path

import pytest
from typer.testing import CliRunner

from auditor.cli import app


def test_bundle_permissions_and_marker(cli_runner: CliRunner, tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    bundle = tmp_path / "bundle"

    res = cli_runner.invoke(app, [str(target), "-o", str(bundle)])
    assert res.exit_code == 0

    mode = stat.S_IMODE(bundle.stat().st_mode)
    assert mode == 0o700, f"Expected 0700, got {oct(mode)}"

    marker_file = bundle / ".codebase-audit-bundle"
    assert marker_file.is_file()
    assert "safe for auditor-probe to clear on reuse" in marker_file.read_text(encoding="utf-8")


def test_bundle_refuses_regular_file(cli_runner: CliRunner, tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    bundle_file = tmp_path / "afile"
    bundle_file.write_text("hello", encoding="utf-8")

    res = cli_runner.invoke(app, [str(target), "-o", str(bundle_file)])
    assert res.exit_code == 2
    assert "exists and is not a directory" in res.stderr


def test_bundle_refuses_unmarked_nonempty_directory(cli_runner: CliRunner, tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    bundle_dir = tmp_path / "foreign_bundle"
    bundle_dir.mkdir()
    (bundle_dir / "somefile.txt").write_text("preexisting", encoding="utf-8")

    res = cli_runner.invoke(app, [str(target), "-o", str(bundle_dir)])
    assert res.exit_code == 2
    assert "not empty and was not created by auditor-probe" in res.stderr


def test_bundle_reuse_clears_out_directory(cli_runner: CliRunner, tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    bundle_dir = tmp_path / "reused_bundle"

    # First run creates bundle
    res1 = cli_runner.invoke(app, [str(target), "-o", str(bundle_dir)])
    assert res1.exit_code == 0

    # Put a stale file in out/
    stale_file = bundle_dir / "out" / "stale.txt"
    stale_file.write_text("old data", encoding="utf-8")

    # Second run should clear out/
    res2 = cli_runner.invoke(app, [str(target), "-o", str(bundle_dir)])
    assert res2.exit_code == 0
    assert not stale_file.exists()


def test_bundle_refuses_inside_target(cli_runner: CliRunner, tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    bundle_inside = target / "bundle"

    res = cli_runner.invoke(app, [str(target), "-o", str(bundle_inside)])
    assert res.exit_code == 2
    assert "is inside the target" in res.stderr


def test_bundle_refuses_naming_target_itself(cli_runner: CliRunner, tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()

    res = cli_runner.invoke(app, [str(target), "-o", str(target)])
    assert res.exit_code == 2
    assert "is inside the target" in res.stderr


def test_bundle_refuses_symlink_into_target(cli_runner: CliRunner, tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    link_to_target = tmp_path / "link_target"
    try:
        link_to_target.symlink_to(target)
    except OSError:
        return  # Symlinks not supported

    res = cli_runner.invoke(app, [str(target), "-o", str(link_to_target / "sub_bundle")])
    assert res.exit_code == 2
    assert "is inside the target" in res.stderr


def test_cdpath_export_does_not_interfere(
    cli_runner: CliRunner, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "target"
    target.mkdir()
    bundle = tmp_path / "bundle"
    monkeypatch.setenv("CDPATH", str(tmp_path))

    res = cli_runner.invoke(app, [str(target), "-o", str(bundle)])
    assert res.exit_code == 0
    assert (bundle / "manifest.tsv").is_file()
