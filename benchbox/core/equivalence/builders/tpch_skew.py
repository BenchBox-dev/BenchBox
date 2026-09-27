"""TPC-H Skew cross-surface gate builder."""

from __future__ import annotations

from pathlib import Path

from benchbox.core.equivalence.builders.base import CrossSurfaceData, _assemble_simple_duckdb_cell


def build_tpch_skew_duckdb(scale_factor: float, output_dir: Path) -> CrossSurfaceData:
    """Generate TPC-H Skew data, load it into in-memory DuckDB, and wire both surfaces."""
    from benchbox.core.tpch.schema import TABLES
    from benchbox.tpch_skew import TPCHSkew

    def _dataframe_query(query_id: str) -> object:
        from benchbox.core.tpch_skew.dataframe_queries import TPCH_SKEW_DATAFRAME_QUERIES

        return TPCH_SKEW_DATAFRAME_QUERIES.get_or_raise(f"Q{query_id}")

    return _assemble_simple_duckdb_cell(
        TPCHSkew(scale_factor=scale_factor, output_dir=Path(output_dir)),
        Path(output_dir),
        [table.name for table in TABLES],
        label="TPC-H Skew",
        dataframe_query=_dataframe_query,
    )
