"""Tests for line capping, .full.txt creation, and TRUNCATED notes."""

from __future__ import annotations

from pathlib import Path

from auditor.bundle import BundleManager
from auditor.models import ProbeAxis, ProbeOutput


def test_truncation_over_cap(temp_target: Path, temp_bundle: Path) -> None:
    bm = BundleManager(temp_target, temp_bundle)
    content = "".join(f"line {i}\n" for i in range(1, 26))  # 25 lines

    rec = bm.record_probe(
        "cap_test", ProbeAxis.PERFORMANCE.value, ProbeOutput(0, content, ""), cap=10
    )
    assert "TRUNCATED: 10 of 25 lines shown" in rec.note

    out_file = temp_bundle / "out" / "cap_test.txt"
    full_file = temp_bundle / "out" / "cap_test.full.txt"

    assert out_file.is_file()
    assert full_file.is_file()

    out_lines = out_file.read_text(encoding="utf-8").splitlines()
    assert len(out_lines) == 10
    assert out_lines[0] == "line 1"
    assert out_lines[-1] == "line 10"

    full_lines = full_file.read_text(encoding="utf-8").splitlines()
    assert len(full_lines) == 25


def test_truncation_exact_and_under_cap(temp_target: Path, temp_bundle: Path) -> None:
    bm = BundleManager(temp_target, temp_bundle)

    # Exactly at cap
    exact_content = "".join(f"line {i}\n" for i in range(1, 11))
    rec1 = bm.record_probe(
        "exact_cap", ProbeAxis.PERFORMANCE.value, ProbeOutput(0, exact_content, ""), cap=10
    )
    assert not rec1.note.startswith("TRUNCATED")
    assert not (temp_bundle / "out" / "exact_cap.full.txt").exists()

    # Under cap
    under_content = "".join(f"line {i}\n" for i in range(1, 6))
    rec2 = bm.record_probe(
        "under_cap", ProbeAxis.PERFORMANCE.value, ProbeOutput(0, under_content, ""), cap=10
    )
    assert not rec2.note.startswith("TRUNCATED")
    assert not (temp_bundle / "out" / "under_cap.full.txt").exists()
