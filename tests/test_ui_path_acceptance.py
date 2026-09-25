"""Acceptance tests for the OpenEMR Patient Dashboard audit.

Acceptance criteria:
- The four defects are fixed, proven by tests.
- On the fork, the header and the five cards #201 trace to FHIR with file:line evidence:
  - Allergies -> AllergyIntolerance
  - Problems -> Condition, category=problem-list-item
  - Medications and Prescriptions -> MedicationRequest, from lists ∪ prescriptions union in PrescriptionService.php:91-260
  - Care Team -> CareTeam, plus Practitioner read for display names
- Header facts:
  - Patient.active is hard-coded true (FhirPatientService.php:212)
  - MRN is identifier of type v2-0203|PT
"""

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


def test_acceptance_criteria(analyzer: OpenEMRScreenAnalyzer) -> None:
    """Validate full acceptance criteria on openemr-base-clean."""
    report = analyzer.audit_screen("interface/patient_file/summary/demographics.php")
    assert report.items, "Report must contain items"

    cards = {i.card: i for i in report.items if i.kind == ItemKind.CARD and i.card}

    # 1. Allergies -> AllergyIntolerance
    allergy = cards.get("Allergies")
    assert allergy is not None
    assert allergy.api is not None
    assert allergy.api.resource == "AllergyIntolerance"
    assert any(":" in ev for ev in allergy.api.evidence), "Must carry file:line evidence"

    # 2. Problems -> Condition, category=problem-list-item
    problems = cards.get("Medical Problems")
    assert problems is not None
    assert problems.api is not None
    assert problems.api.resource == "Condition"
    assert any("category=problem-list-item" in ev or "category=problem-list-item" in (problems.api.path or "") for ev in problems.api.evidence)
    assert any(":" in ev for ev in problems.api.evidence), "Must carry file:line evidence"

    # 3. Medications and Prescriptions -> MedicationRequest, from lists ∪ prescriptions union in PrescriptionService.php:91-260
    meds = cards.get("Medications")
    assert meds is not None
    assert meds.api is not None
    assert meds.api.resource == "MedicationRequest"
    assert any("PrescriptionService.php:91" in ev for ev in meds.api.evidence), "Must cite PrescriptionService union"

    rx = cards.get("Prescriptions")
    assert rx is not None
    assert rx.api is not None
    assert rx.api.resource == "MedicationRequest"
    assert any("PrescriptionService.php:91" in ev for ev in rx.api.evidence), "Must cite PrescriptionService union"

    # 4. Care Team -> CareTeam, plus Practitioner read for display names
    care_team = cards.get("Care Team")
    assert care_team is not None
    assert care_team.api is not None
    assert care_team.api.resource == "CareTeam"
    assert any("Practitioner" in ev for ev in care_team.api.evidence), "Must cite Practitioner read for display names"

    # 5. Header facts
    header_items = [i for i in report.items if i.kind == ItemKind.HEADER]
    mrn_items = [i for i in header_items if "pubpid" in i.item_id]
    assert mrn_items, "MRN header item must be present"
    mrn = mrn_items[0]
    assert mrn.api is not None
    assert mrn.api.resource == "Patient"
    assert any("Patient.active" in ev and "true" in ev and "FhirPatientService.php:212" in ev for ev in mrn.api.evidence)
    assert any("v2-0203|PT" in ev and "FhirPatientService.php:555" in ev for ev in mrn.api.evidence)

    # 6. Verify EVERY trace carries evidence as file:line, never a bare file name
    for item in report.items:
        all_evidence = list(item.evidence)
        if item.storage:
            all_evidence.extend(item.storage.evidence)
        if item.api:
            all_evidence.extend(item.api.evidence)
        if item.write_path:
            all_evidence.append(item.write_path.file_line)

        for ev in all_evidence:
            # Check that any referenced PHP or Twig file has a line number colon
            if ".php" in ev or ".twig" in ev:
                assert ":" in ev, f"Evidence '{ev}' must carry file:line, not a bare filename"
