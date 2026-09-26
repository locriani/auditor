"""Tests pinning the 4 known reference defects for UI data-path audit.

Each test verifies that the UI data-path audit engine corrects the flaw in the
reference Babashka tool:
1. Care Team storage: reads care_teams + care_team_member via CareTeamService:550, not patient_data.care_team_*.
2. AJAX fragment loaders: demographics.php:606-732 followed to stats.php:272-314 for Immunizations.
3. Persistent header: patient_data_template.php:100-112 populated by setMyPatient() in demographics.php:916-967.
4. Intra-card columns: Allergy severity, Prescription Qty/Refills/Filled, Care Team role/facility/since/status.
"""


import pytest
from conftest import OPENEMR_CLEAN_DIR

from auditor.ui_path.analyzer import OpenEMRScreenAnalyzer
from auditor.ui_path.models import ItemKind


@pytest.fixture
def analyzer() -> OpenEMRScreenAnalyzer:
    if not OPENEMR_CLEAN_DIR.exists():
        pytest.skip(f"OpenEMR clean tree not found at {OPENEMR_CLEAN_DIR}")
    return OpenEMRScreenAnalyzer(target_root=OPENEMR_CLEAN_DIR)


def test_defect_1_care_team_storage_and_fhir_trace(analyzer: OpenEMRScreenAnalyzer) -> None:
    """Defect 1: Care Team card traced to care_teams + care_team_member via CareTeamService::getCareTeamData (line 550).

    The reference incorrectly traced Care Team to patient_data.care_team_*.
    """
    report = analyzer.audit_screen("interface/patient_file/summary/demographics.php")
    care_team_items = [i for i in report.items if i.card == "Care Team" and i.kind == ItemKind.CARD]
    assert len(care_team_items) == 1, "Care Team card must be cataloged"

    card = care_team_items[0]
    assert card.storage is not None, "Care Team storage must be populated"
    assert card.storage.table == "care_teams", f"Expected storage table 'care_teams', got '{card.storage.table}'"
    assert "care_team_member" in card.storage.joins, "Storage joins must include care_team_member"
    assert any("src/Services/CareTeamService.php:550" in ev for ev in card.storage.evidence), (
        f"Storage evidence must cite CareTeamService.php:550: {card.storage.evidence}"
    )

    assert card.api is not None, "Care Team API ref must be populated"
    assert card.api.resource == "CareTeam", f"Expected FHIR resource 'CareTeam', got '{card.api.resource}'"
    assert any("src/Services/FHIR/FhirCareTeamService.php" in ev for ev in card.api.evidence)
    assert any("Practitioner" in ev for ev in card.api.evidence), "Must cite Practitioner read for display names"


def test_defect_2_ajax_fragment_immunizations(analyzer: OpenEMRScreenAnalyzer) -> None:
    """Defect 2: AJAX fragment loaders followed from demographics.php:606-732 to stats.php:272-314.

    The reference completely missed cards rendered by AJAX fragments like Immunizations.
    """
    report = analyzer.audit_screen("interface/patient_file/summary/demographics.php")
    imx_items = [i for i in report.items if i.card == "Immunizations" and i.kind == ItemKind.CARD]
    assert len(imx_items) == 1, "Immunizations card from stats.php fragment must be cataloged"

    imx = imx_items[0]
    assert imx.storage is not None
    assert imx.storage.table == "immunizations"
    assert any("interface/patient_file/summary/stats.php:277" in ev or "stats.php:272" in ev for ev in imx.storage.evidence)
    assert any("interface/patient_file/summary/demographics.php:606" in ev for ev in imx.evidence), (
        "Evidence must cite fragment loader in demographics.php:606"
    )

    assert imx.api is not None
    assert imx.api.resource == "Immunization"
    assert imx.rendering_rules is not None
    assert imx.rendering_rules.empty_state is not None
    assert "None{{Immunizations}}" in imx.rendering_rules.empty_state


def test_defect_3_persistent_header_patient_data(analyzer: OpenEMRScreenAnalyzer) -> None:
    """Defect 3: Persistent header (patient_data_template.php:100-112 filled by setMyPatient in demographics.php:916-967).

    The reference omitted the persistent Knockout header.
    """
    report = analyzer.audit_screen("interface/patient_file/summary/demographics.php")
    header_items = [i for i in report.items if i.kind == ItemKind.HEADER]
    assert len(header_items) >= 3, f"Expected at least 3 header items (pname, pubpid, DOB), found {len(header_items)}"

    # Check MRN / pubpid item
    mrn_items = [i for i in header_items if "pubpid" in i.item_id or "mrn" in i.item_id.lower() or "identifier" in i.label.lower() or "MRN" in i.label]
    assert len(mrn_items) >= 1, "MRN / pubpid must be in header items"
    mrn = mrn_items[0]
    assert mrn.storage is not None
    assert mrn.storage.table == "patient_data"
    assert "pubpid" in mrn.storage.columns
    assert any("demographics.php:925" in ev for ev in mrn.evidence)
    assert any("patient_data_template.php:102" in ev for ev in mrn.evidence)

    assert mrn.api is not None
    assert mrn.api.resource == "Patient"
    assert mrn.api.path == "Patient.identifier"
    assert any("v2-0203|PT" in ev or "PT" in ev for ev in mrn.api.evidence), "MRN must record identifier type v2-0203|PT"

    # Verify Patient.active is recorded as hard-coded true
    active_facts = [ev for i in header_items if i.api for ev in i.api.evidence if "Patient.active" in ev and "true" in ev]
    assert len(active_facts) >= 1, "Must record that Patient.active is hard-coded true at FhirPatientService.php:212"


def test_defect_4_card_column_level_traces(analyzer: OpenEMRScreenAnalyzer) -> None:
    """Defect 4: Intra-card columns cataloged with individual traces.

    The reference lacked intra-card columns:
    - Allergy severity
    - Prescription Qty/Refills/Filled
    - Care Team role/facility/since/status
    """
    report = analyzer.audit_screen("interface/patient_file/summary/demographics.php")
    columns = [i for i in report.items if i.kind == ItemKind.COLUMN]

    # Care Team columns: role, facility, since, status
    ct_columns = {i.label: i for i in columns if i.card == "Care Team"}
    for expected in ["Role", "Facility", "Since", "Status"]:
        matching = [label for label in ct_columns if expected.lower() in label.lower()]
        assert matching, f"Care Team column '{expected}' must be cataloged; found {list(ct_columns.keys())}"

    # Allergy severity column
    allergy_cols = [i for i in columns if i.card == "Allergies" and "severity" in i.label.lower()]
    assert allergy_cols, "Allergy severity column must be cataloged"
    assert allergy_cols[0].storage is not None
    assert "severity_al" in allergy_cols[0].storage.columns
    assert any("stats.php:89" in ev or "stats.php:98" in ev for ev in allergy_cols[0].storage.evidence)
    assert allergy_cols[0].api is not None
    assert allergy_cols[0].api.resource == "AllergyIntolerance"

    # Prescription Qty / Refills / Filled columns
    rx_columns = [i for i in columns if i.card in ("Prescriptions", "Current Medications")]
    rx_labels = [i.label.lower() for i in rx_columns]
    for expected in ["qty", "refill", "fill"]:
        assert any(expected in lbl for lbl in rx_labels), f"Prescription column '{expected}' missing; found {rx_labels}"
