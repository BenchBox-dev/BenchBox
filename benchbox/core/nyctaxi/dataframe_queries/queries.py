"""NYC Taxi DataFrame query implementations.

All 25 NYC Taxi benchmark queries implemented for both Expression and Pandas families.

Categories:
- Temporal (Q1-Q4): Time-based aggregations (hourly, daily, monthly, day-of-week)
- Geographic (Q5-Q8): Zone-based analytics with LEFT JOIN to taxi_zones
- Financial (Q9-Q12): Revenue, tip, fare, surcharge analysis
- Characteristics (Q13-Q15): Distance, passenger, duration distributions
- Rates (Q16-Q17): Rate code and airport trip analysis
- Vendor (Q18): Vendor comparison
- Complex (Q19-Q22): Multi-dimensional analytics (heatmap, weekday/weekend, rush hour, YoY)
- Point (Q23-Q24): Single-day summary, zone detail
- Baseline (Q25): Full scan count

Schema: trips fact table with optional LEFT JOIN to taxi_zones dimension.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

from csv import reader
from typing import Any

from benchbox.core.dataframe.context import DataFrameContext
from benchbox.core.dataframe.query import DataFrameQuery, QueryCategory

from .parameters import get_parameters
from .registry import register_query


def _date_bounds(query_id: str, default_start: str, default_end: str) -> tuple[Any, Any]:
    params = get_parameters(query_id)
    return params.get("start_date", default_start), params.get("end_date", default_end)


def _expression_window(
    ctx: DataFrameContext,
    query_id: str,
    default_start: str,
    default_end: str,
    extra: Any = None,
) -> tuple[Any, Any, Any]:
    start_date, end_date = _date_bounds(query_id, default_start, default_end)
    col, lit = ctx.col, ctx.lit
    condition = (col("pickup_datetime") >= lit(start_date)) & (col("pickup_datetime") < lit(end_date))
    if extra is not None:
        extras = extra(col, lit)
        if not isinstance(extras, tuple):
            extras = (extras,)
        for extra_condition in extras:
            condition = condition & extra_condition
    return ctx.get_table("trips").filter(condition), col, lit


def _pandas_window(
    ctx: DataFrameContext,
    query_id: str,
    default_start: str,
    default_end: str,
    *,
    copy: bool = False,
    extra: Any = None,
) -> Any:
    start_date, end_date = _date_bounds(query_id, default_start, default_end)
    trips = ctx.get_table("trips")
    condition = (trips["pickup_datetime"] >= start_date) & (trips["pickup_datetime"] < end_date)
    if extra is not None:
        condition &= extra(trips)
    filtered = trips[condition]
    return filtered.copy() if copy else filtered


def _expression_top_zone(ctx: DataFrameContext, query_id: str, location_col: str) -> Any:
    trips, col, _ = _expression_window(ctx, query_id, "2019-01-01", "2019-01-31")
    return (
        trips.join(ctx.get_table("taxi_zones"), left_on=location_col, right_on="location_id", how="left")
        .group_by(location_col, "zone", "borough")
        .agg(col(location_col).count().alias("trip_count"))
        .sort("trip_count", descending=True)
        .limit(20)
    )


def _pandas_top_zone(ctx: DataFrameContext, query_id: str, location_col: str) -> Any:
    merged = _pandas_window(ctx, query_id, "2019-01-01", "2019-01-31").merge(
        ctx.get_table("taxi_zones"), left_on=location_col, right_on="location_id", how="left"
    )
    return (
        merged.groupby([location_col, "zone", "borough"], as_index=False)
        .agg(trip_count=(location_col, "count"))
        .sort_values("trip_count", ascending=False)
        .head(20)
    )


def _expression_trip_summary(
    ctx: DataFrameContext, query_id: str, default_end: str, group_col: str, *, tip: bool
) -> Any:
    trips, col, _ = _expression_window(ctx, query_id, "2019-01-01", default_end)
    aggregations = [
        col(group_col).count().alias("trip_count"),
        col("trip_distance").mean().alias("avg_distance"),
        col("total_amount").mean().alias("avg_fare"),
    ]
    if tip:
        aggregations.append(col("tip_amount").mean().alias("avg_tip"))
    aggregations.append(col("total_amount").sum().alias("total_revenue"))
    return trips.group_by(group_col).agg(*aggregations).sort("trip_count", descending=True)


def _pandas_trip_summary(ctx: DataFrameContext, query_id: str, default_end: str, group_col: str, *, tip: bool) -> Any:
    aggregations = {
        "trip_count": (group_col, "count"),
        "avg_distance": ("trip_distance", "mean"),
        "avg_fare": ("total_amount", "mean"),
    }
    if tip:
        aggregations["avg_tip"] = ("tip_amount", "mean")
    aggregations["total_revenue"] = ("total_amount", "sum")
    return (
        _pandas_window(ctx, query_id, "2019-01-01", default_end)
        .groupby([group_col], as_index=False)
        .agg(**aggregations)
        .sort_values("trip_count", ascending=False)
    )


# =============================================================================
# Temporal Aggregations (Q1-Q4)
# =============================================================================


def q1_expression_impl(ctx: DataFrameContext) -> Any:
    trips, col, _ = _expression_window(ctx, "Q1", "2019-01-01", "2019-01-31")

    return (
        trips.with_columns(col("pickup_datetime").dt.hour().alias("hour"))
        .group_by("hour")
        .agg(col("hour").count().alias("trip_count"))
        .sort("hour")
    )


def q1_pandas_impl(ctx: DataFrameContext) -> Any:
    filtered = _pandas_window(ctx, "Q1", "2019-01-01", "2019-01-31", copy=True)
    filtered["hour"] = filtered["pickup_datetime"].dt.hour
    return filtered.groupby(["hour"], as_index=False).agg(trip_count=("hour", "count")).sort_values("hour")


def q2_expression_impl(ctx: DataFrameContext) -> Any:
    trips, col, _ = _expression_window(ctx, "Q2", "2019-01-01", "2019-12-31")

    return (
        trips.with_columns(col("pickup_datetime").dt.truncate("1d").alias("day"))
        .group_by("day")
        .agg(col("day").count().alias("trip_count"))
        .sort("day")
    )


def q2_pandas_impl(ctx: DataFrameContext) -> Any:
    filtered = _pandas_window(ctx, "Q2", "2019-01-01", "2019-12-31", copy=True)
    filtered["day"] = filtered["pickup_datetime"].dt.floor("D")
    return filtered.groupby(["day"], as_index=False).agg(trip_count=("day", "count")).sort_values("day")


def q3_expression_impl(ctx: DataFrameContext) -> Any:
    trips, col, _ = _expression_window(ctx, "Q3", "2019-01-01", "2019-12-31")

    return (
        trips.with_columns(col("pickup_datetime").dt.truncate("1mo").alias("month"))
        .group_by("month")
        .agg(
            col("month").count().alias("trip_count"),
            col("total_amount").sum().alias("total_revenue"),
        )
        .sort("month")
    )


def q3_pandas_impl(ctx: DataFrameContext) -> Any:
    filtered = _pandas_window(ctx, "Q3", "2019-01-01", "2019-12-31", copy=True)
    filtered["month"] = filtered["pickup_datetime"].dt.to_period("M").dt.to_timestamp()
    return (
        filtered.groupby(["month"], as_index=False)
        .agg(trip_count=("month", "count"), total_revenue=("total_amount", "sum"))
        .sort_values("month")
    )


def q4_expression_impl(ctx: DataFrameContext) -> Any:
    trips, col, _ = _expression_window(ctx, "Q4", "2019-01-01", "2019-03-31")

    return (
        trips.with_columns(col("pickup_datetime").dt.weekday().alias("day_of_week"))
        .group_by("day_of_week")
        .agg(
            col("day_of_week").count().alias("trip_count"),
            col("trip_distance").mean().alias("avg_distance"),
            col("total_amount").mean().alias("avg_fare"),
        )
        .sort("day_of_week")
    )


def q4_pandas_impl(ctx: DataFrameContext) -> Any:
    filtered = _pandas_window(ctx, "Q4", "2019-01-01", "2019-03-31", copy=True)
    filtered["day_of_week"] = filtered["pickup_datetime"].dt.dayofweek
    return (
        filtered.groupby(["day_of_week"], as_index=False)
        .agg(
            trip_count=("day_of_week", "count"),
            avg_distance=("trip_distance", "mean"),
            avg_fare=("total_amount", "mean"),
        )
        .sort_values("day_of_week")
    )


# =============================================================================
# Geographic Analytics (Q5-Q8)
# =============================================================================


def q5_expression_impl(ctx: DataFrameContext) -> Any:
    return _expression_top_zone(ctx, "Q5", "pickup_location_id")


def q5_pandas_impl(ctx: DataFrameContext) -> Any:
    return _pandas_top_zone(ctx, "Q5", "pickup_location_id")


def q6_expression_impl(ctx: DataFrameContext) -> Any:
    return _expression_top_zone(ctx, "Q6", "dropoff_location_id")


def q6_pandas_impl(ctx: DataFrameContext) -> Any:
    return _pandas_top_zone(ctx, "Q6", "dropoff_location_id")


def q7_expression_impl(ctx: DataFrameContext) -> Any:
    trips, col, _ = _expression_window(ctx, "Q7", "2019-01-01", "2019-01-31")
    zones = ctx.get_table("taxi_zones")

    with_pickup = trips.join(
        zones.rename({"zone": "pickup_zone", "borough": "pickup_borough", "service_zone": "pickup_svc"}),
        left_on="pickup_location_id",
        right_on="location_id",
        how="left",
    )
    with_both = with_pickup.join(
        zones.rename({"zone": "dropoff_zone", "borough": "dropoff_borough", "service_zone": "dropoff_svc"}),
        left_on="dropoff_location_id",
        right_on="location_id",
        how="left",
    )
    return (
        with_both.group_by("pickup_location_id", "pickup_zone", "dropoff_location_id", "dropoff_zone")
        .agg(
            col("pickup_location_id").count().alias("trip_count"),
            col("trip_distance").mean().alias("avg_distance"),
            col("total_amount").mean().alias("avg_fare"),
        )
        .sort("trip_count", descending=True)
        .limit(50)
    )


def q7_pandas_impl(ctx: DataFrameContext) -> Any:
    zones = ctx.get_table("taxi_zones")
    filtered = _pandas_window(ctx, "Q7", "2019-01-01", "2019-01-31")

    pz = zones.rename(columns={"zone": "pickup_zone", "borough": "pickup_borough"})
    merged = filtered.merge(
        pz[["location_id", "pickup_zone"]], left_on="pickup_location_id", right_on="location_id", how="left"
    )
    dz = zones.rename(columns={"zone": "dropoff_zone", "borough": "dropoff_borough"})
    merged = merged.merge(
        dz[["location_id", "dropoff_zone"]],
        left_on="dropoff_location_id",
        right_on="location_id",
        how="left",
        suffixes=("", "_dz"),
    )

    return (
        merged.groupby(["pickup_location_id", "pickup_zone", "dropoff_location_id", "dropoff_zone"], as_index=False)
        .agg(
            trip_count=("pickup_location_id", "count"),
            avg_distance=("trip_distance", "mean"),
            avg_fare=("total_amount", "mean"),
        )
        .sort_values("trip_count", ascending=False)
        .head(50)
    )


def q8_expression_impl(ctx: DataFrameContext) -> Any:
    trips, col, _ = _expression_window(ctx, "Q8", "2019-01-01", "2019-03-31")
    zones = ctx.get_table("taxi_zones")

    return (
        trips.join(zones, left_on="pickup_location_id", right_on="location_id", how="left")
        .filter(col("borough").is_not_null())
        .group_by("borough")
        .agg(
            col("borough").count().alias("trip_count"),
            col("total_amount").sum().alias("total_revenue"),
            col("trip_distance").mean().alias("avg_distance"),
            col("tip_amount").mean().alias("avg_tip"),
        )
        .sort("trip_count", descending=True)
    )


def q8_pandas_impl(ctx: DataFrameContext) -> Any:
    zones = ctx.get_table("taxi_zones")
    filtered = _pandas_window(ctx, "Q8", "2019-01-01", "2019-03-31")
    merged = filtered.merge(zones, left_on="pickup_location_id", right_on="location_id", how="left")
    merged = merged[merged["borough"].notna()]
    return (
        merged.groupby(["borough"], as_index=False)
        .agg(
            trip_count=("borough", "count"),
            total_revenue=("total_amount", "sum"),
            avg_distance=("trip_distance", "mean"),
            avg_tip=("tip_amount", "mean"),
        )
        .sort_values("trip_count", ascending=False)
    )


# =============================================================================
# Financial Analytics (Q9-Q12)
# =============================================================================


def q9_expression_impl(ctx: DataFrameContext) -> Any:
    trips, col, lit = _expression_window(
        ctx, "Q9", "2019-01-01", "2019-01-31", lambda col, lit: col("fare_amount") > lit(0)
    )

    return (
        trips.with_columns(
            ctx.when(col("fare_amount") != lit(0))
            .then(col("tip_amount") / col("fare_amount") * lit(100))
            .otherwise(lit(None))
            .alias("tip_pct")
        )
        .group_by("payment_type")
        .agg(
            col("payment_type").count().alias("trip_count"),
            col("total_amount").sum().alias("total_revenue"),
            col("tip_amount").sum().alias("total_tips"),
            col("tip_pct").mean().alias("avg_tip_percentage"),
        )
        .sort("total_revenue", descending=True)
    )


def q9_pandas_impl(ctx: DataFrameContext) -> Any:
    import numpy as np

    filtered = _pandas_window(
        ctx, "Q9", "2019-01-01", "2019-01-31", copy=True, extra=lambda trips: trips["fare_amount"] > 0
    )
    filtered["tip_pct"] = np.where(
        filtered["fare_amount"] != 0, filtered["tip_amount"] / filtered["fare_amount"] * 100, np.nan
    )
    return (
        filtered.groupby(["payment_type"], as_index=False)
        .agg(
            trip_count=("payment_type", "count"),
            total_revenue=("total_amount", "sum"),
            total_tips=("tip_amount", "sum"),
            avg_tip_percentage=("tip_pct", "mean"),
        )
        .sort_values("total_revenue", ascending=False)
    )


def q10_expression_impl(ctx: DataFrameContext) -> Any:
    trips, col, lit = _expression_window(
        ctx,
        "Q10",
        "2019-01-01",
        "2019-01-31",
        lambda col, lit: (col("fare_amount") >= lit(0), col("fare_amount") <= lit(100)),
    )

    return (
        trips.with_columns(((col("fare_amount") / lit(5)).floor() * lit(5)).alias("fare_bucket"))
        .group_by("fare_bucket")
        .agg(
            col("fare_bucket").count().alias("trip_count"),
            col("trip_distance").mean().alias("avg_distance"),
            col("tip_amount").mean().alias("avg_tip"),
        )
        .sort("fare_bucket")
    )


def q10_pandas_impl(ctx: DataFrameContext) -> Any:
    import numpy as np

    filtered = _pandas_window(
        ctx,
        "Q10",
        "2019-01-01",
        "2019-01-31",
        copy=True,
        extra=lambda trips: (trips["fare_amount"] >= 0) & (trips["fare_amount"] <= 100),
    )
    filtered["fare_bucket"] = np.floor(filtered["fare_amount"] / 5) * 5
    return (
        filtered.groupby(["fare_bucket"], as_index=False)
        .agg(
            trip_count=("fare_bucket", "count"), avg_distance=("trip_distance", "mean"), avg_tip=("tip_amount", "mean")
        )
        .sort_values("fare_bucket")
    )


def q11_expression_impl(ctx: DataFrameContext) -> Any:
    trips, col, lit = _expression_window(
        ctx, "Q11", "2019-01-01", "2019-01-31", lambda col, lit: col("payment_type") == lit(1)
    )

    return (
        trips.with_columns(
            col("pickup_datetime").dt.hour().alias("hour"),
            ctx.when(col("fare_amount") > lit(0))
            .then(col("tip_amount") / col("fare_amount") * lit(100))
            .otherwise(lit(None))
            .alias("tip_pct"),
        )
        .group_by("hour")
        .agg(
            col("hour").count().alias("trip_count"),
            col("tip_amount").mean().alias("avg_tip"),
            col("tip_pct").mean().alias("avg_tip_pct"),
        )
        .sort("hour")
    )


def q11_pandas_impl(ctx: DataFrameContext) -> Any:
    import numpy as np

    filtered = _pandas_window(
        ctx, "Q11", "2019-01-01", "2019-01-31", copy=True, extra=lambda trips: trips["payment_type"] == 1
    )
    filtered["hour"] = filtered["pickup_datetime"].dt.hour
    filtered["tip_pct"] = np.where(
        filtered["fare_amount"] > 0, filtered["tip_amount"] / filtered["fare_amount"] * 100, np.nan
    )
    return (
        filtered.groupby(["hour"], as_index=False)
        .agg(trip_count=("hour", "count"), avg_tip=("tip_amount", "mean"), avg_tip_pct=("tip_pct", "mean"))
        .sort_values("hour")
    )


def q12_expression_impl(ctx: DataFrameContext) -> Any:
    trips, col, _ = _expression_window(ctx, "Q12", "2019-01-01", "2019-12-31")

    return (
        trips.with_columns(col("pickup_datetime").dt.truncate("1mo").alias("month"))
        .group_by("month")
        .agg(
            col("extra").sum().alias("extra_revenue"),
            col("mta_tax").sum().alias("mta_tax_revenue"),
            col("improvement_surcharge").sum().alias("improvement_revenue"),
            col("congestion_surcharge").sum().alias("congestion_revenue"),
            col("tolls_amount").sum().alias("tolls_revenue"),
        )
        .sort("month")
    )


def q12_pandas_impl(ctx: DataFrameContext) -> Any:
    filtered = _pandas_window(ctx, "Q12", "2019-01-01", "2019-12-31", copy=True)
    filtered["month"] = filtered["pickup_datetime"].dt.to_period("M").dt.to_timestamp()
    return (
        filtered.groupby(["month"], as_index=False)
        .agg(
            extra_revenue=("extra", "sum"),
            mta_tax_revenue=("mta_tax", "sum"),
            improvement_revenue=("improvement_surcharge", "sum"),
            congestion_revenue=("congestion_surcharge", "sum"),
            tolls_revenue=("tolls_amount", "sum"),
        )
        .sort_values("month")
    )


# =============================================================================
# Trip Characteristics (Q13-Q15)
# =============================================================================


def q13_expression_impl(ctx: DataFrameContext) -> Any:
    trips, col, _ = _expression_window(
        ctx,
        "Q13",
        "2019-01-01",
        "2019-01-31",
        lambda col, lit: (col("trip_distance") >= lit(0), col("trip_distance") <= lit(30)),
    )

    return (
        trips.with_columns(col("trip_distance").floor().alias("distance_miles"))
        .group_by("distance_miles")
        .agg(
            col("distance_miles").count().alias("trip_count"),
            col("total_amount").mean().alias("avg_fare"),
        )
        .sort("distance_miles")
    )


def q13_pandas_impl(ctx: DataFrameContext) -> Any:
    import numpy as np

    filtered = _pandas_window(
        ctx,
        "Q13",
        "2019-01-01",
        "2019-01-31",
        copy=True,
        extra=lambda trips: (trips["trip_distance"] >= 0) & (trips["trip_distance"] <= 30),
    )
    filtered["distance_miles"] = np.floor(filtered["trip_distance"])
    return (
        filtered.groupby(["distance_miles"], as_index=False)
        .agg(trip_count=("distance_miles", "count"), avg_fare=("total_amount", "mean"))
        .sort_values("distance_miles")
    )


def q14_expression_impl(ctx: DataFrameContext) -> Any:
    trips, col, lit = _expression_window(
        ctx,
        "Q14",
        "2019-01-01",
        "2019-01-31",
        lambda col, lit: (col("passenger_count") >= lit(1), col("passenger_count") <= lit(6)),
    )

    return (
        trips.with_columns(
            ctx.when(col("trip_distance") != lit(0))
            .then(col("total_amount") / col("trip_distance"))
            .otherwise(lit(None))
            .alias("fare_per_mile")
        )
        .group_by("passenger_count")
        .agg(
            col("passenger_count").count().alias("trip_count"),
            col("trip_distance").mean().alias("avg_distance"),
            col("total_amount").mean().alias("avg_fare"),
            col("fare_per_mile").mean().alias("avg_fare_per_mile"),
        )
        .sort("passenger_count")
    )


def q14_pandas_impl(ctx: DataFrameContext) -> Any:
    import numpy as np

    filtered = _pandas_window(
        ctx,
        "Q14",
        "2019-01-01",
        "2019-01-31",
        copy=True,
        extra=lambda trips: (trips["passenger_count"] >= 1) & (trips["passenger_count"] <= 6),
    )
    filtered["fare_per_mile"] = np.where(
        filtered["trip_distance"] != 0, filtered["total_amount"] / filtered["trip_distance"], np.nan
    )
    return (
        filtered.groupby(["passenger_count"], as_index=False)
        .agg(
            trip_count=("passenger_count", "count"),
            avg_distance=("trip_distance", "mean"),
            avg_fare=("total_amount", "mean"),
            avg_fare_per_mile=("fare_per_mile", "mean"),
        )
        .sort_values("passenger_count")
    )


def q15_expression_impl(ctx: DataFrameContext) -> Any:
    trips, col, lit = _expression_window(
        ctx, "Q15", "2019-01-01", "2019-01-31", lambda col, _lit: col("dropoff_datetime") > col("pickup_datetime")
    )

    return (
        trips.with_columns(
            ((col("dropoff_datetime") - col("pickup_datetime")).dt.total_seconds()).alias("duration_sec")
        )
        .filter((col("duration_sec") >= lit(60)) & (col("duration_sec") <= lit(7200)))
        .with_columns(((col("duration_sec") / lit(60) / lit(5)).floor() * lit(5)).alias("duration_bucket_min"))
        .group_by("duration_bucket_min")
        .agg(
            col("duration_bucket_min").count().alias("trip_count"),
            col("trip_distance").mean().alias("avg_distance"),
            col("total_amount").mean().alias("avg_fare"),
        )
        .sort("duration_bucket_min")
    )


def q15_pandas_impl(ctx: DataFrameContext) -> Any:
    import numpy as np

    filtered = _pandas_window(
        ctx,
        "Q15",
        "2019-01-01",
        "2019-01-31",
        copy=True,
        extra=lambda trips: trips["dropoff_datetime"] > trips["pickup_datetime"],
    )
    filtered["duration_sec"] = (filtered["dropoff_datetime"] - filtered["pickup_datetime"]).dt.total_seconds()
    filtered = filtered[(filtered["duration_sec"] >= 60) & (filtered["duration_sec"] <= 7200)]
    filtered["duration_bucket_min"] = np.floor(filtered["duration_sec"] / 60 / 5) * 5
    return (
        filtered.groupby(["duration_bucket_min"], as_index=False)
        .agg(
            trip_count=("duration_bucket_min", "count"),
            avg_distance=("trip_distance", "mean"),
            avg_fare=("total_amount", "mean"),
        )
        .sort_values("duration_bucket_min")
    )


# =============================================================================
# Rate Code Analysis (Q16-Q17)
# =============================================================================


def q16_expression_impl(ctx: DataFrameContext) -> Any:
    return _expression_trip_summary(ctx, "Q16", "2019-03-31", "rate_code_id", tip=False)


def q16_pandas_impl(ctx: DataFrameContext) -> Any:
    return _pandas_trip_summary(ctx, "Q16", "2019-03-31", "rate_code_id", tip=False)


def q17_expression_impl(ctx: DataFrameContext) -> Any:
    trips, col, _ = _expression_window(
        ctx, "Q17", "2019-01-01", "2019-03-31", lambda col, _lit: col("rate_code_id").is_in([2, 3])
    )
    zones = ctx.get_table("taxi_zones")

    return (
        trips.join(zones, left_on="pickup_location_id", right_on="location_id", how="left")
        .group_by("rate_code_id", "zone")
        .agg(
            col("rate_code_id").count().alias("trip_count"),
            col("trip_distance").mean().alias("avg_distance"),
            col("total_amount").mean().alias("avg_fare"),
            col("tip_amount").mean().alias("avg_tip"),
        )
        .sort("trip_count", descending=True)
        .limit(20)
    )


def q17_pandas_impl(ctx: DataFrameContext) -> Any:
    zones = ctx.get_table("taxi_zones")
    filtered = _pandas_window(
        ctx, "Q17", "2019-01-01", "2019-03-31", extra=lambda trips: trips["rate_code_id"].isin([2, 3])
    )
    merged = filtered.merge(zones, left_on="pickup_location_id", right_on="location_id", how="left")
    return (
        merged.groupby(["rate_code_id", "zone"], as_index=False)
        .agg(
            trip_count=("rate_code_id", "count"),
            avg_distance=("trip_distance", "mean"),
            avg_fare=("total_amount", "mean"),
            avg_tip=("tip_amount", "mean"),
        )
        .sort_values("trip_count", ascending=False)
        .head(20)
    )


# =============================================================================
# Vendor Analysis (Q18)
# =============================================================================


def q18_expression_impl(ctx: DataFrameContext) -> Any:
    return _expression_trip_summary(ctx, "Q18", "2019-01-31", "vendor_id", tip=True)


def q18_pandas_impl(ctx: DataFrameContext) -> Any:
    return _pandas_trip_summary(ctx, "Q18", "2019-01-31", "vendor_id", tip=True)


# =============================================================================
# Complex Analytics (Q19-Q22)
# =============================================================================


def q19_expression_impl(ctx: DataFrameContext) -> Any:
    trips, col, _ = _expression_window(ctx, "Q19", "2019-01-01", "2019-01-07")

    return (
        trips.with_columns(col("pickup_datetime").dt.hour().alias("hour"))
        .group_by("hour", "pickup_location_id")
        .agg(col("hour").count().alias("trip_count"))
        .sort(["hour", "trip_count"], descending=[False, True])
    )


def q19_pandas_impl(ctx: DataFrameContext) -> Any:
    filtered = _pandas_window(ctx, "Q19", "2019-01-01", "2019-01-07", copy=True)
    filtered["hour"] = filtered["pickup_datetime"].dt.hour
    return (
        filtered.groupby(["hour", "pickup_location_id"], as_index=False)
        .agg(trip_count=("hour", "count"))
        .sort_values(["hour", "trip_count"], ascending=[True, False])
    )


def q20_expression_impl(ctx: DataFrameContext) -> Any:
    trips, col, lit = _expression_window(ctx, "Q20", "2019-01-01", "2019-01-31")

    return (
        trips.with_columns(
            col("pickup_datetime").dt.hour().alias("hour"),
            ctx.when(col("pickup_datetime").dt.weekday().is_in([5, 6]))
            .then(lit("weekend"))
            .otherwise(lit("weekday"))
            .alias("day_type"),
        )
        .group_by("day_type", "hour")
        .agg(
            col("hour").count().alias("trip_count"),
            col("trip_distance").mean().alias("avg_distance"),
            col("total_amount").mean().alias("avg_fare"),
        )
        .sort(["day_type", "hour"])
    )


def q20_pandas_impl(ctx: DataFrameContext) -> Any:
    import numpy as np

    filtered = _pandas_window(ctx, "Q20", "2019-01-01", "2019-01-31", copy=True)
    filtered["hour"] = filtered["pickup_datetime"].dt.hour
    filtered["day_type"] = np.where(filtered["pickup_datetime"].dt.dayofweek.isin([5, 6]), "weekend", "weekday")
    return (
        filtered.groupby(["day_type", "hour"], as_index=False)
        .agg(trip_count=("hour", "count"), avg_distance=("trip_distance", "mean"), avg_fare=("total_amount", "mean"))
        .sort_values(["day_type", "hour"])
    )


def q21_expression_impl(ctx: DataFrameContext) -> Any:
    filtered, col, lit = _expression_window(
        ctx, "Q21", "2019-01-01", "2019-01-31", lambda col, _lit: col("dropoff_datetime") > col("pickup_datetime")
    )
    with_cols = filtered.with_columns(
        col("pickup_datetime").dt.hour().alias("hour"),
        ((col("dropoff_datetime") - col("pickup_datetime")).dt.total_seconds() / lit(60)).alias("duration_min"),
    )
    with_period = with_cols.with_columns(
        ctx.when((col("hour") >= lit(7)) & (col("hour") <= lit(9)))
        .then(lit("morning_rush"))
        .otherwise(
            ctx.when((col("hour") >= lit(17)) & (col("hour") <= lit(19)))
            .then(lit("evening_rush"))
            .otherwise(lit("off_peak"))
        )
        .alias("period")
    )
    return (
        with_period.group_by("period")
        .agg(
            col("period").count().alias("trip_count"),
            col("trip_distance").mean().alias("avg_distance"),
            col("total_amount").mean().alias("avg_fare"),
            col("duration_min").mean().alias("avg_duration_min"),
        )
        .sort("trip_count", descending=True)
    )


def q21_pandas_impl(ctx: DataFrameContext) -> Any:
    import numpy as np

    filtered = _pandas_window(
        ctx,
        "Q21",
        "2019-01-01",
        "2019-01-31",
        copy=True,
        extra=lambda trips: trips["dropoff_datetime"] > trips["pickup_datetime"],
    )
    filtered["hour"] = filtered["pickup_datetime"].dt.hour
    filtered["duration_min"] = (filtered["dropoff_datetime"] - filtered["pickup_datetime"]).dt.total_seconds() / 60
    conditions = [
        (filtered["hour"] >= 7) & (filtered["hour"] <= 9),
        (filtered["hour"] >= 17) & (filtered["hour"] <= 19),
    ]
    filtered["period"] = np.select(conditions, ["morning_rush", "evening_rush"], default="off_peak")
    return (
        filtered.groupby(["period"], as_index=False)
        .agg(
            trip_count=("period", "count"),
            avg_distance=("trip_distance", "mean"),
            avg_fare=("total_amount", "mean"),
            avg_duration_min=("duration_min", "mean"),
        )
        .sort_values("trip_count", ascending=False)
    )


def q22_expression_impl(ctx: DataFrameContext) -> Any:
    trips, col, _ = _expression_window(ctx, "Q22", "2019-01-01", "2019-12-31")

    return (
        trips.with_columns(
            col("pickup_datetime").dt.year().alias("year"),
            col("pickup_datetime").dt.month().alias("month"),
        )
        .group_by("year", "month")
        .agg(
            col("year").count().alias("trip_count"),
            col("total_amount").sum().alias("total_revenue"),
            col("total_amount").mean().alias("avg_fare"),
        )
        .sort(["year", "month"])
    )


def q22_pandas_impl(ctx: DataFrameContext) -> Any:
    filtered = _pandas_window(ctx, "Q22", "2019-01-01", "2019-12-31", copy=True)
    filtered["year"] = filtered["pickup_datetime"].dt.year
    filtered["month"] = filtered["pickup_datetime"].dt.month
    return (
        filtered.groupby(["year", "month"], as_index=False)
        .agg(trip_count=("year", "count"), total_revenue=("total_amount", "sum"), avg_fare=("total_amount", "mean"))
        .sort_values(["year", "month"])
    )


# =============================================================================
# Point Queries (Q23-Q24) and Baseline (Q25)
# =============================================================================


def q23_expression_impl(ctx: DataFrameContext) -> Any:
    trips, col, _ = _expression_window(ctx, "Q23", "2019-06-15", "2019-06-16")

    return trips.select(
        col("trip_id").count().alias("trip_count"),
        col("total_amount").sum().alias("total_revenue"),
        col("trip_distance").mean().alias("avg_distance"),
        col("total_amount").mean().alias("avg_fare"),
        col("tip_amount").mean().alias("avg_tip"),
        col("pickup_datetime").min().alias("first_trip"),
        col("pickup_datetime").max().alias("last_trip"),
    )


def q23_pandas_impl(ctx: DataFrameContext) -> Any:
    import pandas as pd

    filtered = _pandas_window(ctx, "Q23", "2019-06-15", "2019-06-16")
    return pd.DataFrame(
        {
            "trip_count": [len(filtered)],
            "total_revenue": [filtered["total_amount"].sum()],
            "avg_distance": [filtered["trip_distance"].mean()],
            "avg_fare": [filtered["total_amount"].mean()],
            "avg_tip": [filtered["tip_amount"].mean()],
            "first_trip": [filtered["pickup_datetime"].min()],
            "last_trip": [filtered["pickup_datetime"].max()],
        }
    )


def q24_expression_impl(ctx: DataFrameContext) -> Any:
    params = get_parameters("Q24")
    zone_id = params.get("zone_id", 132)
    trips, col, _ = _expression_window(
        ctx, "Q24", "2019-01-01", "2019-01-31", lambda col, lit: col("pickup_location_id") == lit(zone_id)
    )
    zones = ctx.get_table("taxi_zones")

    return (
        trips.join(zones, left_on="pickup_location_id", right_on="location_id")
        .group_by("zone", "borough")
        .agg(
            col("zone").count().alias("pickup_count"),
            col("trip_distance").mean().alias("avg_distance"),
            col("total_amount").mean().alias("avg_fare"),
            col("total_amount").sum().alias("total_revenue"),
        )
    )


def q24_pandas_impl(ctx: DataFrameContext) -> Any:
    params = get_parameters("Q24")
    zone_id = params.get("zone_id", 132)
    zones = ctx.get_table("taxi_zones")
    filtered = _pandas_window(
        ctx, "Q24", "2019-01-01", "2019-01-31", extra=lambda trips: trips["pickup_location_id"] == zone_id
    )
    merged = filtered.merge(zones, left_on="pickup_location_id", right_on="location_id")
    return merged.groupby(["zone", "borough"], as_index=False).agg(
        pickup_count=("zone", "count"),
        avg_distance=("trip_distance", "mean"),
        avg_fare=("total_amount", "mean"),
        total_revenue=("total_amount", "sum"),
    )


def q25_expression_impl(ctx: DataFrameContext) -> Any:
    trips = ctx.get_table("trips")
    col = ctx.col
    return trips.select(col("trip_id").count().alias("total_trips"))


def q25_pandas_impl(ctx: DataFrameContext) -> Any:
    import pandas as pd

    trips = ctx.get_table("trips")
    return pd.DataFrame({"total_trips": [len(trips)]})


# =============================================================================
# Query Registration
# =============================================================================

_CATEGORY_CODES = {
    "AG": QueryCategory.AGGREGATE,
    "AN": QueryCategory.ANALYTICAL,
    "FI": QueryCategory.FILTER,
    "GB": QueryCategory.GROUP_BY,
    "JO": QueryCategory.JOIN,
    "MJ": QueryCategory.MULTI_JOIN,
    "SC": QueryCategory.SCAN,
    "SO": QueryCategory.SORT,
}

_QUERY_METADATA = """Q1|Trips per Hour|Hourly trip count distribution using EXTRACT(HOUR)|FI,GB,AG,AN
Q2|Trips per Day|Daily trip count using DATE_TRUNC('day')|FI,GB,AG,AN
Q3|Trips per Month|Monthly trip count and total revenue using DATE_TRUNC('month')|FI,GB,AG,AN
Q4|Trips by Day of Week|Day-of-week distribution with avg distance and fare|FI,GB,AG,AN
Q5|Top Pickup Zones|Top 20 pickup zones by trip count with LEFT JOIN to taxi_zones|FI,JO,GB,SO
Q6|Top Dropoff Zones|Top 20 dropoff zones by trip count with LEFT JOIN to taxi_zones|FI,JO,GB,SO
Q7|Top Routes|Top 50 routes (pickup->dropoff) with double LEFT JOIN to taxi_zones|FI,MJ,GB,SO
Q8|Borough Summary|Borough-level trip count, revenue, distance, and tip averages|FI,JO,GB,SO
Q9|Revenue by Payment Type|Revenue and tip analysis by payment type with NULLIF protection|FI,GB,AG,AN
Q10|Fare Distribution|Fare distribution in $5 buckets using FLOOR bucketing|FI,GB,AG,AN
Q11|Tip Analysis|Tip analysis by hour for credit card payments with conditional avg|FI,GB,AG,AN
Q12|Surcharge Revenue|Monthly surcharge revenue breakdown (extra, MTA tax, improvement, congestion, tolls)|FI,GB,AG,AN
Q13|Distance Distribution|Trip distance distribution in 1-mile buckets|FI,GB,AG
Q14|Passenger Count Analysis|Metrics by passenger count (1-6) with NULLIF fare-per-mile|FI,GB,AG,AN
Q15|Trip Duration Analysis|Duration distribution in 5-min buckets using timestamp arithmetic|FI,GB,AG,AN
Q16|Rate Code Summary|Trip metrics by rate code (Standard, JFK, Newark, etc.)|FI,GB,AG
Q17|Airport Trips|Airport trip analysis (JFK/Newark) with zone join|FI,JO,GB,SO
Q18|Vendor Comparison|Vendor-level trip metrics comparison|FI,GB,AG
Q19|Hourly Zone Heatmap|2D grouping by hour and pickup zone for heatmap visualization|FI,GB,SO,AN
Q20|Weekday/Weekend Comparison|Weekday vs weekend metrics by hour using CASE WHEN on day-of-week|FI,GB,SO,AN
Q21|Rush Hour Analysis|Morning rush, evening rush, and off-peak period comparison|FI,GB,AG,AN
Q22|Monthly Year-over-Year|Year and month grouping for YoY comparison over 2-year window|FI,GB,AG,AN
Q23|Single-Day Summary|Scalar aggregation for a single day (no GROUP BY)|FI,AG
Q24|Zone Detail|Detailed metrics for a specific zone with INNER JOIN|FI,JO,GB,AG
Q25|Full Scan Count|COUNT(*) baseline full table scan|SC,AG
"""


def _impl_for(query_id: str, family: str) -> Any:
    return globals()[f"q{query_id[1:]}_{family}_impl"]


def _register_all_queries() -> None:
    for query_id, query_name, description, category_codes in reader(_QUERY_METADATA.splitlines(), delimiter="|"):
        register_query(
            DataFrameQuery(
                query_id=query_id,
                query_name=query_name,
                description=description,
                categories=[_CATEGORY_CODES[code] for code in category_codes.split(",")],
                expression_impl=_impl_for(query_id, "expression"),
                pandas_impl=_impl_for(query_id, "pandas"),
            )
        )


_register_all_queries()
