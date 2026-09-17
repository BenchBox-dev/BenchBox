"""FlightData cross-surface gate builder."""

from __future__ import annotations

from pathlib import Path

from benchbox.core.equivalence.builders.base import CrossSurfaceData, _load_duckdb_cell


def build_flightdata_duckdb(scale_factor: float, output_dir: Path) -> CrossSurfaceData:
    """Generate FlightData data, load it into in-memory DuckDB, and wire both surfaces."""
    from benchbox.core.flightdata.benchmark import FlightDataBenchmark
    from benchbox.core.flightdata.dataframe_queries import get_dataframe_queries

    output_dir = Path(output_dir)
    benchmark = FlightDataBenchmark(scale_factor=scale_factor, output_dir=output_dir)
    benchmark.generate_data()

    connection = _load_duckdb_cell(benchmark, output_dir, ["flights", "airlines", "airports"], label="FlightData")
    queries = get_dataframe_queries()
    return CrossSurfaceData(
        connection=connection,
        query_ids=list(benchmark.get_queries().keys()),
        reference_sql=lambda query_id: benchmark.get_query(query_id),
        dataframe_query=lambda query_id: queries.get_or_raise(query_id),
        benchmark=benchmark,
        data_dir=output_dir,
    )
