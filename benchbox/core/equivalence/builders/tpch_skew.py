"""TPC-H Skew cross-surface gate builder."""

from __future__ import annotations

from pathlib import Path

from benchbox.core.equivalence.builders.base import CrossSurfaceData, _load_duckdb_cell


def build_tpch_skew_duckdb(scale_factor: float, output_dir: Path) -> CrossSurfaceData:
    """Generate TPC-H Skew data, load it into in-memory DuckDB, and wire both surfaces."""
    from benchbox.core.tpch.schema import TABLES
    from benchbox.tpch_skew import TPCHSkew

    output_dir = Path(output_dir)
    benchmark = TPCHSkew(scale_factor=scale_factor, output_dir=output_dir)
    benchmark.generate_data()

    connection = _load_duckdb_cell(benchmark, output_dir, [table.name for table in TABLES], label="TPC-H Skew")
    sql_queries = benchmark.get_queries()

    def _dataframe_query(query_id: str) -> object:
        from benchbox.core.tpch_skew.dataframe_queries import TPCH_SKEW_DATAFRAME_QUERIES

        return TPCH_SKEW_DATAFRAME_QUERIES.get_or_raise(f"Q{query_id}")

    return CrossSurfaceData(
        connection=connection,
        query_ids=list(sql_queries.keys()),
        reference_sql=lambda query_id: sql_queries[query_id],
        dataframe_query=_dataframe_query,
        benchmark=benchmark,
        data_dir=output_dir,
    )
