"""TPC-H cross-surface gate builder."""

from __future__ import annotations

from pathlib import Path

from benchbox.core.equivalence.builders.base import CrossSurfaceData, _assemble_simple_duckdb_cell


def build_tpch_duckdb(scale_factor: float, output_dir: Path) -> CrossSurfaceData:
    """Generate TPC-H data, load it into in-memory DuckDB, and wire both surfaces."""
    from benchbox.core.tpch.schema import TABLES
    from benchbox.tpch import TPCH

    def _dataframe_query(query_id: str) -> object:
        import benchbox.core.dataframe.benchmark_suite  # noqa: F401  # break circular import
        from benchbox.core.tpch.dataframe_queries import TPCH_DATAFRAME_QUERIES

        return TPCH_DATAFRAME_QUERIES.get_or_raise(f"Q{query_id}")

    return _assemble_simple_duckdb_cell(
        TPCH(scale_factor=scale_factor, output_dir=Path(output_dir)),
        Path(output_dir),
        [table.name for table in TABLES],
        label="TPC-H",
        dataframe_query=_dataframe_query,
    )
