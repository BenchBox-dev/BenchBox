"""TPC-H Skew cross-surface gate builder."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from benchbox.core.equivalence.builders.base import CrossSurfaceData, _assemble_simple_duckdb_cell

# Fixed generator seed so the skewed cell is deterministic across gate runs.
# Without this the Zipfian sampler draws fresh randomness per build and
# reference row counts drift between runs (Q17 NULL vs valued, Q8/Q20
# vacuous vs populated).
TPCH_SKEW_GATE_SEED = 42


def build_tpch_skew_duckdb(scale_factor: float, output_dir: Path) -> CrossSurfaceData:
    """Generate TPC-H Skew data, load it into in-memory DuckDB, and wire both surfaces."""
    from benchbox.core.tpch.schema import TABLES
    from benchbox.core.tpch_skew.skew_config import SkewPreset, get_preset_config
    from benchbox.tpch_skew import TPCHSkew

    # Q11's value threshold is scale-dependent (0.0001/SF): align the shared
    # DataFrame parameter seam with this run's scale on each query lookup.
    def _dataframe_query(query_id: str) -> object:
        import benchbox.core.dataframe.benchmark_suite  # noqa: F401  # break circular import
        from benchbox.core.tpch.dataframe_queries import set_scale_factor_for_benchmark
        from benchbox.core.tpch_skew.dataframe_queries import TPCH_SKEW_DATAFRAME_QUERIES

        set_scale_factor_for_benchmark("tpch_skew", scale_factor)
        return TPCH_SKEW_DATAFRAME_QUERIES.get_or_raise(f"Q{query_id}")

    skew_config = replace(get_preset_config(SkewPreset.MODERATE), seed=TPCH_SKEW_GATE_SEED)
    return _assemble_simple_duckdb_cell(
        TPCHSkew(scale_factor=scale_factor, output_dir=Path(output_dir), skew_config=skew_config),
        Path(output_dir),
        [table.name for table in TABLES],
        label="TPC-H Skew",
        dataframe_query=_dataframe_query,
    )
