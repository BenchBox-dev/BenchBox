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

from typing import Any

from benchbox.core.dataframe.context import DataFrameContext
from benchbox.core.dataframe.query import DataFrameQuery, QueryCategory

from .parameters import get_parameters
from .registry import register_query

# =============================================================================
# Temporal Aggregations (Q1-Q4)
# =============================================================================


def q1_expression_impl(ctx: DataFrameContext) -> Any:
    """Q1: Trips per hour - EXTRACT(HOUR) grouping."""
    params = get_parameters("Q1")
    start_date = params.get("start_date", "2019-01-01")
    end_date = params.get("end_date", "2019-01-31")

    trips = ctx.get_table("trips")
    col = ctx.col
    lit = ctx.lit

    return (
        trips.filter((col("pickup_datetime") >= lit(start_date)) & (col("pickup_datetime") < lit(end_date)))
        .with_columns(col("pickup_datetime").dt.hour().alias("hour"))
        .group_by("hour")
        .agg(col("hour").count().alias("trip_count"))
        .sort("hour")
    )


def q1_pandas_impl(ctx: DataFrameContext) -> Any:
    """Q1: Trips per hour - EXTRACT(HOUR) grouping."""
    params = get_parameters("Q1")
    start_date = params.get("start_date", "2019-01-01")
    end_date = params.get("end_date", "2019-01-31")

    trips = ctx.get_table("trips")
    filtered = trips[(trips["pickup_datetime"] >= start_date) & (trips["pickup_datetime"] < end_date)].copy()
    filtered["hour"] = filtered["pickup_datetime"].dt.hour
    return filtered.groupby(["hour"], as_index=False).agg(trip_count=("hour", "count")).sort_values("hour")


def q2_expression_impl(ctx: DataFrameContext) -> Any:
    """Q2: Trips per day - DATE_TRUNC('day') grouping."""
    params = get_parameters("Q2")
    start_date = params.get("start_date", "2019-01-01")
    end_date = params.get("end_date", "2019-12-31")

    trips = ctx.get_table("trips")
    col = ctx.col
    lit = ctx.lit

    return (
        trips.filter((col("pickup_datetime") >= lit(start_date)) & (col("pickup_datetime") < lit(end_date)))
        .with_columns(col("pickup_datetime").dt.truncate("1d").alias("day"))
        .group_by("day")
        .agg(col("day").count().alias("trip_count"))
        .sort("day")
    )


def q2_pandas_impl(ctx: DataFrameContext) -> Any:
    """Q2: Trips per day - DATE_TRUNC('day') grouping."""
    params = get_parameters("Q2")
    start_date = params.get("start_date", "2019-01-01")
    end_date = params.get("end_date", "2019-12-31")

    trips = ctx.get_table("trips")
    filtered = trips[(trips["pickup_datetime"] >= start_date) & (trips["pickup_datetime"] < end_date)].copy()
    filtered["day"] = filtered["pickup_datetime"].dt.floor("D")
    return filtered.groupby(["day"], as_index=False).agg(trip_count=("day", "count")).sort_values("day")


def q3_expression_impl(ctx: DataFrameContext) -> Any:
    """Q3: Trips and revenue per month."""
    params = get_parameters("Q3")
    start_date = params.get("start_date", "2019-01-01")
    end_date = params.get("end_date", "2019-12-31")

    trips = ctx.get_table("trips")
    col = ctx.col
    lit = ctx.lit

    return (
        trips.filter((col("pickup_datetime") >= lit(start_date)) & (col("pickup_datetime") < lit(end_date)))
        .with_columns(col("pickup_datetime").dt.truncate("1mo").alias("month"))
        .group_by("month")
        .agg(
            col("month").count().alias("trip_count"),
            col("total_amount").sum().alias("total_revenue"),
        )
        .sort("month")
    )


def q3_pandas_impl(ctx: DataFrameContext) -> Any:
    """Q3: Trips and revenue per month."""
    params = get_parameters("Q3")
    start_date = params.get("start_date", "2019-01-01")
    end_date = params.get("end_date", "2019-12-31")

    trips = ctx.get_table("trips")
    filtered = trips[(trips["pickup_datetime"] >= start_date) & (trips["pickup_datetime"] < end_date)].copy()
    filtered["month"] = filtered["pickup_datetime"].dt.to_period("M").dt.to_timestamp()
    return (
        filtered.groupby(["month"], as_index=False)
        .agg(trip_count=("month", "count"), total_revenue=("total_amount", "sum"))
        .sort_values("month")
    )


def q4_expression_impl(ctx: DataFrameContext) -> Any:
    """Q4: Trips by day of week with avg distance and fare."""
    params = get_parameters("Q4")
    start_date = params.get("start_date", "2019-01-01")
    end_date = params.get("end_date", "2019-03-31")

    trips = ctx.get_table("trips")
    col = ctx.col
    lit = ctx.lit

    return (
        trips.filter((col("pickup_datetime") >= lit(start_date)) & (col("pickup_datetime") < lit(end_date)))
        .with_columns(col("pickup_datetime").dt.weekday().alias("day_of_week"))
        .group_by("day_of_week")
        .agg(
            col("day_of_week").count().alias("trip_count"),
            col("trip_distance").mean().alias("avg_distance"),
            col("total_amount").mean().alias("avg_fare"),
        )
        .sort("day_of_week")
    )


def q4_pandas_impl(ctx: DataFrameContext) -> Any:
    """Q4: Trips by day of week with avg distance and fare."""
    params = get_parameters("Q4")
    start_date = params.get("start_date", "2019-01-01")
    end_date = params.get("end_date", "2019-03-31")

    trips = ctx.get_table("trips")
    filtered = trips[(trips["pickup_datetime"] >= start_date) & (trips["pickup_datetime"] < end_date)].copy()
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
    """Q5: Top pickup zones - LEFT JOIN to taxi_zones."""
    params = get_parameters("Q5")
    start_date = params.get("start_date", "2019-01-01")
    end_date = params.get("end_date", "2019-01-31")

    trips = ctx.get_table("trips")
    zones = ctx.get_table("taxi_zones")
    col = ctx.col
    lit = ctx.lit

    return (
        trips.filter((col("pickup_datetime") >= lit(start_date)) & (col("pickup_datetime") < lit(end_date)))
        .join(zones, left_on="pickup_location_id", right_on="location_id", how="left")
        .group_by("pickup_location_id", "zone", "borough")
        .agg(col("pickup_location_id").count().alias("trip_count"))
        .sort("trip_count", descending=True)
        .limit(20)
    )


def q5_pandas_impl(ctx: DataFrameContext) -> Any:
    """Q5: Top pickup zones - LEFT JOIN to taxi_zones."""
    params = get_parameters("Q5")
    start_date = params.get("start_date", "2019-01-01")
    end_date = params.get("end_date", "2019-01-31")

    trips = ctx.get_table("trips")
    zones = ctx.get_table("taxi_zones")
    filtered = trips[(trips["pickup_datetime"] >= start_date) & (trips["pickup_datetime"] < end_date)]
    merged = filtered.merge(zones, left_on="pickup_location_id", right_on="location_id", how="left")
    return (
        merged.groupby(["pickup_location_id", "zone", "borough"], as_index=False)
        .agg(trip_count=("pickup_location_id", "count"))
        .sort_values("trip_count", ascending=False)
        .head(20)
    )


def q6_expression_impl(ctx: DataFrameContext) -> Any:
    """Q6: Top dropoff zones."""
    params = get_parameters("Q6")
    start_date = params.get("start_date", "2019-01-01")
    end_date = params.get("end_date", "2019-01-31")

    trips = ctx.get_table("trips")
    zones = ctx.get_table("taxi_zones")
    col = ctx.col
    lit = ctx.lit

    return (
        trips.filter((col("pickup_datetime") >= lit(start_date)) & (col("pickup_datetime") < lit(end_date)))
        .join(zones, left_on="dropoff_location_id", right_on="location_id", how="left")
        .group_by("dropoff_location_id", "zone", "borough")
        .agg(col("dropoff_location_id").count().alias("trip_count"))
        .sort("trip_count", descending=True)
        .limit(20)
    )


def q6_pandas_impl(ctx: DataFrameContext) -> Any:
    """Q6: Top dropoff zones."""
    params = get_parameters("Q6")
    start_date = params.get("start_date", "2019-01-01")
    end_date = params.get("end_date", "2019-01-31")

    trips = ctx.get_table("trips")
    zones = ctx.get_table("taxi_zones")
    filtered = trips[(trips["pickup_datetime"] >= start_date) & (trips["pickup_datetime"] < end_date)]
    merged = filtered.merge(zones, left_on="dropoff_location_id", right_on="location_id", how="left")
    return (
        merged.groupby(["dropoff_location_id", "zone", "borough"], as_index=False)
        .agg(trip_count=("dropoff_location_id", "count"))
        .sort_values("trip_count", ascending=False)
        .head(20)
    )


def q7_expression_impl(ctx: DataFrameContext) -> Any:
    """Q7: Top routes - double LEFT JOIN to taxi_zones for pickup and dropoff."""
    params = get_parameters("Q7")
    start_date = params.get("start_date", "2019-01-01")
    end_date = params.get("end_date", "2019-01-31")

    trips = ctx.get_table("trips")
    zones = ctx.get_table("taxi_zones")
    col = ctx.col
    lit = ctx.lit

    # Join pickup zones
    with_pickup = trips.filter(
        (col("pickup_datetime") >= lit(start_date)) & (col("pickup_datetime") < lit(end_date))
    ).join(
        zones.rename({"zone": "pickup_zone", "borough": "pickup_borough", "service_zone": "pickup_svc"}),
        left_on="pickup_location_id",
        right_on="location_id",
        how="left",
    )
    # Join dropoff zones
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
    """Q7: Top routes - double LEFT JOIN to taxi_zones."""
    params = get_parameters("Q7")
    start_date = params.get("start_date", "2019-01-01")
    end_date = params.get("end_date", "2019-01-31")

    trips = ctx.get_table("trips")
    zones = ctx.get_table("taxi_zones")
    filtered = trips[(trips["pickup_datetime"] >= start_date) & (trips["pickup_datetime"] < end_date)]

    # Join pickup zones with suffix
    pz = zones.rename(columns={"zone": "pickup_zone", "borough": "pickup_borough"})
    merged = filtered.merge(
        pz[["location_id", "pickup_zone"]], left_on="pickup_location_id", right_on="location_id", how="left"
    )
    # Join dropoff zones with suffix
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
    """Q8: Borough summary with LEFT JOIN."""
    params = get_parameters("Q8")
    start_date = params.get("start_date", "2019-01-01")
    end_date = params.get("end_date", "2019-03-31")

    trips = ctx.get_table("trips")
    zones = ctx.get_table("taxi_zones")
    col = ctx.col
    lit = ctx.lit

    return (
        trips.filter((col("pickup_datetime") >= lit(start_date)) & (col("pickup_datetime") < lit(end_date)))
        .join(zones, left_on="pickup_location_id", right_on="location_id", how="left")
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
    """Q8: Borough summary with LEFT JOIN."""
    params = get_parameters("Q8")
    start_date = params.get("start_date", "2019-01-01")
    end_date = params.get("end_date", "2019-03-31")

    trips = ctx.get_table("trips")
    zones = ctx.get_table("taxi_zones")
    filtered = trips[(trips["pickup_datetime"] >= start_date) & (trips["pickup_datetime"] < end_date)]
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
    """Q9: Revenue by payment type with tip percentage using NULLIF."""
    params = get_parameters("Q9")
    start_date = params.get("start_date", "2019-01-01")
    end_date = params.get("end_date", "2019-01-31")

    trips = ctx.get_table("trips")
    col = ctx.col
    lit = ctx.lit

    # NULLIF(fare_amount, 0) -> when fare_amount != 0 then fare_amount else null
    return (
        trips.filter(
            (col("pickup_datetime") >= lit(start_date))
            & (col("pickup_datetime") < lit(end_date))
            & (col("fare_amount") > lit(0))
        )
        .with_columns(
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
    """Q9: Revenue by payment type with tip percentage."""
    import numpy as np

    params = get_parameters("Q9")
    start_date = params.get("start_date", "2019-01-01")
    end_date = params.get("end_date", "2019-01-31")

    trips = ctx.get_table("trips")
    filtered = trips[
        (trips["pickup_datetime"] >= start_date) & (trips["pickup_datetime"] < end_date) & (trips["fare_amount"] > 0)
    ].copy()
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
    """Q10: Fare distribution in $5 buckets."""
    params = get_parameters("Q10")
    start_date = params.get("start_date", "2019-01-01")
    end_date = params.get("end_date", "2019-01-31")

    trips = ctx.get_table("trips")
    col = ctx.col
    lit = ctx.lit

    return (
        trips.filter(
            (col("pickup_datetime") >= lit(start_date))
            & (col("pickup_datetime") < lit(end_date))
            & (col("fare_amount") >= lit(0))
            & (col("fare_amount") <= lit(100))
        )
        .with_columns(((col("fare_amount") / lit(5)).floor() * lit(5)).alias("fare_bucket"))
        .group_by("fare_bucket")
        .agg(
            col("fare_bucket").count().alias("trip_count"),
            col("trip_distance").mean().alias("avg_distance"),
            col("tip_amount").mean().alias("avg_tip"),
        )
        .sort("fare_bucket")
    )


def q10_pandas_impl(ctx: DataFrameContext) -> Any:
    """Q10: Fare distribution in $5 buckets."""
    import numpy as np

    params = get_parameters("Q10")
    start_date = params.get("start_date", "2019-01-01")
    end_date = params.get("end_date", "2019-01-31")

    trips = ctx.get_table("trips")
    filtered = trips[
        (trips["pickup_datetime"] >= start_date)
        & (trips["pickup_datetime"] < end_date)
        & (trips["fare_amount"] >= 0)
        & (trips["fare_amount"] <= 100)
    ].copy()
    filtered["fare_bucket"] = np.floor(filtered["fare_amount"] / 5) * 5
    return (
        filtered.groupby(["fare_bucket"], as_index=False)
        .agg(
            trip_count=("fare_bucket", "count"), avg_distance=("trip_distance", "mean"), avg_tip=("tip_amount", "mean")
        )
        .sort_values("fare_bucket")
    )


def q11_expression_impl(ctx: DataFrameContext) -> Any:
    """Q11: Tip analysis by hour for credit card payments."""
    params = get_parameters("Q11")
    start_date = params.get("start_date", "2019-01-01")
    end_date = params.get("end_date", "2019-01-31")

    trips = ctx.get_table("trips")
    col = ctx.col
    lit = ctx.lit

    return (
        trips.filter(
            (col("pickup_datetime") >= lit(start_date))
            & (col("pickup_datetime") < lit(end_date))
            & (col("payment_type") == lit(1))
        )
        .with_columns(
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
    """Q11: Tip analysis by hour for credit card payments."""
    import numpy as np

    params = get_parameters("Q11")
    start_date = params.get("start_date", "2019-01-01")
    end_date = params.get("end_date", "2019-01-31")

    trips = ctx.get_table("trips")
    filtered = trips[
        (trips["pickup_datetime"] >= start_date) & (trips["pickup_datetime"] < end_date) & (trips["payment_type"] == 1)
    ].copy()
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
    """Q12: Surcharge revenue by month."""
    params = get_parameters("Q12")
    start_date = params.get("start_date", "2019-01-01")
    end_date = params.get("end_date", "2019-12-31")

    trips = ctx.get_table("trips")
    col = ctx.col
    lit = ctx.lit

    return (
        trips.filter((col("pickup_datetime") >= lit(start_date)) & (col("pickup_datetime") < lit(end_date)))
        .with_columns(col("pickup_datetime").dt.truncate("1mo").alias("month"))
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
    """Q12: Surcharge revenue by month."""
    params = get_parameters("Q12")
    start_date = params.get("start_date", "2019-01-01")
    end_date = params.get("end_date", "2019-12-31")

    trips = ctx.get_table("trips")
    filtered = trips[(trips["pickup_datetime"] >= start_date) & (trips["pickup_datetime"] < end_date)].copy()
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
    """Q13: Distance distribution in 1-mile buckets."""
    params = get_parameters("Q13")
    start_date = params.get("start_date", "2019-01-01")
    end_date = params.get("end_date", "2019-01-31")

    trips = ctx.get_table("trips")
    col = ctx.col
    lit = ctx.lit

    return (
        trips.filter(
            (col("pickup_datetime") >= lit(start_date))
            & (col("pickup_datetime") < lit(end_date))
            & (col("trip_distance") >= lit(0))
            & (col("trip_distance") <= lit(30))
        )
        .with_columns(col("trip_distance").floor().alias("distance_miles"))
        .group_by("distance_miles")
        .agg(
            col("distance_miles").count().alias("trip_count"),
            col("total_amount").mean().alias("avg_fare"),
        )
        .sort("distance_miles")
    )


def q13_pandas_impl(ctx: DataFrameContext) -> Any:
    """Q13: Distance distribution in 1-mile buckets."""
    import numpy as np

    params = get_parameters("Q13")
    start_date = params.get("start_date", "2019-01-01")
    end_date = params.get("end_date", "2019-01-31")

    trips = ctx.get_table("trips")
    filtered = trips[
        (trips["pickup_datetime"] >= start_date)
        & (trips["pickup_datetime"] < end_date)
        & (trips["trip_distance"] >= 0)
        & (trips["trip_distance"] <= 30)
    ].copy()
    filtered["distance_miles"] = np.floor(filtered["trip_distance"])
    return (
        filtered.groupby(["distance_miles"], as_index=False)
        .agg(trip_count=("distance_miles", "count"), avg_fare=("total_amount", "mean"))
        .sort_values("distance_miles")
    )


def q14_expression_impl(ctx: DataFrameContext) -> Any:
    """Q14: Passenger count analysis with NULLIF for fare per mile."""
    params = get_parameters("Q14")
    start_date = params.get("start_date", "2019-01-01")
    end_date = params.get("end_date", "2019-01-31")

    trips = ctx.get_table("trips")
    col = ctx.col
    lit = ctx.lit

    return (
        trips.filter(
            (col("pickup_datetime") >= lit(start_date))
            & (col("pickup_datetime") < lit(end_date))
            & (col("passenger_count") >= lit(1))
            & (col("passenger_count") <= lit(6))
        )
        .with_columns(
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
    """Q14: Passenger count analysis with NULLIF for fare per mile."""
    import numpy as np

    params = get_parameters("Q14")
    start_date = params.get("start_date", "2019-01-01")
    end_date = params.get("end_date", "2019-01-31")

    trips = ctx.get_table("trips")
    filtered = trips[
        (trips["pickup_datetime"] >= start_date)
        & (trips["pickup_datetime"] < end_date)
        & (trips["passenger_count"] >= 1)
        & (trips["passenger_count"] <= 6)
    ].copy()
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
    """Q15: Trip duration analysis in 5-minute buckets."""
    params = get_parameters("Q15")
    start_date = params.get("start_date", "2019-01-01")
    end_date = params.get("end_date", "2019-01-31")

    trips = ctx.get_table("trips")
    col = ctx.col
    lit = ctx.lit

    return (
        trips.filter(
            (col("pickup_datetime") >= lit(start_date))
            & (col("pickup_datetime") < lit(end_date))
            & (col("dropoff_datetime") > col("pickup_datetime"))
        )
        .with_columns(((col("dropoff_datetime") - col("pickup_datetime")).dt.total_seconds()).alias("duration_sec"))
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
    """Q15: Trip duration analysis in 5-minute buckets."""
    import numpy as np

    params = get_parameters("Q15")
    start_date = params.get("start_date", "2019-01-01")
    end_date = params.get("end_date", "2019-01-31")

    trips = ctx.get_table("trips")
    filtered = trips[
        (trips["pickup_datetime"] >= start_date)
        & (trips["pickup_datetime"] < end_date)
        & (trips["dropoff_datetime"] > trips["pickup_datetime"])
    ].copy()
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
    """Q16: Rate code summary."""
    params = get_parameters("Q16")
    start_date = params.get("start_date", "2019-01-01")
    end_date = params.get("end_date", "2019-03-31")

    trips = ctx.get_table("trips")
    col = ctx.col
    lit = ctx.lit

    return (
        trips.filter((col("pickup_datetime") >= lit(start_date)) & (col("pickup_datetime") < lit(end_date)))
        .group_by("rate_code_id")
        .agg(
            col("rate_code_id").count().alias("trip_count"),
            col("trip_distance").mean().alias("avg_distance"),
            col("total_amount").mean().alias("avg_fare"),
            col("total_amount").sum().alias("total_revenue"),
        )
        .sort("trip_count", descending=True)
    )


def q16_pandas_impl(ctx: DataFrameContext) -> Any:
    """Q16: Rate code summary."""
    params = get_parameters("Q16")
    start_date = params.get("start_date", "2019-01-01")
    end_date = params.get("end_date", "2019-03-31")

    trips = ctx.get_table("trips")
    filtered = trips[(trips["pickup_datetime"] >= start_date) & (trips["pickup_datetime"] < end_date)]
    return (
        filtered.groupby(["rate_code_id"], as_index=False)
        .agg(
            trip_count=("rate_code_id", "count"),
            avg_distance=("trip_distance", "mean"),
            avg_fare=("total_amount", "mean"),
            total_revenue=("total_amount", "sum"),
        )
        .sort_values("trip_count", ascending=False)
    )


def q17_expression_impl(ctx: DataFrameContext) -> Any:
    """Q17: Airport trips with zone join."""
    params = get_parameters("Q17")
    start_date = params.get("start_date", "2019-01-01")
    end_date = params.get("end_date", "2019-03-31")

    trips = ctx.get_table("trips")
    zones = ctx.get_table("taxi_zones")
    col = ctx.col
    lit = ctx.lit

    return (
        trips.filter(
            (col("pickup_datetime") >= lit(start_date))
            & (col("pickup_datetime") < lit(end_date))
            & (col("rate_code_id").is_in([2, 3]))
        )
        .join(zones, left_on="pickup_location_id", right_on="location_id", how="left")
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
    """Q17: Airport trips with zone join."""
    params = get_parameters("Q17")
    start_date = params.get("start_date", "2019-01-01")
    end_date = params.get("end_date", "2019-03-31")

    trips = ctx.get_table("trips")
    zones = ctx.get_table("taxi_zones")
    filtered = trips[
        (trips["pickup_datetime"] >= start_date)
        & (trips["pickup_datetime"] < end_date)
        & (trips["rate_code_id"].isin([2, 3]))
    ]
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
    """Q18: Vendor comparison."""
    params = get_parameters("Q18")
    start_date = params.get("start_date", "2019-01-01")
    end_date = params.get("end_date", "2019-01-31")

    trips = ctx.get_table("trips")
    col = ctx.col
    lit = ctx.lit

    return (
        trips.filter((col("pickup_datetime") >= lit(start_date)) & (col("pickup_datetime") < lit(end_date)))
        .group_by("vendor_id")
        .agg(
            col("vendor_id").count().alias("trip_count"),
            col("trip_distance").mean().alias("avg_distance"),
            col("total_amount").mean().alias("avg_fare"),
            col("tip_amount").mean().alias("avg_tip"),
            col("total_amount").sum().alias("total_revenue"),
        )
        .sort("trip_count", descending=True)
    )


def q18_pandas_impl(ctx: DataFrameContext) -> Any:
    """Q18: Vendor comparison."""
    params = get_parameters("Q18")
    start_date = params.get("start_date", "2019-01-01")
    end_date = params.get("end_date", "2019-01-31")

    trips = ctx.get_table("trips")
    filtered = trips[(trips["pickup_datetime"] >= start_date) & (trips["pickup_datetime"] < end_date)]
    return (
        filtered.groupby(["vendor_id"], as_index=False)
        .agg(
            trip_count=("vendor_id", "count"),
            avg_distance=("trip_distance", "mean"),
            avg_fare=("total_amount", "mean"),
            avg_tip=("tip_amount", "mean"),
            total_revenue=("total_amount", "sum"),
        )
        .sort_values("trip_count", ascending=False)
    )


# =============================================================================
# Complex Analytics (Q19-Q22)
# =============================================================================


def q19_expression_impl(ctx: DataFrameContext) -> Any:
    """Q19: Hourly zone heatmap - 2D grouping."""
    params = get_parameters("Q19")
    start_date = params.get("start_date", "2019-01-01")
    end_date = params.get("end_date", "2019-01-07")

    trips = ctx.get_table("trips")
    col = ctx.col
    lit = ctx.lit

    return (
        trips.filter((col("pickup_datetime") >= lit(start_date)) & (col("pickup_datetime") < lit(end_date)))
        .with_columns(col("pickup_datetime").dt.hour().alias("hour"))
        .group_by("hour", "pickup_location_id")
        .agg(col("hour").count().alias("trip_count"))
        .sort(["hour", "trip_count"], descending=[False, True])
    )


def q19_pandas_impl(ctx: DataFrameContext) -> Any:
    """Q19: Hourly zone heatmap - 2D grouping."""
    params = get_parameters("Q19")
    start_date = params.get("start_date", "2019-01-01")
    end_date = params.get("end_date", "2019-01-07")

    trips = ctx.get_table("trips")
    filtered = trips[(trips["pickup_datetime"] >= start_date) & (trips["pickup_datetime"] < end_date)].copy()
    filtered["hour"] = filtered["pickup_datetime"].dt.hour
    return (
        filtered.groupby(["hour", "pickup_location_id"], as_index=False)
        .agg(trip_count=("hour", "count"))
        .sort_values(["hour", "trip_count"], ascending=[True, False])
    )


def q20_expression_impl(ctx: DataFrameContext) -> Any:
    """Q20: Weekday vs weekend comparison with CASE WHEN."""
    params = get_parameters("Q20")
    start_date = params.get("start_date", "2019-01-01")
    end_date = params.get("end_date", "2019-01-31")

    trips = ctx.get_table("trips")
    col = ctx.col
    lit = ctx.lit

    return (
        trips.filter((col("pickup_datetime") >= lit(start_date)) & (col("pickup_datetime") < lit(end_date)))
        .with_columns(
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
    """Q20: Weekday vs weekend comparison."""
    import numpy as np

    params = get_parameters("Q20")
    start_date = params.get("start_date", "2019-01-01")
    end_date = params.get("end_date", "2019-01-31")

    trips = ctx.get_table("trips")
    filtered = trips[(trips["pickup_datetime"] >= start_date) & (trips["pickup_datetime"] < end_date)].copy()
    filtered["hour"] = filtered["pickup_datetime"].dt.hour
    filtered["day_type"] = np.where(filtered["pickup_datetime"].dt.dayofweek.isin([5, 6]), "weekend", "weekday")
    return (
        filtered.groupby(["day_type", "hour"], as_index=False)
        .agg(trip_count=("hour", "count"), avg_distance=("trip_distance", "mean"), avg_fare=("total_amount", "mean"))
        .sort_values(["day_type", "hour"])
    )


def q21_expression_impl(ctx: DataFrameContext) -> Any:
    """Q21: Rush hour analysis with multi-way CASE WHEN."""
    params = get_parameters("Q21")
    start_date = params.get("start_date", "2019-01-01")
    end_date = params.get("end_date", "2019-01-31")

    trips = ctx.get_table("trips")
    col = ctx.col
    lit = ctx.lit

    filtered = trips.filter(
        (col("pickup_datetime") >= lit(start_date))
        & (col("pickup_datetime") < lit(end_date))
        & (col("dropoff_datetime") > col("pickup_datetime"))
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
    """Q21: Rush hour analysis with multi-way CASE WHEN."""
    import numpy as np

    params = get_parameters("Q21")
    start_date = params.get("start_date", "2019-01-01")
    end_date = params.get("end_date", "2019-01-31")

    trips = ctx.get_table("trips")
    filtered = trips[
        (trips["pickup_datetime"] >= start_date)
        & (trips["pickup_datetime"] < end_date)
        & (trips["dropoff_datetime"] > trips["pickup_datetime"])
    ].copy()
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
    """Q22: Monthly year-over-year comparison."""
    params = get_parameters("Q22")
    start_date = params.get("start_date", "2019-01-01")
    end_date = params.get("end_date", "2019-12-31")

    trips = ctx.get_table("trips")
    col = ctx.col
    lit = ctx.lit

    return (
        trips.filter((col("pickup_datetime") >= lit(start_date)) & (col("pickup_datetime") < lit(end_date)))
        .with_columns(
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
    """Q22: Monthly year-over-year comparison."""
    params = get_parameters("Q22")
    start_date = params.get("start_date", "2019-01-01")
    end_date = params.get("end_date", "2019-12-31")

    trips = ctx.get_table("trips")
    filtered = trips[(trips["pickup_datetime"] >= start_date) & (trips["pickup_datetime"] < end_date)].copy()
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
    """Q23: Single-day summary - scalar aggregation."""
    params = get_parameters("Q23")
    start_date = params.get("start_date", "2019-06-15")
    end_date = params.get("end_date", "2019-06-16")

    trips = ctx.get_table("trips")
    col = ctx.col
    lit = ctx.lit

    return trips.filter((col("pickup_datetime") >= lit(start_date)) & (col("pickup_datetime") < lit(end_date))).select(
        col("trip_id").count().alias("trip_count"),
        col("total_amount").sum().alias("total_revenue"),
        col("trip_distance").mean().alias("avg_distance"),
        col("total_amount").mean().alias("avg_fare"),
        col("tip_amount").mean().alias("avg_tip"),
        col("pickup_datetime").min().alias("first_trip"),
        col("pickup_datetime").max().alias("last_trip"),
    )


def q23_pandas_impl(ctx: DataFrameContext) -> Any:
    """Q23: Single-day summary - scalar aggregation."""
    import pandas as pd

    params = get_parameters("Q23")
    start_date = params.get("start_date", "2019-06-15")
    end_date = params.get("end_date", "2019-06-16")

    trips = ctx.get_table("trips")
    filtered = trips[(trips["pickup_datetime"] >= start_date) & (trips["pickup_datetime"] < end_date)]
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
    """Q24: Zone detail with INNER JOIN and zone_id filter."""
    params = get_parameters("Q24")
    start_date = params.get("start_date", "2019-01-01")
    end_date = params.get("end_date", "2019-01-31")
    zone_id = params.get("zone_id", 132)

    trips = ctx.get_table("trips")
    zones = ctx.get_table("taxi_zones")
    col = ctx.col
    lit = ctx.lit

    return (
        trips.filter(
            (col("pickup_datetime") >= lit(start_date))
            & (col("pickup_datetime") < lit(end_date))
            & (col("pickup_location_id") == lit(zone_id))
        )
        .join(zones, left_on="pickup_location_id", right_on="location_id")
        .group_by("zone", "borough")
        .agg(
            col("zone").count().alias("pickup_count"),
            col("trip_distance").mean().alias("avg_distance"),
            col("total_amount").mean().alias("avg_fare"),
            col("total_amount").sum().alias("total_revenue"),
        )
    )


def q24_pandas_impl(ctx: DataFrameContext) -> Any:
    """Q24: Zone detail with INNER JOIN and zone_id filter."""
    params = get_parameters("Q24")
    start_date = params.get("start_date", "2019-01-01")
    end_date = params.get("end_date", "2019-01-31")
    zone_id = params.get("zone_id", 132)

    trips = ctx.get_table("trips")
    zones = ctx.get_table("taxi_zones")
    filtered = trips[
        (trips["pickup_datetime"] >= start_date)
        & (trips["pickup_datetime"] < end_date)
        & (trips["pickup_location_id"] == zone_id)
    ]
    merged = filtered.merge(zones, left_on="pickup_location_id", right_on="location_id")
    return merged.groupby(["zone", "borough"], as_index=False).agg(
        pickup_count=("zone", "count"),
        avg_distance=("trip_distance", "mean"),
        avg_fare=("total_amount", "mean"),
        total_revenue=("total_amount", "sum"),
    )


def q25_expression_impl(ctx: DataFrameContext) -> Any:
    """Q25: Full scan count - baseline."""
    trips = ctx.get_table("trips")
    col = ctx.col
    return trips.select(col("trip_id").count().alias("total_trips"))


def q25_pandas_impl(ctx: DataFrameContext) -> Any:
    """Q25: Full scan count - baseline."""
    import pandas as pd

    trips = ctx.get_table("trips")
    return pd.DataFrame({"total_trips": [len(trips)]})


# =============================================================================
# Query Registration
# =============================================================================


def _register_all_queries() -> None:
    """Register all 25 NYC Taxi DataFrame queries."""
    # Temporal (Q1-Q4)
    register_query(
        DataFrameQuery(
            query_id="Q1",
            query_name="Trips per Hour",
            description="Hourly trip count distribution using EXTRACT(HOUR)",
            categories=[
                QueryCategory.FILTER,
                QueryCategory.GROUP_BY,
                QueryCategory.AGGREGATE,
                QueryCategory.ANALYTICAL,
            ],
            expression_impl=q1_expression_impl,
            pandas_impl=q1_pandas_impl,
        )
    )
    register_query(
        DataFrameQuery(
            query_id="Q2",
            query_name="Trips per Day",
            description="Daily trip count using DATE_TRUNC('day')",
            categories=[
                QueryCategory.FILTER,
                QueryCategory.GROUP_BY,
                QueryCategory.AGGREGATE,
                QueryCategory.ANALYTICAL,
            ],
            expression_impl=q2_expression_impl,
            pandas_impl=q2_pandas_impl,
        )
    )
    register_query(
        DataFrameQuery(
            query_id="Q3",
            query_name="Trips per Month",
            description="Monthly trip count and total revenue using DATE_TRUNC('month')",
            categories=[
                QueryCategory.FILTER,
                QueryCategory.GROUP_BY,
                QueryCategory.AGGREGATE,
                QueryCategory.ANALYTICAL,
            ],
            expression_impl=q3_expression_impl,
            pandas_impl=q3_pandas_impl,
        )
    )
    register_query(
        DataFrameQuery(
            query_id="Q4",
            query_name="Trips by Day of Week",
            description="Day-of-week distribution with avg distance and fare",
            categories=[
                QueryCategory.FILTER,
                QueryCategory.GROUP_BY,
                QueryCategory.AGGREGATE,
                QueryCategory.ANALYTICAL,
            ],
            expression_impl=q4_expression_impl,
            pandas_impl=q4_pandas_impl,
        )
    )

    # Geographic (Q5-Q8)
    register_query(
        DataFrameQuery(
            query_id="Q5",
            query_name="Top Pickup Zones",
            description="Top 20 pickup zones by trip count with LEFT JOIN to taxi_zones",
            categories=[QueryCategory.FILTER, QueryCategory.JOIN, QueryCategory.GROUP_BY, QueryCategory.SORT],
            expression_impl=q5_expression_impl,
            pandas_impl=q5_pandas_impl,
        )
    )
    register_query(
        DataFrameQuery(
            query_id="Q6",
            query_name="Top Dropoff Zones",
            description="Top 20 dropoff zones by trip count with LEFT JOIN to taxi_zones",
            categories=[QueryCategory.FILTER, QueryCategory.JOIN, QueryCategory.GROUP_BY, QueryCategory.SORT],
            expression_impl=q6_expression_impl,
            pandas_impl=q6_pandas_impl,
        )
    )
    register_query(
        DataFrameQuery(
            query_id="Q7",
            query_name="Top Routes",
            description="Top 50 routes (pickup->dropoff) with double LEFT JOIN to taxi_zones",
            categories=[QueryCategory.FILTER, QueryCategory.MULTI_JOIN, QueryCategory.GROUP_BY, QueryCategory.SORT],
            expression_impl=q7_expression_impl,
            pandas_impl=q7_pandas_impl,
        )
    )
    register_query(
        DataFrameQuery(
            query_id="Q8",
            query_name="Borough Summary",
            description="Borough-level trip count, revenue, distance, and tip averages",
            categories=[QueryCategory.FILTER, QueryCategory.JOIN, QueryCategory.GROUP_BY, QueryCategory.SORT],
            expression_impl=q8_expression_impl,
            pandas_impl=q8_pandas_impl,
        )
    )

    # Financial (Q9-Q12)
    register_query(
        DataFrameQuery(
            query_id="Q9",
            query_name="Revenue by Payment Type",
            description="Revenue and tip analysis by payment type with NULLIF protection",
            categories=[
                QueryCategory.FILTER,
                QueryCategory.GROUP_BY,
                QueryCategory.AGGREGATE,
                QueryCategory.ANALYTICAL,
            ],
            expression_impl=q9_expression_impl,
            pandas_impl=q9_pandas_impl,
        )
    )
    register_query(
        DataFrameQuery(
            query_id="Q10",
            query_name="Fare Distribution",
            description="Fare distribution in $5 buckets using FLOOR bucketing",
            categories=[
                QueryCategory.FILTER,
                QueryCategory.GROUP_BY,
                QueryCategory.AGGREGATE,
                QueryCategory.ANALYTICAL,
            ],
            expression_impl=q10_expression_impl,
            pandas_impl=q10_pandas_impl,
        )
    )
    register_query(
        DataFrameQuery(
            query_id="Q11",
            query_name="Tip Analysis",
            description="Tip analysis by hour for credit card payments with conditional avg",
            categories=[
                QueryCategory.FILTER,
                QueryCategory.GROUP_BY,
                QueryCategory.AGGREGATE,
                QueryCategory.ANALYTICAL,
            ],
            expression_impl=q11_expression_impl,
            pandas_impl=q11_pandas_impl,
        )
    )
    register_query(
        DataFrameQuery(
            query_id="Q12",
            query_name="Surcharge Revenue",
            description="Monthly surcharge revenue breakdown (extra, MTA tax, improvement, congestion, tolls)",
            categories=[
                QueryCategory.FILTER,
                QueryCategory.GROUP_BY,
                QueryCategory.AGGREGATE,
                QueryCategory.ANALYTICAL,
            ],
            expression_impl=q12_expression_impl,
            pandas_impl=q12_pandas_impl,
        )
    )

    # Characteristics (Q13-Q15)
    register_query(
        DataFrameQuery(
            query_id="Q13",
            query_name="Distance Distribution",
            description="Trip distance distribution in 1-mile buckets",
            categories=[QueryCategory.FILTER, QueryCategory.GROUP_BY, QueryCategory.AGGREGATE],
            expression_impl=q13_expression_impl,
            pandas_impl=q13_pandas_impl,
        )
    )
    register_query(
        DataFrameQuery(
            query_id="Q14",
            query_name="Passenger Count Analysis",
            description="Metrics by passenger count (1-6) with NULLIF fare-per-mile",
            categories=[
                QueryCategory.FILTER,
                QueryCategory.GROUP_BY,
                QueryCategory.AGGREGATE,
                QueryCategory.ANALYTICAL,
            ],
            expression_impl=q14_expression_impl,
            pandas_impl=q14_pandas_impl,
        )
    )
    register_query(
        DataFrameQuery(
            query_id="Q15",
            query_name="Trip Duration Analysis",
            description="Duration distribution in 5-min buckets using timestamp arithmetic",
            categories=[
                QueryCategory.FILTER,
                QueryCategory.GROUP_BY,
                QueryCategory.AGGREGATE,
                QueryCategory.ANALYTICAL,
            ],
            expression_impl=q15_expression_impl,
            pandas_impl=q15_pandas_impl,
        )
    )

    # Rates (Q16-Q17)
    register_query(
        DataFrameQuery(
            query_id="Q16",
            query_name="Rate Code Summary",
            description="Trip metrics by rate code (Standard, JFK, Newark, etc.)",
            categories=[QueryCategory.FILTER, QueryCategory.GROUP_BY, QueryCategory.AGGREGATE],
            expression_impl=q16_expression_impl,
            pandas_impl=q16_pandas_impl,
        )
    )
    register_query(
        DataFrameQuery(
            query_id="Q17",
            query_name="Airport Trips",
            description="Airport trip analysis (JFK/Newark) with zone join",
            categories=[QueryCategory.FILTER, QueryCategory.JOIN, QueryCategory.GROUP_BY, QueryCategory.SORT],
            expression_impl=q17_expression_impl,
            pandas_impl=q17_pandas_impl,
        )
    )

    # Vendor (Q18)
    register_query(
        DataFrameQuery(
            query_id="Q18",
            query_name="Vendor Comparison",
            description="Vendor-level trip metrics comparison",
            categories=[QueryCategory.FILTER, QueryCategory.GROUP_BY, QueryCategory.AGGREGATE],
            expression_impl=q18_expression_impl,
            pandas_impl=q18_pandas_impl,
        )
    )

    # Complex (Q19-Q22)
    register_query(
        DataFrameQuery(
            query_id="Q19",
            query_name="Hourly Zone Heatmap",
            description="2D grouping by hour and pickup zone for heatmap visualization",
            categories=[QueryCategory.FILTER, QueryCategory.GROUP_BY, QueryCategory.SORT, QueryCategory.ANALYTICAL],
            expression_impl=q19_expression_impl,
            pandas_impl=q19_pandas_impl,
        )
    )
    register_query(
        DataFrameQuery(
            query_id="Q20",
            query_name="Weekday/Weekend Comparison",
            description="Weekday vs weekend metrics by hour using CASE WHEN on day-of-week",
            categories=[QueryCategory.FILTER, QueryCategory.GROUP_BY, QueryCategory.SORT, QueryCategory.ANALYTICAL],
            expression_impl=q20_expression_impl,
            pandas_impl=q20_pandas_impl,
        )
    )
    register_query(
        DataFrameQuery(
            query_id="Q21",
            query_name="Rush Hour Analysis",
            description="Morning rush, evening rush, and off-peak period comparison",
            categories=[
                QueryCategory.FILTER,
                QueryCategory.GROUP_BY,
                QueryCategory.AGGREGATE,
                QueryCategory.ANALYTICAL,
            ],
            expression_impl=q21_expression_impl,
            pandas_impl=q21_pandas_impl,
        )
    )
    register_query(
        DataFrameQuery(
            query_id="Q22",
            query_name="Monthly Year-over-Year",
            description="Year and month grouping for YoY comparison over 2-year window",
            categories=[
                QueryCategory.FILTER,
                QueryCategory.GROUP_BY,
                QueryCategory.AGGREGATE,
                QueryCategory.ANALYTICAL,
            ],
            expression_impl=q22_expression_impl,
            pandas_impl=q22_pandas_impl,
        )
    )

    # Point (Q23-Q24)
    register_query(
        DataFrameQuery(
            query_id="Q23",
            query_name="Single-Day Summary",
            description="Scalar aggregation for a single day (no GROUP BY)",
            categories=[QueryCategory.FILTER, QueryCategory.AGGREGATE],
            expression_impl=q23_expression_impl,
            pandas_impl=q23_pandas_impl,
        )
    )
    register_query(
        DataFrameQuery(
            query_id="Q24",
            query_name="Zone Detail",
            description="Detailed metrics for a specific zone with INNER JOIN",
            categories=[QueryCategory.FILTER, QueryCategory.JOIN, QueryCategory.GROUP_BY, QueryCategory.AGGREGATE],
            expression_impl=q24_expression_impl,
            pandas_impl=q24_pandas_impl,
        )
    )

    # Baseline (Q25)
    register_query(
        DataFrameQuery(
            query_id="Q25",
            query_name="Full Scan Count",
            description="COUNT(*) baseline full table scan",
            categories=[QueryCategory.SCAN, QueryCategory.AGGREGATE],
            expression_impl=q25_expression_impl,
            pandas_impl=q25_pandas_impl,
        )
    )


_register_all_queries()
