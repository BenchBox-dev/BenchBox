"""Approved consequence-prefix convention for sql_compat rule reason strings.

Rule reason fields must lead with the user-visible consequence, then state
the platform-specific cause. This module defines the approved set of prefixes
so both rule files and the linter import from one place.

Enforcement: scripts/compat_lint.py walks the registry and warns (not errors)
on rules whose reason does not start with an approved prefix. Promotion to error
mode is a separate follow-up after all existing rules comply.

Usage in rule files:
    from benchbox.sql_compat._reason_conventions import REASON_PREFIXES
    # pick the prefix that matches the user-visible outcome, then append cause
"""

from __future__ import annotations

# Consequence prefixes keyed by the SupportLevel they are associated with.
# Values are tuple[str, str]: (prefix, description of when to use it).
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

# Flat set of all approved leading strings for fast prefix-check in the linter.
APPROVED_PREFIXES: frozenset[str] = frozenset(v[0] for v in REASON_PREFIXES.values())
