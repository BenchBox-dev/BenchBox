"""Snowflake post-load schema introspector.

Reads ``INFORMATION_SCHEMA.TABLES.CLUSTERING_KEY`` for the tables the
applied-tuning ledger touched and surfaces them as ``cluster_key`` facts, so a
recorded ``ALTER TABLE ... CLUSTER BY (cols)`` can be corroborated and earn
``applied_verified`` (TODO ``snowflake-cluster-key-corroboration-20260730``;
design note ``docs/development/tuning-introspection-receipts.md``).

Snowflake is the platform whose tuning footprint lands *after* load: the adapter
applies the clustering key with ``ALTER TABLE``, not in ``CREATE TABLE``. Those
statements are already captured -- ``apply_standard_unified_tuning`` wraps the
connection in a recording connection -- so the only thing missing was a catalog
read to check them against.

Bounded (one query, capped, scoped to the ledger's tables) and non-fatal (any
failure returns an :class:`IntrospectedState` carrying ``error``, which refuses
the upgrade rather than guessing).

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from benchbox.core.tuning.applied_ledger import AppliedTuningLedger
from benchbox.core.tuning.introspection import (
    KIND_CLUSTER_KEY,
    IntrospectedObject,
    IntrospectedState,
    ledger_tables,
    normalize_columns,
    normalize_identifier,
)

logger = logging.getLogger(__name__)

#: Hard cap on catalog rows read.
_MAX_TABLE_ROWS = 1000

#: Snowflake reports a clustering key as ``LINEAR(A, B)``. Older/other paths in
#: this repo compare against a bare ``(A, B)``, so both forms are accepted --
#: guessing wrong here would mismatch every clustered table against its own
#: catalog fact, which fails CLOSED and would be invisible.
_CLUSTERING_KEY_RE = re.compile(r"^\s*(?:linear\s*)?\((?P<cols>.*)\)\s*$", re.IGNORECASE | re.DOTALL)


def parse_clustering_key(raw: Any) -> tuple[str, ...]:
    """Normalize a Snowflake ``CLUSTERING_KEY`` into comparable columns.

    Accepts ``LINEAR(A, B)``, ``(A, B)`` and a bare ``A, B``; returns ``()`` for
    NULL/empty (an unclustered table).
    """
    if raw is None:
        return ()
    text = str(raw).strip()
    if not text:
        return ()
    match = _CLUSTERING_KEY_RE.match(text)
    if match:
        text = match.group("cols")
    return normalize_columns(text)


class SnowflakeTuningIntrospector:
    """Introspect Snowflake ``INFORMATION_SCHEMA`` clustering keys."""

    platform = "snowflake"

    def __init__(self, schema: str | None = None) -> None:
        self._schema = schema

    def introspect(self, connection: Any, ledger: AppliedTuningLedger) -> IntrospectedState:
        """Read ``CLUSTERING_KEY`` from ``INFORMATION_SCHEMA.TABLES``.

        Never raises: a failed catalog read degrades to a state carrying
        ``error``, and corroboration then refuses the upgrade.
        """
        tables = ledger_tables(ledger)
        query = (
            "SELECT TABLE_NAME, CLUSTERING_KEY FROM INFORMATION_SCHEMA.TABLES "
            f"WHERE CLUSTERING_KEY IS NOT NULL LIMIT {_MAX_TABLE_ROWS}"
        )
        if self._schema:
            query = (
                "SELECT TABLE_NAME, CLUSTERING_KEY FROM INFORMATION_SCHEMA.TABLES "
                f"WHERE TABLE_SCHEMA = '{self._schema}' AND CLUSTERING_KEY IS NOT NULL "
                f"LIMIT {_MAX_TABLE_ROWS}"
            )

        try:
            rows = _fetch(connection, query)
        except Exception as exc:  # introspection must never break a run
            logger.debug("snowflake clustering introspection degraded: %s", exc)
            return IntrospectedState(platform=self.platform, error=f"INFORMATION_SCHEMA read failed: {exc}")

        relevant_rows = [row for row in rows if not tables or (row and normalize_identifier(row[0] or "") in tables)]
        truncated = len(relevant_rows) >= _MAX_TABLE_ROWS
        objects: list[IntrospectedObject] = []
        for row in relevant_rows:
            try:
                name, clustering_key = row[0], row[1]
            except Exception:  # pragma: no cover - defensive on row shape
                continue
            columns = parse_clustering_key(clustering_key)
            if not columns:
                continue
            objects.append(
                IntrospectedObject(
                    kind=KIND_CLUSTER_KEY,
                    table=name,
                    columns=columns,
                    evidence={"clustering_key": str(clustering_key)},
                )
            )
        return IntrospectedState(platform=self.platform, objects=objects, truncated=truncated)


def _fetch(connection: Any, query: str) -> list[Any]:
    """Run a read through either a cursor-style or execute-style connection."""
    cursor_factory = getattr(connection, "cursor", None)
    if callable(cursor_factory):
        cursor = cursor_factory()
        try:
            cursor.execute(query)
            return list(cursor.fetchall() or [])
        finally:
            close = getattr(cursor, "close", None)
            if callable(close):
                close()
    result = connection.execute(query)
    return list(result) if result is not None else []


__all__ = ["SnowflakeTuningIntrospector", "parse_clustering_key"]
