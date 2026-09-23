"""Result-equivalence regression test for the Data Vault cross-surface gate.

This is the fast, default-lane companion to the full Data Vault cross-surface
equivalence gate in ``benchbox/core/equivalence/cross_surface.py`` (run via
``make datavault-cross-surface-equivalence-report``, wired into the
``correctness-gate`` CI job), mirroring
``tests/integration/test_h2odb_cross_surface_equivalence.py``. It executes every
Data Vault query's DataFrame surface (both backends) against its OWN SQL surface
on a bounded DuckDB cell and asserts they agree - SQL is the trusted reference
for its own DataFrame surface, so no hand-curated answer key is needed.

The gate carries an empty baseline: the 22 SQL ids (``"1"`` .. ``"22"``) map
1:1 to the DataFrame ids by a mechanical ``Q`` prefix (``"Q1"`` .. ``"Q22"``,
the same convention as enforced amplab), and every compared cell matches. Any
divergence is an unclassified regression.

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
)
from benchbox.core.tpchavoc.validation import ResultValidator

pytestmark = [
    pytest.mark.integration,
    pytest.mark.medium,
    pytest.mark.duckdb,
]


def test_datavault_dataframe_surface_equivalent_to_sql(tmp_path):
    """Every Data Vault DataFrame query (both backends) must match its own SQL surface."""
    gate = GATES["datavault"]
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
            validator=ResultValidator(tolerance=gate.tolerance),
            backends=gate.backends,
        )
        coverage = count_executed_cells(data.query_ids, data.dataframe_query, gate.backends)
    finally:
        connection.close()

    # Both gated backends must actually compare something - a fully-unimplemented
    # backend would make the gate silently green by comparing nothing.
    missing = sorted(backend for backend, count in coverage.items() if count == 0)
    assert not missing, f"gated Data Vault backend(s) implement no queries: {missing}"

    # The baseline is empty: every divergence is an unclassified regression.
    assert not divergences, "Data Vault DataFrame surface diverges from SQL: " + ", ".join(
        f"{d.key} ({d.detail})" for d in divergences
    )
