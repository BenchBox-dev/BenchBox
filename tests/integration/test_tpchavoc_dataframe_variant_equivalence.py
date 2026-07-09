"""Result-equivalence regression test for the fixed TPC-Havoc DataFrame variants.

This is the fast, default-lane companion to the full DataFrame
semantic-equivalence gate in ``benchbox/core/tpchavoc/dataframe_equivalence.py``
(run via ``make tpchavoc-dataframe-equivalence-report``, wired into the
``correctness-gate`` CI job), exactly as
``tests/integration/test_tpchavoc_variant_equivalence.py`` is for the SQL gate.
The full gate sweeps all 220 variants x 2 backends; this test re-checks the
query families where DataFrame variant correctness defects were found and
fixed:

* ``q3_v*`` / ``q10_v*`` - emitted columns in group-keys-first order instead of
  the TPC-H spec output order (rooted in the canonical TPC-H DataFrame
  implementations, mirrored by every variant on both backends).
* ``q5_v7`` / ``q10_v7`` / ``q15_v7`` - expression-family join-reorder variants
  referenced the right-side join key that Polars drops, crashing on execution.

Copyright 2026 Joe Harris / BenchBox Project

TPC Benchmark(TM) H (TPC-H) - Copyright (C) Transaction Processing Performance Council.
This implementation is derived from TPC-H.

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import pytest

pytest.importorskip("polars", reason="Polars not installed")
pytest.importorskip("pandas", reason="Pandas not installed")

from benchbox.core.tpchavoc.dataframe_equivalence import (
    KNOWN_DIVERGENCES,
    build_dataframe_contexts,
    find_dataframe_divergences,
)
from benchbox.core.tpchavoc.equivalence import EQUIVALENCE_SCALE, build_duckdb_with_tpch

pytestmark = [
    pytest.mark.integration,
    pytest.mark.medium,
    pytest.mark.duckdb,
    pytest.mark.tpchavoc,
]


@pytest.fixture(scope="module")
def populated_environment(tmp_path_factory):
    """Generate SF=0.1 TPC-H data once; yield the connection and DataFrame contexts."""
    output_dir = tmp_path_factory.mktemp("tpchavoc_dataframe_equivalence")
    connection, tpchavoc, tpch = build_duckdb_with_tpch(EQUIVALENCE_SCALE, output_dir)
    try:
        contexts = build_dataframe_contexts(connection)
        yield connection, tpchavoc, tpch, contexts
    finally:
        connection.close()


# Queries whose DataFrame variants had correctness defects (spec column-order
# deviations or crashing join-reorder variants); every variant of these queries
# must now match canonical TPC-H on both backends.
FIXED_DEFECT_QUERIES = (3, 5, 10, 15)


def test_fixed_dataframe_variant_families_equivalent_to_canonical(populated_environment):
    """Every DataFrame variant of the previously-defective queries must match canonical.

    Covers the column-order fixes (``q3_v*``, ``q10_v*``) and the
    dropped-join-key crash fixes (``q5_v7``, ``q10_v7``, ``q15_v7``). The full
    440-cell gate runs in the ``correctness-gate`` CI job; this is the fast
    default-lane regression for the riskiest families.
    """
    connection, tpchavoc, tpch, contexts = populated_environment

    divergences = find_dataframe_divergences(
        connection,
        tpchavoc,
        lambda query_id: tpch.get_query(query_id),
        contexts,
        query_ids=list(FIXED_DEFECT_QUERIES),
    )

    # KNOWN_DIVERGENCES is empty after the burndown; tolerate only entries that
    # are explicitly classified there, never an unclassified regression.
    unexpected = {d.key for d in divergences} - set(KNOWN_DIVERGENCES)
    assert not unexpected, "DataFrame variant(s) diverge from canonical TPC-H: " + ", ".join(
        f"{d.key} ({d.detail})" for d in divergences if d.key in unexpected
    )
