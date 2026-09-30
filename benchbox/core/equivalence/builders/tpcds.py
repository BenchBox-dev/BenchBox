"""TPC-DS cross-surface gate builder."""

from __future__ import annotations

from pathlib import Path

from benchbox.core.equivalence.builders.base import CrossSurfaceData, _assemble_simple_duckdb_cell


def build_tpcds_duckdb(scale_factor: float, output_dir: Path) -> CrossSurfaceData:
    """Generate TPC-DS data, load it into in-memory DuckDB, and wire both surfaces."""
    from benchbox.core.tpcds.schema.registry import TABLES
    from benchbox.tpcds import TPCDS

    def _dataframe_query(query_id: str) -> object:
        from benchbox.core.tpcds.dataframe_queries import TPCDS_DATAFRAME_QUERIES

        return TPCDS_DATAFRAME_QUERIES.get_or_raise(f"Q{query_id}")

    return _assemble_simple_duckdb_cell(
        TPCDS(scale_factor=scale_factor, output_dir=Path(output_dir)),
        Path(output_dir),
        [table.name for table in TABLES],
        label="TPC-DS",
        dataframe_query=_dataframe_query,
    )
