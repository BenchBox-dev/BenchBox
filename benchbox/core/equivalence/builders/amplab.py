"""AMPLab cross-surface gate builder."""

from __future__ import annotations

from pathlib import Path

from benchbox.core.equivalence.builders.base import CrossSurfaceData, _load_duckdb_cell


def build_amplab_duckdb(scale_factor: float, output_dir: Path) -> CrossSurfaceData:
    """Generate AMPLab data, load it into in-memory DuckDB, and wire both surfaces."""
    from benchbox.core.amplab.benchmark import AMPLabBenchmark
    from benchbox.core.amplab.dataframe_queries import AMPLAB_DATAFRAME_QUERIES
    from benchbox.core.amplab.generator import AMPLabDataGenerator
    from benchbox.core.amplab.schema import TABLES

    output_dir = Path(output_dir)
    AMPLabDataGenerator(scale_factor=scale_factor, output_dir=output_dir).generate_data()
    benchmark = AMPLabBenchmark(scale_factor=scale_factor, output_dir=output_dir)

    connection = _load_duckdb_cell(benchmark, output_dir, [table["name"] for table in TABLES.values()], label="AMPLab")
    return CrossSurfaceData(
        connection=connection,
        query_ids=list(benchmark.get_queries().keys()),
        reference_sql=lambda query_id: benchmark.get_query(query_id),
        dataframe_query=lambda query_id: AMPLAB_DATAFRAME_QUERIES.get_or_raise(f"Q{query_id}"),
        benchmark=benchmark,
        data_dir=output_dir,
    )
