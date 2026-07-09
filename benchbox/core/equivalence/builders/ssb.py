"""SSB cross-surface gate builder."""

from __future__ import annotations

from pathlib import Path

from benchbox.core.equivalence.builders.base import CrossSurfaceData, _load_duckdb_cell


def build_ssb_duckdb(scale_factor: float, output_dir: Path) -> CrossSurfaceData:
    """Generate SSB data, load it into in-memory DuckDB, and wire both surfaces."""
    from benchbox.core.ssb.benchmark import SSBBenchmark
    from benchbox.core.ssb.dataframe_queries import SSB_DATAFRAME_QUERIES
    from benchbox.core.ssb.generator import SSBDataGenerator
    from benchbox.core.ssb.schema import TABLES

    output_dir = Path(output_dir)
    SSBDataGenerator(scale_factor=scale_factor, output_dir=output_dir).generate_data()
    benchmark = SSBBenchmark(scale_factor=scale_factor, output_dir=output_dir)

    connection = _load_duckdb_cell(benchmark, output_dir, [table["name"] for table in TABLES.values()], label="SSB")
    return CrossSurfaceData(
        connection=connection,
        query_ids=list(benchmark.get_queries().keys()),
        reference_sql=lambda query_id: benchmark.get_query(query_id),
        dataframe_query=lambda query_id: SSB_DATAFRAME_QUERIES.get_or_raise(query_id),
        benchmark=benchmark,
        data_dir=output_dir,
    )
