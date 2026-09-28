"""NYC Taxi cross-surface gate builder."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from benchbox.core.equivalence.builders.base import CrossSurfaceData, _load_duckdb_cell

if TYPE_CHECKING:
    from benchbox.core.nyctaxi.downloader import NYCTaxiDataDownloader

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


def _force_offline_synthesis(downloader: NYCTaxiDataDownloader) -> None:
    """Replace the network download with direct synthetic generation.

    The gate must stay offline and hermetic: patching ``_process_parquet_file``
    to call ``_generate_synthetic_month`` directly means no
    ``urllib.request.urlretrieve`` ever runs, so the gate passes with network
    disabled. ``taxi_zones`` generation is already local (embedded
    ``TAXI_ZONES_DATA``), so only the trips path needs forcing.
    """

    def _synthetic_only(self: NYCTaxiDataDownloader, url: str, writer: Any, start_trip_id: int) -> int:
        return self._generate_synthetic_month(writer, start_trip_id)

    downloader._process_parquet_file = _synthetic_only.__get__(downloader)  # type: ignore[method-assign]


# Fixed query seed so SQL windows are deterministic across gate runs. The
# query manager draws random date offsets and zone picks per query; without a
# seed the SQL and DF surfaces can never share a window.
NYCTAXI_GATE_SEED = 42


def _extract_sql_windows(sql_queries: dict[str, str]) -> dict[str, dict[str, Any]]:
    """Parse each rendered SQL query's date window and zone into DF overrides."""
    overrides: dict[str, dict[str, Any]] = {}
    for sql_id, sql in sql_queries.items():
        df_id = NYCTAXI_SQL_TO_DF_IDS[sql_id]
        dates = re.findall(r"'(\d{4}-\d{2}-\d{2})(?: \d{2}:\d{2}:\d{2})?'", sql)
        params: dict[str, Any] = {}
        if len(dates) >= 2:
            params["start_date"] = datetime.fromisoformat(dates[0])
            params["end_date"] = datetime.fromisoformat(dates[1])
        zone = re.search(r"pickup_location_id = (\d+)", sql)
        if zone:
            params["zone_id"] = int(zone.group(1))
        if params:
            overrides[df_id] = params
    return overrides


def build_nyctaxi_duckdb(scale_factor: float, output_dir: Path) -> CrossSurfaceData:
    """Generate NYC Taxi data offline, load it into in-memory DuckDB, and wire both surfaces."""
    import urllib.request

    from benchbox.core.nyctaxi.benchmark import NYCTaxiBenchmark
    from benchbox.core.nyctaxi.dataframe_queries import NYCTAXI_DATAFRAME_QUERIES
    from benchbox.core.nyctaxi.dataframe_queries.parameters import set_parameter_overrides

    output_dir = Path(output_dir)
    benchmark = NYCTaxiBenchmark(scale_factor=scale_factor, output_dir=output_dir, seed=NYCTAXI_GATE_SEED)
    _force_offline_synthesis(benchmark.downloader)

    def _forbidden_urlretrieve(*args: object, **kwargs: object) -> object:
        raise AssertionError("nyctaxi gate must not touch the network")

    urllib.request.urlretrieve = _forbidden_urlretrieve  # type: ignore[method-assign]
    try:
        benchmark.generate_data()
    finally:
        import importlib

        importlib.reload(urllib.request)

    connection = _load_duckdb_cell(benchmark, output_dir, ["taxi_zones", "trips"], label="NYC Taxi")
    sql_queries = benchmark.get_queries()
    # Align the DF surface with the seeded SQL windows for this gate run
    # only: install the seed-derived overrides, and restore the prior
    # (default None) value when the gate data leaves this builder so later
    # ordinary NYC Taxi runs in the same process keep documented defaults.
    _prior_overrides = set_parameter_overrides(_extract_sql_windows(sql_queries))
    queries = NYCTAXI_DATAFRAME_QUERIES
    return CrossSurfaceData(
        connection=connection,
        query_ids=list(sql_queries.keys()),
        reference_sql=lambda query_id: sql_queries[query_id],
        dataframe_query=lambda query_id: queries.get_or_raise(NYCTAXI_SQL_TO_DF_IDS[query_id]),
        benchmark=benchmark,
        data_dir=output_dir,
        cleanup=lambda: set_parameter_overrides(_prior_overrides),
    )
