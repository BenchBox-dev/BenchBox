"""ClickHouse post-load schema introspector.

Reads the structured ``system.tables`` catalog (``sorting_key`` /
``partition_key`` columns) for the tables the applied-tuning ledger touched
and surfaces them as receipt evidence (TODO
``tuning-introspection-receipts-20260716`` / design note
``docs/development/tuning-introspection-receipts.md``).

Bounded (one query, capped, scoped to ``currentDatabase()`` and the ledger's
tables) and non-fatal (any failure returns an :class:`IntrospectedState` with
``error`` set). Uses structured catalog columns, never ``SHOW CREATE TABLE``
DDL text.

ClickHouse applies ``ORDER BY`` / ``PARTITION BY`` at ``CREATE TABLE`` time in
the schema phase, which is not wrapped by the tuning recording connection. A
*tuned* sort key is therefore folded into the applied ledger explicitly by
``create_schema`` (``_record_tuned_sort_key_op`` records the executed
``CREATE TABLE ... ORDER BY (cols)`` as a ``PHASE_DDL`` statement), so this
introspector's ``sorting_key`` read can corroborate that recorded intent and
earn ``applied_verified``. The *engine-mandatory baseline* ``ORDER BY``
(primary-key derived or ``tuple()``) is not tuning and is deliberately NOT
recorded -- a MergeTree table's ``sorting_key`` is always present, so
corroborating it against nothing would be an unearned upgrade. The ledger's
other ClickHouse tuning entries remain ``OPTIMIZE TABLE`` (maintenance,
non-blocking) and session SETs.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import logging
from typing import Any

from benchbox.core.tuning.applied_ledger import AppliedTuningLedger
from benchbox.core.tuning.introspection import (
    KIND_PARTITION_KEY,
    KIND_SORT_KEY,
    IntrospectedObject,
    IntrospectedState,
    ledger_tables,
    normalize_columns,
    normalize_identifier,
)

logger = logging.getLogger(__name__)

#: Hard cap on catalog rows read.
_MAX_TABLE_ROWS = 1000


class ClickHouseTuningIntrospector:
    """Introspect ClickHouse ``system.tables`` keys to corroborate the ledger."""

    platform = "clickhouse"

    def introspect(self, connection: Any, ledger: AppliedTuningLedger) -> IntrospectedState:
        """Read ``sorting_key`` / ``partition_key`` from ``system.tables``.

        Returns ``sort_key`` / ``partition_key`` facts for the ledger's tables.
        Never raises: a failed catalog read degrades to a state carrying
        ``error``.
        """
        tables = ledger_tables(ledger)
        try:
            result = connection.execute(
                "SELECT name, sorting_key, partition_key FROM system.tables "
                f"WHERE database = currentDatabase() LIMIT {_MAX_TABLE_ROWS}"
            )
            rows = list(result) if result is not None else []
        except Exception as exc:  # introspection must never break a run
            logger.debug("clickhouse table introspection degraded: %s", exc)
            return IntrospectedState(platform=self.platform, error=f"system.tables read failed: {exc}")

        truncated = len(rows) >= _MAX_TABLE_ROWS
        objects: list[IntrospectedObject] = []
        for row in rows:
            try:
                name, sorting_key, partition_key = row[0], row[1], row[2]
            except Exception:  # pragma: no cover - defensive on row shape
                continue
            if tables and normalize_identifier(name or "") not in tables:
                continue
            if sorting_key:
                objects.append(
                    IntrospectedObject(
                        kind=KIND_SORT_KEY,
                        table=name,
                        columns=normalize_columns(sorting_key),
                        evidence={"sorting_key": sorting_key},
                    )
                )
            if partition_key:
                objects.append(
                    IntrospectedObject(
                        kind=KIND_PARTITION_KEY,
                        table=name,
                        columns=normalize_columns(partition_key),
                        evidence={"partition_key": partition_key},
                    )
                )
        return IntrospectedState(platform=self.platform, objects=objects, truncated=truncated)


__all__ = ["ClickHouseTuningIntrospector"]
