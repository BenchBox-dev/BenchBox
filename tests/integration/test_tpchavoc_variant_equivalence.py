"""Result-equivalence regression test for the fixed TPC-Havoc variants.

This is the narrow, gating companion to the non-gating diagnostic in
``benchbox/core/tpchavoc/equivalence.py`` (run via
``make tpchavoc-equivalence-report``). The diagnostic enumerates every variant
that diverges from canonical TPC-H; this test locks in the two value-zeroing
projection defects that were fixed (``q2_v10`` and ``q10_v10`` clamped negative
account balances to ``0`` via CASE projections) by asserting the whole Q2 and
Q10 variant families are now equivalent to canonical TPC-H.

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
    pytest.mark.stress,
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


def test_fixed_projection_variants_equivalent_to_canonical(populated_duckdb):
    """``q2_v10`` and ``q10_v10`` must match canonical TPC-H after the projection fix.

    Pre-fix, both reported negative ``s_acctbal``/``c_acctbal`` as ``0`` via a
    CASE-wrapped projection, diverging from canonical on the negative-balance
    rows. This asserts the fix holds and that no other Q2/Q10 variant regressed
    beyond the documented, deferred divergences (e.g. the ``10_v9`` extra-column
    window variant).
    """
    connection, tpchavoc, tpch = populated_duckdb

    divergences = find_divergences(connection, tpchavoc, lambda query_id: tpch.get_query(query_id), query_ids=[2, 10])
    divergent = {d.key for d in divergences}

    assert {"2_v10", "10_v10"}.isdisjoint(divergent), (
        "Fixed value-zeroing variants diverge from canonical TPC-H: "
        + ", ".join(f"{d.key} ({d.detail})" for d in divergences if d.key in {"2_v10", "10_v10"})
    )

    # Guard against a NEW Q2/Q10 regression without coupling to the whole global
    # baseline: only the Q2/Q10 entries of KNOWN_DIVERGENCES are tolerated here.
    known_q2_q10 = {key for key in KNOWN_DIVERGENCES if int(key.split("_v")[0]) in {2, 10}}
    unexpected = divergent - known_q2_q10
    assert not unexpected, f"New, unclassified Q2/Q10 divergence(s) from canonical TPC-H: {sorted(unexpected)}"
