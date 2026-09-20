"""Staged Data Vault cross-surface gate: forced regeneration plus full-cell run.

The gate lives in STAGED_GATES (not CI-enforced) while the query-execution
burn-down is open. These tests lock what "staged" guarantees: every build
regenerates (probes can never pass on a stale manifest), the probe manifest is
recorded, and all 22 queries execute on both expression and pandas backends.
Greenness of every cell belongs to the burn-down, not here.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from benchbox.core.equivalence.cross_surface import (
    GATES,
    STAGED_GATES,
    build_production_contexts,
    count_executed_cells,
    find_cross_surface_divergences,
    get_gate,
)
from benchbox.utils.datagen_manifest import MANIFEST_FILENAME, load_manifest

pytestmark = [
    pytest.mark.integration,
    pytest.mark.slow,
]

EXPECTED_QUERY_IDS = [f"Q{i}" for i in range(1, 23)]


def test_datavault_gate_is_staged_not_enforced():
    assert "datavault" not in GATES
    gate = get_gate("datavault")
    assert gate is STAGED_GATES["datavault"]
    assert gate.scale_factor == 0.01
    assert tuple(gate.backends) == ("expression", "pandas")


@pytest.mark.timeout(1200)
def test_staged_gate_forces_regeneration_records_manifest_and_runs_all_cells(tmp_path, caplog):
    gate = get_gate("datavault")

    with caplog.at_level(logging.INFO, logger="benchbox.core.equivalence.builders.datavault"):
        data = gate.build(gate.scale_factor, tmp_path)
    try:
        assert sorted(data.query_ids) == sorted(EXPECTED_QUERY_IDS)
        assert data.benchmark.force_regenerate is True

        manifest_path = Path(data.data_dir) / MANIFEST_FILENAME
        assert manifest_path.exists(), "builder must leave the probe manifest behind"
        manifest = load_manifest(manifest_path)
        assert manifest.get("benchmark") == "datavault"
        assert float(manifest.get("scale_factor", 0)) == pytest.approx(gate.scale_factor)
        assert len(manifest.get("tables", {})) == 21
        assert "probe manifest" in caplog.text, "every run must record which manifest its cell came from"

        # Poison the cell: empty every table file but keep the manifest. A
        # manifest-honoring builder would load the empties (and fail the
        # non-empty load check); forced regeneration restores full data.
        table_files = list(Path(data.data_dir).glob("*.tbl"))
        assert len(table_files) == 21, f"expected 21 table files, found {len(table_files)}"
        for path in table_files:
            path.write_text("")
        before = manifest_path.read_bytes()

        data.connection.close()
        data = gate.build(gate.scale_factor, tmp_path)
        assert manifest_path.read_bytes() != before, "rebuild must rewrite the probe manifest"
        from benchbox.core.datavault.schema import LOADING_ORDER

        counts = {
            table: data.connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in LOADING_ORDER
        }
        assert len(counts) == 21
        assert all(count > 0 for count in counts.values()), f"cell not fully regenerated: {counts}"

        contexts = build_production_contexts(
            data.benchmark, data.data_dir, backends=gate.backends, scale_factor=gate.scale_factor
        )
        divergences = find_cross_surface_divergences(
            data.connection,
            query_ids=data.query_ids,
            reference_sql=data.reference_sql,
            dataframe_query=data.dataframe_query,
            contexts=contexts,
            validator=gate.build_validator(),
            backends=gate.backends,
        )
        coverage = count_executed_cells(data.query_ids, data.dataframe_query, gate.backends)
        assert coverage == {"expression": 22, "pandas": 22}, (
            f"every query must run on both backends, coverage={coverage}, divergences={[d.key for d in divergences]}"
        )
        assert isinstance(divergences, list)
    finally:
        data.connection.close()
