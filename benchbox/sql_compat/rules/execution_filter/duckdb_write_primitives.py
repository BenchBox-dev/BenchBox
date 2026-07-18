"""DuckDB execution-filter rule for write_primitives ``MERGE INTO`` gaps.

Bundled DuckDB 1.3.2 rejects ``MERGE INTO``. Operations are gated on the presence
of that statement in the SQL DuckDB will actually execute, rather than on the
whole ``merge`` operation category, because the category also covers the portable
SCD Type 2 ops (merge_scd_type2_basic / _no_change / _new_keys_only) expressed as
UPDATE + INSERT, which DuckDB runs and validates correctly. Token-gating keeps
those portable ops executing and automatically covers any future ``MERGE INTO``
operation with no per-operation skip list to maintain.

Detection strips SQL comments and string literals and matches ``MERGE`` and
``INTO`` separated by arbitrary whitespace, so a commented-out or quoted token is
not a false skip and a ``MERGE\\nINTO`` / ``MERGE  INTO`` / CTE-prefixed variant
is not a false pass (bundled DuckDB rejects all of those).

``duckdb_write_primitive_skip_reason`` is the runtime source of truth;
``benchbox.core.write_primitives.benchmark`` imports and calls it directly. The
same detector also drives the REGISTRY registration below: every catalog op whose
write_sql contains a ``MERGE INTO`` statement is registered, so the registry (and
the compat-docs skip reference generated from it) reflects the full runtime skip
set - all 21 such ops today, not a hand-maintained subset. The registration is
derived, not enumerated, so it stays in sync with the catalog automatically.

Evidence: DuckDB 1.3.2 local execution verification on 2026-06-30 - the legacy
MERGE INTO ops raise a parser error while the portable SCD Type 2 ops execute and
validate green (tests/integration/test_write_primitives_duckdb.py -k scd2).
"""

from __future__ import annotations

import re

from benchbox.sql_compat.actions import CompatAction
from benchbox.sql_compat.context import Phase
from benchbox.sql_compat.decision import CompatibilityDecision, FailureMode, SkipQueryPayload, SupportLevel
from benchbox.sql_compat.registry import REGISTRY

_LINE_COMMENT = re.compile(r"--[^\n]*")
_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
_STRING_LITERAL = re.compile(r"'(?:[^']|'')*'")
_MERGE_INTO = re.compile(r"\bMERGE\s+INTO\b", re.IGNORECASE)

DUCKDB_WRITE_PRIMITIVES_MERGE_SKIP_REASON = (
    "DuckDB 1.3.2 rejects the catalog's MERGE INTO statements; keep them explicit skips until the "
    "bundled driver supports MERGE. Portable merge operations written as UPDATE/INSERT run normally."
)


def _has_merge_into(sql: str) -> bool:
    """True if ``sql`` contains a real ``MERGE INTO`` statement (ignoring comments/strings)."""
    stripped = _BLOCK_COMMENT.sub(" ", sql)
    stripped = _LINE_COMMENT.sub(" ", stripped)
    stripped = _STRING_LITERAL.sub(" ", stripped)
    return _MERGE_INTO.search(stripped) is not None


def duckdb_write_primitive_skip_reason(operation, effective_sql: str | None = None) -> str | None:
    """Return a skip reason if ``operation`` cannot execute on bundled DuckDB, else ``None``.

    Args:
        operation: The write operation (used only for its default ``write_sql``).
        effective_sql: The SQL DuckDB will actually run, after platform-override
            resolution. When provided it is authoritative, so a per-platform
            override that removes (or introduces) a ``MERGE INTO`` is gated
            correctly. Defaults to ``operation.write_sql``.
    """
    sql = effective_sql if effective_sql is not None else (getattr(operation, "write_sql", "") or "")
    if _has_merge_into(sql):
        return DUCKDB_WRITE_PRIMITIVES_MERGE_SKIP_REASON
    return None


def _register_merge_into_skips() -> None:
    """Register every catalog write_primitives op with a MERGE INTO statement.

    Derived from the catalog with the same detector the runtime uses, so the
    registry (and the generated compat-docs skip reference) matches the runtime
    skip set exactly. Degrades to a no-op if the catalog cannot be loaded at
    import time - the runtime token gate is unaffected either way.
    """
    try:
        from benchbox.core.write_primitives.catalog import load_write_primitives_catalog

        catalog = load_write_primitives_catalog()
    except Exception:
        return

    for op_id, operation in catalog.operations.items():
        if not _has_merge_into(getattr(operation, "write_sql", "") or ""):
            continue
        REGISTRY.register(
            CompatibilityDecision(
                rule_id=f"execution_filter.duckdb.write_primitives.{op_id}",
                action=CompatAction.SKIP_QUERY,
                support_level=SupportLevel.SKIPPED_QUERY,
                failure_mode=FailureMode.UNSUPPORTED_FEATURE,
                payload=SkipQueryPayload(
                    reason=(
                        f"{DUCKDB_WRITE_PRIMITIVES_MERGE_SKIP_REASON} "
                        "Evidence: DuckDB 1.3.2 local execution verification on 2026-06-30."
                    ),
                    query_id=op_id,
                ),
                reason=DUCKDB_WRITE_PRIMITIVES_MERGE_SKIP_REASON,
            ),
            Phase.EXECUTION_FILTER,
            "duckdb",
            benchmark="write_primitives",
            query_id=op_id,
        )


_register_merge_into_skips()
