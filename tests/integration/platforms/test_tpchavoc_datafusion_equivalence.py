"""Third-engine (DataFusion) TPC-Havoc variant-equivalence sample.

The DuckDB equivalence gate (``benchbox/core/tpchavoc/equivalence.py``, run via
``make tpchavoc-equivalence-report``) proves every variant is result-equivalent
to canonical TPC-H on ONE engine, DuckDB at SF=0.1. The PostgreSQL sample added
a second engine. This test is the bounded *third-engine sample* on the
in-process DataFusion engine: it runs canonical TPC-H and every variant through
the SAME translation to the SAME DataFusion session (so shared translation
cancels out), excludes the variants DataFusion cannot plan
(DATAFUSION_TPCHAVOC_SKIPS), and asserts no residual divergence beyond the
classified DATAFUSION_KNOWN_DIVERGENCES baseline (empty).

DataFusion's execution gaps DIFFER from PostgreSQL's (correlated EXISTS / IN /
scalar sub-query physical planning rather than HAVING/WHERE alias and
aggregate-in-window limits), so a green result here tests whether the
translation fidelity is systematic across engines or Postgres-specific. The
DuckDB gate remains the hard, blocking gate; this sample (and the gate body of
the non-blocking ``datafusion-integration`` CI job) catches translation-induced
divergence a third engine over without gating all ~20 platforms.

Copyright 2026 Joe Harris / BenchBox Project

TPC Benchmark(TM) H (TPC-H) - Copyright (C) Transaction Processing Performance Council.
This implementation is derived from TPC-H.

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import pytest

from benchbox.core.tpchavoc.equivalence import (
    DATAFUSION_KNOWN_DIVERGENCES,
    EQUIVALENCE_SCALE,
    _close_quietly,
    build_datafusion_with_tpch,
    find_datafusion_divergences,
)
from benchbox.sql_compat.rules.execution_filter.datafusion_tpchavoc import DATAFUSION_TPCHAVOC_SKIPS

pytestmark = [
    pytest.mark.integration,
    pytest.mark.tpchavoc,
    pytest.mark.slow,
]


@pytest.fixture(scope="module")
def datafusion_divergences(tmp_path_factory):
    """Load SF=0.1 TPC-H into an in-process DataFusion session and sweep ONCE.

    DataFusion is in-process, so "unreachable" means "not installed" - skip
    cleanly in that case (mirroring the Postgres sample's connect-only skip). The
    206-variant sweep is the expensive part, so it is computed a single time at
    module scope and shared across the assertions below.
    """
    pytest.importorskip("datafusion", reason="DataFusion not installed")
    output_dir = tmp_path_factory.mktemp("tpchavoc_df_equivalence")
    connection, tpchavoc, tpch = build_datafusion_with_tpch(EQUIVALENCE_SCALE, output_dir)
    try:
        yield find_datafusion_divergences(connection, tpchavoc, tpch)
    finally:
        _close_quietly(connection)


def test_all_executable_variants_equivalent_on_datafusion(datafusion_divergences):
    """Every DataFusion-executable variant matches canonical TPC-H on DataFusion.

    Both sides are translated to the datafusion dialect through the same seam and
    compared on the same session, so a divergence here points at the dialect
    translation layer (or a real variant defect), never at a cross-engine
    mismatch against DuckDB or Postgres.
    """
    unexpected = {d.key for d in datafusion_divergences} - set(DATAFUSION_KNOWN_DIVERGENCES)
    assert not unexpected, "Variant(s) diverge from canonical TPC-H on DataFusion: " + ", ".join(
        f"{d.key} ({d.detail})" for d in datafusion_divergences if d.key in unexpected
    )


def test_skipped_variants_are_excluded_never_marked_equivalent(datafusion_divergences):
    """DATAFUSION_TPCHAVOC_SKIPS variants are excluded from the sweep entirely."""
    reported = {d.key for d in datafusion_divergences}
    assert reported.isdisjoint(set(DATAFUSION_TPCHAVOC_SKIPS)), (
        "Un-executable (skip-list) variants must be excluded, not evaluated"
    )
