"""Pytest fixtures and test helpers for auditor test suite."""

from __future__ import annotations

import csv
import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from typer.testing import CliRunner

from auditor.cli import app


@pytest.fixture
def cli_runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def temp_target(tmp_path: Path) -> Path:
    """Creates a temporary target directory."""
    target = tmp_path / "target"
    target.mkdir(parents=True, exist_ok=True)
    return target


@pytest.fixture
def temp_bundle(tmp_path: Path) -> Path:
    """Creates a temporary bundle path."""
    return tmp_path / "bundle"


class ManifestHelper:
    def __init__(self, bundle_dir: Path) -> None:
        self.bundle_dir = bundle_dir
        self.manifest_file = bundle_dir / "manifest.tsv"
        self.env_file = bundle_dir / "env.txt"
        self.summary_file = bundle_dir / "summary.txt"

    def rows(self) -> list[dict[str, str]]:
        if not self.manifest_file.is_file():
            return []
        with open(self.manifest_file, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f, delimiter="\t")
            return list(reader)

    def row(self, probe_name: str) -> dict[str, str]:
        for r in self.rows():
            if r["probe"] == probe_name:
                return r
        raise KeyError(f"Probe '{probe_name}' not found in manifest")

    def status(self, probe_name: str) -> str:
        return self.row(probe_name)["status"]

    def note(self, probe_name: str) -> str:
        return self.row(probe_name)["note"]

    def out_content(self, probe_name: str) -> str:
        p = self.bundle_dir / "out" / f"{probe_name}.txt"
        return p.read_text(encoding="utf-8") if p.is_file() else ""


@pytest.fixture
def run_probe(tmp_path: Path) -> Iterator[any]:
    """Helper function to run auditor-probe and return ManifestHelper."""

    def _run(target: Path, *extra_args: str) -> ManifestHelper:
        bundle_dir = tmp_path / f"bundle_{os.urandom(4).hex()}"
        runner = CliRunner()
        cmd = [str(target), "-o", str(bundle_dir), *extra_args]
        res = runner.invoke(app, cmd)
        assert res.exit_code == 0, (
            f"auditor-probe failed ({res.exit_code}): {res.stderr}\n{res.stdout}"
        )
        return ManifestHelper(bundle_dir)

    yield _run


@pytest.fixture
def mock_bin_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Provides a directory at the front of PATH for mock executables."""
    bin_dir = tmp_path / "mock_bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    orig_path = os.environ.get("PATH", "")
    monkeypatch.setenv("PATH", f"{bin_dir}:{orig_path}")
    return bin_dir
