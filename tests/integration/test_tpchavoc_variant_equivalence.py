"""Result-equivalence regression test for the fixed TPC-Havoc variants.

This is the narrow, gating companion to the non-gating diagnostic in
``benchbox/core/tpchavoc/equivalence.py`` (run via
``make tpchavoc-equivalence-report``). The diagnostic enumerates every variant
that diverges from canonical TPC-H; this test locks in the variant correctness
defects that have been fixed so far:

* ``q2_v10`` / ``q10_v10`` - clamped negative account balances to ``0`` via CASE
  projections.
* ``q1_v8`` - aggregated over unfiltered ``lineitem`` (the shipdate predicate was
  in ``QUALIFY``, which filters output rows, not aggregation input).
* ``q7_v5`` - fanned a date-filtered-orders CTE back against the full
  ``lineitem`` table, inflating revenue ~4.5x.
* ``q9_v10`` - bucketed 22 nations into ``OTHER AMERICAS`` and clamped negative
  profit to ``0``.

A broader hard gate over all queries is deliberately deferred until the
remaining divergence classes recorded in
``benchbox.core.tpchavoc.equivalence.KNOWN_DIVERGENCES`` are triaged (see
``_project/TODO/main/planning/tpchavoc-variant-equivalence-gate.yaml``).

Copyright 2026 Joe Harris / BenchBox Project

TPC Benchmark(TM) H (TPC-H) - Copyright (C) Transaction Processing Performance Council.
This implementation is derived from TPC-H.

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import pytest

from benchbox.core.tpchavoc.equivalence import (
    EQUIVALENCE_SCALE,
    KNOWN_DIVERGENCES,
    build_duckdb_with_tpch,
    find_divergences,
)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.medium,
    pytest.mark.duckdb,
    pytest.mark.tpchavoc,
]


@pytest.fixture(scope="module")
def populated_duckdb(tmp_path_factory):
    """Generate SF=0.1 TPC-H data once and yield a populated DuckDB connection."""
    output_dir = tmp_path_factory.mktemp("tpchavoc_equivalence")
    connection, tpchavoc, tpch = build_duckdb_with_tpch(EQUIVALENCE_SCALE, output_dir)
    try:
        yield connection, tpchavoc, tpch
    finally:
        connection.close()


# Variants whose correctness defects have been fixed and must stay equivalent to
# canonical TPC-H. Their parent queries are also swept for new, unclassified
# regressions (tolerating only that query's documented KNOWN_DIVERGENCES).
FIXED_VARIANTS = frozenset({"1_v8", "2_v10", "7_v5", "9_v10", "10_v10"})


def test_fixed_variants_equivalent_to_canonical(populated_duckdb):
    """Every fixed variant must match canonical TPC-H, with no new regressions.

    Covers the value-zeroing projection fixes (``q2_v10``, ``q10_v10``) and the
    three triaged correctness defects (``q1_v8`` filtered in ``QUALIFY`` instead
    of ``WHERE``; ``q7_v5`` fanned out revenue ~4.5x; ``q9_v10`` bucketed nations
    and clamped negative profit). Also guards the affected query families against
    a *new* unclassified divergence without coupling to the global baseline.
    """
    connection, tpchavoc, tpch = populated_duckdb

    query_ids = sorted({int(key.split("_v")[0]) for key in FIXED_VARIANTS})
    divergences = find_divergences(connection, tpchavoc, lambda query_id: tpch.get_query(query_id), query_ids=query_ids)
    divergent = {d.key for d in divergences}

    regressed = FIXED_VARIANTS & divergent
    assert not regressed, "Fixed variants diverge from canonical TPC-H: " + ", ".join(
        f"{d.key} ({d.detail})" for d in divergences if d.key in regressed
    )

    # Only the tested queries' entries of KNOWN_DIVERGENCES are tolerated here, so
    # a new Q2/Q10 entry to the global baseline can't silently excuse a regression.
    known_for_queries = {key for key in KNOWN_DIVERGENCES if int(key.split("_v")[0]) in query_ids}
    unexpected = divergent - known_for_queries
    assert not unexpected, f"New, unclassified divergence(s) from canonical TPC-H: {sorted(unexpected)}"
