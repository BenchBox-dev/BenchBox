"""NYC Taxi cross-surface gate builder."""

from __future__ import annotations

from pathlib import Path

from benchbox.core.equivalence.builders.base import CrossSurfaceData, _load_duckdb_cell

# Builder-local SQL-slug to DataFrame-ID map. The SQL surface uses slug IDs
# (for example ``trips-per-hour``) while the DataFrame surface uses ``Q<N>``
# IDs. Most pairs join on the display name; Q20 (``Weekday/Weekend
# Comparison`` vs ``Weekday vs Weekend``) and Q23 (``Single-Day Summary`` vs
# ``Single Day Summary``) are hand-resolved punctuation variants.
NYCTAXI_SQL_TO_DF_IDS: dict[str, str] = {
    "trips-per-hour": "Q1",
    "trips-per-day": "Q2",
    "trips-per-month": "Q3",
    "trips-by-day-of-week": "Q4",
    "top-pickup-zones": "Q5",
    "top-dropoff-zones": "Q6",
    "top-routes": "Q7",
    "borough-summary": "Q8",
    "revenue-by-payment-type": "Q9",
    "fare-distribution": "Q10",
    "tip-analysis": "Q11",
    "surcharge-revenue": "Q12",
    "distance-distribution": "Q13",
    "passenger-count-analysis": "Q14",
    "trip-duration-analysis": "Q15",
    "rate-code-summary": "Q16",
    "airport-trips": "Q17",
    "vendor-comparison": "Q18",
    "hourly-zone-heatmap": "Q19",
    "weekday-weekend-comparison": "Q20",
    "rush-hour-analysis": "Q21",
    "monthly-year-over-year": "Q22",
    "single-day-summary": "Q23",
    "zone-detail": "Q24",
    "full-scan-count": "Q25",
}

NYCTAXI_DF_TO_SQL_IDS: dict[str, str] = {df_id: sql_id for sql_id, df_id in NYCTAXI_SQL_TO_DF_IDS.items()}


def build_nyctaxi_duckdb(scale_factor: float, output_dir: Path) -> CrossSurfaceData:
    """Generate NYC Taxi data, load it into in-memory DuckDB, and wire both surfaces."""
    from benchbox.core.nyctaxi.benchmark import NYCTaxiBenchmark
    from benchbox.core.nyctaxi.dataframe_queries import NYCTAXI_DATAFRAME_QUERIES
    from benchbox.core.nyctaxi.schema import TABLE_ORDER

    output_dir = Path(output_dir)
    benchmark = NYCTaxiBenchmark(scale_factor=scale_factor, output_dir=output_dir)
    benchmark.generate_data()

    connection = _load_duckdb_cell(benchmark, output_dir, list(TABLE_ORDER), label="NYC Taxi")
    sql_queries = benchmark.get_queries()
    queries = NYCTAXI_DATAFRAME_QUERIES
    return CrossSurfaceData(
        connection=connection,
        query_ids=list(sql_queries.keys()),
        reference_sql=lambda query_id: sql_queries[query_id],
        dataframe_query=lambda query_id: queries.get_or_raise(NYCTAXI_SQL_TO_DF_IDS[query_id]),
        benchmark=benchmark,
        data_dir=output_dir,
    )
