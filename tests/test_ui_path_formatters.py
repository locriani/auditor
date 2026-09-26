"""Tests for formatters (Markdown parity table and JSON serialization)."""

import json

import pytest
from conftest import OPENEMR_CLEAN_DIR

from auditor.ui_path.analyzer import OpenEMRScreenAnalyzer
from auditor.ui_path.formatters import format_json, format_parity_table


@pytest.fixture
def analyzer() -> OpenEMRScreenAnalyzer:
    if not OPENEMR_CLEAN_DIR.exists():
        pytest.skip(f"OpenEMR clean tree not found at {OPENEMR_CLEAN_DIR}")
    return OpenEMRScreenAnalyzer(target_root=OPENEMR_CLEAN_DIR)


def test_markdown_parity_table_format(analyzer: OpenEMRScreenAnalyzer) -> None:
    """Parity table has one row per item: Item, Storage, API Path, Confidence, Evidence, Mismatch."""
    report = analyzer.audit_screen("interface/patient_file/summary/demographics.php")
    table = format_parity_table(report)

    assert "| Item | Storage | API Path | Confidence | Evidence | Mismatch |" in table
    assert "dashboard/card/care-team" in table or "Care Team" in table
    assert "care_teams" in table
    assert "CareTeam" in table

    # Verify rows exist for each item
    lines = [line for line in table.splitlines() if line.startswith("|") and not line.startswith("| Item") and not line.startswith("|---")]
    assert len(lines) == len(report.items)


def test_json_serialization_validity(analyzer: OpenEMRScreenAnalyzer) -> None:
    """Report serializes to schema-valid JSON that deserializes cleanly."""
    report = analyzer.audit_screen("interface/patient_file/summary/demographics.php")
    json_str = format_json(report)

    data = json.loads(json_str)
    assert data["screen"] == "interface/patient_file/summary/demographics.php"
    assert "items" in data
    assert len(data["items"]) == len(report.items)
    assert data["summary"]["total_items"] == len(report.items)
