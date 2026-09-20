"""Result-equivalence regression test for the Read Primitives cross-surface gate.

This is the fast, default-lane companion to the full Read Primitives cross-surface
equivalence gate in ``benchbox/core/equivalence/cross_surface.py`` (run via
``make read-primitives-cross-surface-equivalence-report``, wired into the
``correctness-gate`` CI job), mirroring
``tests/integration/test_h2odb_cross_surface_equivalence.py``. It executes every
gateable Read Primitives query's DataFrame surface (both backends) against its OWN
DuckDB-dialect SQL surface on a bounded DuckDB cell and asserts they agree - SQL is
the trusted reference for its own DataFrame surface, so no hand-curated answer key
is needed.

Read Primitives is a *primitives* benchmark, so a handful of cells are classified
in the gate's ``known_divergences`` baseline: engine differences with no faithful
exact DataFrame equivalent - HyperLogLog/T-Digest approximations
(``APPROX_COUNT_DISTINCT``/``APPROX_QUANTILE``), DECIMAL-scale ``PERCENTILE_CONT``
and ``ROUND`` residues, the non-deterministic ``ARG_MIN`` tie, JSON text vs native
containers, and the Polars Map-dtype gap. A few selective / no-JSON filters are
legitimately empty on the bounded cell (``legitimately_empty``) and therefore
compare empty-vs-empty rather than diverging. Everything else must match.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import pytest

pytest.importorskip("polars", reason="Polars not installed")
pytest.importorskip("pandas", reason="Pandas not installed")
pytest.importorskip("duckdb", reason="DuckDB not installed")

from benchbox.core.equivalence.cross_surface import (
    GATES,
    build_production_contexts,
    count_executed_cells,
    find_cross_surface_divergences,
    find_cross_surface_dtype_divergences,
)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.medium,
    pytest.mark.duckdb,
]


# Runs to completion but far exceeds the medium lane's 60s cap: timed out
# on a clean GitHub runner (develop-post-merge run 28706929881, medium-test
# job) and measured ~246s in a 4-core container (2026-07-05). The marker
# overrides the CLI --timeout=60 (pytest-timeout marker precedence) so the
# test keeps running in the medium lane instead of being killed mid-work.
@pytest.mark.timeout(600)
def test_read_primitives_dataframe_surface_equivalent_to_sql(tmp_path):
    """Every gateable Read Primitives DataFrame query (both backends) must match its own SQL."""
    gate = GATES["read_primitives"]
    data = gate.build(gate.scale_factor, tmp_path)
    connection = data.connection
    try:
        contexts = build_production_contexts(
            data.benchmark, data.data_dir, backends=gate.backends, scale_factor=gate.scale_factor
        )
        divergences = find_cross_surface_divergences(
            connection,
            query_ids=data.query_ids,
            reference_sql=data.reference_sql,
            dataframe_query=data.dataframe_query,
            contexts=contexts,
            validator=gate.build_validator(),
            backends=gate.backends,
        )
        coverage = count_executed_cells(data.query_ids, data.dataframe_query, gate.backends)
    finally:
        connection.close()

    # Both gated backends must actually compare something - a fully-unimplemented
    # backend would make the gate silently green by comparing nothing.
    missing = sorted(backend for backend, count in coverage.items() if count == 0)
    assert not missing, f"gated Read Primitives backend(s) implement no queries: {missing}"

    # Tolerate only the cells explicitly classified in the baseline (approximate /
    # DECIMAL / representational / Polars-Map), never an unclassified regression.
    unexpected = {d.key for d in divergences} - set(gate.known_divergences)
    assert not unexpected, "Read Primitives DataFrame surface diverges from SQL: " + ", ".join(
        f"{d.key} ({d.detail})" for d in divergences if d.key in unexpected
    )


# Same medium-lane cost class as the value gate above: the bounded cell build
# dominates, so this carries its own 600s marker rather than sharing the
# module default.
@pytest.mark.timeout(600)
def test_read_primitives_expression_frame_dtypes_match_sql(tmp_path):
    """Every compared expression cell's frame dtypes must match the SQL reference.

    Value comparison normalizes scalars, so a wrong-dtype column with
    equal-looking values passes the gate above silently. This dtype cell
    compares per-column dtype categories instead. Pandas frames are out of
    scope (numpy/object dtypes carry no type signal; value comparison remains
    their guard). Dtype waivers are separate from value-divergence waivers.
    Legitimately-empty selective filters are NOT skipped: empty Arrow tables
    and empty Polars frames retain their declared source-column schemas, so a
    loader regression (e.g. Decimal/String becoming Null) stays detectable
    with zero rows. Only json_extract_nested is skipped: its frame columns are
    computed by JSON extraction over zero rows, which Polars infers as Null -
    an empty-input inference artifact, not a loader regression - while DuckDB
    still declares the JSON function's string output type.
    """
    gate = GATES["read_primitives"]
    data = gate.build(gate.scale_factor, tmp_path)
    connection = data.connection
    try:
        contexts = build_production_contexts(
            data.benchmark, data.data_dir, backends=gate.backends, scale_factor=gate.scale_factor
        )
        divergences, compared = find_cross_surface_dtype_divergences(
            connection,
            query_ids=data.query_ids,
            reference_sql=data.reference_sql,
            dataframe_query=data.dataframe_query,
            contexts=contexts,
            backends=("expression",),
            skip_keys=gate.dtype_skip_keys,
            # Only the computed-over-empty JSON query is skipped (see
            # docstring); the selective filters compare schemas with zero rows.
            skip_query_ids=frozenset({"json_extract_nested"}),
        )
    finally:
        connection.close()

    assert compared.get("expression", 0) > 100, (
        f"dtypes compared on too few cells ({compared}): the cell must not go green by comparing nothing"
    )
    assert not divergences, "Read Primitives expression frame dtypes diverge from SQL: " + ", ".join(
        f"{d.key} ({d.detail})" for d in divergences
    )
