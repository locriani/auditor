"""Data models and enums for auditor."""

from dataclasses import dataclass
from enum import StrEnum
from typing import Literal


class ProbeStatus(StrEnum):
    OK = "ok"
    EMPTY = "empty"
    NA = "n/a"
    ERROR = "error"
    OUTPUT = "output"


class ProbeAxis(StrEnum):
    SECURITY = "security"
    SUPPLY_CHAIN = "supply-chain"
    PERFORMANCE = "performance"
    ARCHITECTURE = "architecture"
    CODE_QUALITY = "code-quality"
    TESTING = "testing"
    OBSERVABILITY = "observability"
    DATA_QUALITY = "data-quality"
    COMPLIANCE = "compliance"


@dataclass
class ProbeRecord:
    probe: str
    axis: str
    status: ProbeStatus
    exit: str
    bytes: int
    lines: int
    stderr: Literal["yes", "no"]
    file: str
    note: str

    def to_tsv_row(self) -> str:
        return f"{self.probe}\t{self.axis}\t{self.status.value}\t{self.exit}\t{self.bytes}\t{self.lines}\t{self.stderr}\t{self.file}\t{self.note}"


@dataclass
class ProbeOutput:
    exit_code: int
    stdout: str
    stderr: str
    truncated: bool = False
    full_output: str | None = None
    timed_out: bool = False
