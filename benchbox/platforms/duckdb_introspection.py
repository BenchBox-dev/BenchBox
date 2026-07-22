"""DuckDB post-load schema introspector.

Confirms the ``CREATE INDEX`` statements the applied-tuning ledger recorded
against the real catalog via the structured ``duckdb_indexes()`` table
function (TODO ``tuning-introspection-receipts-20260716`` / design note
``docs/development/tuning-introspection-receipts.md``).

Bounded (one query, capped, filtered to the tables the ledger touched) and
non-fatal (any failure returns an :class:`IntrospectedState` with ``error``
set, never raises). Uses the ``expressions`` catalog column -- the structured
indexed-column list -- rather than screen-scraping the ``sql`` DDL text.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import logging
from typing import Any

from benchbox.core.tuning.applied_ledger import AppliedTuningLedger
from benchbox.core.tuning.introspection import (
    KIND_INDEX,
    IntrospectedObject,
    IntrospectedState,
    ledger_tables,
    normalize_columns,
    normalize_identifier,
)

logger = logging.getLogger(__name__)

#: Hard cap on catalog rows read, so a pathological schema can never turn
#: introspection into an unbounded scan.
_MAX_INDEX_ROWS = 1000


class DuckDBTuningIntrospector:
    """Introspect DuckDB indexes to corroborate the applied ledger."""

    platform = "duckdb"

    def introspect(self, connection: Any, ledger: AppliedTuningLedger) -> IntrospectedState:
        """Read ``duckdb_indexes()`` for the tables the ledger touched.

        Returns an :class:`IntrospectedState` of ``index`` facts. Never raises:
        a failed catalog read degrades to a state carrying ``error`` so
        corroboration refuses the verification upgrade.
        """
        tables = ledger_tables(ledger)
        try:
            cursor = connection.execute(
                "SELECT table_name, index_name, expressions, is_unique, is_primary "
                f"FROM duckdb_indexes() LIMIT {_MAX_INDEX_ROWS}"
            )
            rows = cursor.fetchall()
        except Exception as exc:  # introspection must never break a run
            logger.debug("duckdb index introspection degraded: %s", exc)
            return IntrospectedState(platform=self.platform, error=f"duckdb_indexes read failed: {exc}")

        truncated = len(rows) >= _MAX_INDEX_ROWS
        objects: list[IntrospectedObject] = []
        for row in rows:
            try:
                table_name, index_name, expressions, is_unique, is_primary = (
                    row[0],
                    row[1],
                    row[2],
                    row[3],
                    row[4],
                )
            except Exception:  # pragma: no cover - defensive on row shape
                continue
            # Bound to the ledger's tables (when known) so evidence stays scoped.
            if tables and normalize_identifier(table_name or "") not in tables:
                continue
            objects.append(
                IntrospectedObject(
                    kind=KIND_INDEX,
                    table=table_name,
                    columns=normalize_columns(expressions),
                    name=index_name,
                    evidence={
                        "index_name": index_name,
                        "expressions": expressions,
                        "is_unique": bool(is_unique),
                        "is_primary": bool(is_primary),
                    },
                )
            )
        return IntrospectedState(platform=self.platform, objects=objects, truncated=truncated)


__all__ = ["DuckDBTuningIntrospector"]
