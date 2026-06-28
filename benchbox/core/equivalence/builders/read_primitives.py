"""Read Primitives cross-surface gate builder."""

from __future__ import annotations

from pathlib import Path

from benchbox.core.equivalence.builders.base import CrossSurfaceData, _load_duckdb_cell


def build_read_primitives_duckdb(scale_factor: float, output_dir: Path) -> CrossSurfaceData:
    """Generate Read Primitives data, load it into DuckDB, and wire both surfaces."""
    from benchbox.core.read_primitives.benchmark import ReadPrimitivesBenchmark
    from benchbox.core.read_primitives.dataframe_queries import get_dataframe_queries
    from benchbox.core.read_primitives.schema import TABLES

    output_dir = Path(output_dir)
    benchmark = ReadPrimitivesBenchmark(scale_factor=scale_factor, output_dir=output_dir)
    benchmark.data_generator.output_dir = output_dir
    benchmark.data_generator.generate_data()

    duckdb_sql = benchmark.get_queries(dialect="duckdb")
    registry = get_dataframe_queries()
    gateable_ids = [qid for qid in registry.get_query_ids() if qid in duckdb_sql]

    connection = _load_duckdb_cell(
        benchmark, output_dir, [table["name"] for table in TABLES.values()], label="Read Primitives"
    )
    return CrossSurfaceData(
        connection=connection,
        query_ids=gateable_ids,
        reference_sql=lambda query_id: duckdb_sql[query_id],
        dataframe_query=lambda query_id: registry.get_or_raise(query_id),
        benchmark=benchmark,
        data_dir=output_dir,
    )
