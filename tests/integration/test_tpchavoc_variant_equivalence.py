"""Result-equivalence regression test for the fixed TPC-Havoc variants.

This is the fast, default-lane companion to the full semantic-equivalence gate
in ``benchbox/core/tpchavoc/equivalence.py`` (run via
``make tpchavoc-equivalence-report``, wired into the ``correctness-gate`` CI
job). The full gate sweeps all 220 variants; this test re-checks the query
families where variant correctness defects were found and fixed:

* ``q2_v10`` / ``q10_v10`` - clamped negative account balances to ``0`` via CASE
  projections.
* ``q1_v8`` - aggregated over unfiltered ``lineitem`` (the shipdate predicate was
  in ``QUALIFY``, which filters output rows, not aggregation input).
* ``q7_v5`` - fanned a date-filtered-orders CTE back against the full
  ``lineitem`` table, inflating revenue ~4.5x.
* ``q9_v10`` - bucketed 22 nations into ``OTHER AMERICAS`` and clamped negative
  profit to ``0``.
* ``q7_v9`` / ``q9_v9`` / ``q10_v9`` - projected a helper ``rank()`` column,
  changing the output schema.

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


# Queries whose variants had correctness defects (value distortion or schema
# leakage); every variant of these queries must now match canonical TPC-H.
FIXED_DEFECT_QUERIES = (1, 2, 7, 9, 10)


def test_fixed_variant_families_equivalent_to_canonical(populated_duckdb):
    """Every variant of the previously-defective queries must match canonical.

    Covers the value-distorting fixes (``q1_v8``, ``q2_v10``, ``q7_v5``,
    ``q9_v10``, ``q10_v10``) and the schema fixes (``q7_v9``, ``q9_v9``,
    ``q10_v9``). The full 220-variant gate runs in the ``correctness-gate`` CI
    job; this is the fast default-lane regression for the riskiest families.
    """
    connection, tpchavoc, tpch = populated_duckdb

    divergences = find_divergences(
        connection,
        tpchavoc,
        lambda query_id: tpch.get_query(query_id),
        query_ids=list(FIXED_DEFECT_QUERIES),
    )

    # KNOWN_DIVERGENCES is empty after the burndown; tolerate only entries that
    # are explicitly classified there, never an unclassified regression.
    unexpected = {d.key for d in divergences} - set(KNOWN_DIVERGENCES)
    assert not unexpected, "Variant(s) diverge from canonical TPC-H: " + ", ".join(
        f"{d.key} ({d.detail})" for d in divergences if d.key in unexpected
    )
