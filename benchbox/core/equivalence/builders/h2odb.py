"""H2O-DB cross-surface gate builder."""

from __future__ import annotations

from pathlib import Path

from benchbox.core.equivalence.builders.base import CrossSurfaceData, _load_duckdb_cell


def build_h2odb_duckdb(scale_factor: float, output_dir: Path) -> CrossSurfaceData:
    """Generate H2O-DB data, load it into in-memory DuckDB, and wire both surfaces."""
    from benchbox.core.h2odb.benchmark import H2OBenchmark
    from benchbox.core.h2odb.dataframe_queries import H2ODB_DATAFRAME_QUERIES
    from benchbox.core.h2odb.generator import H2ODataGenerator
    from benchbox.core.h2odb.schema import TABLES

    output_dir = Path(output_dir)
    H2ODataGenerator(scale_factor=scale_factor, output_dir=output_dir).generate_data()
    benchmark = H2OBenchmark(scale_factor=scale_factor, output_dir=output_dir)

    connection = _load_duckdb_cell(benchmark, output_dir, [table["name"] for table in TABLES.values()], label="H2O-DB")
    return CrossSurfaceData(
        connection=connection,
        query_ids=list(benchmark.get_queries().keys()),
        reference_sql=lambda query_id: benchmark.get_query(query_id),
        dataframe_query=lambda query_id: H2ODB_DATAFRAME_QUERIES.get_or_raise(query_id),
        benchmark=benchmark,
        data_dir=output_dir,
    )
