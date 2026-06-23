"""Cross-surface SQL<->DataFrame equivalence for ClickBench (staged gate).

ClickBench is a single wide ``hits`` table whose queries are dominated by
``ORDER BY <aggregate> [DESC] LIMIT N`` with heavily tied aggregates. The
order-aware, tie-tolerant comparator (w2) compares the ordered prefix exactly
and tolerates only the ambiguous LIMIT-boundary tie group, so the two surfaces
agree without masking real value/group bugs (proven by the empty baseline here
and by the planted-defect sensitivity test).
"""

from __future__ import annotations

import pytest

pytest.importorskip("polars", reason="Polars not installed")
pytest.importorskip("pandas", reason="Pandas not installed")
pytest.importorskip("duckdb", reason="DuckDB not installed")

from benchbox.core.equivalence.cross_surface import (
    EQUIVALENCE_SCALE,
    build_production_contexts,
    count_executed_cells,
    find_cross_surface_divergences,
    get_gate,
)
from benchbox.core.tpchavoc.validation import ResultValidator

pytestmark = [
    pytest.mark.integration,
    pytest.mark.medium,
    pytest.mark.duckdb,
]


def _run_gate(tmp_path):
    """Build the ClickBench cell and return (sorted divergence keys, coverage)."""
    gate = get_gate("clickbench")
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
    return sorted(d.key for d in divergences), coverage, {d.key: d.detail for d in divergences}


def test_clickbench_dataframe_surface_equivalent_to_sql(tmp_path):
    """Every ClickBench DataFrame query (both backends) must match its SQL surface."""
    gate = get_gate("clickbench")
    keys, coverage, details = _run_gate(tmp_path)

    # A fully-unimplemented backend would make the gate silently green.
    missing = sorted(backend for backend, count in coverage.items() if count == 0)
    assert not missing, f"gated ClickBench backend(s) implement no queries: {missing}"

    unexpected = set(keys) - set(gate.known_divergences)
    assert not unexpected, "ClickBench DataFrame surface diverges from SQL: " + ", ".join(
        f"{key} ({details[key]})" for key in sorted(unexpected)
    )


def test_clickbench_gate_is_byte_stable_across_runs(tmp_path):
    """Seeded data + the tie-tolerant comparator + single-thread make the gate
    output identical run-to-run (determinism, H1)."""
    first, _, _ = _run_gate(tmp_path / "run1")
    second, _, _ = _run_gate(tmp_path / "run2")
    assert first == second, f"non-deterministic gate output: {first} != {second}"
