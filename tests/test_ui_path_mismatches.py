"""Tests for API vs Screen mismatch detection in UI data-path audit."""

from pathlib import Path

import pytest

from auditor.ui_path.analyzer import OpenEMRScreenAnalyzer
from auditor.ui_path.models import ItemKind

OPENEMR_CLEAN_DIR = Path("/Users/locriani/Developer/Gauntlet/Projects/agentic-openemr/openemr-base-clean")


@pytest.fixture
def analyzer() -> OpenEMRScreenAnalyzer:
    if not OPENEMR_CLEAN_DIR.exists():
        pytest.skip(f"OpenEMR clean tree not found at {OPENEMR_CLEAN_DIR}")
    return OpenEMRScreenAnalyzer(target_root=OPENEMR_CLEAN_DIR)


def test_care_team_inactive_status_mismatch(analyzer: OpenEMRScreenAnalyzer) -> None:
    """Flag mismatch where Care Team hides inactive members and FHIR CareTeam returns them.

    Both sides must carry file:line evidence:
    - UI: src/Services/CareTeamService.php:565
    - FHIR: src/Services/CareTeamService.php:190
    """
    report = analyzer.audit_screen("interface/patient_file/summary/demographics.php")
    ct_card = next(i for i in report.items if i.card == "Care Team" and i.kind == ItemKind.CARD)

    assert len(ct_card.mismatches) >= 1, "Care Team card must have at least one API mismatch flagged"
    mismatch = ct_card.mismatches[0]

    assert "inactive" in mismatch.ui_behavior.lower() or "status" in mismatch.ui_behavior.lower()
    assert "src/Services/CareTeamService.php:565" in mismatch.ui_evidence
    assert "src/Services/CareTeamService.php:190" in mismatch.api_evidence
    assert ":" in mismatch.ui_evidence, "UI evidence must carry file:line"
    assert ":" in mismatch.api_evidence, "API evidence must carry file:line"
