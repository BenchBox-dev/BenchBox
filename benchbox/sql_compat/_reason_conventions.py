from __future__ import annotations

REASON_PREFIXES: dict[str, tuple[str, str]] = {
    "BLOCKED": (
        "Benchmark blocked at preflight.",
        "Use for BLOCKED rules where the entire benchmark is refused before any execution.",
    ),
    "SKIPPED_QUERY": (
        "Query omitted from results.",
        "Use for SKIPPED_QUERY rules where a specific query is excluded from the result set.",
    ),
    "SKIPPED_DDL_FRAGMENT": (
        "Workload runs; auxiliary DDL is suppressed.",
        "Use for SKIPPED_DDL_FRAGMENT rules where a DDL statement is dropped but the workload completes.",
    ),
    "INFORMATIONAL": (
        "Workload runs;",
        "Use for INFORMATIONAL rules where the workload runs but a semantic guarantee is not enforced. "
        "Follow with the specific gap (e.g. 'PRIMARY KEY uniqueness is not enforced').",
    ),
}

APPROVED_PREFIXES: frozenset[str] = frozenset(v[0] for v in REASON_PREFIXES.values())
