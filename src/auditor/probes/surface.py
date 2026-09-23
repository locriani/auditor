"""Surface probes (route-tables and route-verbs)."""

from __future__ import annotations

import collections
import re
from pathlib import Path

from auditor.bundle import BundleManager
from auditor.models import ProbeAxis, ProbeOutput
from auditor.probes.base import walk_target_files

ROUTE_TABLE_EXTENSIONS = {".php", ".js", ".ts", ".py", ".rb", ".go"}
ROUTE_TABLE_REGEX = re.compile(r"(GET|POST|PUT|PATCH|DELETE)\s+/", re.IGNORECASE)

ROUTE_VERB_EXTENSIONS = {".php", ".inc.php", ".js", ".ts"}
ROUTE_VERB_REGEX = re.compile(
    r"\"(GET|POST|PUT|PATCH|DELETE)\s+/[A-Za-z0-9_/:.-]*\"", re.IGNORECASE
)


def run_surface_probes(bundle: BundleManager, target: Path) -> None:
    """Execute route-tables and route-verbs probes."""
    route_table_files: list[str] = []
    verb_counter: collections.Counter[str] = collections.Counter()

    for rel_path, full_path in walk_target_files(target):
        rel_str = str(rel_path)
        # Check route-tables
        ext = rel_path.suffix
        if ext in ROUTE_TABLE_EXTENSIONS:
            # Exclude node_modules, vendor, test, spec from path
            lower_path = rel_str.lower()
            if not any(k in lower_path for k in ("node_modules", "vendor", "test", "spec")):
                try:
                    content = full_path.read_text(encoding="utf-8", errors="replace")
                    if ROUTE_TABLE_REGEX.search(content):
                        route_table_files.append(f"./{rel_path}")
                except Exception:
                    pass

        # Check route-verbs
        is_verb_file = ext in ROUTE_VERB_EXTENSIONS or rel_str.endswith(".inc.php")
        if is_verb_file:
            try:
                content = full_path.read_text(encoding="utf-8", errors="replace")
                for m in ROUTE_VERB_REGEX.finditer(content):
                    match_str = m.group(0).strip('"')
                    verb = match_str.split()[0].upper()
                    verb_counter[verb] += 1
            except Exception:
                pass

    # 1. route-tables
    route_tables_out = "\n".join(route_table_files) + ("\n" if route_table_files else "")
    rt_rc = 0 if route_table_files else 1
    bundle.record_probe(
        "route-tables",
        ProbeAxis.ARCHITECTURE.value,
        ProbeOutput(rt_rc, route_tables_out, ""),
        ok_exits=[0, 1],
        cap=20,
    )

    # 2. route-verbs
    verb_lines = [f"{count:>7} {verb}" for verb, count in verb_counter.most_common()]
    route_verbs_out = "\n".join(verb_lines) + ("\n" if verb_lines else "")
    rv_rc = 0 if verb_lines else 1
    bundle.record_probe(
        "route-verbs",
        ProbeAxis.ARCHITECTURE.value,
        ProbeOutput(rv_rc, route_verbs_out, ""),
        ok_exits=[0, 1],
        cap=20,
    )
