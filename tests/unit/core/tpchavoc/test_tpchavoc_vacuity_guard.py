"""Negative tests for the TPC-Havoc DuckDB gate's vacuity/staleness guards.

Locks three failure modes that a silent partial load, an empty canonical query,
or a stale known-divergence baseline entry must all surface as a GATE FAILURE
rather than a silent false green - see
``_project/TODO/main/planning/tpchavoc-duckdb-gate-vacuity-guard.yaml``.

Uses pure fakes (no real DuckDB data generation) so these stay fast/unit, mirroring
``tests/unit/core/tpchavoc/test_equivalence_execute_transform.py``.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

import benchbox.core.tpchavoc.equivalence as equivalence_module
from benchbox.core.tpchavoc.equivalence import _report, find_divergences

pytestmark = [pytest.mark.unit, pytest.mark.fast]


class _FakeDuckDBAdapterVacuousLoad:
    """Stand-in for DuckDBAdapter whose load leaves one table at 0 rows."""

    def __init__(self, *, database):
        self.database = database

    def load_data(self, benchmark, connection, data_dir):
        stats = {
            "lineitem": 100,
            "orders": 0,  # the partial/empty table
            "partsupp": 10,
            "part": 10,
            "customer": 10,
            "supplier": 10,
            "nation": 25,
            "region": 5,
        }
        return stats, 0.0, None


def test_build_duckdb_with_tpch_vacuity_guard_raises_on_partial_load(monkeypatch, tmp_path):
    """A DuckDB load that leaves any table at 0 rows must raise, not return silently."""
    fake_tpchavoc = MagicMock()
    fake_tpchavoc.get_create_tables_sql.return_value = ""
    fake_tpch = MagicMock()

    monkeypatch.setattr(
        equivalence_module,
        "_generate_tpch",
        lambda scale_factor, output_dir: (tmp_path, fake_tpchavoc, fake_tpch),
    )
    fake_connection = MagicMock()
    monkeypatch.setattr("duckdb.connect", lambda *_a, **_kw: fake_connection)
    monkeypatch.setattr("benchbox.platforms.duckdb.DuckDBAdapter", _FakeDuckDBAdapterVacuousLoad)

    with pytest.raises(RuntimeError, match=r"DuckDB TPC-H load failed - no rows in \['orders'\]"):
        equivalence_module.build_duckdb_with_tpch(0.1, tmp_path)

    # The connection opened for the failed build must not leak.
    fake_connection.close.assert_called_once()


class _VacuousCanonicalConnection:
    """Fake connection whose canonical query always returns 0 rows."""

    def __init__(self):
        self.executed: list[str] = []

    def execute(self, sql: str):
        self.executed.append(sql)
        result = MagicMock()
        result.fetchall.return_value = []
        return result


def test_find_divergences_vacuity_guard_fails_on_empty_canonical_query():
    """A canonical query returning 0 rows must fail loudly, not silently pass every variant."""
    conn = _VacuousCanonicalConnection()
    benchmark = MagicMock()
    benchmark.get_implemented_queries.return_value = [1]

    divergences = find_divergences(conn, benchmark, lambda q: "SELECT c FROM t")

    assert len(divergences) == 1
    divergence = divergences[0]
    assert divergence.query_id == 1
    assert divergence.variant_id == 0
    assert "vacuous" in divergence.detail.lower()
    # Only the canonical query was executed - the vacuous canonical short-circuits
    # the variant sweep instead of comparing empty-vs-empty for all ten variants.
    assert len(conn.executed) == 1
    benchmark.get_query.assert_not_called()


def test_find_divergences_vacuity_guard_does_not_flag_a_nonempty_canonical_query():
    """A normal, non-empty canonical query is unaffected by the vacuity guard."""

    class _NonEmptyConnection:
        def execute(self, sql: str):
            result = MagicMock()
            result.fetchall.return_value = [(1,)]
            return result

    benchmark = MagicMock()
    benchmark.get_implemented_queries.return_value = [1]
    benchmark.get_query.return_value = "SELECT v FROM t"
    benchmark.validate_variant_equivalence.return_value = None

    divergences = find_divergences(_NonEmptyConnection(), benchmark, lambda q: "SELECT c FROM t")

    assert divergences == []


def test_report_vacuity_guard_fails_on_stale_resolved_baseline(capsys):
    """A known-divergence entry whose divergence no longer reproduces must fail the report."""
    exit_code = _report(
        [],  # no live divergences this run
        total=10,
        known={"1_v1": "a variant defect that has since been fixed"},
        engine_label="DuckDB",
        baseline_name="KNOWN_DIVERGENCES",
    )

    out = capsys.readouterr().out
    assert exit_code == 1
    assert "GATE FAILURE - previously-known divergences now equivalent" in out
    assert "1_v1" in out
    assert "KNOWN_DIVERGENCES" in out


def test_report_vacuity_guard_stays_green_with_no_new_or_resolved_entries(capsys):
    """Regression guard: an empty new/resolved set must still return 0 (unchanged behavior)."""
    exit_code = _report(
        [],
        total=10,
        known={},
        engine_label="DuckDB",
        baseline_name="KNOWN_DIVERGENCES",
    )

    out = capsys.readouterr().out
    assert exit_code == 0
    assert "All variants equivalent to canonical TPC-H" in out
