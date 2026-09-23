"""Tests for probe status classification and manifest TSV formatting."""

from __future__ import annotations

from pathlib import Path

from auditor.bundle import BundleManager
from auditor.models import ProbeAxis, ProbeOutput, ProbeStatus


def test_manifest_columns_and_empty_target(temp_target: Path, temp_bundle: Path, run_probe) -> None:
    manifest = run_probe(temp_target)
    rows = manifest.rows()
    assert len(rows) > 0

    expected_cols = ["probe", "axis", "status", "exit", "bytes", "lines", "stderr", "file", "note"]
    with open(manifest.manifest_file, encoding="utf-8") as f:
        header = f.readline().rstrip("\r\n").split("\t")
        assert header == expected_cols

    for r in rows:
        assert list(r.keys()) == expected_cols
        assert r["status"] in ("ok", "empty", "n/a", "error", "output")

    # Empty target should produce zero error rows
    error_rows = [r["probe"] for r in rows if r["status"] == "error"]
    assert not error_rows, f"Empty target produced unexpected error rows: {error_rows}"


def test_status_classification_rules(temp_target: Path, temp_bundle: Path) -> None:
    bm = BundleManager(temp_target, temp_bundle)

    # 1. Expected exit (0) + bytes > 0 -> ok
    rec1 = bm.record_probe("p1", ProbeAxis.SECURITY.value, ProbeOutput(0, "content\n", ""))
    assert rec1.status == ProbeStatus.OK
    assert rec1.note == "see output file"

    # 2. Expected exit (0) + bytes == 0 + no stderr -> empty ("ran clean, produced no output")
    rec2 = bm.record_probe("p2", ProbeAxis.SECURITY.value, ProbeOutput(0, "", ""))
    assert rec2.status == ProbeStatus.EMPTY
    assert "ran clean" in rec2.note

    # 3. Expected exit (0) + bytes == 0 + stderr present -> empty with warning
    rec3 = bm.record_probe("p3", ProbeAxis.SECURITY.value, ProbeOutput(0, "", "some warning\n"))
    assert rec3.status == ProbeStatus.EMPTY
    assert "produced no output, but wrote stderr" in rec3.note

    # 4. Nonzero exit + stdout present -> output
    rec4 = bm.record_probe(
        "p4", ProbeAxis.SECURITY.value, ProbeOutput(1, "findings\nsecond line\n", "")
    )
    assert rec4.status == ProbeStatus.OUTPUT
    assert rec4.exit == "1"
    assert rec4.lines == 2
    assert rec4.bytes == 21
    assert "produced output — read it, do not discard" in rec4.note
    tsv_cols = rec4.to_tsv_row().split("\t")
    assert tsv_cols[3] == "1", "Exit column must match"
    assert tsv_cols[4] == "21", "Bytes column must match"
    assert tsv_cols[5] == "2", "Lines column must match"

    # 5. Nonzero exit + no stdout -> error
    rec5 = bm.record_probe("p5", ProbeAxis.SECURITY.value, ProbeOutput(2, "", "error msg\n"))
    assert rec5.status == ProbeStatus.ERROR
    assert "error msg" in rec5.note

    # 6. Timed out
    rec6 = bm.record_probe(
        "p6", ProbeAxis.SECURITY.value, ProbeOutput(124, "partial", "", timed_out=True)
    )
    assert rec6.status == ProbeStatus.ERROR
    assert "TIMED OUT" in rec6.note

    # 7. Valid pattern not matched
    rec7 = bm.record_probe(
        "p7",
        ProbeAxis.SUPPLY_CHAIN.value,
        ProbeOutput(1, '{"error": {"code": "ENOLOCK"}}', ""),
        ok_exits=[0, 1],
        valid_pat=r'"(auditReportVersion|vulnerabilities)"\s*:',
    )
    assert rec7.status == ProbeStatus.ERROR
    assert "printed no report" in rec7.note
