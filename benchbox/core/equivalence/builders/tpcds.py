"""TPC-DS cross-surface gate builder."""

from __future__ import annotations

from pathlib import Path

from benchbox.core.equivalence.builders.base import CrossSurfaceData, _load_duckdb_cell


def build_tpcds_duckdb(scale_factor: float, output_dir: Path) -> CrossSurfaceData:
    """Generate TPC-DS data, load it into in-memory DuckDB, and wire both surfaces."""
    from benchbox.core.tpcds.schema.registry import TABLES
    from benchbox.tpcds import TPCDS

    output_dir = Path(output_dir)
    benchmark = TPCDS(scale_factor=scale_factor, output_dir=output_dir)
    benchmark.generate_data()

    connection = _load_duckdb_cell(benchmark, output_dir, [table.name for table in TABLES], label="TPC-DS")
    sql_queries = benchmark.get_queries()

    def _dataframe_query(query_id: str) -> object:
        from benchbox.core.tpcds.dataframe_queries import TPCDS_DATAFRAME_QUERIES

        return TPCDS_DATAFRAME_QUERIES.get_or_raise(f"Q{query_id}")

    return CrossSurfaceData(
        connection=connection,
        query_ids=list(sql_queries.keys()),
        reference_sql=lambda query_id: sql_queries[query_id],
        dataframe_query=_dataframe_query,
        benchmark=benchmark,
        data_dir=output_dir,
    )
