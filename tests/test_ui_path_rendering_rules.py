"""Tests for card rendering rules extraction in UI data-path audit."""


import pytest
from conftest import OPENEMR_CLEAN_DIR

from auditor.ui_path.analyzer import OpenEMRScreenAnalyzer
from auditor.ui_path.models import ItemKind


@pytest.fixture
def analyzer() -> OpenEMRScreenAnalyzer:
    if not OPENEMR_CLEAN_DIR.exists():
        pytest.skip(f"OpenEMR clean tree not found at {OPENEMR_CLEAN_DIR}")
    return OpenEMRScreenAnalyzer(target_root=OPENEMR_CLEAN_DIR)


def test_card_rendering_rules_present(analyzer: OpenEMRScreenAnalyzer) -> None:
    """Verify rendering rules (gate, active filter, sort order, empty state, highlighting)."""
    report = analyzer.audit_screen("interface/patient_file/summary/demographics.php")
    cards = {i.card: i for i in report.items if i.kind == ItemKind.CARD and i.card}

    # Allergies card rules
    allergy = cards.get("Allergies")
    assert allergy is not None
    assert allergy.rendering_rules is not None
    assert allergy.rendering_rules.gate is not None
    assert "aclCheckIssue('allergy')" in allergy.rendering_rules.gate
    assert allergy.rendering_rules.active_filter is not None
    assert "filterActiveIssues" in allergy.rendering_rules.active_filter
    assert allergy.rendering_rules.highlighting is not None
    assert "critical" in allergy.rendering_rules.highlighting or "severity" in allergy.rendering_rules.highlighting

    # Care Team card rules
    ct = cards.get("Care Team")
    assert ct is not None
    assert ct.rendering_rules is not None
    assert ct.rendering_rules.gate is not None
    assert "card_care_team" in ct.rendering_rules.gate
    assert ct.rendering_rules.active_filter is not None
    assert "inactive" in ct.rendering_rules.active_filter

    # Immunizations card rules
    imx = cards.get("Immunizations")
    assert imx is not None
    assert imx.rendering_rules is not None
    assert imx.rendering_rules.gate is not None
    assert "disable_immunizations" in imx.rendering_rules.gate
    assert imx.rendering_rules.empty_state is not None
    assert "None{{Immunizations}}" in imx.rendering_rules.empty_state
