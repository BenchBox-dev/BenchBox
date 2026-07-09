"""Result-equivalence regression test for the SSB cross-surface gate.

This is the fast, default-lane companion to the full SSB cross-surface
equivalence gate in ``benchbox/core/equivalence/cross_surface.py`` (run via
``make ssb-cross-surface-equivalence-report``, wired into the
``correctness-gate`` CI job), exactly as
``tests/integration/test_tpchavoc_dataframe_variant_equivalence.py`` is for the
TPC-Havoc DataFrame gate. It executes every SSB query's DataFrame surface (both
backends) against its OWN SQL surface on a bounded SF=0.1 DuckDB cell and
asserts they agree - SQL is the trusted reference for its own DataFrame surface,
so no hand-curated answer key is needed.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import pytest

pytest.importorskip("polars", reason="Polars not installed")
pytest.importorskip("pandas", reason="Pandas not installed")
pytest.importorskip("duckdb", reason="DuckDB not installed")

from benchbox.core.equivalence.cross_surface import (
    EQUIVALENCE_SCALE,
    GATES,
    build_production_contexts,
    count_executed_cells,
    find_cross_surface_divergences,
)
from benchbox.core.tpchavoc.validation import ResultValidator

pytestmark = [
    pytest.mark.integration,
    pytest.mark.medium,
    pytest.mark.duckdb,
]


def test_ssb_dataframe_surface_equivalent_to_sql(tmp_path):
    """Every SSB DataFrame query (both backends) must match its own SQL surface."""
    gate = GATES["ssb"]
    data = gate.build(EQUIVALENCE_SCALE, tmp_path)
    connection = data.connection
    try:
        contexts = build_production_contexts(data.benchmark, data.data_dir, backends=gate.backends)
        divergences = find_cross_surface_divergences(
            connection,
            query_ids=data.query_ids,
            reference_sql=data.reference_sql,
            dataframe_query=data.dataframe_query,
            contexts=contexts,
            validator=ResultValidator(tolerance=gate.tolerance),
            backends=gate.backends,
        )
        coverage = count_executed_cells(data.query_ids, data.dataframe_query, gate.backends)
    finally:
        connection.close()

    # Both gated backends must actually compare something - a fully-unimplemented
    # backend would make the gate silently green by comparing nothing.
    missing = sorted(backend for backend, count in coverage.items() if count == 0)
    assert not missing, f"gated SSB backend(s) implement no queries: {missing}"

    # The baseline is empty; tolerate only entries explicitly classified there,
    # never an unclassified regression.
    unexpected = {d.key for d in divergences} - set(gate.known_divergences)
    assert not unexpected, "SSB DataFrame surface diverges from SQL: " + ", ".join(
        f"{d.key} ({d.detail})" for d in divergences if d.key in unexpected
    )
