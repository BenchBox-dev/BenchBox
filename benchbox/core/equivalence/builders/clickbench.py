"""ClickBench cross-surface gate builder."""

from __future__ import annotations

from pathlib import Path

from benchbox.core.equivalence.builders.base import CrossSurfaceData, _load_duckdb_cell


def build_clickbench_duckdb(scale_factor: float, output_dir: Path) -> CrossSurfaceData:
    """Generate ClickBench data, load it into in-memory DuckDB, and wire both surfaces."""
    from benchbox.core.clickbench.benchmark import ClickBenchBenchmark
    from benchbox.core.clickbench.dataframe_queries import CLICKBENCH_DATAFRAME_QUERIES
    from benchbox.core.clickbench.generator import ClickBenchDataGenerator
    from benchbox.core.clickbench.schema import TABLES

    output_dir = Path(output_dir)
    ClickBenchDataGenerator(scale_factor=scale_factor, output_dir=output_dir).generate_data()
    benchmark = ClickBenchBenchmark(scale_factor=scale_factor, output_dir=output_dir)

    connection = _load_duckdb_cell(
        benchmark, output_dir, [table["name"] for table in TABLES.values()], label="ClickBench"
    )
    return CrossSurfaceData(
        connection=connection,
        query_ids=list(benchmark.get_queries().keys()),
        reference_sql=lambda query_id: benchmark.get_query(query_id),
        dataframe_query=lambda query_id: CLICKBENCH_DATAFRAME_QUERIES.get_or_raise(query_id),
        benchmark=benchmark,
        data_dir=output_dir,
    )
