"""Formatters for ScreenAuditReport (Markdown parity table and JSON)."""

from __future__ import annotations

from auditor.ui_path.models import ScreenAuditReport


def format_json(report: ScreenAuditReport, indent: int = 2) -> str:
    """Format report as indented JSON string."""
    return report.model_dump_json(indent=indent)


def format_parity_table(report: ScreenAuditReport) -> str:
    """Format report items as a Markdown parity table.

    Columns: Item | Storage | API Path | Confidence | Evidence | Mismatch
    """
    lines = [
        f"# Parity Table: {report.screen}",
        f"**Target:** `{report.target_path}` | **Observed run:** `{report.observed_run}` | **Total items:** {len(report.items)}",
        "",
        "| Item | Storage | API Path | Confidence | Evidence | Mismatch |",
        "|---|---|---|---|---|---|",
    ]

    for item in report.items:
        # Item label/kind
        item_desc = f"**{item.label}** (`{item.kind.value}`)"
        if item.card:
            item_desc = f"[{item.card}] {item_desc}"

        # Storage
        if item.storage:
            cols = f" ({', '.join(item.storage.columns)})" if item.storage.columns else ""
            storage_desc = f"`{item.storage.table}{cols}`"
            if item.storage.joins:
                storage_desc += f"<br>joins: `{', '.join(item.storage.joins)}`"
        else:
            storage_desc = "*(none)*"

        # API Path
        if item.api:
            api_path = item.api.path if item.api.path else item.api.resource
            api_desc = f"`{item.api.system}`: `{api_path}`"
        else:
            api_desc = "*(none)*"

        # Confidence
        confidence_desc = f"`{item.confidence.value}`"

        # Evidence
        all_evidence: list[str] = []
        if item.evidence:
            all_evidence.extend(item.evidence)
        if item.storage and item.storage.evidence:
            all_evidence.extend(item.storage.evidence)
        if item.api and item.api.evidence:
            all_evidence.extend(item.api.evidence)

        # Deduplicate while preserving order
        seen: set[str] = set()
        deduped_evidence: list[str] = []
        for ev in all_evidence:
            if ev not in seen:
                seen.add(ev)
                deduped_evidence.append(ev)

        evidence_desc = "<br>".join(f"`{ev}`" for ev in deduped_evidence) if deduped_evidence else "*(none)*"

        # Mismatch
        if item.mismatches:
            mismatch_parts = []
            for m in item.mismatches:
                mismatch_parts.append(
                    f"**{m.description}**<br>UI: `{m.ui_behavior}` (`{m.ui_evidence}`)<br>API: `{m.api_behavior}` (`{m.api_evidence}`)"
                )
            mismatch_desc = "<br><hr>".join(mismatch_parts)
        else:
            mismatch_desc = "*(none)*"

        # Escape pipe characters inside cells
        c_item = item_desc.replace("|", "\\|")
        c_storage = storage_desc.replace("|", "\\|")
        c_api = api_desc.replace("|", "\\|")
        c_conf = confidence_desc.replace("|", "\\|")
        c_ev = evidence_desc.replace("|", "\\|")
        c_mis = mismatch_desc.replace("|", "\\|")

        lines.append(f"| {c_item} | {c_storage} | {c_api} | {c_conf} | {c_ev} | {c_mis} |")

    return "\n".join(lines) + "\n"
