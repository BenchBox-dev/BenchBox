"""NYC Taxi query variant rules for Phase.QUERY_SOURCE.

StarRocks lacks EXTRACT(DOW …) and EXTRACT(EPOCH FROM interval); ClickHouse
lacks EXTRACT(DOW …) and EXTRACT(EPOCH FROM interval) as well but uses
different native replacements.  All SQL constants are TEMPLATES - callers
must apply date parameters via .format(**params) before executing.
"""

from __future__ import annotations

from benchbox.sql_compat.actions import CompatAction
from benchbox.sql_compat.context import Phase
from benchbox.sql_compat.decision import (
    CompatibilityDecision,
    FailureMode,
    SelectVariantPayload,
    SupportLevel,
)
from benchbox.sql_compat.registry import REGISTRY

_B = "nyctaxi"
_P = Phase.QUERY_SOURCE

# ---------------------------------------------------------------------------
# StarRocks variants
#   EXTRACT(DOW FROM ts)                → DAYOFWEEK(ts) - 1
#   weekend check IN (0, 6)             → DAYOFWEEK(ts) IN (1, 7)  (Sun=1, Sat=7)
#   EXTRACT(EPOCH FROM (t2 - t1)) / 60 → TIMESTAMPDIFF(SECOND, t1, t2) / 60
# ---------------------------------------------------------------------------

STARROCKS_TRIPS_BY_DOW_SQL = """\
            SELECT
                DAYOFWEEK(pickup_datetime) - 1 as day_of_week,
                COUNT(*) as trip_count,
                AVG(trip_distance) as avg_distance,
                AVG(total_amount) as avg_fare
            FROM trips
            WHERE pickup_datetime >= '{start_date}'
              AND pickup_datetime < '{end_date}'
            GROUP BY DAYOFWEEK(pickup_datetime) - 1
            ORDER BY day_of_week"""

STARROCKS_WEEKDAY_WEEKEND_SQL = """\
            SELECT
                CASE WHEN DAYOFWEEK(pickup_datetime) IN (1, 7) THEN 'weekend' ELSE 'weekday' END as day_type,
                EXTRACT(HOUR FROM pickup_datetime) as hour,
                COUNT(*) as trip_count,
                AVG(trip_distance) as avg_distance,
                AVG(total_amount) as avg_fare
            FROM trips
            WHERE pickup_datetime >= '{start_date}'
              AND pickup_datetime < '{end_date}'
            GROUP BY
                CASE WHEN DAYOFWEEK(pickup_datetime) IN (1, 7) THEN 'weekend' ELSE 'weekday' END,
                EXTRACT(HOUR FROM pickup_datetime)
            ORDER BY day_type, hour"""

STARROCKS_RUSH_HOUR_SQL = """\
            SELECT
                CASE
                    WHEN EXTRACT(HOUR FROM pickup_datetime) BETWEEN 7 AND 9 THEN 'morning_rush'
                    WHEN EXTRACT(HOUR FROM pickup_datetime) BETWEEN 17 AND 19 THEN 'evening_rush'
                    ELSE 'off_peak'
                END as period,
                COUNT(*) as trip_count,
                AVG(trip_distance) as avg_distance,
                AVG(total_amount) as avg_fare,
                AVG(TIMESTAMPDIFF(SECOND, pickup_datetime, dropoff_datetime) / 60) as avg_duration_min
            FROM trips
            WHERE pickup_datetime >= '{start_date}'
              AND pickup_datetime < '{end_date}'
              AND dropoff_datetime > pickup_datetime
            GROUP BY
                CASE
                    WHEN EXTRACT(HOUR FROM pickup_datetime) BETWEEN 7 AND 9 THEN 'morning_rush'
                    WHEN EXTRACT(HOUR FROM pickup_datetime) BETWEEN 17 AND 19 THEN 'evening_rush'
                    ELSE 'off_peak'
                END
            ORDER BY trip_count DESC"""

STARROCKS_TRIP_DURATION_SQL = """\
            SELECT
                FLOOR(TIMESTAMPDIFF(SECOND, pickup_datetime, dropoff_datetime) / 60 / 5) * 5 as duration_bucket_min,
                COUNT(*) as trip_count,
                AVG(trip_distance) as avg_distance,
                AVG(total_amount) as avg_fare
            FROM trips
            WHERE pickup_datetime >= '{start_date}'
              AND pickup_datetime < '{end_date}'
              AND dropoff_datetime > pickup_datetime
              AND TIMESTAMPDIFF(SECOND, pickup_datetime, dropoff_datetime) BETWEEN 60 AND 7200
            GROUP BY FLOOR(TIMESTAMPDIFF(SECOND, pickup_datetime, dropoff_datetime) / 60 / 5) * 5
            ORDER BY duration_bucket_min"""

# ---------------------------------------------------------------------------
# ClickHouse variants
#   EXTRACT(HOUR FROM ts)              → toHour(ts)
#   EXTRACT(DOW FROM ts)               → toDayOfWeek(ts) % 7
#   EXTRACT(EPOCH FROM (t2 - t1)) / 60 → dateDiff('second', t1, t2) / 60
# ---------------------------------------------------------------------------

CLICKHOUSE_TRIPS_BY_DOW_SQL = """\
            SELECT
                toDayOfWeek(pickup_datetime) % 7 as day_of_week,
                COUNT(*) as trip_count,
                AVG(trip_distance) as avg_distance,
                AVG(total_amount) as avg_fare
            FROM trips
            WHERE pickup_datetime >= '{start_date}'
              AND pickup_datetime < '{end_date}'
            GROUP BY toDayOfWeek(pickup_datetime) % 7
            ORDER BY day_of_week"""

CLICKHOUSE_WEEKDAY_WEEKEND_SQL = """\
            SELECT
                CASE WHEN toDayOfWeek(pickup_datetime) % 7 IN (0, 6) THEN 'weekend' ELSE 'weekday' END as day_type,
                toHour(pickup_datetime) as hour,
                COUNT(*) as trip_count,
                AVG(trip_distance) as avg_distance,
                AVG(total_amount) as avg_fare
            FROM trips
            WHERE pickup_datetime >= '{start_date}'
              AND pickup_datetime < '{end_date}'
            GROUP BY
                CASE WHEN toDayOfWeek(pickup_datetime) % 7 IN (0, 6) THEN 'weekend' ELSE 'weekday' END,
                toHour(pickup_datetime)
            ORDER BY day_type, hour"""

CLICKHOUSE_RUSH_HOUR_SQL = """\
            SELECT
                CASE
                    WHEN toHour(pickup_datetime) BETWEEN 7 AND 9 THEN 'morning_rush'
                    WHEN toHour(pickup_datetime) BETWEEN 17 AND 19 THEN 'evening_rush'
                    ELSE 'off_peak'
                END as period,
                COUNT(*) as trip_count,
                AVG(trip_distance) as avg_distance,
                AVG(total_amount) as avg_fare,
                AVG(dateDiff('second', pickup_datetime, dropoff_datetime) / 60) as avg_duration_min
            FROM trips
            WHERE pickup_datetime >= '{start_date}'
              AND pickup_datetime < '{end_date}'
              AND dropoff_datetime > pickup_datetime
            GROUP BY
                CASE
                    WHEN toHour(pickup_datetime) BETWEEN 7 AND 9 THEN 'morning_rush'
                    WHEN toHour(pickup_datetime) BETWEEN 17 AND 19 THEN 'evening_rush'
                    ELSE 'off_peak'
                END
            ORDER BY trip_count DESC"""

# ---------------------------------------------------------------------------
# StarRocks rule registrations
# ---------------------------------------------------------------------------

REGISTRY.register(
    CompatibilityDecision(
        rule_id="query_source.starrocks.nyctaxi.trips_by_dow_dayofweek_variant",
        action=CompatAction.SELECT_VARIANT,
        support_level=SupportLevel.REWRITTEN,
        failure_mode=FailureMode.UNSUPPORTED_FEATURE,
        payload=SelectVariantPayload(
            variant_key="starrocks",
            variant_sql=STARROCKS_TRIPS_BY_DOW_SQL,
        ),
        reason="StarRocks lacks EXTRACT(DOW FROM ts); replace with DAYOFWEEK(ts) - 1",
    ),
    _P,
    "starrocks",
    benchmark=_B,
    query_id="trips-by-day-of-week",
)

REGISTRY.register(
    CompatibilityDecision(
        rule_id="query_source.starrocks.nyctaxi.weekday_weekend_dayofweek_variant",
        action=CompatAction.SELECT_VARIANT,
        support_level=SupportLevel.REWRITTEN,
        failure_mode=FailureMode.UNSUPPORTED_FEATURE,
        payload=SelectVariantPayload(
            variant_key="starrocks",
            variant_sql=STARROCKS_WEEKDAY_WEEKEND_SQL,
        ),
        reason="StarRocks lacks EXTRACT(DOW FROM ts); replace weekday/weekend check with DAYOFWEEK() IN (1, 7)",
    ),
    _P,
    "starrocks",
    benchmark=_B,
    query_id="weekday-weekend-comparison",
)

REGISTRY.register(
    CompatibilityDecision(
        rule_id="query_source.starrocks.nyctaxi.rush_hour_timestampdiff_variant",
        action=CompatAction.SELECT_VARIANT,
        support_level=SupportLevel.REWRITTEN,
        failure_mode=FailureMode.UNSUPPORTED_FEATURE,
        payload=SelectVariantPayload(
            variant_key="starrocks",
            variant_sql=STARROCKS_RUSH_HOUR_SQL,
        ),
        reason="StarRocks lacks EXTRACT(EPOCH FROM interval); replace with TIMESTAMPDIFF(SECOND, ...)",
    ),
    _P,
    "starrocks",
    benchmark=_B,
    query_id="rush-hour-analysis",
)

REGISTRY.register(
    CompatibilityDecision(
        rule_id="query_source.starrocks.nyctaxi.trip_duration_timestampdiff_variant",
        action=CompatAction.SELECT_VARIANT,
        support_level=SupportLevel.REWRITTEN,
        failure_mode=FailureMode.UNSUPPORTED_FEATURE,
        payload=SelectVariantPayload(
            variant_key="starrocks",
            variant_sql=STARROCKS_TRIP_DURATION_SQL,
        ),
        reason="StarRocks lacks EXTRACT(EPOCH FROM interval); replace with TIMESTAMPDIFF(SECOND, ...)",
    ),
    _P,
    "starrocks",
    benchmark=_B,
    query_id="trip-duration-analysis",
)

# ---------------------------------------------------------------------------
# ClickHouse rule registrations
# ---------------------------------------------------------------------------

REGISTRY.register(
    CompatibilityDecision(
        rule_id="query_source.clickhouse.nyctaxi.trips_by_dow_todayofweek_variant",
        action=CompatAction.SELECT_VARIANT,
        support_level=SupportLevel.REWRITTEN,
        failure_mode=FailureMode.UNSUPPORTED_FEATURE,
        payload=SelectVariantPayload(
            variant_key="clickhouse",
            variant_sql=CLICKHOUSE_TRIPS_BY_DOW_SQL,
        ),
        reason="ClickHouse lacks EXTRACT(DOW FROM ts); replace with toDayOfWeek(ts) % 7",
    ),
    _P,
    "clickhouse",
    benchmark=_B,
    query_id="trips-by-day-of-week",
)

REGISTRY.register(
    CompatibilityDecision(
        rule_id="query_source.clickhouse.nyctaxi.weekday_weekend_tohour_variant",
        action=CompatAction.SELECT_VARIANT,
        support_level=SupportLevel.REWRITTEN,
        failure_mode=FailureMode.UNSUPPORTED_FEATURE,
        payload=SelectVariantPayload(
            variant_key="clickhouse",
            variant_sql=CLICKHOUSE_WEEKDAY_WEEKEND_SQL,
        ),
        reason="ClickHouse lacks EXTRACT(DOW/HOUR FROM ts); replace with toDayOfWeek() % 7 and toHour()",
    ),
    _P,
    "clickhouse",
    benchmark=_B,
    query_id="weekday-weekend-comparison",
)

REGISTRY.register(
    CompatibilityDecision(
        rule_id="query_source.clickhouse.nyctaxi.rush_hour_datediff_variant",
        action=CompatAction.SELECT_VARIANT,
        support_level=SupportLevel.REWRITTEN,
        failure_mode=FailureMode.UNSUPPORTED_FEATURE,
        payload=SelectVariantPayload(
            variant_key="clickhouse",
            variant_sql=CLICKHOUSE_RUSH_HOUR_SQL,
        ),
        reason="ClickHouse lacks EXTRACT(HOUR/EPOCH FROM ts); replace with toHour() and dateDiff('second', ...)",
    ),
    _P,
    "clickhouse",
    benchmark=_B,
    query_id="rush-hour-analysis",
)
