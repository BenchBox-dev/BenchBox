"""Result-equivalence regression test for the ClickBench cross-surface gate.

The fast, default-lane companion to the full ClickBench cross-surface gate in
``benchbox/core/equivalence/cross_surface.py`` (run via
``make clickbench-cross-surface-equivalence-report``, wired into the
``correctness-gate`` CI job), mirroring
``tests/integration/test_ssb_cross_surface_equivalence.py``. It executes every
ClickBench query's DataFrame surface (both backends) against its OWN SQL surface
on a bounded SF=0.1 DuckDB cell and asserts they agree - SQL is the trusted
reference for its own DataFrame surface, so no hand-curated answer key is needed.
The comparison runs through the tie-aware comparator (top-N boundary ties are
accepted); the only classified exception is the genuinely order-less Q18.

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


def test_clickbench_dataframe_surface_equivalent_to_sql(tmp_path):
    """Every ClickBench DataFrame query (both backends) must match its own SQL surface."""
    gate = GATES["clickbench"]
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
    assert not missing, f"gated ClickBench backend(s) implement no queries: {missing}"

    # Only the classified order-less Q18 is tolerated; never an unclassified regression.
    unexpected = {d.key for d in divergences} - set(gate.known_divergences)
    assert not unexpected, "ClickBench DataFrame surface diverges from SQL: " + ", ".join(
        f"{d.key} ({d.detail})" for d in divergences if d.key in unexpected
    )
