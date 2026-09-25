"""Pydantic data models for UI data-path audit records."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ConfidenceLevel(StrEnum):
    PRECISE = "precise"
    RESOURCE_LEVEL = "resource-level"
    TABLE_FALLBACK = "table-fallback"
    OBSERVED = "observed"


class ItemKind(StrEnum):
    CARD = "card"
    FIELD = "field"
    COLUMN = "column"
    BADGE = "badge"
    EMPTY_STATE = "empty-state"
    HEADER = "header"
    ACTION = "action"


class StorageRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    table: str
    columns: list[str] = Field(default_factory=list)
    joins: list[str] = Field(default_factory=list)
    filters: dict[str, Any] = Field(default_factory=dict)
    evidence: list[str] = Field(default_factory=list)


class ApiRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    system: str = "FHIR"
    resource: str
    path: str | None = None
    evidence: list[str] = Field(default_factory=list)


class WriteRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    file_line: str
    method_or_service: str
    payload_shape: dict[str, Any] | None = None


class CardRenderingRules(BaseModel):
    model_config = ConfigDict(extra="forbid")

    gate: str | None = None
    gate_evidence: str | None = None
    active_filter: str | None = None
    active_filter_evidence: str | None = None
    sort_order: str | None = None
    sort_order_evidence: str | None = None
    empty_state: str | None = None
    empty_state_evidence: str | None = None
    highlighting: str | None = None
    highlighting_evidence: str | None = None


class ApiMismatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ui_behavior: str
    ui_evidence: str  # file:line
    api_behavior: str
    api_evidence: str  # file:line
    description: str


class ItemTraceRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_id: str
    screen: str
    card: str | None = None
    label: str
    kind: ItemKind
    storage: StorageRef | None = None
    api: ApiRef | None = None
    write_path: WriteRef | None = None
    confidence: ConfidenceLevel
    rendering_rules: CardRenderingRules | None = None
    mismatches: list[ApiMismatch] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)


class ScreenAuditReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    screen: str
    target_path: str
    observed_run: bool = False
    items: list[ItemTraceRecord] = Field(default_factory=list)
    summary: dict[str, Any] = Field(default_factory=dict)
