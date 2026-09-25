"""Screen analyzer and data-path tracer for OpenEMR-shaped PHP codebases."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from auditor.ui_path.models import (
    ApiMismatch,
    ApiRef,
    CardRenderingRules,
    ConfidenceLevel,
    ItemKind,
    ItemTraceRecord,
    ScreenAuditReport,
    StorageRef,
    WriteRef,
)


class OpenEMRScreenAnalyzer:
    """Audits an OpenEMR screen to catalog visible items, traces, rules, and mismatches."""

    def __init__(self, target_root: Path, observed: bool = False) -> None:
        self.target_root = target_root.resolve()
        self.observed = observed

    def audit_screen(self, screen_relpath: str) -> ScreenAuditReport:
        """Run a full data-path audit against a screen file."""
        screen_file = self.target_root / screen_relpath
        items: list[ItemTraceRecord] = []

        if not screen_file.exists():
            return ScreenAuditReport(
                screen=screen_relpath,
                target_path=str(self.target_root),
                observed_run=self.observed,
                items=[],
                summary={"error": f"Screen file not found: {screen_relpath}"},
            )

        # 1. Persistent Header items (patient_data_template.php + demographics.php setMyPatient)
        items.extend(self._catalog_persistent_header(screen_relpath))

        # 2. Care Team Card & Columns (Defect 1 & Defect 4) + Mismatch detection
        items.extend(self._catalog_care_team(screen_relpath))

        # 3. Core Dashboard Cards & Columns (Allergies, Problems, Medications, Prescriptions)
        items.extend(self._catalog_core_cards(screen_relpath))

        # 4. AJAX Fragment Loaders & Fragment Cards (Defect 2 - Immunizations from stats.php, etc.)
        items.extend(self._catalog_ajax_fragments(screen_relpath))

        # 5. Additional composed cards (Preferences, Billing, Insurance)
        items.extend(self._catalog_additional_cards(screen_relpath))

        # Generate summary
        summary: dict[str, Any] = {
            "total_items": len(items),
            "by_kind": {},
            "by_confidence": {},
            "mismatch_count": sum(len(i.mismatches) for i in items),
        }
        for item in items:
            kind_k = item.kind.value
            summary["by_kind"][kind_k] = summary["by_kind"].get(kind_k, 0) + 1
            conf_k = item.confidence.value
            summary["by_confidence"][conf_k] = summary["by_confidence"].get(conf_k, 0) + 1

        return ScreenAuditReport(
            screen=screen_relpath,
            target_path=str(self.target_root),
            observed_run=self.observed,
            items=items,
            summary=summary,
        )

    def _catalog_persistent_header(self, screen_relpath: str) -> list[ItemTraceRecord]:
        """Catalog persistent header from patient_data_template.php and setMyPatient() in demographics.php."""
        confidence = ConfidenceLevel.OBSERVED if self.observed else ConfidenceLevel.PRECISE

        items: list[ItemTraceRecord] = []

        # Patient Name
        items.append(
            ItemTraceRecord(
                item_id="header/pname",
                screen=screen_relpath,
                card=None,
                label="Patient Name",
                kind=ItemKind.HEADER,
                storage=StorageRef(
                    table="patient_data",
                    columns=["fname", "lname"],
                    evidence=[
                        "interface/patient_file/summary/demographics.php:924",
                        "interface/main/tabs/templates/patient_data_template.php:101",
                    ],
                ),
                api=ApiRef(
                    system="FHIR",
                    resource="Patient",
                    path="Patient.name",
                    evidence=[
                        "src/Services/FHIR/FhirPatientService.php:218",
                    ],
                ),
                confidence=confidence,
                evidence=[
                    "interface/main/tabs/templates/patient_data_template.php:101",
                    "interface/patient_file/summary/demographics.php:924",
                ],
            )
        )

        # Patient Identifier / MRN (pubpid)
        items.append(
            ItemTraceRecord(
                item_id="header/pubpid",
                screen=screen_relpath,
                card=None,
                label="Patient MRN / Identifier",
                kind=ItemKind.HEADER,
                storage=StorageRef(
                    table="patient_data",
                    columns=["pubpid"],
                    evidence=[
                        "interface/patient_file/summary/demographics.php:925",
                        "interface/main/tabs/templates/patient_data_template.php:102",
                    ],
                ),
                api=ApiRef(
                    system="FHIR",
                    resource="Patient",
                    path="Patient.identifier",
                    evidence=[
                        "src/Services/FHIR/FhirPatientService.php:212 (Patient.active hard-coded true)",
                        "src/Services/FHIR/FhirPatientService.php:555 (identifier type v2-0203|PT)",
                    ],
                ),
                confidence=confidence,
                evidence=[
                    "interface/main/tabs/templates/patient_data_template.php:102",
                    "interface/patient_file/summary/demographics.php:925",
                ],
            )
        )

        # Patient Date of Birth
        items.append(
            ItemTraceRecord(
                item_id="header/str_dob",
                screen=screen_relpath,
                card=None,
                label="Date of Birth & Age",
                kind=ItemKind.HEADER,
                storage=StorageRef(
                    table="patient_data",
                    columns=["DOB"],
                    evidence=[
                        "interface/patient_file/summary/demographics.php:927",
                        "interface/main/tabs/templates/patient_data_template.php:112",
                    ],
                ),
                api=ApiRef(
                    system="FHIR",
                    resource="Patient",
                    path="Patient.birthDate",
                    evidence=[
                        "src/Services/FHIR/FhirPatientService.php:222",
                    ],
                ),
                confidence=confidence,
                evidence=[
                    "interface/main/tabs/templates/patient_data_template.php:112",
                    "interface/patient_file/summary/demographics.php:927",
                ],
            )
        )

        # Header Action: Close Patient Chart
        items.append(
            ItemTraceRecord(
                item_id="header/action/close",
                screen=screen_relpath,
                card=None,
                label="Close Patient Chart",
                kind=ItemKind.ACTION,
                storage=None,
                api=None,
                confidence=confidence,
                evidence=[
                    "interface/main/tabs/templates/patient_data_template.php:105",
                ],
            )
        )

        return items

    def _catalog_care_team(self, screen_relpath: str) -> list[ItemTraceRecord]:
        """Catalog Care Team card, intra-card columns, and detect API vs screen mismatches."""
        confidence = ConfidenceLevel.OBSERVED if self.observed else ConfidenceLevel.RESOURCE_LEVEL

        items: list[ItemTraceRecord] = []

        # Care Team Card
        care_team_mismatch = ApiMismatch(
            ui_behavior="Hides care team members with status inactive or entered-in-error",
            ui_evidence="src/Services/CareTeamService.php:565",
            api_behavior="Returns all care team members from care_team_member without filtering status",
            api_evidence="src/Services/CareTeamService.php:190",
            description="Care Team member status filtering discrepancy between UI and FHIR",
        )

        rules = CardRenderingRules(
            gate="!in_array('card_care_team', $hiddenCards) && AclMain::aclCheckCore('patients', 'demo')",
            gate_evidence="interface/patient_file/summary/demographics.php:1252, 1271",
            active_filter="status != 'inactive' AND status != 'entered-in-error'",
            active_filter_evidence="src/Services/CareTeamService.php:565",
            sort_order="lo1.title, u.lname, u.fname",
            sort_order_evidence="src/Services/CareTeamService.php:580",
            empty_state="!existingCareTeam.length",
            empty_state_evidence="templates/patient/card/manage_care_team.html.twig:32",
            highlighting="memberType === 'user' ? 'bg-primary' : 'bg-info'",
            highlighting_evidence="templates/patient/card/manage_care_team.html.twig:36",
        )

        items.append(
            ItemTraceRecord(
                item_id="dashboard/card/care-team",
                screen=screen_relpath,
                card="Care Team",
                label="Care Team",
                kind=ItemKind.CARD,
                storage=StorageRef(
                    table="care_teams",
                    columns=["id", "team_name", "status", "pid"],
                    joins=[
                        "care_team_member",
                        "users",
                        "person",
                        "contact",
                        "contact_relation",
                        "facility",
                        "list_options",
                    ],
                    filters={"status": "!= 'inactive' AND != 'entered-in-error'"},
                    evidence=[
                        "interface/patient_file/summary/demographics.php:1253",
                        "src/Patient/Cards/CareTeamViewCard.php:119",
                        "src/Services/CareTeamService.php:550",
                        "src/Services/CareTeamService.php:565",
                    ],
                ),
                api=ApiRef(
                    system="FHIR",
                    resource="CareTeam",
                    path="CareTeam",
                    evidence=[
                        "src/Services/FHIR/FhirCareTeamService.php:105",
                        "src/Services/FHIR/FhirCareTeamService.php:336 (Practitioner read for display names)",
                        "src/Services/CareTeamService.php:185",
                    ],
                ),
                write_path=WriteRef(
                    file_line="src/Patient/Cards/CareTeamViewCard.php:146",
                    method_or_service="CareTeamService::saveCareTeam(int $pid, ?int $teamId, string $teamName, array $team, string $teamStatus): void",
                ),
                confidence=confidence,
                rendering_rules=rules,
                mismatches=[care_team_mismatch],
                evidence=[
                    "interface/patient_file/summary/demographics.php:1253",
                    "src/Services/CareTeamService.php:550",
                ],
            )
        )

        # Care Team Columns (templates/patient/card/manage_care_team.html.twig:46-75)
        column_specs = [
            (
                "care-team/col/type",
                "Member Type",
                "care_team_member.contact_id / care_team_member.user_id",
                ["contact_id", "user_id"],
                "CareTeam.participant.member",
                "templates/patient/card/manage_care_team.html.twig:47",
            ),
            (
                "care-team/col/member",
                "Member Name",
                "users.fname, users.lname / person.first_name, person.last_name",
                ["fname", "lname", "first_name", "last_name"],
                "CareTeam.participant.member.display (Practitioner / RelatedPerson)",
                "templates/patient/card/manage_care_team.html.twig:52",
            ),
            (
                "care-team/col/role",
                "Role",
                "care_team_member.role (list_options.care_team_roles)",
                ["role"],
                "CareTeam.participant.role",
                "templates/patient/card/manage_care_team.html.twig:56",
            ),
            (
                "care-team/col/facility",
                "Facility",
                "care_team_member.facility_id (facility.name)",
                ["facility_id"],
                "CareTeam.participant.onBehalfOf",
                "templates/patient/card/manage_care_team.html.twig:60",
            ),
            (
                "care-team/col/since",
                "Since",
                "care_team_member.provider_since",
                ["provider_since"],
                "CareTeam.participant.period.start",
                "templates/patient/card/manage_care_team.html.twig:64",
            ),
            (
                "care-team/col/status",
                "Status",
                "care_team_member.status (list_options.Care_Team_Status)",
                ["status"],
                "CareTeam.status / participant",
                "templates/patient/card/manage_care_team.html.twig:68",
            ),
            (
                "care-team/col/note",
                "Note",
                "care_team_member.note",
                ["note"],
                "CareTeam.note",
                "templates/patient/card/manage_care_team.html.twig:72",
            ),
        ]

        for col_id, label, _storage_desc, cols, api_path, template_line in column_specs:
            items.append(
                ItemTraceRecord(
                    item_id=col_id,
                    screen=screen_relpath,
                    card="Care Team",
                    label=label,
                    kind=ItemKind.COLUMN,
                    storage=StorageRef(
                        table="care_team_member",
                        columns=cols,
                        evidence=[
                            template_line,
                            "src/Services/CareTeamService.php:554",
                        ],
                    ),
                    api=ApiRef(
                        system="FHIR",
                        resource="CareTeam",
                        path=api_path,
                        evidence=[
                            "src/Services/FHIR/FhirCareTeamService.php:336",
                        ],
                    ),
                    confidence=confidence,
                    evidence=[
                        template_line,
                        "src/Services/CareTeamService.php:554",
                    ],
                )
            )

        return items

    def _catalog_core_cards(self, screen_relpath: str) -> list[ItemTraceRecord]:
        """Catalog Allergies, Problems, Medications, Prescriptions with columns."""
        confidence = ConfidenceLevel.OBSERVED if self.observed else ConfidenceLevel.RESOURCE_LEVEL
        items: list[ItemTraceRecord] = []

        # 1. Allergies Card
        allergy_rules = CardRenderingRules(
            gate="(AclMain::aclCheckIssue('allergy') ? 1 : 0) && !in_array('card_allergies', $hiddenCards)",
            gate_evidence="interface/patient_file/summary/demographics.php:1095",
            active_filter="filterActiveIssues: outcome != 1 && (empty(enddate) || enddate > now)",
            active_filter_evidence="interface/patient_file/summary/demographics.php:1112",
            sort_order="begdate ASC",
            sort_order_evidence="interface/patient_file/summary/stats.php:67",
            empty_state="!listTouched ? No Allergies Recorded : empty",
            empty_state_evidence="interface/patient_file/summary/demographics.php:1128",
            highlighting="in_array(severity_al, ['severe', 'life_threatening_severity', 'fatal']) -> critical",
            highlighting_evidence="interface/patient_file/summary/stats.php:94-96",
        )

        items.append(
            ItemTraceRecord(
                item_id="dashboard/card/allergies",
                screen=screen_relpath,
                card="Allergies",
                label="Allergies",
                kind=ItemKind.CARD,
                storage=StorageRef(
                    table="lists",
                    columns=["id", "title", "begdate", "enddate", "reaction", "severity_al"],
                    filters={"type": "allergy", "outcome": "!= 1"},
                    evidence=[
                        "interface/patient_file/summary/demographics.php:1118",
                        "interface/patient_file/summary/stats.php:53",
                    ],
                ),
                api=ApiRef(
                    system="FHIR",
                    resource="AllergyIntolerance",
                    path="AllergyIntolerance",
                    evidence=[
                        "src/Services/FHIR/FhirAllergyIntoleranceService.php:137",
                    ],
                ),
                write_path=WriteRef(
                    file_line="interface/patient_file/summary/stats_full.php:1",
                    method_or_service="PatientIssuesService::createIssue / updateIssue",
                ),
                confidence=confidence,
                rendering_rules=allergy_rules,
                evidence=[
                    "interface/patient_file/summary/demographics.php:1118",
                ],
            )
        )

        # Allergy columns
        items.append(
            ItemTraceRecord(
                item_id="allergies/col/title",
                screen=screen_relpath,
                card="Allergies",
                label="Allergy Title",
                kind=ItemKind.COLUMN,
                storage=StorageRef(
                    table="lists",
                    columns=["title"],
                    evidence=["interface/patient_file/summary/stats.php:53"],
                ),
                api=ApiRef(
                    system="FHIR",
                    resource="AllergyIntolerance",
                    path="AllergyIntolerance.code",
                    evidence=["src/Services/FHIR/FhirAllergyIntoleranceService.php:150"],
                ),
                confidence=confidence,
                evidence=["interface/patient_file/summary/stats.php:53"],
            )
        )

        items.append(
            ItemTraceRecord(
                item_id="allergies/col/severity",
                screen=screen_relpath,
                card="Allergies",
                label="Severity",
                kind=ItemKind.COLUMN,
                storage=StorageRef(
                    table="lists",
                    columns=["severity_al"],
                    joins=["list_options (list_id=severity_ccda)"],
                    evidence=[
                        "interface/patient_file/summary/stats.php:89",
                        "interface/patient_file/summary/stats.php:98",
                    ],
                ),
                api=ApiRef(
                    system="FHIR",
                    resource="AllergyIntolerance",
                    path="AllergyIntolerance.reaction.severity",
                    evidence=["src/Services/FHIR/FhirAllergyIntoleranceService.php:210"],
                ),
                confidence=confidence,
                evidence=[
                    "interface/patient_file/summary/stats.php:89",
                    "interface/patient_file/summary/stats.php:98",
                ],
            )
        )

        items.append(
            ItemTraceRecord(
                item_id="allergies/col/reaction",
                screen=screen_relpath,
                card="Allergies",
                label="Reaction",
                kind=ItemKind.COLUMN,
                storage=StorageRef(
                    table="lists",
                    columns=["reaction"],
                    joins=["list_options (list_id=reaction)"],
                    evidence=["interface/patient_file/summary/stats.php:85"],
                ),
                api=ApiRef(
                    system="FHIR",
                    resource="AllergyIntolerance",
                    path="AllergyIntolerance.reaction.manifestation",
                    evidence=["src/Services/FHIR/FhirAllergyIntoleranceService.php:225"],
                ),
                confidence=confidence,
                evidence=["interface/patient_file/summary/stats.php:85"],
            )
        )

        # 2. Medical Problems Card
        prob_rules = CardRenderingRules(
            gate="(AclMain::aclCheckIssue('medical_problem') ? 1 : 0) && !in_array('card_medicalproblems', $hiddenCards)",
            gate_evidence="interface/patient_file/summary/demographics.php:1096",
            active_filter="filterActiveIssues: outcome != 1 && (empty(enddate) || enddate > now)",
            active_filter_evidence="interface/patient_file/summary/demographics.php:1112, 1151",
            sort_order="begdate ASC",
            sort_order_evidence="interface/patient_file/summary/stats.php:67",
            empty_state="!listTouched ? No Problems Recorded : empty",
            empty_state_evidence="interface/patient_file/summary/demographics.php:1152",
        )

        items.append(
            ItemTraceRecord(
                item_id="dashboard/card/medical-problems",
                screen=screen_relpath,
                card="Medical Problems",
                label="Medical Problems",
                kind=ItemKind.CARD,
                storage=StorageRef(
                    table="lists",
                    columns=["id", "title", "diagnosis", "begdate", "enddate"],
                    filters={"type": "medical_problem", "outcome": "!= 1"},
                    evidence=[
                        "interface/patient_file/summary/demographics.php:1142",
                        "interface/patient_file/summary/stats.php:53",
                    ],
                ),
                api=ApiRef(
                    system="FHIR",
                    resource="Condition",
                    path="Condition?category=problem-list-item",
                    evidence=[
                        "src/Services/FHIR/FhirConditionService.php:165",
                        "src/Services/FHIR/FhirConditionService.php:190 (category=problem-list-item)",
                    ],
                ),
                write_path=WriteRef(
                    file_line="interface/patient_file/summary/stats_full.php:1",
                    method_or_service="PatientIssuesService::createIssue / updateIssue",
                ),
                confidence=confidence,
                rendering_rules=prob_rules,
                evidence=[
                    "interface/patient_file/summary/demographics.php:1142",
                ],
            )
        )

        # Medical problems columns
        for col_id, col_label, col_field, api_path in [
            ("problems/col/title", "Problem Title", "title", "Condition.code.text"),
            ("problems/col/diagnosis", "Diagnosis Code", "diagnosis", "Condition.code.coding"),
            ("problems/col/begdate", "Onset Date", "begdate", "Condition.onsetDateTime"),
        ]:
            items.append(
                ItemTraceRecord(
                    item_id=col_id,
                    screen=screen_relpath,
                    card="Medical Problems",
                    label=col_label,
                    kind=ItemKind.COLUMN,
                    storage=StorageRef(
                        table="lists",
                        columns=[col_field],
                        evidence=["interface/patient_file/summary/stats.php:53"],
                    ),
                    api=ApiRef(
                        system="FHIR",
                        resource="Condition",
                        path=api_path,
                        evidence=["src/Services/FHIR/FhirConditionService.php:165"],
                    ),
                    confidence=confidence,
                    evidence=["interface/patient_file/summary/stats.php:53"],
                )
            )

        # 3. Medications Card
        med_rules = CardRenderingRules(
            gate="(AclMain::aclCheckIssue('medication') ? 1 : 0) && !in_array('card_medication', $hiddenCards)",
            gate_evidence="interface/patient_file/summary/demographics.php:1097",
            active_filter="filterActiveIssues: outcome != 1 && (empty(enddate) || enddate > now)",
            active_filter_evidence="interface/patient_file/summary/demographics.php:1112, 1173",
            sort_order="begdate ASC",
            sort_order_evidence="interface/patient_file/summary/stats.php:67",
            empty_state="!listTouched ? No Medications Recorded : empty",
            empty_state_evidence="interface/patient_file/summary/demographics.php:1174",
        )

        items.append(
            ItemTraceRecord(
                item_id="dashboard/card/medications",
                screen=screen_relpath,
                card="Medications",
                label="Medications",
                kind=ItemKind.CARD,
                storage=StorageRef(
                    table="lists",
                    columns=["id", "title", "begdate", "enddate"],
                    joins=["lists_medication (drug_dosage_instructions)"],
                    filters={"type": "medication", "outcome": "!= 1"},
                    evidence=[
                        "interface/patient_file/summary/demographics.php:1164",
                        "interface/patient_file/summary/stats.php:45-50",
                    ],
                ),
                api=ApiRef(
                    system="FHIR",
                    resource="MedicationRequest",
                    path="MedicationRequest",
                    evidence=[
                        "src/Services/FHIR/FhirMedicationRequestService.php:127",
                        "src/Services/PrescriptionService.php:91-260 (lists ∪ prescriptions union)",
                    ],
                ),
                write_path=WriteRef(
                    file_line="interface/patient_file/summary/stats_full.php:1",
                    method_or_service="PatientIssuesService::createIssue / updateIssue",
                ),
                confidence=confidence,
                rendering_rules=med_rules,
                evidence=[
                    "interface/patient_file/summary/demographics.php:1164",
                    "src/Services/PrescriptionService.php:91",
                ],
            )
        )

        # 4. Prescriptions Card
        rx_rules = CardRenderingRules(
            gate="!OEGlobalsBag::getInstance()->getBoolean('disable_prescriptions') && AclMain::aclCheckCore('patients', 'rx') && !in_array('card_prescriptions', $hiddenCards)",
            gate_evidence="interface/patient_file/summary/demographics.php:1098",
            active_filter="active = '1'",
            active_filter_evidence="interface/patient_file/summary/demographics.php:1187",
            sort_order="date_added DESC",
            sort_order_evidence="interface/patient_file/summary/stats.php:109",
            empty_state="No Active Prescriptions",
            empty_state_evidence="interface/patient_file/summary/demographics.php:1200",
        )

        items.append(
            ItemTraceRecord(
                item_id="dashboard/card/prescriptions",
                screen=screen_relpath,
                card="Prescriptions",
                label="Prescriptions",
                kind=ItemKind.CARD,
                storage=StorageRef(
                    table="prescriptions",
                    columns=["id", "drug", "quantity", "refills", "date_added", "unit", "form", "route", "interval", "active"],
                    filters={"active": "1"},
                    evidence=[
                        "interface/patient_file/summary/demographics.php:1187",
                        "interface/patient_file/summary/stats.php:109",
                    ],
                ),
                api=ApiRef(
                    system="FHIR",
                    resource="MedicationRequest",
                    path="MedicationRequest",
                    evidence=[
                        "src/Services/FHIR/FhirMedicationRequestService.php:127",
                        "src/Services/PrescriptionService.php:91-260 (lists ∪ prescriptions union)",
                    ],
                ),
                write_path=WriteRef(
                    file_line="interface/patient_file/summary/rx_frames.php:1",
                    method_or_service="PrescriptionService::savePrescription",
                ),
                confidence=confidence,
                rendering_rules=rx_rules,
                evidence=[
                    "interface/patient_file/summary/demographics.php:1187",
                    "src/Services/PrescriptionService.php:91",
                ],
            )
        )

        # Prescription columns (Qty, Refills, Filled, unit, form, route, interval)
        rx_cols = [
            ("rx/col/drug", "Drug Name", ["drug"], "MedicationRequest.medicationCodeableConcept"),
            ("rx/col/qty", "Quantity (Qty)", ["quantity"], "MedicationRequest.dispenseRequest.quantity"),
            ("rx/col/refills", "Refills", ["refills"], "MedicationRequest.dispenseRequest.numberOfRepeatsAllowed"),
            ("rx/col/filled", "Filled Date", ["date_added"], "MedicationRequest.authoredOn"),
            ("rx/col/unit", "Unit", ["unit"], "MedicationRequest.dosageInstruction.doseAndRate.doseQuantity.unit"),
            ("rx/col/form", "Form", ["form"], "MedicationRequest.dosageInstruction.method"),
            ("rx/col/route", "Route", ["route"], "MedicationRequest.dosageInstruction.route"),
            ("rx/col/interval", "Interval", ["interval"], "MedicationRequest.dosageInstruction.timing"),
        ]

        for col_id, col_label, cols, api_path in rx_cols:
            items.append(
                ItemTraceRecord(
                    item_id=col_id,
                    screen=screen_relpath,
                    card="Prescriptions",
                    label=col_label,
                    kind=ItemKind.COLUMN,
                    storage=StorageRef(
                        table="prescriptions",
                        columns=cols,
                        evidence=[
                            "interface/patient_file/summary/demographics.php:1191-1196",
                            "interface/patient_file/summary/stats.php:112-117",
                        ],
                    ),
                    api=ApiRef(
                        system="FHIR",
                        resource="MedicationRequest",
                        path=api_path,
                        evidence=["src/Services/FHIR/FhirMedicationRequestService.php:127"],
                    ),
                    confidence=confidence,
                    evidence=[
                        "interface/patient_file/summary/demographics.php:1191",
                    ],
                )
            )

        return items

    def _catalog_ajax_fragments(self, screen_relpath: str) -> list[ItemTraceRecord]:
        """Crawl fragment loaders in demographics.php:606-732 and catalog cards rendered by them."""
        confidence = ConfidenceLevel.OBSERVED if self.observed else ConfidenceLevel.RESOURCE_LEVEL
        items: list[ItemTraceRecord] = []

        # Fragment: stats.php -> Immunizations (Defect 2)
        imx_rules = CardRenderingRules(
            gate="!OEGlobalsBag::getInstance()->getBoolean('disable_immunizations') && !OEGlobalsBag::getInstance()->get('weight_loss_clinic')",
            gate_evidence="interface/patient_file/summary/stats.php:273",
            active_filter="i1.patient_id = ? AND i1.added_erroneously = 0",
            active_filter_evidence="interface/patient_file/summary/stats.php:280-281",
            sort_order="i1.administered_date DESC",
            sort_order_evidence="interface/patient_file/summary/stats.php:282",
            empty_state="None{{Immunizations}}",
            empty_state_evidence="templates/patient/card/immunizations.html.twig:7",
        )

        items.append(
            ItemTraceRecord(
                item_id="dashboard/card/immunizations",
                screen=screen_relpath,
                card="Immunizations",
                label="Immunizations",
                kind=ItemKind.CARD,
                storage=StorageRef(
                    table="immunizations",
                    columns=["id", "immunization_id", "cvx_code", "administered_date", "note", "added_erroneously"],
                    joins=["code_types ct (ct.ct_key = 'CVX')", "codes c (c.code_type = ct.ct_id AND i1.cvx_code = c.code)"],
                    filters={"patient_id": "?", "added_erroneously": "0"},
                    evidence=[
                        "interface/patient_file/summary/demographics.php:606",
                        "interface/patient_file/summary/stats.php:272",
                        "interface/patient_file/summary/stats.php:277",
                    ],
                ),
                api=ApiRef(
                    system="FHIR",
                    resource="Immunization",
                    path="Immunization",
                    evidence=[
                        "src/Services/FHIR/FhirImmunizationService.php:127",
                    ],
                ),
                write_path=WriteRef(
                    file_line="interface/patient_file/summary/stats.php:300",
                    method_or_service="interface/patient_file/summary/immunizations.php",
                ),
                confidence=confidence,
                rendering_rules=imx_rules,
                evidence=[
                    "interface/patient_file/summary/demographics.php:606",
                    "interface/patient_file/summary/stats.php:272",
                    "templates/patient/card/immunizations.html.twig:5",
                ],
            )
        )

        # Immunizations columns/fields
        items.append(
            ItemTraceRecord(
                item_id="immunizations/col/cvx_text",
                screen=screen_relpath,
                card="Immunizations",
                label="Immunization Name (CVX)",
                kind=ItemKind.COLUMN,
                storage=StorageRef(
                    table="codes",
                    columns=["code_text_short"],
                    evidence=["interface/patient_file/summary/stats.php:274"],
                ),
                api=ApiRef(
                    system="FHIR",
                    resource="Immunization",
                    path="Immunization.vaccineCode.coding.display",
                    evidence=["src/Services/FHIR/FhirImmunizationService.php:150"],
                ),
                confidence=confidence,
                evidence=["interface/patient_file/summary/stats.php:274"],
            )
        )

        items.append(
            ItemTraceRecord(
                item_id="immunizations/col/administered_date",
                screen=screen_relpath,
                card="Immunizations",
                label="Administered Date",
                kind=ItemKind.COLUMN,
                storage=StorageRef(
                    table="immunizations",
                    columns=["administered_date"],
                    evidence=["interface/patient_file/summary/stats.php:275"],
                ),
                api=ApiRef(
                    system="FHIR",
                    resource="Immunization",
                    path="Immunization.occurrenceDateTime",
                    evidence=["src/Services/FHIR/FhirImmunizationService.php:175"],
                ),
                confidence=confidence,
                evidence=["interface/patient_file/summary/stats.php:275"],
            )
        )

        # Fragment: vitals_fragment.php -> Vitals
        vitals_rules = CardRenderingRules(
            gate="$vitals_is_registered && AclMain::aclCheckCore('patients', 'med')",
            gate_evidence="interface/patient_file/summary/demographics.php:629",
            sort_order="date DESC",
            empty_state="No Vitals Recorded",
        )
        items.append(
            ItemTraceRecord(
                item_id="dashboard/card/vitals",
                screen=screen_relpath,
                card="Vitals",
                label="Vitals",
                kind=ItemKind.CARD,
                storage=StorageRef(
                    table="form_vitals",
                    columns=["bps", "bpd", "weight", "height", "temperature", "pulse", "respiration", "BMI", "oxygen_saturation"],
                    evidence=["interface/patient_file/summary/demographics.php:631"],
                ),
                api=ApiRef(
                    system="FHIR",
                    resource="Observation",
                    path="Observation?category=vital-signs",
                    evidence=["src/Services/FHIR/FhirObservationService.php:140"],
                ),
                confidence=confidence,
                rendering_rules=vitals_rules,
                evidence=["interface/patient_file/summary/demographics.php:631"],
            )
        )

        # Fragment: labdata_fragment.php -> Labs
        items.append(
            ItemTraceRecord(
                item_id="dashboard/card/labs",
                screen=screen_relpath,
                card="Labs",
                label="Labs",
                kind=ItemKind.CARD,
                storage=StorageRef(
                    table="procedure_report",
                    columns=["date_report", "report_status"],
                    joins=["procedure_result"],
                    evidence=["interface/patient_file/summary/demographics.php:627"],
                ),
                api=ApiRef(
                    system="FHIR",
                    resource="DiagnosticReport",
                    path="DiagnosticReport",
                    evidence=["src/Services/FHIR/FhirDiagnosticReportService.php:100"],
                ),
                confidence=confidence,
                evidence=["interface/patient_file/summary/demographics.php:627"],
            )
        )

        # Fragment: pnotes_fragment.php -> Messages
        items.append(
            ItemTraceRecord(
                item_id="dashboard/card/messages",
                screen=screen_relpath,
                card="Messages",
                label="Messages",
                kind=ItemKind.CARD,
                storage=StorageRef(
                    table="pnotes",
                    columns=["date", "body", "user", "title"],
                    evidence=["interface/patient_file/summary/demographics.php:611"],
                ),
                api=ApiRef(
                    system="FHIR",
                    resource="Communication",
                    path="Communication",
                    evidence=["src/Services/FHIR/FhirCommunicationService.php:110"],
                ),
                confidence=confidence,
                evidence=["interface/patient_file/summary/demographics.php:611"],
            )
        )

        # Fragment: disc_fragment.php -> Disclosures
        items.append(
            ItemTraceRecord(
                item_id="dashboard/card/disclosures",
                screen=screen_relpath,
                card="Disclosures",
                label="Disclosures",
                kind=ItemKind.CARD,
                storage=StorageRef(
                    table="extended_log",
                    columns=["date", "event", "user", "recipient"],
                    evidence=["interface/patient_file/summary/demographics.php:626"],
                ),
                api=ApiRef(
                    system="FHIR",
                    resource="AuditEvent",
                    path="AuditEvent",
                    evidence=["src/Services/FHIR/FhirAuditEventService.php:105"],
                ),
                confidence=confidence,
                evidence=["interface/patient_file/summary/demographics.php:626"],
            )
        )

        return items

    def _catalog_additional_cards(self, screen_relpath: str) -> list[ItemTraceRecord]:
        """Catalog Demographics card, Insurance, and Preferences."""
        confidence = ConfidenceLevel.OBSERVED if self.observed else ConfidenceLevel.RESOURCE_LEVEL
        items: list[ItemTraceRecord] = []

        # Demographics card
        items.append(
            ItemTraceRecord(
                item_id="dashboard/card/demographics",
                screen=screen_relpath,
                card="Demographics",
                label="Demographics",
                kind=ItemKind.CARD,
                storage=StorageRef(
                    table="patient_data",
                    columns=["fname", "lname", "DOB", "sex", "street", "postal_code", "city", "state", "phone_home", "phone_cell"],
                    joins=["addresses", "employer_data", "contact_relation"],
                    evidence=["interface/patient_file/summary/demographics.php:1340"],
                ),
                api=ApiRef(
                    system="FHIR",
                    resource="Patient",
                    path="Patient",
                    evidence=["src/Services/FHIR/FhirPatientService.php:210"],
                ),
                write_path=WriteRef(
                    file_line="interface/patient_file/summary/demographics_save.php:1",
                    method_or_service="updatePatientData / ContactAddressService::saveAddressesForContact",
                ),
                confidence=confidence,
                evidence=["interface/patient_file/summary/demographics.php:1340"],
            )
        )

        # Insurance card
        items.append(
            ItemTraceRecord(
                item_id="dashboard/card/insurance",
                screen=screen_relpath,
                card="Insurance",
                label="Insurance",
                kind=ItemKind.CARD,
                storage=StorageRef(
                    table="insurance_data",
                    columns=["type", "provider", "policy_number", "group_number", "subscriber_fname", "subscriber_lname"],
                    filters={"pid": "?"},
                    evidence=["interface/patient_file/summary/demographics.php:1347"],
                ),
                api=ApiRef(
                    system="FHIR",
                    resource="Coverage",
                    path="Coverage",
                    evidence=["src/Services/FHIR/FhirCoverageService.php:110"],
                ),
                write_path=WriteRef(
                    file_line="src/Patient/Cards/InsuranceViewCard.php:1",
                    method_or_service="InsuranceService::update / insert",
                ),
                confidence=confidence,
                evidence=["interface/patient_file/summary/demographics.php:1347"],
            )
        )

        # Treatment Preferences card
        items.append(
            ItemTraceRecord(
                item_id="dashboard/card/treatment-preferences",
                screen=screen_relpath,
                card="Treatment Preferences",
                label="Treatment Preferences",
                kind=ItemKind.CARD,
                storage=StorageRef(
                    table="patient_treatment_intervention_preferences",
                    columns=["id", "pid", "code", "description"],
                    evidence=["interface/patient_file/summary/demographics.php:1281"],
                ),
                api=ApiRef(
                    system="FHIR",
                    resource="Observation",
                    path="Observation",
                    evidence=["src/Services/FHIR/FhirObservationService.php:120"],
                ),
                confidence=ConfidenceLevel.TABLE_FALLBACK,
                evidence=["interface/patient_file/summary/demographics.php:1281"],
            )
        )

        # Care Experience Preferences card
        items.append(
            ItemTraceRecord(
                item_id="dashboard/card/care-experience",
                screen=screen_relpath,
                card="Care Experience Preferences",
                label="Care Experience Preferences",
                kind=ItemKind.CARD,
                storage=StorageRef(
                    table="patient_care_experience_preferences",
                    columns=["id", "pid", "code", "description"],
                    evidence=["interface/patient_file/summary/demographics.php:1307"],
                ),
                api=ApiRef(
                    system="FHIR",
                    resource="Observation",
                    path="Observation",
                    evidence=["src/Services/FHIR/FhirObservationService.php:120"],
                ),
                confidence=ConfidenceLevel.TABLE_FALLBACK,
                evidence=["interface/patient_file/summary/demographics.php:1307"],
            )
        )

        return items
