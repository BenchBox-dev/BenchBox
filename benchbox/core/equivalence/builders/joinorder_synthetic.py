"""JoinOrder synthetic cross-surface gate builder."""

from __future__ import annotations

from pathlib import Path

from benchbox.core.equivalence.builders.base import CrossSurfaceData, _load_duckdb_cell


def build_joinorder_synthetic_duckdb(scale_factor: float, output_dir: Path) -> CrossSurfaceData:
    """Generate synthetic Join Order data, load it into DuckDB, and wire both surfaces."""
    from benchbox.core.joinorder_synthetic.benchmark import JoinOrderSyntheticBenchmark
    from benchbox.core.joinorder_synthetic.dataframe_queries import JOINORDER_DATAFRAME_QUERIES
    from benchbox.core.joinorder_synthetic.generator import JoinOrderGenerator

    output_dir = Path(output_dir)
    JoinOrderGenerator(scale_factor=scale_factor, output_dir=output_dir).generate_data()
    benchmark = JoinOrderSyntheticBenchmark(scale_factor=scale_factor, output_dir=output_dir)

    connection = _load_duckdb_cell(benchmark, output_dir, benchmark.get_table_names(), label="JoinOrder synthetic")
    return CrossSurfaceData(
        connection=connection,
        query_ids=list(benchmark.get_queries().keys()),
        reference_sql=lambda query_id: benchmark.get_query(query_id),
        dataframe_query=lambda query_id: JOINORDER_DATAFRAME_QUERIES.get_or_raise(query_id),
        benchmark=benchmark,
        data_dir=output_dir,
    )
