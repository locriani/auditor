"""Observability probes (health endpoints, log surface, telemetry, swallowed exceptions)."""

from __future__ import annotations

import collections
import re
from pathlib import Path

from auditor.bundle import BundleManager
from auditor.models import ProbeAxis, ProbeOutput
from auditor.probes.base import walk_target_files

CODE_EXTENSIONS = {".php", ".js", ".ts", ".py", ".go", ".rs", ".swift"}
HEALTH_REGEX = re.compile(r"(healthz|livez|readyz|/health|/ready|HealthCheck)", re.IGNORECASE)

LOG_FRAMEWORKS = [
    "Monolog",
    "winston",
    "pino",
    "logrus",
    "zap",
    "structlog",
    "SystemLogger",
    "EventAuditLogger",
    "tracing::",
    "use log::",
    "env_logger",
    "OSLog",
    "os_log",
    "swift-log",
]
LOG_REGEX = re.compile(r"(" + "|".join(LOG_FRAMEWORKS) + r")", re.IGNORECASE)

TELEMETRY_EXTENSIONS = CODE_EXTENSIONS | {".yml", ".yaml"}
TELEMETRY_REGEX = re.compile(
    r"(opentelemetry|OTEL_|prometheus|statsd|datadog|langfuse|phoenix)",
    re.IGNORECASE,
)

CATCH_EXTENSIONS = {".php", ".js", ".ts", ".swift"}
# Swift's `catch {` / `catch let e {` and JS's `catch {` take no parenthesis.
CATCH_REGEX = re.compile(r"\bcatch\b")
EMPTY_CATCH_REGEX = re.compile(r"\bcatch\b[^{}]*\{\s*\}")
EMPTY_BLOCK_REGEX = re.compile(r"^\s*\}")


def run_observability_probes(bundle: BundleManager, target: Path) -> None:
    """Execute health-endpoints, log-surface, telemetry, and swallowed-exceptions probes."""
    health_files: list[str] = []
    log_counter: collections.Counter[str] = collections.Counter()
    telemetry_files: list[str] = []
    swallowed_lines: list[str] = []

    for rel_path, full_path in walk_target_files(target):
        rel_str = str(rel_path)
        lower_str = rel_str.lower()
        ext = rel_path.suffix

        # 1. health-endpoints
        if ext in CODE_EXTENSIONS and not any(k in lower_str for k in ("node_modules", "vendor")):
            try:
                content = full_path.read_text(encoding="utf-8", errors="replace")
                if HEALTH_REGEX.search(content):
                    health_files.append(f"./{rel_path}")
            except Exception:
                pass

        # 2. log-surface
        if ext in CODE_EXTENSIONS:
            try:
                content = full_path.read_text(encoding="utf-8", errors="replace")
                for m in LOG_REGEX.finditer(content):
                    match_name = m.group(0)
                    # normalize casing to known frameworks
                    normalized = match_name
                    for fw in LOG_FRAMEWORKS:
                        if fw.lower() == match_name.lower():
                            normalized = fw
                            break
                    log_counter[normalized] += 1
            except Exception:
                pass

        # 3. telemetry
        if ext in TELEMETRY_EXTENSIONS and not any(
            k in lower_str for k in ("node_modules", "vendor")
        ):
            try:
                content = full_path.read_text(encoding="utf-8", errors="replace")
                if TELEMETRY_REGEX.search(content):
                    telemetry_files.append(f"./{rel_path}")
            except Exception:
                pass

        # 4. swallowed-exceptions
        if ext in CATCH_EXTENSIONS and not any(
            k in lower_str for k in ("node_modules", "vendor", "test")
        ):
            try:
                lines = full_path.read_text(encoding="utf-8", errors="replace").splitlines()
                for idx, line in enumerate(lines):
                    if EMPTY_CATCH_REGEX.search(line):
                        swallowed_lines.append(f"./{rel_path}:{idx + 1}:{line}")
                    elif CATCH_REGEX.search(line) and line.rstrip().endswith("{"):
                        # Check if next line closes the catch block immediately
                        if idx + 1 < len(lines) and EMPTY_BLOCK_REGEX.match(lines[idx + 1]):
                            swallowed_lines.append(f"./{rel_path}:{idx + 2}:{lines[idx + 1]}")
            except Exception:
                pass

    # 1. health-endpoints
    health_out = "\n".join(health_files) + ("\n" if health_files else "")
    h_rc = 0 if health_files else 1
    bundle.record_probe(
        "health-endpoints",
        ProbeAxis.OBSERVABILITY.value,
        ProbeOutput(h_rc, health_out, ""),
        ok_exits=[0, 1],
        cap=20,
    )

    # 2. log-surface
    log_lines = [f"{count:>7} {fw}" for fw, count in log_counter.most_common()]
    log_out = "\n".join(log_lines) + ("\n" if log_lines else "")
    l_rc = 0 if log_lines else 1
    bundle.record_probe(
        "log-surface",
        ProbeAxis.OBSERVABILITY.value,
        ProbeOutput(l_rc, log_out, ""),
        ok_exits=[0, 1],
        cap=20,
    )

    # 3. telemetry
    telemetry_out = "\n".join(telemetry_files) + ("\n" if telemetry_files else "")
    t_rc = 0 if telemetry_files else 1
    bundle.record_probe(
        "telemetry",
        ProbeAxis.OBSERVABILITY.value,
        ProbeOutput(t_rc, telemetry_out, ""),
        ok_exits=[0, 1],
        cap=20,
    )

    # 4. swallowed-exceptions
    swallowed_out = "\n".join(swallowed_lines) + ("\n" if swallowed_lines else "")
    s_rc = 0 if swallowed_lines else 1
    bundle.record_probe(
        "swallowed-exceptions",
        ProbeAxis.OBSERVABILITY.value,
        ProbeOutput(s_rc, swallowed_out, ""),
        ok_exits=[0, 1],
        cap=30,
    )
