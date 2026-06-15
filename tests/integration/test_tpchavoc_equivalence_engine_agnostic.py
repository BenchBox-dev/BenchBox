"""Engine-agnostic plumbing tests for the TPC-Havoc equivalence oracle.

These exercise the w0 refactor of :func:`find_divergences` - the dialect
``translate_variant`` injection and the ``skip_variants`` exclusion - WITHOUT a
live database, using a recording fake connection. The live cross-engine
behavior is covered by ``tests/integration/platforms/
test_tpchavoc_postgres_equivalence.py``; this is the fast deterministic guard
that the seam itself stays correct (variant translation is applied, canonical is
not double-translated, and skipped variants are never executed nor counted).

Copyright 2026 Joe Harris / BenchBox Project

TPC Benchmark(TM) H (TPC-H) - Copyright (C) Transaction Processing Performance Council.
This implementation is derived from TPC-H.

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import pytest

from benchbox.core.tpchavoc.benchmark import TPCHavocBenchmark
from benchbox.core.tpchavoc.equivalence import find_divergences

pytestmark = [
    pytest.mark.integration,
    pytest.mark.tpchavoc,
]


class _FakeResult:
    def __init__(self, rows: list[tuple]) -> None:
        self._rows = rows

    def fetchall(self) -> list[tuple]:
        return self._rows


class _RecordingConnection:
    """Minimal connection: records executed SQL and returns canned rows."""

    def __init__(self, rows: list[tuple]) -> None:
        self.rows = rows
        self.executed: list[str] = []

    def execute(self, sql: str) -> _FakeResult:
        self.executed.append(sql)
        return _FakeResult(self.rows)


@pytest.fixture
def havoc_benchmark() -> TPCHavocBenchmark:
    # No data generation/loading needed - get_query only renders SQL text.
    return TPCHavocBenchmark(scale_factor=0.1)


def test_default_path_is_identity_and_runs_every_variant(havoc_benchmark):
    """No translate_variant => variants run as authored (DuckDB-native path)."""
    connection = _RecordingConnection(rows=[(1,)])

    divergences = find_divergences(
        connection,
        havoc_benchmark,
        lambda _q: "SELECT 1 AS canonical",
        query_ids=[3],
    )

    assert divergences == []
    # 1 canonical + 10 variants, none translated (no marker injected).
    assert connection.executed[0] == "SELECT 1 AS canonical"
    assert sum(1 for s in connection.executed if "canonical" in s) == 1
    assert not any("/*translated*/" in s for s in connection.executed)


def test_translate_variant_applies_only_to_variants(havoc_benchmark):
    """translate_variant renders variant SQL; canonical is left untouched."""
    connection = _RecordingConnection(rows=[(1,)])

    divergences = find_divergences(
        connection,
        havoc_benchmark,
        lambda _q: "SELECT 1 AS canonical",
        query_ids=[3],
        translate_variant=lambda sql: sql + " /*translated*/",
    )

    assert divergences == []
    canonical_sql = [s for s in connection.executed if "canonical" in s]
    variant_sql = [s for s in connection.executed if "canonical" not in s]
    assert len(canonical_sql) == 1
    assert "/*translated*/" not in canonical_sql[0], "canonical must not be re-translated"
    assert variant_sql, "variants should have been executed"
    assert all(s.endswith("/*translated*/") for s in variant_sql), "every variant must be translated"


def test_skip_variants_are_excluded_not_executed_not_counted(havoc_benchmark):
    """Skipped variants are never executed and never reported as divergences."""
    connection = _RecordingConnection(rows=[(1,)])

    skipped = {"3_v2", "3_v5"}
    divergences = find_divergences(
        connection,
        havoc_benchmark,
        lambda _q: "SELECT 1 AS canonical",
        query_ids=[3],
        skip_variants=skipped,
    )

    assert divergences == []
    # 1 canonical + (10 - 2 skipped) = 9 variant executions.
    assert len(connection.executed) == 1 + (10 - len(skipped))
    keys = {d.key for d in divergences}
    assert keys.isdisjoint(skipped)
