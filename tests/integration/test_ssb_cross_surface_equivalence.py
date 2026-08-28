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

# The six SSB queries fixed by #870: they returned zero rows at every scale (a
# generator value-format defect) and passed the gate empty-vs-empty. They must now
# be non-empty so a regression that re-empties them fails in this fast lane, not
# only in the heavyweight vacuity gate (which is what masked the bug originally).
_PREVIOUSLY_EMPTY = ("Q2.1", "Q2.2", "Q2.3", "Q3.3", "Q3.4", "Q4.3")


@pytest.fixture(scope="module")
def ssb_cell(tmp_path_factory):
    """Build the bounded SF=0.1 SSB DuckDB cell once for the module's tests."""
    gate = GATES["ssb"]
    data = gate.build(EQUIVALENCE_SCALE, tmp_path_factory.mktemp("ssb_cell"))
    try:
        yield data
    finally:
        data.connection.close()


def test_ssb_dataframe_surface_equivalent_to_sql(ssb_cell):
    """Every SSB DataFrame query (both backends) must match its own SQL surface."""
    gate = GATES["ssb"]
    data = ssb_cell
    contexts = build_production_contexts(data.benchmark, data.data_dir, backends=gate.backends)
    divergences = find_cross_surface_divergences(
        data.connection,
        query_ids=data.query_ids,
        reference_sql=data.reference_sql,
        dataframe_query=data.dataframe_query,
        contexts=contexts,
        validator=ResultValidator(tolerance=gate.tolerance),
        backends=gate.backends,
    )
    coverage = count_executed_cells(data.query_ids, data.dataframe_query, gate.backends)

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


def test_ssb_previously_empty_queries_now_discriminate(ssb_cell):
    """The #870 queries must return >=1 reference row (no allowlist re-masks them)."""
    data = ssb_cell
    # The gate dropped its legitimately_empty allowlist, so no SSB cell may be
    # vacuous; this pins the six historically-empty queries directly and fast.
    assert not GATES["ssb"].legitimately_empty, (
        "the SSB gate must carry no legitimately_empty classification once the data is fixed"
    )
    empty = [qid for qid in _PREVIOUSLY_EMPTY if not data.connection.execute(data.reference_sql(qid)).fetchall()]
    assert not empty, (
        f"SSB queries regressed to vacuous (0 reference rows) at SF={EQUIVALENCE_SCALE}: {empty} - "
        "the generator no longer emits values matching the canonical query literals (#870)."
    )
