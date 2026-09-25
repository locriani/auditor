# PRD: UI Data-Path Audit Engine

## Problem Statement

When porting a legacy UI screen (such as OpenEMR's Patient Dashboard) to a modern API-driven frontend, engineers need to answer: *Which screen items can be reconstructed from the API, which cannot, and what logic does the UI apply that the API does not?*

Today, engineers either manually read thousands of lines of PHP, Twig/Smarty templates, and SQL to guess the API and storage paths, or rely on incomplete scripts that:
- Misidentify underlying tables (e.g. tracing Care Team to `patient_data` instead of `care_teams` and `care_team_member`).
- Miss dynamic cards loaded asynchronously via AJAX fragments (e.g. Immunizations from `stats.php`).
- Miss persistent chrome/header bindings (e.g. Knockout.js patient header).
- Omit intra-card columns and sub-field mappings.
- Fail to highlight semantic mismatches where the API and screen return divergent datasets.

## Solution

A UI data-path audit engine integrated into the `auditor` plugin that:
1. Catalogs every visible item on a specified screen (cards, fields, columns, badges, empty states).
2. Traces each item to:
   - Its database storage read: table, columns, joins, and filters.
   - Its write path (if editable).
   - Its API/FHIR resource and element path.
3. Attaches precise evidence (`file:line`) to every trace—never bare filenames.
4. Categorizes trace confidence into four distinct tiers:
   - `precise`: Exact scalar path match in API (e.g. `Patient.birthDate`).
   - `resource-level`: Maps to an API resource, but not a single scalar path.
   - `table-fallback`: Storage is known, but no direct API path was inferred.
   - `observed`: Proven dynamically by seeding data and confirming retrieval via the live API (opt-in behind `--observed`).
5. Extracts card rendering rules:
   - Gate: ACL check, global flag, or hidden-card setting.
   - Active filter: In-memory or SQL filter criteria applied.
   - Sort order: SQL or presentation sort.
   - Empty-state string: Exact string and display condition.
   - Highlighting: Conditional styles or flags.
6. Flags API vs. Screen mismatches where an API read returns different data than what the UI renders (citing `file:line` on both sides).
7. Emits structured JSON conforming to a Pydantic schema and a Markdown parity table.

## User Stories

1. **US-1**: As a migration engineer, I want to audit an OpenEMR dashboard screen so that I have a complete catalog of every visual item and where its data originates.
2. **US-2**: As a migration engineer, I want intra-card columns and AJAX-loaded fragment cards cataloged so that I don't build a frontend that misses required clinical elements.
3. **US-3**: As a migration engineer, I want API-to-screen discrepancies flagged with `file:line` citations on both sides so that I don't introduce bugs caused by subtle filter differences (e.g. inactive Care Team members).
4. **US-4**: As a security/compliance auditor, I want static traces by default and an opt-in `--observed` verification pass so that I can audit untrusted code safely without accidental execution.
5. **US-5**: As an automation pipeline or auditor agent, I want structured JSON and Markdown parity tables so that verification results can be programmatic gates in CI or audit findings documents.

## Implementation Decisions

- **Generic Schema**: Pydantic models in `src/auditor/ui_path/models.py`:
  - `ConfidenceLevel`: Literal `["precise", "resource-level", "table-fallback", "observed"]`.
  - `StorageRef`: `table`, `columns`, `joins`, `filters`, `evidence` (`file:line`).
  - `ApiRef`: `system` ("FHIR"), `resource`, `path`, `evidence` (`file:line`).
  - `WriteRef`: `file_line`, `method_or_service`, `payload_shape`.
  - `CardRenderingRules`: `gate`, `active_filter`, `sort_order`, `empty_state`, `highlighting`.
  - `ApiMismatch`: `ui_behavior`, `ui_evidence`, `api_behavior`, `api_evidence`, `description`.
  - `ItemTraceRecord`: Full composite item record.
  - `ScreenAuditReport`: Complete document container with summary metrics.

- **OpenEMR Target Seams (`openemr-base-clean`)**:
  - **Care Team Storage & Service**: `src/Services/CareTeamService.php:550-580` (`getCareTeamData`) queries `care_teams` and `care_team_member`. FHIR `FhirCareTeamService.php:105,339` reads `CareTeamService.php:185-190`.
  - **Care Team Mismatch**: `src/Services/CareTeamService.php:565` filters out `status != 'inactive' AND status != 'entered-in-error'`; FHIR query at `src/Services/CareTeamService.php:190` has no status filter.
  - **AJAX Fragment Loaders**: `interface/patient_file/summary/demographics.php:606-732` loads `stats.php`, `pnotes_fragment.php`, `disc_fragment.php`, `labdata_fragment.php`, `track_anything_fragment.php`, `vitals_fragment.php`, `clinical_reminders_fragment.php`, `patient_reminders_fragment.php`.
  - **Immunizations Card**: Rendered in `interface/patient_file/summary/stats.php:272-314`, reading `immunizations` joined with `codes` / `code_types`, template `templates/patient/card/immunizations.html.twig:5-15`.
  - **Persistent Header**: `interface/main/tabs/templates/patient_data_template.php:100-113` Knockout bindings (`pname()`, `pubpid`, `patient().str_dob()`) populated by `demographics.php:916-967` (`setMyPatient()`). Traced to FHIR `Patient`: `FhirPatientService.php:212` (`active = true`), `FhirPatientService.php:218` (name), `FhirPatientService.php:222` (DOB), `FhirPatientService.php:552-566` (identifier `v2-0203|PT`).
  - **Intra-Card Columns**:
    - Allergies: `interface/patient_file/summary/stats.php:88-99` (`severity_al` via `severity_ccda`, `reaction`).
    - Prescriptions: `demographics.php:1187-1196` & `stats.php:107-121` (`prescriptions` table: Qty, Refills, Filled).
    - Care Team: `templates/patient/card/manage_care_team.html.twig:46-75` (`role`, `facility_id`, `provider_since`, `status`, `note`).
  - **Medications & Prescriptions Union**: `src/Services/PrescriptionService.php:91-260` (`lists` ∪ `prescriptions`).

- **CLI & Integration Seams (`auditor`)**:
  - `pyproject.toml:16-17`: Script entrypoint `auditor-ui-path = "auditor.ui_path.cli:app"`.
  - Version bump in `pyproject.toml` (2.1.0 -> 2.3.0) and `.claude-plugin/plugin.json` (2.2.0 -> 2.3.0).
  - Plugin skill `skills/ui-data-path-audit/SKILL.md` linked in `agents/auditor.md`.

## Testing Decisions

- **Failing Tests First**:
  - `test_defect_1_care_team_storage`: Assert Care Team traces to `care_teams` + `care_team_member` via `CareTeamService.php:550`, and FHIR `CareTeam`.
  - `test_defect_2_ajax_fragment_immunizations`: Assert fragment crawler in `demographics.php:606` finds Immunizations in `stats.php:272-314` and traces to `immunizations` and FHIR `Immunization`.
  - `test_defect_3_persistent_header`: Assert persistent header in `patient_data_template.php:100-112` filled by `demographics.php:916-967` traces to `Patient` with `v2-0203|PT` MRN and `active = true`.
  - `test_defect_4_card_columns`: Assert columns for Allergy severity, Prescription Qty/Refills/Filled, and Care Team role/facility/since/status are cataloged with individual traces.
- **Mismatch Testing**: Assert `ApiMismatch` flags Care Team member filtering with exact citations `CareTeamService.php:565` vs `CareTeamService.php:190`.
- **Rendering Rules Testing**: Assert gates, active filters, sort orders, empty states, and highlights are extracted.
- **Mutation Testing**: Domain mutations added to `dev/mutations.py` to ensure tests fail if any defect check or evidence citation is removed or broken.

## Vertical Slices

- **Slice 1 (Tracer Bullet)**: Pydantic Schema, Persistent Header & Markdown/JSON Formatter.
  - End-to-end tracer bullet proving the stack: parses `patient_data_template.php` + `demographics.php:916-967`, traces to FHIR `Patient`, emits JSON and Markdown parity table.
- **Slice 2**: Care Team Storage, Column Breakdown, and API Mismatch Detection.
  - Fixes Defect 1 & 4 (Care Team), verifies `CareTeamService.php:550`, extracts columns, flags status filter mismatch on both sides.
- **Slice 3**: AJAX Fragment Crawler & Core Cards.
  - Fixes Defect 2 & 4 (Allergies and Prescriptions), follows fragment loaders, traces Immunizations, Allergies, Problems, Medications, Prescriptions.
- **Slice 4**: Card Rendering Rules Engine.
  - Extracts gates, active filters, sort orders, empty states, highlights.
- **Slice 5**: Observed Confidence Pass (`--observed`).
  - Opt-in dynamic verification against live OpenEMR API.
- **Slice 6**: CLI, Skill, Packaging, & PR Delivery.
  - Version bump to 2.3.0, skill creation, README entry, git worktree/branch PR.

## Out of Scope

- Modifying or writing any files inside the target codebase (`openemr-base-clean` is strictly read-only).
- Multi-target generic adapter frameworks (built directly for OpenEMR-shaped PHP targets).
- Mutating actions during the `--observed` pass (only non-destructive or seeded read checks).
- Client-only UI elements that do not bind to backend data (pure styling/toggles).

## Success Criteria

1. Failing tests committed first for all 4 reference defects, then passing.
2. Target run against `demographics.php` produces 100% evidence-backed traces (`file:line`) for header and the 5 cards.
3. Care Team mismatch flagged with citations `src/Services/CareTeamService.php:565` vs `src/Services/CareTeamService.php:190`.
4. Header records `Patient.active = true` (`FhirPatientService.php:212`) and MRN `v2-0203|PT` (`FhirPatientService.php:552-566`).
5. All tests pass (`pytest`), strict typing passes (`mypy --strict`), formatting/lint passes (`ruff`), and mutation tests pass (`dev/mutations.py run`).
