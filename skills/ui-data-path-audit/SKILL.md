---
name: ui-data-path-audit
description: Audits a single screen of a web application to catalog visible items (cards, fields, columns, badges, empty states) and trace each one to underlying storage, write paths, and API/FHIR parity with file:line evidence. Use when assessing frontend migration feasibility or auditing UI-to-API data paths.
---

# UI Data-Path Audit

Audits an application screen to determine whether and how every visible item can be rebuilt from backend APIs, and identifies where the screen and API diverge in data or filtering.

## The one rule that governs everything

**Every trace carries evidence as `file:line`, never a bare file name, plus a confidence level.**

```
always:  catalog(screen) → trace(storage, api, write) → cite(file:line) → flag(mismatches)
never:   evidence without line number = ✗
never:   unverified claim marked observed = ✗
never:   quietly dropping intra-card columns or AJAX fragments = ✗
```

## Running the Audit

Run directly with `uv run`:

```sh
uv run auditor-ui-path <screen-path> [--target-dir <target>] [--format json|markdown|both] [--out <file>] [--observed]
```

### Examples

```sh
# Markdown parity table for patient dashboard
uv run auditor-ui-path interface/patient_file/summary/demographics.php --target-dir /path/to/openemr --format markdown

# JSON schema-validated output
uv run auditor-ui-path interface/patient_file/summary/demographics.php --target-dir /path/to/openemr --format json -o audit.json

# Opt-in dynamic observed pass
uv run auditor-ui-path interface/patient_file/summary/demographics.php --target-dir /path/to/openemr --observed
```

## Confidence Tiers

1. `precise`: Concrete scalar API path match found (e.g., `Patient.birthDate`).
2. `resource-level`: UI item maps to an API resource, but not a single scalar path (e.g. Allergies card to `AllergyIntolerance`).
3. `table-fallback`: Underlying storage is known, but no precise API path was inferred.
4. `observed`: Proven dynamically by running the system, seeding known data, and confirming arrival through the API. Opt-in behind `--observed`.

## Card Rendering Rules

For each card on the screen, the audit extracts:
- **The Gate**: ACL check, global flag, or hidden-card setting.
- **The Active Filter**: Query or in-memory criteria filtering active items.
- **The Sort Order**: Ordering applied by query or UI.
- **Empty-State Strings**: Exact strings displayed when empty, and conditions under which they show.
- **Highlighting**: Conditional styling or badges based on field values (e.g., critical allergy highlight).

## API vs. Screen Mismatches

Flag every location where reading from the API would return different data from what the UI screen renders. For example:
- The Care Team card hides members that are inactive or entered in error (`src/Services/CareTeamService.php:565`).
- The FHIR `CareTeam` resource query returns all members from `care_team_member` regardless of status (`src/Services/CareTeamService.php:190`).
- Each flag carries `file:line` evidence on both sides.
