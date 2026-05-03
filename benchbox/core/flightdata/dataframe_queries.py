"""FlightData DataFrame queries for Expression and Pandas families.

Implements all 20 FlightData OLAP queries for DataFrame execution on Polars,
PySpark, DataFusion (expression family) and Pandas, Modin, Dask (pandas family).

Queries cover 5 categories:
- On-time performance (5 queries)
- Delay analysis (4 queries)
- Route analytics (4 queries)
- Temporal patterns (4 queries)
- Carrier comparisons (3 queries)

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd

from benchbox.core.dataframe.context import DataFrameContext
from benchbox.core.dataframe.query import DataFrameQuery, QueryCategory, QueryRegistry

# ---------------------------------------------------------------------------
# Default parameters
# ---------------------------------------------------------------------------

FLIGHTDATA_DEFAULT_PARAMS: dict[str, Any] = {
    "start_date": date(2018, 1, 1),
    "end_date": date(2019, 1, 1),
}

_parameter_overrides: dict[str, Any] | None = None


def set_parameter_overrides(overrides: dict[str, Any] | None) -> None:
    """Set parameter overrides for the current benchmark run."""
    global _parameter_overrides
    _parameter_overrides = overrides


def get_flightdata_parameters() -> dict[str, Any]:
    """Get effective parameters, merging overrides on top of defaults."""
    params = dict(FLIGHTDATA_DEFAULT_PARAMS)
    if _parameter_overrides is not None:
        params.update(_parameter_overrides)
    return params


# ===========================================================================
# Expression Family (Polars, DataFusion, PySpark)
# ===========================================================================


def ontime_by_carrier_expression_impl(ctx: DataFrameContext) -> Any:
    """On-time arrival percentage by airline carrier."""
    flights = ctx.get_table("flights")
    airlines = ctx.get_table("airlines")
    col, lit = ctx.col, ctx.lit
    p = get_flightdata_parameters()

    airlines_a = airlines.select(col("code").alias("a_code"), col("name").alias("airline_name"))

    return (
        flights.join(airlines_a, left_on="reporting_airline", right_on="a_code", how="left")
        .filter(
            (col("cancelled") == lit(0))
            & (col("flight_date") >= lit(p["start_date"]))
            & (col("flight_date") < lit(p["end_date"]))
        )
        .group_by("reporting_airline", "airline_name")
        .agg(
            col("flight_id").count().alias("total_flights"),
            (col("arr_delay") <= lit(15)).cast(int).sum().alias("ontime_flights"),
            col("arr_delay").filter(col("arr_delay") > lit(0)).mean().round(2).alias("avg_delay_when_late"),
        )
        .with_columns((lit(100.0) * col("ontime_flights") / col("total_flights")).round(2).alias("ontime_pct"))
        .sort("ontime_pct", descending=True)
    )


def delay_by_airport_expression_impl(ctx: DataFrameContext) -> Any:
    """Average departure delay by origin airport (min 100 flights)."""
    flights = ctx.get_table("flights")
    airports = ctx.get_table("airports")
    col, lit = ctx.col, ctx.lit
    p = get_flightdata_parameters()

    ap = airports.select(
        col("code").alias("ap_code"),
        col("name").alias("airport_name"),
        col("city"),
        col("state"),
    )

    return (
        flights.join(ap, left_on="origin", right_on="ap_code", how="left")
        .filter(
            (col("cancelled") == lit(0))
            & col("dep_delay").is_not_null()
            & (col("flight_date") >= lit(p["start_date"]))
            & (col("flight_date") < lit(p["end_date"]))
        )
        .group_by("origin", "airport_name", "city", "state")
        .agg(
            col("flight_id").count().alias("total_flights"),
            col("dep_delay").mean().round(2).alias("avg_dep_delay"),
            col("arr_delay").mean().round(2).alias("avg_arr_delay"),
            (col("dep_delay") > lit(15)).cast(int).sum().alias("delayed_flights"),
        )
        .filter(col("total_flights") >= lit(100))
        .sort("avg_dep_delay", descending=True)
        .limit(50)
    )


def delay_by_hour_expression_impl(ctx: DataFrameContext) -> Any:
    """Average delay by scheduled departure hour."""
    flights = ctx.get_table("flights")
    col, lit = ctx.col, ctx.lit
    p = get_flightdata_parameters()

    return (
        flights.filter(
            (col("cancelled") == lit(0))
            & col("dep_delay").is_not_null()
            & col("crs_dep_time").is_not_null()
            & (col("flight_date") >= lit(p["start_date"]))
            & (col("flight_date") < lit(p["end_date"]))
        )
        .with_columns((col("crs_dep_time") / lit(100)).floor().cast(int).alias("dep_hour"))
        .group_by("dep_hour")
        .agg(
            col("flight_id").count().alias("total_flights"),
            col("dep_delay").mean().round(2).alias("avg_dep_delay"),
            col("arr_delay").mean().round(2).alias("avg_arr_delay"),
            (col("dep_delay") > lit(15)).cast(int).sum().alias("delayed_count"),
        )
        .with_columns((lit(100.0) * col("delayed_count") / col("total_flights")).round(2).alias("delay_rate_pct"))
        .sort("dep_hour")
    )


def best_routes_expression_impl(ctx: DataFrameContext) -> Any:
    """Routes with highest on-time rate (min 50 flights)."""
    flights = ctx.get_table("flights")
    airports = ctx.get_table("airports")
    col, lit = ctx.col, ctx.lit
    p = get_flightdata_parameters()

    ao = airports.select(col("code").alias("ao_code"), col("city").alias("origin_city"))
    ad = airports.select(col("code").alias("ad_code"), col("city").alias("dest_city"))

    return (
        flights.join(ao, left_on="origin", right_on="ao_code", how="left")
        .join(ad, left_on="dest", right_on="ad_code", how="left")
        .filter(
            (col("cancelled") == lit(0))
            & col("arr_delay").is_not_null()
            & (col("flight_date") >= lit(p["start_date"]))
            & (col("flight_date") < lit(p["end_date"]))
        )
        .group_by("origin", "dest", "origin_city", "dest_city")
        .agg(
            col("flight_id").count().alias("total_flights"),
            (col("arr_delay") <= lit(15)).cast(int).sum().alias("_ontime"),
            col("arr_delay").mean().round(2).alias("avg_arr_delay"),
            col("distance").mean().round(0).alias("avg_distance_miles"),
        )
        .filter(col("total_flights") >= lit(50))
        .with_columns((lit(100.0) * col("_ontime") / col("total_flights")).round(2).alias("ontime_pct"))
        .drop("_ontime")
        .sort("ontime_pct", descending=True)
        .limit(25)
    )


def improvement_trend_expression_impl(ctx: DataFrameContext) -> Any:
    """Annual on-time performance trend."""
    flights = ctx.get_table("flights")
    col, lit = ctx.col, ctx.lit
    p = get_flightdata_parameters()

    return (
        flights.filter((col("flight_date") >= lit(p["start_date"])) & (col("flight_date") < lit(p["end_date"])))
        .group_by("year")
        .agg(
            col("flight_id").count().alias("total_flights"),
            (col("cancelled") == lit(1)).cast(int).sum().alias("cancelled_flights"),
            ((col("cancelled") == lit(0)) & (col("arr_delay") <= lit(15))).cast(int).sum().alias("ontime_flights"),
            (col("cancelled") == lit(0)).cast(int).sum().alias("_non_cancelled"),
            col("arr_delay").filter(col("cancelled") == lit(0)).mean().round(2).alias("avg_arr_delay"),
        )
        .with_columns(
            (lit(100.0) * col("cancelled_flights") / col("total_flights")).round(2).alias("cancellation_rate_pct"),
            (lit(100.0) * col("ontime_flights") / col("_non_cancelled")).round(2).alias("ontime_pct"),
        )
        .drop("_non_cancelled")
        .sort("year")
    )


def delay_causes_expression_impl(ctx: DataFrameContext) -> Any:
    """Distribution of delay causes across all delayed flights."""
    flights = ctx.get_table("flights")
    col, lit = ctx.col, ctx.lit
    p = get_flightdata_parameters()

    return flights.filter(
        (col("cancelled") == lit(0))
        & (col("arr_delay") > lit(15))
        & (col("flight_date") >= lit(p["start_date"]))
        & (col("flight_date") < lit(p["end_date"]))
    ).select(
        col("flight_id").count().alias("total_delayed_flights"),
        (col("carrier_delay") > lit(0)).cast(int).sum().alias("carrier_delay_count"),
        col("carrier_delay").filter(col("carrier_delay") > lit(0)).mean().round(2).alias("avg_carrier_delay"),
        (col("weather_delay") > lit(0)).cast(int).sum().alias("weather_delay_count"),
        col("weather_delay").filter(col("weather_delay") > lit(0)).mean().round(2).alias("avg_weather_delay"),
        (col("nas_delay") > lit(0)).cast(int).sum().alias("nas_delay_count"),
        col("nas_delay").filter(col("nas_delay") > lit(0)).mean().round(2).alias("avg_nas_delay"),
        (col("security_delay") > lit(0)).cast(int).sum().alias("security_delay_count"),
        col("security_delay").filter(col("security_delay") > lit(0)).mean().round(2).alias("avg_security_delay"),
        (col("late_aircraft_delay") > lit(0)).cast(int).sum().alias("late_aircraft_count"),
        col("late_aircraft_delay")
        .filter(col("late_aircraft_delay") > lit(0))
        .mean()
        .round(2)
        .alias("avg_late_aircraft_delay"),
    )


def cascade_delays_expression_impl(ctx: DataFrameContext) -> Any:
    """Late aircraft delay patterns by carrier."""
    flights = ctx.get_table("flights")
    airlines = ctx.get_table("airlines")
    col, lit = ctx.col, ctx.lit
    p = get_flightdata_parameters()

    airlines_a = airlines.select(col("code").alias("a_code"), col("name").alias("airline_name"))

    return (
        flights.join(airlines_a, left_on="reporting_airline", right_on="a_code", how="left")
        .filter(
            (col("cancelled") == lit(0))
            & (col("flight_date") >= lit(p["start_date"]))
            & (col("flight_date") < lit(p["end_date"]))
        )
        .group_by("reporting_airline", "airline_name")
        .agg(
            col("flight_id").count().alias("total_flights"),
            (col("late_aircraft_delay") > lit(0)).cast(int).sum().alias("cascade_delayed"),
            col("late_aircraft_delay")
            .filter(col("late_aircraft_delay") > lit(0))
            .mean()
            .round(2)
            .alias("avg_cascade_delay"),
            col("late_aircraft_delay").fill_null(lit(0)).sum().round(0).alias("total_cascade_minutes"),
        )
        .with_columns((lit(100.0) * col("cascade_delayed") / col("total_flights")).round(2).alias("cascade_rate_pct"))
        .sort("cascade_rate_pct", descending=True)
    )


def weather_impact_expression_impl(ctx: DataFrameContext) -> Any:
    """Weather delay by month (seasonal patterns)."""
    flights = ctx.get_table("flights")
    col, lit = ctx.col, ctx.lit
    p = get_flightdata_parameters()

    return (
        flights.filter(
            (col("cancelled") == lit(0))
            & (col("flight_date") >= lit(p["start_date"]))
            & (col("flight_date") < lit(p["end_date"]))
        )
        .group_by("month")
        .agg(
            col("flight_id").count().alias("total_flights"),
            (col("weather_delay") > lit(0)).cast(int).sum().alias("weather_delayed"),
            col("weather_delay").filter(col("weather_delay") > lit(0)).mean().round(2).alias("avg_weather_delay_min"),
            col("weather_delay").fill_null(lit(0)).sum().round(0).alias("total_weather_minutes"),
        )
        .with_columns(
            (lit(100.0) * col("weather_delayed") / col("total_flights")).round(2).alias("weather_delay_rate_pct")
        )
        .sort("month")
    )


def recovery_time_expression_impl(ctx: DataFrameContext) -> Any:
    """Delay recovery analysis by departure delay bucket."""
    flights = ctx.get_table("flights")
    col, lit = ctx.col, ctx.lit
    p = get_flightdata_parameters()

    return (
        flights.filter(
            (col("cancelled") == lit(0))
            & col("dep_delay").is_not_null()
            & col("arr_delay").is_not_null()
            & (col("flight_date") >= lit(p["start_date"]))
            & (col("flight_date") < lit(p["end_date"]))
        )
        .with_columns(
            (col("dep_delay") - col("arr_delay")).alias("minutes_recovered"),
            (col("arr_delay") < col("dep_delay")).cast(int).alias("recovered_flag"),
            # Delay bucket mapping to string labels
            ctx.when(col("dep_delay") <= lit(0))
            .then(lit("No departure delay"))
            .when(col("dep_delay") <= lit(15))
            .then(lit("1-15 min departure delay"))
            .when(col("dep_delay") <= lit(30))
            .then(lit("16-30 min departure delay"))
            .when(col("dep_delay") <= lit(60))
            .then(lit("31-60 min departure delay"))
            .otherwise(lit("60+ min departure delay"))
            .alias("delay_bucket"),
        )
        .group_by("delay_bucket")
        .agg(
            col("flight_id").count().alias("flight_count"),
            col("dep_delay").mean().round(2).alias("avg_dep_delay"),
            col("arr_delay").mean().round(2).alias("avg_arr_delay"),
            col("minutes_recovered").mean().round(2).alias("avg_minutes_recovered"),
            (lit(100.0) * col("recovered_flag").sum() / col("flight_id").count()).round(2).alias("pct_recovered"),
        )
        .sort("avg_dep_delay")
    )


def busiest_routes_expression_impl(ctx: DataFrameContext) -> Any:
    """Top 25 routes by flight count."""
    flights = ctx.get_table("flights")
    airports = ctx.get_table("airports")
    col, lit = ctx.col, ctx.lit
    p = get_flightdata_parameters()

    ao = airports.select(
        col("code").alias("ao_code"),
        col("city").alias("origin_city"),
        col("state").alias("origin_state"),
    )
    ad = airports.select(
        col("code").alias("ad_code"),
        col("city").alias("dest_city"),
        col("state").alias("dest_state"),
    )

    return (
        flights.join(ao, left_on="origin", right_on="ao_code", how="left")
        .join(ad, left_on="dest", right_on="ad_code", how="left")
        .filter(
            (col("cancelled") == lit(0))
            & (col("flight_date") >= lit(p["start_date"]))
            & (col("flight_date") < lit(p["end_date"]))
        )
        .group_by("origin", "dest", "origin_city", "origin_state", "dest_city", "dest_state")
        .agg(
            col("flight_id").count().alias("total_flights"),
            col("distance").mean().round(0).alias("avg_distance_miles"),
            col("actual_elapsed_time").mean().round(0).alias("avg_duration_min"),
            (col("arr_delay") <= lit(15)).cast(int).sum().alias("_ontime"),
        )
        .with_columns((lit(100.0) * col("_ontime") / col("total_flights")).round(2).alias("ontime_pct"))
        .drop("_ontime")
        .sort("total_flights", descending=True)
        .limit(25)
    )


def route_reliability_expression_impl(ctx: DataFrameContext) -> Any:
    """Routes ranked by reliability (min 100 scheduled)."""
    flights = ctx.get_table("flights")
    airports = ctx.get_table("airports")
    col, lit = ctx.col, ctx.lit
    p = get_flightdata_parameters()

    ao = airports.select(col("code").alias("ao_code"), col("city").alias("origin_city"))
    ad = airports.select(col("code").alias("ad_code"), col("city").alias("dest_city"))

    return (
        flights.join(ao, left_on="origin", right_on="ao_code", how="left")
        .join(ad, left_on="dest", right_on="ad_code", how="left")
        .filter((col("flight_date") >= lit(p["start_date"])) & (col("flight_date") < lit(p["end_date"])))
        .group_by("origin", "dest", "origin_city", "dest_city")
        .agg(
            col("flight_id").count().alias("total_scheduled"),
            (col("cancelled") == lit(1)).cast(int).sum().alias("cancelled_count"),
            ((col("cancelled") == lit(0)) & (col("arr_delay") <= lit(15))).cast(int).sum().alias("ontime_count"),
            (col("cancelled") == lit(0)).cast(int).sum().alias("_non_cancelled"),
            col("distance").mean().round(0).alias("distance_miles"),
        )
        .filter(col("total_scheduled") >= lit(100))
        .with_columns(
            (lit(100.0) * col("cancelled_count") / col("total_scheduled")).round(2).alias("cancellation_rate_pct"),
            (lit(100.0) * col("ontime_count") / col("_non_cancelled")).round(2).alias("ontime_pct"),
        )
        .drop("_non_cancelled")
        .sort(["ontime_pct", "cancellation_rate_pct"], descending=[True, False])
        .limit(30)
    )


def distance_delay_expression_impl(ctx: DataFrameContext) -> Any:
    """Average delay by flight distance bucket."""
    flights = ctx.get_table("flights")
    col, lit = ctx.col, ctx.lit
    p = get_flightdata_parameters()

    return (
        flights.filter(
            (col("cancelled") == lit(0))
            & col("arr_delay").is_not_null()
            & (col("flight_date") >= lit(p["start_date"]))
            & (col("flight_date") < lit(p["end_date"]))
        )
        .with_columns(
            # Distance bucket mapping to string labels
            ctx.when(col("distance") < lit(250))
            .then(lit("Short-haul (<250 mi)"))
            .when(col("distance") < lit(500))
            .then(lit("Medium-haul (250-499 mi)"))
            .when(col("distance") < lit(1000))
            .then(lit("Long-haul (500-999 mi)"))
            .when(col("distance") < lit(2000))
            .then(lit("Cross-country (1000-1999 mi)"))
            .otherwise(lit("Ultra-long (2000+ mi)"))
            .alias("distance_bucket"),
        )
        .group_by("distance_bucket")
        .agg(
            col("flight_id").count().alias("total_flights"),
            col("distance").mean().round(0).alias("avg_distance_miles"),
            col("dep_delay").mean().round(2).alias("avg_dep_delay"),
            col("arr_delay").mean().round(2).alias("avg_arr_delay"),
            (col("arr_delay") <= lit(15)).cast(int).sum().alias("_ontime"),
        )
        .with_columns((lit(100.0) * col("_ontime") / col("total_flights")).round(2).alias("ontime_pct"))
        .drop("_ontime")
        .sort("avg_distance_miles")
    )


def hub_connectivity_expression_impl(ctx: DataFrameContext) -> Any:
    """Hub airport connectivity (unique destinations, carriers)."""
    flights = ctx.get_table("flights")
    airports = ctx.get_table("airports")
    col, lit = ctx.col, ctx.lit
    p = get_flightdata_parameters()

    ap = airports.select(
        col("code").alias("ap_code"),
        col("name").alias("airport_name"),
        col("city"),
        col("state"),
    )

    return (
        flights.join(ap, left_on="origin", right_on="ap_code", how="left")
        .filter(
            (col("cancelled") == lit(0))
            & (col("flight_date") >= lit(p["start_date"]))
            & (col("flight_date") < lit(p["end_date"]))
        )
        .group_by("origin", "airport_name", "city", "state")
        .agg(
            col("dest").n_unique().alias("unique_destinations"),
            col("reporting_airline").n_unique().alias("serving_carriers"),
            col("flight_id").count().alias("total_departures"),
            col("dep_delay").mean().round(2).alias("avg_dep_delay"),
        )
        .sort("total_departures", descending=True)
        .limit(30)
    )


def day_of_week_expression_impl(ctx: DataFrameContext) -> Any:
    """Flight patterns by day of week."""
    flights = ctx.get_table("flights")
    col, lit = ctx.col, ctx.lit
    p = get_flightdata_parameters()

    return (
        flights.filter((col("flight_date") >= lit(p["start_date"])) & (col("flight_date") < lit(p["end_date"])))
        .with_columns(
            ctx.when(col("day_of_week") == lit(1))
            .then(lit("Monday"))
            .when(col("day_of_week") == lit(2))
            .then(lit("Tuesday"))
            .when(col("day_of_week") == lit(3))
            .then(lit("Wednesday"))
            .when(col("day_of_week") == lit(4))
            .then(lit("Thursday"))
            .when(col("day_of_week") == lit(5))
            .then(lit("Friday"))
            .when(col("day_of_week") == lit(6))
            .then(lit("Saturday"))
            .otherwise(lit("Sunday"))
            .alias("day_name")
        )
        .group_by("day_of_week", "day_name")
        .agg(
            col("flight_id").count().alias("total_flights"),
            (col("cancelled") == lit(1)).cast(int).sum().alias("cancelled_count"),
            col("dep_delay").filter(col("cancelled") == lit(0)).mean().round(2).alias("avg_dep_delay"),
            col("arr_delay").filter(col("cancelled") == lit(0)).mean().round(2).alias("avg_arr_delay"),
            ((col("cancelled") == lit(0)) & (col("arr_delay") <= lit(15))).cast(int).sum().alias("_ontime"),
            (col("cancelled") == lit(0)).cast(int).sum().alias("_non_cancelled"),
        )
        .with_columns((lit(100.0) * col("_ontime") / col("_non_cancelled")).round(2).alias("ontime_pct"))
        .drop("_ontime", "_non_cancelled")
        .sort("day_of_week")
    )


def seasonal_trends_expression_impl(ctx: DataFrameContext) -> Any:
    """Monthly flight volume and performance aggregated across all years."""
    flights = ctx.get_table("flights")
    col, lit = ctx.col, ctx.lit
    p = get_flightdata_parameters()

    return (
        flights.filter((col("flight_date") >= lit(p["start_date"])) & (col("flight_date") < lit(p["end_date"])))
        .with_columns(
            ctx.when(col("month") == lit(1))
            .then(lit("January"))
            .when(col("month") == lit(2))
            .then(lit("February"))
            .when(col("month") == lit(3))
            .then(lit("March"))
            .when(col("month") == lit(4))
            .then(lit("April"))
            .when(col("month") == lit(5))
            .then(lit("May"))
            .when(col("month") == lit(6))
            .then(lit("June"))
            .when(col("month") == lit(7))
            .then(lit("July"))
            .when(col("month") == lit(8))
            .then(lit("August"))
            .when(col("month") == lit(9))
            .then(lit("September"))
            .when(col("month") == lit(10))
            .then(lit("October"))
            .when(col("month") == lit(11))
            .then(lit("November"))
            .otherwise(lit("December"))
            .alias("month_name")
        )
        .group_by("month", "month_name")
        .agg(
            col("flight_id").count().alias("total_flights"),
            (col("cancelled") == lit(1)).cast(int).sum().alias("cancelled_count"),
            col("arr_delay").filter(col("cancelled") == lit(0)).mean().round(2).alias("avg_arr_delay"),
            ((col("cancelled") == lit(0)) & (col("arr_delay") <= lit(15))).cast(int).sum().alias("_ontime"),
            (col("cancelled") == lit(0)).cast(int).sum().alias("_non_cancelled"),
        )
        .with_columns(
            (lit(100.0) * col("cancelled_count") / col("total_flights")).round(2).alias("cancellation_rate_pct"),
            (lit(100.0) * col("_ontime") / col("_non_cancelled")).round(2).alias("ontime_pct"),
        )
        .drop("_ontime", "_non_cancelled")
        .sort("month")
    )


def holiday_impact_expression_impl(ctx: DataFrameContext) -> Any:
    """Holiday period delay impact."""
    flights = ctx.get_table("flights")
    col, lit = ctx.col, ctx.lit
    p = get_flightdata_parameters()

    # Encode each holiday period as a numeric id (0=regular, 1=thanksgiving, etc.)
    thanksgiving = (col("month") == lit(11)) & (col("day_of_month") >= lit(21)) & (col("day_of_month") <= lit(27))
    christmas = (col("month") == lit(12)) & (col("day_of_month") >= lit(23)) & (col("day_of_month") <= lit(27))
    new_year = ((col("month") == lit(1)) & (col("day_of_month") <= lit(2))) | (
        (col("month") == lit(12)) & (col("day_of_month") == lit(31))
    )
    july4 = (col("month") == lit(7)) & (col("day_of_month") >= lit(3)) & (col("day_of_month") <= lit(5))
    memorial = (
        (col("month") == lit(5))
        & (col("day_of_week") == lit(1))
        & (col("day_of_month") >= lit(25))
        & (col("day_of_month") <= lit(31))
    )
    labor = (
        (col("month") == lit(9))
        & (col("day_of_week") == lit(1))
        & (col("day_of_month") >= lit(1))
        & (col("day_of_month") <= lit(7))
    )

    return (
        flights.filter((col("flight_date") >= lit(p["start_date"])) & (col("flight_date") < lit(p["end_date"])))
        .with_columns(
            # Holiday period mapping to string labels
            ctx.when(thanksgiving)
            .then(lit("Thanksgiving Week"))
            .when(christmas)
            .then(lit("Christmas"))
            .when(new_year)
            .then(lit("New Year"))
            .when(july4)
            .then(lit("July 4th"))
            .when(memorial)
            .then(lit("Memorial Day"))
            .when(labor)
            .then(lit("Labor Day"))
            .otherwise(lit("Regular Day"))
            .alias("period"),
        )
        .group_by("period")
        .agg(
            col("flight_id").count().alias("total_flights"),
            col("arr_delay").filter(col("cancelled") == lit(0)).mean().round(2).alias("avg_arr_delay"),
            (lit(100.0) * (col("cancelled") == lit(1)).cast(int).sum() / col("flight_id").count())
            .round(2)
            .alias("cancellation_rate_pct"),
            ((col("cancelled") == lit(0)) & (col("arr_delay") <= lit(15))).cast(int).sum().alias("_ontime"),
            (col("cancelled") == lit(0)).cast(int).sum().alias("_non_cancelled"),
        )
        .with_columns((lit(100.0) * col("_ontime") / col("_non_cancelled")).round(2).alias("ontime_pct"))
        .drop("_ontime", "_non_cancelled")
        .sort("avg_arr_delay", descending=True)
    )


def time_of_day_expression_impl(ctx: DataFrameContext) -> Any:
    """Flight volume and delay by scheduled departure hour."""
    flights = ctx.get_table("flights")
    col, lit = ctx.col, ctx.lit
    p = get_flightdata_parameters()

    return (
        flights.filter(
            col("crs_dep_time").is_not_null()
            & (col("flight_date") >= lit(p["start_date"]))
            & (col("flight_date") < lit(p["end_date"]))
        )
        .with_columns((col("crs_dep_time") / lit(100)).floor().cast(int).alias("hour_of_day"))
        .group_by("hour_of_day")
        .agg(
            col("flight_id").count().alias("total_flights"),
            col("dep_delay").filter(col("cancelled") == lit(0)).mean().round(2).alias("avg_dep_delay"),
            col("arr_delay").filter(col("cancelled") == lit(0)).mean().round(2).alias("avg_arr_delay"),
            (col("dep_delay") > lit(60)).cast(int).sum().alias("severely_delayed"),
            ((col("cancelled") == lit(0)) & (col("arr_delay") <= lit(15))).cast(int).sum().alias("_ontime"),
            (col("cancelled") == lit(0)).cast(int).sum().alias("_non_cancelled"),
        )
        .with_columns((lit(100.0) * col("_ontime") / col("_non_cancelled")).round(2).alias("ontime_pct"))
        .drop("_ontime", "_non_cancelled")
        .sort("hour_of_day")
    )


def carrier_ranking_expression_impl(ctx: DataFrameContext) -> Any:
    """Full carrier scorecard (min 1000 scheduled flights)."""
    flights = ctx.get_table("flights")
    airlines = ctx.get_table("airlines")
    col, lit = ctx.col, ctx.lit
    p = get_flightdata_parameters()

    airlines_a = airlines.select(col("code").alias("a_code"), col("name").alias("airline_name"))

    return (
        flights.join(airlines_a, left_on="reporting_airline", right_on="a_code", how="left")
        .filter((col("flight_date") >= lit(p["start_date"])) & (col("flight_date") < lit(p["end_date"])))
        .group_by("reporting_airline", "airline_name")
        .agg(
            col("flight_id").count().alias("total_scheduled"),
            (col("cancelled") == lit(0)).cast(int).sum().alias("operated_flights"),
            (col("cancelled") == lit(1)).cast(int).sum().alias("cancelled_flights"),
            col("dep_delay").filter(col("cancelled") == lit(0)).mean().round(2).alias("avg_dep_delay"),
            col("arr_delay").filter(col("cancelled") == lit(0)).mean().round(2).alias("avg_arr_delay"),
            ((col("cancelled") == lit(0)) & (col("arr_delay") <= lit(15))).cast(int).sum().alias("_ontime"),
            (col("cancelled") == lit(0)).cast(int).sum().alias("_non_cancelled"),
            col("distance").mean().round(0).alias("avg_route_distance_miles"),
        )
        .filter(col("total_scheduled") >= lit(1000))
        .with_columns(
            (lit(100.0) * col("cancelled_flights") / col("total_scheduled")).round(2).alias("cancellation_rate_pct"),
            (lit(100.0) * col("_ontime") / col("_non_cancelled")).round(2).alias("ontime_pct"),
        )
        .drop("_ontime", "_non_cancelled")
        .sort("ontime_pct", descending=True)
    )


def cancellation_rate_expression_impl(ctx: DataFrameContext) -> Any:
    """Cancellation rates by carrier (min 100 flights)."""
    flights = ctx.get_table("flights")
    airlines = ctx.get_table("airlines")
    col, lit = ctx.col, ctx.lit
    p = get_flightdata_parameters()

    airlines_a = airlines.select(col("code").alias("a_code"), col("name").alias("airline_name"))

    return (
        flights.join(airlines_a, left_on="reporting_airline", right_on="a_code", how="left")
        .filter((col("flight_date") >= lit(p["start_date"])) & (col("flight_date") < lit(p["end_date"])))
        .group_by("reporting_airline", "airline_name")
        .agg(
            col("flight_id").count().alias("total_flights"),
            (col("cancelled") == lit(1)).cast(int).sum().alias("total_cancelled"),
            (col("cancellation_code") == lit("A")).cast(int).sum().alias("carrier_cancellations"),
            (col("cancellation_code") == lit("B")).cast(int).sum().alias("weather_cancellations"),
            (col("cancellation_code") == lit("C")).cast(int).sum().alias("nas_cancellations"),
            (col("cancellation_code") == lit("D")).cast(int).sum().alias("security_cancellations"),
        )
        .filter(col("total_flights") >= lit(100))
        .with_columns(
            (lit(100.0) * col("total_cancelled") / col("total_flights")).round(3).alias("cancellation_rate_pct")
        )
        .sort("cancellation_rate_pct", descending=True)
    )


def market_share_expression_impl(ctx: DataFrameContext) -> Any:
    """Carrier market share (CTE pattern via window sum)."""
    flights = ctx.get_table("flights")
    airlines = ctx.get_table("airlines")
    col, lit = ctx.col, ctx.lit
    p = get_flightdata_parameters()

    airlines_a = airlines.select(col("code").alias("a_code"), col("name").alias("airline_name"))

    # carrier_totals equivalent
    carrier_totals = (
        flights.join(airlines_a, left_on="reporting_airline", right_on="a_code", how="left")
        .filter(
            (col("cancelled") == lit(0))
            & (col("flight_date") >= lit(p["start_date"]))
            & (col("flight_date") < lit(p["end_date"]))
        )
        .with_columns((col("origin") + lit("-") + col("dest")).alias("route"))
        .group_by("reporting_airline", "airline_name")
        .agg(
            col("flight_id").count().alias("flight_count"),
            col("route").n_unique().alias("routes_served"),
            col("distance").mean().round(0).alias("avg_distance_miles"),
        )
    )

    # Compute grand_total as a window sum, then derive market share
    return (
        carrier_totals.with_columns(col("flight_count").sum().alias("grand_total"))
        .with_columns((lit(100.0) * col("flight_count") / col("grand_total")).round(2).alias("market_share_pct"))
        .drop("grand_total")
        .sort("flight_count", descending=True)
        .limit(20)
    )


# ===========================================================================
# Pandas Family (Pandas, Modin, cuDF, Dask)
# ===========================================================================


def ontime_by_carrier_pandas_impl(ctx: DataFrameContext) -> Any:
    """On-time arrival percentage by airline carrier (pandas)."""
    flights = ctx.get_table("flights")
    airlines = ctx.get_table("airlines")
    p = get_flightdata_parameters()

    merged = flights.merge(airlines, left_on="reporting_airline", right_on="code", how="left")
    merged = merged.rename(columns={"name": "airline_name"})
    filtered = merged[
        (merged["cancelled"] == 0)
        & (merged["flight_date"] >= p["start_date"])
        & (merged["flight_date"] < p["end_date"])
    ].copy()

    filtered["_ontime"] = (filtered["arr_delay"] <= 15).astype(int)
    filtered["_delayed_val"] = filtered["arr_delay"].where(filtered["arr_delay"] > 0)

    result = filtered.groupby(["reporting_airline", "airline_name"], as_index=False).agg(
        total_flights=("flight_id", "count"),
        ontime_flights=("_ontime", "sum"),
        avg_delay_when_late=("_delayed_val", "mean"),
    )
    result["avg_delay_when_late"] = result["avg_delay_when_late"].round(2)
    result["ontime_pct"] = (100.0 * result["ontime_flights"] / result["total_flights"]).round(2)
    return result.sort_values("ontime_pct", ascending=False).reset_index(drop=True)


def delay_by_airport_pandas_impl(ctx: DataFrameContext) -> Any:
    """Average departure delay by origin airport (pandas)."""
    flights = ctx.get_table("flights")
    airports = ctx.get_table("airports")
    p = get_flightdata_parameters()

    merged = flights.merge(airports, left_on="origin", right_on="code", how="left")
    merged = merged.rename(columns={"name": "airport_name"})
    filtered = merged[
        (merged["cancelled"] == 0)
        & merged["dep_delay"].notna()
        & (merged["flight_date"] >= p["start_date"])
        & (merged["flight_date"] < p["end_date"])
    ].copy()
    filtered["_delayed"] = (filtered["dep_delay"] > 15).astype(int)

    result = filtered.groupby(["origin", "airport_name", "city", "state"], as_index=False).agg(
        total_flights=("flight_id", "count"),
        avg_dep_delay=("dep_delay", "mean"),
        avg_arr_delay=("arr_delay", "mean"),
        delayed_flights=("_delayed", "sum"),
    )
    result["avg_dep_delay"] = result["avg_dep_delay"].round(2)
    result["avg_arr_delay"] = result["avg_arr_delay"].round(2)
    result = result[result["total_flights"] >= 100]
    return result.sort_values("avg_dep_delay", ascending=False).head(50).reset_index(drop=True)


def delay_by_hour_pandas_impl(ctx: DataFrameContext) -> Any:
    """Average delay by scheduled departure hour (pandas)."""
    flights = ctx.get_table("flights")
    p = get_flightdata_parameters()

    filtered = flights[
        (flights["cancelled"] == 0)
        & flights["dep_delay"].notna()
        & flights["crs_dep_time"].notna()
        & (flights["flight_date"] >= p["start_date"])
        & (flights["flight_date"] < p["end_date"])
    ].copy()
    filtered["dep_hour"] = (filtered["crs_dep_time"] // 100).astype(int)
    filtered["_delayed"] = (filtered["dep_delay"] > 15).astype(int)

    result = filtered.groupby("dep_hour", as_index=False).agg(
        total_flights=("flight_id", "count"),
        avg_dep_delay=("dep_delay", "mean"),
        avg_arr_delay=("arr_delay", "mean"),
        delayed_count=("_delayed", "sum"),
    )
    result["avg_dep_delay"] = result["avg_dep_delay"].round(2)
    result["avg_arr_delay"] = result["avg_arr_delay"].round(2)
    result["delay_rate_pct"] = (100.0 * result["delayed_count"] / result["total_flights"]).round(2)
    return result.sort_values("dep_hour").reset_index(drop=True)


def best_routes_pandas_impl(ctx: DataFrameContext) -> Any:
    """Routes with highest on-time rate (pandas)."""
    flights = ctx.get_table("flights")
    airports = ctx.get_table("airports")
    p = get_flightdata_parameters()

    ao = airports[["code", "city"]].rename(columns={"code": "ao_code", "city": "origin_city"})
    ad = airports[["code", "city"]].rename(columns={"code": "ad_code", "city": "dest_city"})

    filtered = (
        flights[
            (flights["cancelled"] == 0)
            & flights["arr_delay"].notna()
            & (flights["flight_date"] >= p["start_date"])
            & (flights["flight_date"] < p["end_date"])
        ]
        .merge(ao, left_on="origin", right_on="ao_code", how="left")
        .merge(ad, left_on="dest", right_on="ad_code", how="left")
    ).copy()
    filtered["_ontime"] = (filtered["arr_delay"] <= 15).astype(int)

    result = filtered.groupby(["origin", "dest", "origin_city", "dest_city"], as_index=False).agg(
        total_flights=("flight_id", "count"),
        _ontime_sum=("_ontime", "sum"),
        avg_arr_delay=("arr_delay", "mean"),
        avg_distance_miles=("distance", "mean"),
    )
    result = result[result["total_flights"] >= 50]
    result["ontime_pct"] = (100.0 * result["_ontime_sum"] / result["total_flights"]).round(2)
    result["avg_arr_delay"] = result["avg_arr_delay"].round(2)
    result["avg_distance_miles"] = result["avg_distance_miles"].round(0)
    return (
        result.sort_values("ontime_pct", ascending=False).head(25).drop(columns=["_ontime_sum"]).reset_index(drop=True)
    )


def improvement_trend_pandas_impl(ctx: DataFrameContext) -> Any:
    """Annual on-time performance trend (pandas)."""
    flights = ctx.get_table("flights")
    p = get_flightdata_parameters()

    filtered = flights[(flights["flight_date"] >= p["start_date"]) & (flights["flight_date"] < p["end_date"])].copy()
    filtered["_cancelled"] = (filtered["cancelled"] == 1).astype(int)
    filtered["_ontime"] = ((filtered["cancelled"] == 0) & (filtered["arr_delay"] <= 15)).astype(int)
    filtered["_non_cancelled"] = (filtered["cancelled"] == 0).astype(int)
    filtered["_arr_delay_nc"] = filtered["arr_delay"].where(filtered["cancelled"] == 0)

    result = filtered.groupby("year", as_index=False).agg(
        total_flights=("flight_id", "count"),
        cancelled_flights=("_cancelled", "sum"),
        ontime_flights=("_ontime", "sum"),
        _non_cancelled=("_non_cancelled", "sum"),
        avg_arr_delay=("_arr_delay_nc", "mean"),
    )
    result["cancellation_rate_pct"] = (100.0 * result["cancelled_flights"] / result["total_flights"]).round(2)
    result["ontime_pct"] = (100.0 * result["ontime_flights"] / result["_non_cancelled"]).round(2)
    result["avg_arr_delay"] = result["avg_arr_delay"].round(2)
    return result.drop(columns=["_non_cancelled"]).sort_values("year").reset_index(drop=True)


def delay_causes_pandas_impl(ctx: DataFrameContext) -> Any:
    """Distribution of delay causes (pandas)."""
    flights = ctx.get_table("flights")
    p = get_flightdata_parameters()

    filtered = flights[
        (flights["cancelled"] == 0)
        & (flights["arr_delay"] > 15)
        & (flights["flight_date"] >= p["start_date"])
        & (flights["flight_date"] < p["end_date"])
    ]

    def _cond_mean(series: Any, cond: Any) -> float:
        return float(series.where(cond).mean())

    return pd.DataFrame(
        [
            {
                "total_delayed_flights": len(filtered),
                "carrier_delay_count": int((filtered["carrier_delay"] > 0).sum()),
                "avg_carrier_delay": round(_cond_mean(filtered["carrier_delay"], filtered["carrier_delay"] > 0), 2),
                "weather_delay_count": int((filtered["weather_delay"] > 0).sum()),
                "avg_weather_delay": round(_cond_mean(filtered["weather_delay"], filtered["weather_delay"] > 0), 2),
                "nas_delay_count": int((filtered["nas_delay"] > 0).sum()),
                "avg_nas_delay": round(_cond_mean(filtered["nas_delay"], filtered["nas_delay"] > 0), 2),
                "security_delay_count": int((filtered["security_delay"] > 0).sum()),
                "avg_security_delay": round(_cond_mean(filtered["security_delay"], filtered["security_delay"] > 0), 2),
                "late_aircraft_count": int((filtered["late_aircraft_delay"] > 0).sum()),
                "avg_late_aircraft_delay": round(
                    _cond_mean(filtered["late_aircraft_delay"], filtered["late_aircraft_delay"] > 0), 2
                ),
            }
        ]
    )


def cascade_delays_pandas_impl(ctx: DataFrameContext) -> Any:
    """Late aircraft cascade delay patterns (pandas)."""
    flights = ctx.get_table("flights")
    airlines = ctx.get_table("airlines")
    p = get_flightdata_parameters()

    merged = flights.merge(airlines, left_on="reporting_airline", right_on="code", how="left")
    merged = merged.rename(columns={"name": "airline_name"})
    filtered = merged[
        (merged["cancelled"] == 0)
        & (merged["flight_date"] >= p["start_date"])
        & (merged["flight_date"] < p["end_date"])
    ].copy()
    filtered["_cascade"] = (filtered["late_aircraft_delay"] > 0).astype(int)
    filtered["_cascade_val"] = filtered["late_aircraft_delay"].where(filtered["late_aircraft_delay"] > 0)
    filtered["_cascade_total"] = filtered["late_aircraft_delay"].fillna(0)

    result = filtered.groupby(["reporting_airline", "airline_name"], as_index=False).agg(
        total_flights=("flight_id", "count"),
        cascade_delayed=("_cascade", "sum"),
        avg_cascade_delay=("_cascade_val", "mean"),
        total_cascade_minutes=("_cascade_total", "sum"),
    )
    result["avg_cascade_delay"] = result["avg_cascade_delay"].round(2)
    result["total_cascade_minutes"] = result["total_cascade_minutes"].round(0)
    result["cascade_rate_pct"] = (100.0 * result["cascade_delayed"] / result["total_flights"]).round(2)
    return result.sort_values("cascade_rate_pct", ascending=False).reset_index(drop=True)


def weather_impact_pandas_impl(ctx: DataFrameContext) -> Any:
    """Weather delay by month (pandas)."""
    flights = ctx.get_table("flights")
    p = get_flightdata_parameters()

    filtered = flights[
        (flights["cancelled"] == 0)
        & (flights["flight_date"] >= p["start_date"])
        & (flights["flight_date"] < p["end_date"])
    ].copy()
    filtered["_weather_flag"] = (filtered["weather_delay"] > 0).astype(int)
    filtered["_weather_val"] = filtered["weather_delay"].where(filtered["weather_delay"] > 0)
    filtered["_weather_total"] = filtered["weather_delay"].fillna(0)

    result = filtered.groupby("month", as_index=False).agg(
        total_flights=("flight_id", "count"),
        weather_delayed=("_weather_flag", "sum"),
        avg_weather_delay_min=("_weather_val", "mean"),
        total_weather_minutes=("_weather_total", "sum"),
    )
    result["weather_delay_rate_pct"] = (100.0 * result["weather_delayed"] / result["total_flights"]).round(2)
    result["avg_weather_delay_min"] = result["avg_weather_delay_min"].round(2)
    result["total_weather_minutes"] = result["total_weather_minutes"].round(0)
    return result.sort_values("month").reset_index(drop=True)


def recovery_time_pandas_impl(ctx: DataFrameContext) -> Any:
    """Delay recovery analysis by departure delay bucket (pandas)."""
    flights = ctx.get_table("flights")
    p = get_flightdata_parameters()

    filtered = flights[
        (flights["cancelled"] == 0)
        & flights["dep_delay"].notna()
        & flights["arr_delay"].notna()
        & (flights["flight_date"] >= p["start_date"])
        & (flights["flight_date"] < p["end_date"])
    ].copy()

    # Build delay bucket labels
    filtered["delay_bucket"] = "60+ min departure delay"
    filtered.loc[filtered["dep_delay"] <= 60, "delay_bucket"] = "31-60 min departure delay"
    filtered.loc[filtered["dep_delay"] <= 30, "delay_bucket"] = "16-30 min departure delay"
    filtered.loc[filtered["dep_delay"] <= 15, "delay_bucket"] = "1-15 min departure delay"
    filtered.loc[filtered["dep_delay"] <= 0, "delay_bucket"] = "No departure delay"

    filtered["_minutes_recovered"] = filtered["dep_delay"] - filtered["arr_delay"]
    filtered["_recovered"] = (filtered["arr_delay"] < filtered["dep_delay"]).astype(int)

    result = filtered.groupby("delay_bucket", as_index=False).agg(
        flight_count=("flight_id", "count"),
        avg_dep_delay=("dep_delay", "mean"),
        avg_arr_delay=("arr_delay", "mean"),
        avg_minutes_recovered=("_minutes_recovered", "mean"),
        _total=("flight_id", "count"),
        _recovered_sum=("_recovered", "sum"),
    )
    result["pct_recovered"] = (100.0 * result["_recovered_sum"] / result["_total"]).round(2)
    result["avg_dep_delay"] = result["avg_dep_delay"].round(2)
    result["avg_arr_delay"] = result["avg_arr_delay"].round(2)
    result["avg_minutes_recovered"] = result["avg_minutes_recovered"].round(2)
    return result.drop(columns=["_total", "_recovered_sum"]).sort_values("avg_dep_delay").reset_index(drop=True)


def busiest_routes_pandas_impl(ctx: DataFrameContext) -> Any:
    """Top 25 routes by flight count (pandas)."""
    flights = ctx.get_table("flights")
    airports = ctx.get_table("airports")
    p = get_flightdata_parameters()

    ao = airports[["code", "city", "state"]].rename(
        columns={"code": "ao_code", "city": "origin_city", "state": "origin_state"}
    )
    ad = airports[["code", "city", "state"]].rename(
        columns={"code": "ad_code", "city": "dest_city", "state": "dest_state"}
    )

    filtered = (
        flights[
            (flights["cancelled"] == 0)
            & (flights["flight_date"] >= p["start_date"])
            & (flights["flight_date"] < p["end_date"])
        ]
        .merge(ao, left_on="origin", right_on="ao_code", how="left")
        .merge(ad, left_on="dest", right_on="ad_code", how="left")
    ).copy()
    filtered["_ontime"] = (filtered["arr_delay"] <= 15).astype(int)

    result = filtered.groupby(
        ["origin", "dest", "origin_city", "origin_state", "dest_city", "dest_state"], as_index=False
    ).agg(
        total_flights=("flight_id", "count"),
        avg_distance_miles=("distance", "mean"),
        avg_duration_min=("actual_elapsed_time", "mean"),
        _ontime_sum=("_ontime", "sum"),
    )
    result["ontime_pct"] = (100.0 * result["_ontime_sum"] / result["total_flights"]).round(2)
    result["avg_distance_miles"] = result["avg_distance_miles"].round(0)
    result["avg_duration_min"] = result["avg_duration_min"].round(0)
    return (
        result.sort_values("total_flights", ascending=False)
        .head(25)
        .drop(columns=["_ontime_sum"])
        .reset_index(drop=True)
    )


def route_reliability_pandas_impl(ctx: DataFrameContext) -> Any:
    """Routes ranked by reliability (pandas)."""
    flights = ctx.get_table("flights")
    airports = ctx.get_table("airports")
    p = get_flightdata_parameters()

    ao = airports[["code", "city"]].rename(columns={"code": "ao_code", "city": "origin_city"})
    ad = airports[["code", "city"]].rename(columns={"code": "ad_code", "city": "dest_city"})

    filtered = (
        flights[(flights["flight_date"] >= p["start_date"]) & (flights["flight_date"] < p["end_date"])]
        .merge(ao, left_on="origin", right_on="ao_code", how="left")
        .merge(ad, left_on="dest", right_on="ad_code", how="left")
    ).copy()
    filtered["_cancelled"] = (filtered["cancelled"] == 1).astype(int)
    filtered["_ontime"] = ((filtered["cancelled"] == 0) & (filtered["arr_delay"] <= 15)).astype(int)
    filtered["_non_cancelled"] = (filtered["cancelled"] == 0).astype(int)

    result = filtered.groupby(["origin", "dest", "origin_city", "dest_city"], as_index=False).agg(
        total_scheduled=("flight_id", "count"),
        cancelled_count=("_cancelled", "sum"),
        ontime_count=("_ontime", "sum"),
        _non_cancelled=("_non_cancelled", "sum"),
        distance_miles=("distance", "mean"),
    )
    result = result[result["total_scheduled"] >= 100]
    result["cancellation_rate_pct"] = (100.0 * result["cancelled_count"] / result["total_scheduled"]).round(2)
    result["ontime_pct"] = (100.0 * result["ontime_count"] / result["_non_cancelled"]).round(2)
    result["distance_miles"] = result["distance_miles"].round(0)
    return (
        result.drop(columns=["_non_cancelled"])
        .sort_values(["ontime_pct", "cancellation_rate_pct"], ascending=[False, True])
        .head(30)
        .reset_index(drop=True)
    )


def distance_delay_pandas_impl(ctx: DataFrameContext) -> Any:
    """Average delay by flight distance bucket (pandas)."""
    flights = ctx.get_table("flights")
    p = get_flightdata_parameters()

    filtered = flights[
        (flights["cancelled"] == 0)
        & flights["arr_delay"].notna()
        & (flights["flight_date"] >= p["start_date"])
        & (flights["flight_date"] < p["end_date"])
    ].copy()

    filtered["distance_bucket"] = "Ultra-long (2000+ mi)"
    filtered.loc[filtered["distance"] < 2000, "distance_bucket"] = "Cross-country (1000-1999 mi)"
    filtered.loc[filtered["distance"] < 1000, "distance_bucket"] = "Long-haul (500-999 mi)"
    filtered.loc[filtered["distance"] < 500, "distance_bucket"] = "Medium-haul (250-499 mi)"
    filtered.loc[filtered["distance"] < 250, "distance_bucket"] = "Short-haul (<250 mi)"

    filtered["_ontime"] = (filtered["arr_delay"] <= 15).astype(int)

    result = filtered.groupby("distance_bucket", as_index=False).agg(
        total_flights=("flight_id", "count"),
        avg_distance_miles=("distance", "mean"),
        avg_dep_delay=("dep_delay", "mean"),
        avg_arr_delay=("arr_delay", "mean"),
        _ontime_sum=("_ontime", "sum"),
    )
    result["ontime_pct"] = (100.0 * result["_ontime_sum"] / result["total_flights"]).round(2)
    result["avg_distance_miles"] = result["avg_distance_miles"].round(0)
    result["avg_dep_delay"] = result["avg_dep_delay"].round(2)
    result["avg_arr_delay"] = result["avg_arr_delay"].round(2)
    return result.drop(columns=["_ontime_sum"]).sort_values("avg_distance_miles").reset_index(drop=True)


def hub_connectivity_pandas_impl(ctx: DataFrameContext) -> Any:
    """Hub airport connectivity (pandas)."""
    flights = ctx.get_table("flights")
    airports = ctx.get_table("airports")
    p = get_flightdata_parameters()

    merged = flights.merge(airports, left_on="origin", right_on="code", how="left")
    merged = merged.rename(columns={"name": "airport_name"})
    filtered = merged[
        (merged["cancelled"] == 0)
        & (merged["flight_date"] >= p["start_date"])
        & (merged["flight_date"] < p["end_date"])
    ]

    result = filtered.groupby(["origin", "airport_name", "city", "state"], as_index=False).agg(
        unique_destinations=("dest", "nunique"),
        serving_carriers=("reporting_airline", "nunique"),
        total_departures=("flight_id", "count"),
        avg_dep_delay=("dep_delay", "mean"),
    )
    result["avg_dep_delay"] = result["avg_dep_delay"].round(2)
    return result.sort_values("total_departures", ascending=False).head(30).reset_index(drop=True)


def day_of_week_pandas_impl(ctx: DataFrameContext) -> Any:
    """Flight patterns by day of week (pandas)."""
    flights = ctx.get_table("flights")
    p = get_flightdata_parameters()

    filtered = flights[(flights["flight_date"] >= p["start_date"]) & (flights["flight_date"] < p["end_date"])].copy()
    day_names = {1: "Monday", 2: "Tuesday", 3: "Wednesday", 4: "Thursday", 5: "Friday", 6: "Saturday", 7: "Sunday"}
    filtered["day_name"] = filtered["day_of_week"].map(day_names)
    filtered["_cancelled"] = (filtered["cancelled"] == 1).astype(int)
    filtered["_dep_delay_nc"] = filtered["dep_delay"].where(filtered["cancelled"] == 0)
    filtered["_arr_delay_nc"] = filtered["arr_delay"].where(filtered["cancelled"] == 0)
    filtered["_ontime"] = ((filtered["cancelled"] == 0) & (filtered["arr_delay"] <= 15)).astype(int)
    filtered["_non_cancelled"] = (filtered["cancelled"] == 0).astype(int)

    result = filtered.groupby(["day_of_week", "day_name"], as_index=False).agg(
        total_flights=("flight_id", "count"),
        cancelled_count=("_cancelled", "sum"),
        avg_dep_delay=("_dep_delay_nc", "mean"),
        avg_arr_delay=("_arr_delay_nc", "mean"),
        _ontime=("_ontime", "sum"),
        _non_cancelled=("_non_cancelled", "sum"),
    )
    result["ontime_pct"] = (100.0 * result["_ontime"] / result["_non_cancelled"]).round(2)
    result["avg_dep_delay"] = result["avg_dep_delay"].round(2)
    result["avg_arr_delay"] = result["avg_arr_delay"].round(2)
    return result.drop(columns=["_ontime", "_non_cancelled"]).sort_values("day_of_week").reset_index(drop=True)


def seasonal_trends_pandas_impl(ctx: DataFrameContext) -> Any:
    """Seasonal performance trends by month (pandas)."""
    flights = ctx.get_table("flights")
    p = get_flightdata_parameters()

    filtered = flights[(flights["flight_date"] >= p["start_date"]) & (flights["flight_date"] < p["end_date"])].copy()
    month_names = {
        1: "January",
        2: "February",
        3: "March",
        4: "April",
        5: "May",
        6: "June",
        7: "July",
        8: "August",
        9: "September",
        10: "October",
        11: "November",
        12: "December",
    }
    filtered["month_name"] = filtered["month"].map(month_names)
    filtered["_cancelled"] = (filtered["cancelled"] == 1).astype(int)
    filtered["_arr_delay_nc"] = filtered["arr_delay"].where(filtered["cancelled"] == 0)
    filtered["_ontime"] = ((filtered["cancelled"] == 0) & (filtered["arr_delay"] <= 15)).astype(int)
    filtered["_non_cancelled"] = (filtered["cancelled"] == 0).astype(int)

    result = filtered.groupby(["month", "month_name"], as_index=False).agg(
        total_flights=("flight_id", "count"),
        cancelled_count=("_cancelled", "sum"),
        avg_arr_delay=("_arr_delay_nc", "mean"),
        _ontime=("_ontime", "sum"),
        _non_cancelled=("_non_cancelled", "sum"),
    )
    result["cancellation_rate_pct"] = (100.0 * result["cancelled_count"] / result["total_flights"]).round(2)
    result["ontime_pct"] = (100.0 * result["_ontime"] / result["_non_cancelled"]).round(2)
    result["avg_arr_delay"] = result["avg_arr_delay"].round(2)
    return result.drop(columns=["_ontime", "_non_cancelled"]).sort_values("month").reset_index(drop=True)


def holiday_impact_pandas_impl(ctx: DataFrameContext) -> Any:
    """Holiday period delay impact (pandas)."""
    flights = ctx.get_table("flights")
    p = get_flightdata_parameters()

    filtered = flights[(flights["flight_date"] >= p["start_date"]) & (flights["flight_date"] < p["end_date"])].copy()

    # Assign period labels using reverse-priority masking
    filtered["period"] = "Regular Day"
    filtered.loc[
        (filtered["month"] == 9) & (filtered["day_of_week"] == 1) & (filtered["day_of_month"] <= 7), "period"
    ] = "Labor Day"
    filtered.loc[
        (filtered["month"] == 5) & (filtered["day_of_week"] == 1) & (filtered["day_of_month"] >= 25), "period"
    ] = "Memorial Day"
    filtered.loc[(filtered["month"] == 7) & (filtered["day_of_month"].between(3, 5)), "period"] = "July 4th"
    filtered.loc[
        ((filtered["month"] == 1) & (filtered["day_of_month"] <= 2))
        | ((filtered["month"] == 12) & (filtered["day_of_month"] == 31)),
        "period",
    ] = "New Year"
    filtered.loc[(filtered["month"] == 12) & (filtered["day_of_month"].between(23, 27)), "period"] = "Christmas"
    filtered.loc[(filtered["month"] == 11) & (filtered["day_of_month"].between(21, 27)), "period"] = "Thanksgiving Week"

    filtered["_cancelled"] = (filtered["cancelled"] == 1).astype(int)
    filtered["_arr_delay_nc"] = filtered["arr_delay"].where(filtered["cancelled"] == 0)
    filtered["_ontime"] = ((filtered["cancelled"] == 0) & (filtered["arr_delay"] <= 15)).astype(int)
    filtered["_non_cancelled"] = (filtered["cancelled"] == 0).astype(int)

    result = filtered.groupby("period", as_index=False).agg(
        total_flights=("flight_id", "count"),
        avg_arr_delay=("_arr_delay_nc", "mean"),
        _cancelled_sum=("_cancelled", "sum"),
        _ontime=("_ontime", "sum"),
        _non_cancelled=("_non_cancelled", "sum"),
    )
    result["cancellation_rate_pct"] = (100.0 * result["_cancelled_sum"] / result["total_flights"]).round(2)
    result["ontime_pct"] = (100.0 * result["_ontime"] / result["_non_cancelled"]).round(2)
    result["avg_arr_delay"] = result["avg_arr_delay"].round(2)
    return (
        result.drop(columns=["_cancelled_sum", "_ontime", "_non_cancelled"])
        .sort_values("avg_arr_delay", ascending=False)
        .reset_index(drop=True)
    )


def time_of_day_pandas_impl(ctx: DataFrameContext) -> Any:
    """Hourly congestion pattern (pandas)."""
    flights = ctx.get_table("flights")
    p = get_flightdata_parameters()

    filtered = flights[
        flights["crs_dep_time"].notna()
        & (flights["flight_date"] >= p["start_date"])
        & (flights["flight_date"] < p["end_date"])
    ].copy()
    filtered["hour_of_day"] = (filtered["crs_dep_time"] // 100).astype(int)
    filtered["_dep_delay_nc"] = filtered["dep_delay"].where(filtered["cancelled"] == 0)
    filtered["_arr_delay_nc"] = filtered["arr_delay"].where(filtered["cancelled"] == 0)
    filtered["_severely_delayed"] = (filtered["dep_delay"] > 60).astype(int)
    filtered["_ontime"] = ((filtered["cancelled"] == 0) & (filtered["arr_delay"] <= 15)).astype(int)
    filtered["_non_cancelled"] = (filtered["cancelled"] == 0).astype(int)

    result = filtered.groupby("hour_of_day", as_index=False).agg(
        total_flights=("flight_id", "count"),
        avg_dep_delay=("_dep_delay_nc", "mean"),
        avg_arr_delay=("_arr_delay_nc", "mean"),
        severely_delayed=("_severely_delayed", "sum"),
        _ontime=("_ontime", "sum"),
        _non_cancelled=("_non_cancelled", "sum"),
    )
    result["ontime_pct"] = (100.0 * result["_ontime"] / result["_non_cancelled"]).round(2)
    result["avg_dep_delay"] = result["avg_dep_delay"].round(2)
    result["avg_arr_delay"] = result["avg_arr_delay"].round(2)
    return result.drop(columns=["_ontime", "_non_cancelled"]).sort_values("hour_of_day").reset_index(drop=True)


def carrier_ranking_pandas_impl(ctx: DataFrameContext) -> Any:
    """Full carrier scorecard (pandas)."""
    flights = ctx.get_table("flights")
    airlines = ctx.get_table("airlines")
    p = get_flightdata_parameters()

    merged = flights.merge(airlines, left_on="reporting_airline", right_on="code", how="left")
    merged = merged.rename(columns={"name": "airline_name"})
    filtered = merged[(merged["flight_date"] >= p["start_date"]) & (merged["flight_date"] < p["end_date"])].copy()
    filtered["_operated"] = (filtered["cancelled"] == 0).astype(int)
    filtered["_cancelled"] = (filtered["cancelled"] == 1).astype(int)
    filtered["_dep_delay_nc"] = filtered["dep_delay"].where(filtered["cancelled"] == 0)
    filtered["_arr_delay_nc"] = filtered["arr_delay"].where(filtered["cancelled"] == 0)
    filtered["_ontime"] = ((filtered["cancelled"] == 0) & (filtered["arr_delay"] <= 15)).astype(int)
    filtered["_non_cancelled"] = (filtered["cancelled"] == 0).astype(int)

    result = filtered.groupby(["reporting_airline", "airline_name"], as_index=False).agg(
        total_scheduled=("flight_id", "count"),
        operated_flights=("_operated", "sum"),
        cancelled_flights=("_cancelled", "sum"),
        avg_dep_delay=("_dep_delay_nc", "mean"),
        avg_arr_delay=("_arr_delay_nc", "mean"),
        _ontime=("_ontime", "sum"),
        _non_cancelled=("_non_cancelled", "sum"),
        avg_route_distance_miles=("distance", "mean"),
    )
    result = result[result["total_scheduled"] >= 1000]
    result["cancellation_rate_pct"] = (100.0 * result["cancelled_flights"] / result["total_scheduled"]).round(2)
    result["ontime_pct"] = (100.0 * result["_ontime"] / result["_non_cancelled"]).round(2)
    result["avg_dep_delay"] = result["avg_dep_delay"].round(2)
    result["avg_arr_delay"] = result["avg_arr_delay"].round(2)
    result["avg_route_distance_miles"] = result["avg_route_distance_miles"].round(0)
    return (
        result.drop(columns=["_ontime", "_non_cancelled"])
        .sort_values("ontime_pct", ascending=False)
        .reset_index(drop=True)
    )


def cancellation_rate_pandas_impl(ctx: DataFrameContext) -> Any:
    """Cancellation rates by carrier (pandas)."""
    flights = ctx.get_table("flights")
    airlines = ctx.get_table("airlines")
    p = get_flightdata_parameters()

    merged = flights.merge(airlines, left_on="reporting_airline", right_on="code", how="left")
    merged = merged.rename(columns={"name": "airline_name"})
    filtered = merged[(merged["flight_date"] >= p["start_date"]) & (merged["flight_date"] < p["end_date"])].copy()
    filtered["_cancelled"] = (filtered["cancelled"] == 1).astype(int)
    filtered["_code_a"] = (filtered["cancellation_code"] == "A").astype(int)
    filtered["_code_b"] = (filtered["cancellation_code"] == "B").astype(int)
    filtered["_code_c"] = (filtered["cancellation_code"] == "C").astype(int)
    filtered["_code_d"] = (filtered["cancellation_code"] == "D").astype(int)

    result = filtered.groupby(["reporting_airline", "airline_name"], as_index=False).agg(
        total_flights=("flight_id", "count"),
        total_cancelled=("_cancelled", "sum"),
        carrier_cancellations=("_code_a", "sum"),
        weather_cancellations=("_code_b", "sum"),
        nas_cancellations=("_code_c", "sum"),
        security_cancellations=("_code_d", "sum"),
    )
    result = result[result["total_flights"] >= 100]
    result["cancellation_rate_pct"] = (100.0 * result["total_cancelled"] / result["total_flights"]).round(3)
    return result.sort_values("cancellation_rate_pct", ascending=False).reset_index(drop=True)


def market_share_pandas_impl(ctx: DataFrameContext) -> Any:
    """Carrier market share (pandas)."""
    flights = ctx.get_table("flights")
    airlines = ctx.get_table("airlines")
    p = get_flightdata_parameters()

    merged = flights.merge(airlines, left_on="reporting_airline", right_on="code", how="left")
    merged = merged.rename(columns={"name": "airline_name"})
    filtered = merged[
        (merged["cancelled"] == 0)
        & (merged["flight_date"] >= p["start_date"])
        & (merged["flight_date"] < p["end_date"])
    ].copy()
    filtered["route"] = filtered["origin"] + "-" + filtered["dest"]

    result = filtered.groupby(["reporting_airline", "airline_name"], as_index=False).agg(
        flight_count=("flight_id", "count"),
        routes_served=("route", "nunique"),
        avg_distance_miles=("distance", "mean"),
    )
    grand_total = result["flight_count"].sum()
    result["market_share_pct"] = (100.0 * result["flight_count"] / grand_total).round(2)
    result["avg_distance_miles"] = result["avg_distance_miles"].round(0)
    return result.sort_values("flight_count", ascending=False).head(20).reset_index(drop=True)


# ===========================================================================
# Registry
# ===========================================================================

FLIGHTDATA_DATAFRAME_QUERIES = QueryRegistry("FlightData DataFrame")

_QUERIES = [
    DataFrameQuery(
        query_id="ontime-by-carrier",
        query_name="On-Time Rate by Carrier",
        description="On-time arrival percentage by airline carrier",
        categories=[QueryCategory.JOIN, QueryCategory.AGGREGATE, QueryCategory.GROUP_BY],
        expression_impl=ontime_by_carrier_expression_impl,
        pandas_impl=ontime_by_carrier_pandas_impl,
    ),
    DataFrameQuery(
        query_id="delay-by-airport",
        query_name="Average Departure Delay by Origin Airport",
        description="Average departure delay in minutes by origin airport",
        categories=[QueryCategory.JOIN, QueryCategory.AGGREGATE, QueryCategory.GROUP_BY, QueryCategory.FILTER],
        expression_impl=delay_by_airport_expression_impl,
        pandas_impl=delay_by_airport_pandas_impl,
    ),
    DataFrameQuery(
        query_id="delay-by-hour",
        query_name="Delay Pattern by Departure Hour",
        description="Average delay minutes by scheduled departure hour",
        categories=[QueryCategory.AGGREGATE, QueryCategory.GROUP_BY],
        expression_impl=delay_by_hour_expression_impl,
        pandas_impl=delay_by_hour_pandas_impl,
    ),
    DataFrameQuery(
        query_id="best-routes",
        query_name="Best Performing Routes by On-Time Rate",
        description="Routes with highest on-time arrival percentage (min 50 flights)",
        categories=[QueryCategory.JOIN, QueryCategory.AGGREGATE, QueryCategory.GROUP_BY, QueryCategory.FILTER],
        expression_impl=best_routes_expression_impl,
        pandas_impl=best_routes_pandas_impl,
    ),
    DataFrameQuery(
        query_id="improvement-trend",
        query_name="On-Time Performance Trend Over Years",
        description="Annual on-time arrival percentage trend",
        categories=[QueryCategory.AGGREGATE, QueryCategory.GROUP_BY],
        expression_impl=improvement_trend_expression_impl,
        pandas_impl=improvement_trend_pandas_impl,
    ),
    DataFrameQuery(
        query_id="delay-causes",
        query_name="Delay Cause Breakdown",
        description="Distribution of delay causes across all delayed flights",
        categories=[QueryCategory.AGGREGATE, QueryCategory.FILTER],
        expression_impl=delay_causes_expression_impl,
        pandas_impl=delay_causes_pandas_impl,
    ),
    DataFrameQuery(
        query_id="cascade-delays",
        query_name="Late Aircraft (Cascade) Delay Patterns",
        description="Flights delayed due to late incoming aircraft by carrier",
        categories=[QueryCategory.JOIN, QueryCategory.AGGREGATE, QueryCategory.GROUP_BY],
        expression_impl=cascade_delays_expression_impl,
        pandas_impl=cascade_delays_pandas_impl,
    ),
    DataFrameQuery(
        query_id="weather-impact",
        query_name="Weather Delay Impact by Month",
        description="Average weather delay by month showing seasonal patterns",
        categories=[QueryCategory.AGGREGATE, QueryCategory.GROUP_BY],
        expression_impl=weather_impact_expression_impl,
        pandas_impl=weather_impact_pandas_impl,
    ),
    DataFrameQuery(
        query_id="recovery-time",
        query_name="Delay Recovery Analysis",
        description="How much of departure delay is recovered in flight",
        categories=[QueryCategory.AGGREGATE, QueryCategory.GROUP_BY],
        expression_impl=recovery_time_expression_impl,
        pandas_impl=recovery_time_pandas_impl,
    ),
    DataFrameQuery(
        query_id="busiest-routes",
        query_name="Busiest Routes by Flight Count",
        description="Top 25 routes ranked by total flight count",
        categories=[QueryCategory.JOIN, QueryCategory.AGGREGATE, QueryCategory.GROUP_BY, QueryCategory.SORT],
        expression_impl=busiest_routes_expression_impl,
        pandas_impl=busiest_routes_pandas_impl,
    ),
    DataFrameQuery(
        query_id="route-reliability",
        query_name="Route Reliability Ranking",
        description="Routes ranked by reliability (on-time + low cancellation)",
        categories=[QueryCategory.JOIN, QueryCategory.AGGREGATE, QueryCategory.GROUP_BY, QueryCategory.FILTER],
        expression_impl=route_reliability_expression_impl,
        pandas_impl=route_reliability_pandas_impl,
    ),
    DataFrameQuery(
        query_id="distance-delay",
        query_name="Distance vs Delay Correlation",
        description="Average delay grouped by flight distance buckets",
        categories=[QueryCategory.AGGREGATE, QueryCategory.GROUP_BY],
        expression_impl=distance_delay_expression_impl,
        pandas_impl=distance_delay_pandas_impl,
    ),
    DataFrameQuery(
        query_id="hub-connectivity",
        query_name="Hub Airport Connectivity",
        description="Number of unique destinations served from each origin airport",
        categories=[QueryCategory.JOIN, QueryCategory.AGGREGATE, QueryCategory.GROUP_BY],
        expression_impl=hub_connectivity_expression_impl,
        pandas_impl=hub_connectivity_pandas_impl,
    ),
    DataFrameQuery(
        query_id="day-of-week",
        query_name="Flight Patterns by Day of Week",
        description="Flight volume and delay patterns by day of week",
        categories=[QueryCategory.AGGREGATE, QueryCategory.GROUP_BY],
        expression_impl=day_of_week_expression_impl,
        pandas_impl=day_of_week_pandas_impl,
    ),
    DataFrameQuery(
        query_id="seasonal-trends",
        query_name="Seasonal Performance Trends",
        description="Monthly flight volume and performance aggregated across all years",
        categories=[QueryCategory.AGGREGATE, QueryCategory.GROUP_BY],
        expression_impl=seasonal_trends_expression_impl,
        pandas_impl=seasonal_trends_pandas_impl,
    ),
    DataFrameQuery(
        query_id="holiday-impact",
        query_name="Holiday Period Delay Impact",
        description="Compare performance during major holiday periods vs normal days",
        categories=[QueryCategory.AGGREGATE, QueryCategory.GROUP_BY, QueryCategory.FILTER],
        expression_impl=holiday_impact_expression_impl,
        pandas_impl=holiday_impact_pandas_impl,
    ),
    DataFrameQuery(
        query_id="time-of-day",
        query_name="Hourly Congestion Pattern",
        description="Flight volume and delay by scheduled departure hour of day",
        categories=[QueryCategory.AGGREGATE, QueryCategory.GROUP_BY],
        expression_impl=time_of_day_expression_impl,
        pandas_impl=time_of_day_pandas_impl,
    ),
    DataFrameQuery(
        query_id="carrier-ranking",
        query_name="Carrier On-Time Performance Ranking",
        description="Full carrier scorecard: on-time, delays, cancellations",
        categories=[QueryCategory.JOIN, QueryCategory.AGGREGATE, QueryCategory.GROUP_BY, QueryCategory.FILTER],
        expression_impl=carrier_ranking_expression_impl,
        pandas_impl=carrier_ranking_pandas_impl,
    ),
    DataFrameQuery(
        query_id="cancellation-rate",
        query_name="Cancellation Rates by Carrier and Cause",
        description="Cancellation frequency and reason breakdown by carrier",
        categories=[QueryCategory.JOIN, QueryCategory.AGGREGATE, QueryCategory.GROUP_BY],
        expression_impl=cancellation_rate_expression_impl,
        pandas_impl=cancellation_rate_pandas_impl,
    ),
    DataFrameQuery(
        query_id="market-share",
        query_name="Carrier Market Share by Route",
        description="Top carriers ranked by flight volume and market share",
        categories=[QueryCategory.JOIN, QueryCategory.AGGREGATE, QueryCategory.GROUP_BY, QueryCategory.SORT],
        expression_impl=market_share_expression_impl,
        pandas_impl=market_share_pandas_impl,
    ),
]

for _query in _QUERIES:
    FLIGHTDATA_DATAFRAME_QUERIES.register(_query)


def get_dataframe_queries() -> QueryRegistry:
    """Get the FlightData DataFrame query registry.

    Returns:
        QueryRegistry containing all 20 FlightData DataFrame queries
    """
    return FLIGHTDATA_DATAFRAME_QUERIES
