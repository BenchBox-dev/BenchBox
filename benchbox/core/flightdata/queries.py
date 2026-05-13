"""Flight data benchmark queries.

20 OLAP queries across 5 categories covering US aviation on-time performance:
- On-time performance (5 queries)
- Delay analysis (4 queries)
- Route analytics (4 queries)
- Temporal patterns (4 queries)
- Carrier comparisons (3 queries)

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

from typing import Any, Optional

import sqlglot

# Query definitions: 20 OLAP queries across 5 categories
QUERIES: dict[str, dict[str, Any]] = {
    # ==== On-Time Performance (5 queries) ====
    "ontime-by-carrier": {
        "id": "1",
        "name": "On-Time Rate by Carrier",
        "description": "On-time arrival percentage by airline carrier",
        "category": "ontime",
        "sql": """
            SELECT
                f.reporting_airline,
                a.name AS airline_name,
                COUNT(*) AS total_flights,
                SUM(CASE WHEN f.arr_delay <= 15 THEN 1 ELSE 0 END) AS ontime_flights,
                ROUND(100.0 * SUM(CASE WHEN f.arr_delay <= 15 THEN 1 ELSE 0 END) / COUNT(*), 2) AS ontime_pct,
                ROUND(AVG(CASE WHEN f.arr_delay > 0 THEN f.arr_delay END), 2) AS avg_delay_when_late
            FROM flights f
            LEFT JOIN airlines a ON f.reporting_airline = a.code
            WHERE f.cancelled = 0
              AND f.flight_date >= '{start_date}'
              AND f.flight_date < '{end_date}'
            GROUP BY f.reporting_airline, a.name
            ORDER BY ontime_pct DESC
        """,
    },
    "delay-by-airport": {
        "id": "2",
        "name": "Average Departure Delay by Origin Airport",
        "description": "Average departure delay in minutes by origin airport",
        "category": "ontime",
        "sql": """
            SELECT
                f.origin,
                ap.name AS airport_name,
                ap.city,
                ap.state,
                COUNT(*) AS total_flights,
                ROUND(AVG(f.dep_delay), 2) AS avg_dep_delay,
                ROUND(AVG(f.arr_delay), 2) AS avg_arr_delay,
                SUM(CASE WHEN f.dep_delay > 15 THEN 1 ELSE 0 END) AS delayed_flights
            FROM flights f
            LEFT JOIN airports ap ON f.origin = ap.code
            WHERE f.cancelled = 0
              AND f.dep_delay IS NOT NULL
              AND f.flight_date >= '{start_date}'
              AND f.flight_date < '{end_date}'
            GROUP BY f.origin, ap.name, ap.city, ap.state
            HAVING COUNT(*) >= 100
            ORDER BY avg_dep_delay DESC
            LIMIT 50
        """,
    },
    "delay-by-hour": {
        "id": "3",
        "name": "Delay Pattern by Departure Hour",
        "description": "Average delay minutes by scheduled departure hour",
        "category": "ontime",
        "sql": """
            SELECT
                (f.crs_dep_time / 100) AS dep_hour,
                COUNT(*) AS total_flights,
                ROUND(AVG(f.dep_delay), 2) AS avg_dep_delay,
                ROUND(AVG(f.arr_delay), 2) AS avg_arr_delay,
                SUM(CASE WHEN f.dep_delay > 15 THEN 1 ELSE 0 END) AS delayed_count,
                ROUND(100.0 * SUM(CASE WHEN f.dep_delay > 15 THEN 1 ELSE 0 END) / COUNT(*), 2) AS delay_rate_pct
            FROM flights f
            WHERE f.cancelled = 0
              AND f.dep_delay IS NOT NULL
              AND f.crs_dep_time IS NOT NULL
              AND f.flight_date >= '{start_date}'
              AND f.flight_date < '{end_date}'
            GROUP BY (f.crs_dep_time / 100)
            ORDER BY dep_hour
        """,
    },
    "best-routes": {
        "id": "4",
        "name": "Best Performing Routes by On-Time Rate",
        "description": "Routes with highest on-time arrival percentage (min 50 flights)",
        "category": "ontime",
        "sql": """
            SELECT
                f.origin,
                f.dest,
                ao.city AS origin_city,
                ad.city AS dest_city,
                COUNT(*) AS total_flights,
                ROUND(100.0 * SUM(CASE WHEN f.arr_delay <= 15 THEN 1 ELSE 0 END) / COUNT(*), 2) AS ontime_pct,
                ROUND(AVG(f.arr_delay), 2) AS avg_arr_delay,
                ROUND(AVG(f.distance), 0) AS avg_distance_miles
            FROM flights f
            LEFT JOIN airports ao ON f.origin = ao.code
            LEFT JOIN airports ad ON f.dest = ad.code
            WHERE f.cancelled = 0
              AND f.arr_delay IS NOT NULL
              AND f.flight_date >= '{start_date}'
              AND f.flight_date < '{end_date}'
            GROUP BY f.origin, f.dest, ao.city, ad.city
            HAVING COUNT(*) >= 50
            ORDER BY ontime_pct DESC
            LIMIT 25
        """,
    },
    "improvement-trend": {
        "id": "5",
        "name": "On-Time Performance Trend Over Years",
        "description": "Annual on-time arrival percentage trend",
        "category": "ontime",
        "sql": """
            SELECT
                f.year,
                COUNT(*) AS total_flights,
                SUM(CASE WHEN f.cancelled = 1 THEN 1 ELSE 0 END) AS cancelled_flights,
                ROUND(100.0 * SUM(CASE WHEN f.cancelled = 1 THEN 1 ELSE 0 END) / COUNT(*), 2) AS cancellation_rate_pct,
                SUM(CASE WHEN f.cancelled = 0 AND f.arr_delay <= 15 THEN 1 ELSE 0 END) AS ontime_flights,
                ROUND(100.0 * SUM(CASE WHEN f.cancelled = 0 AND f.arr_delay <= 15 THEN 1 ELSE 0 END)
                    / NULLIF(SUM(CASE WHEN f.cancelled = 0 THEN 1 ELSE 0 END), 0), 2) AS ontime_pct,
                ROUND(AVG(CASE WHEN f.cancelled = 0 THEN f.arr_delay END), 2) AS avg_arr_delay
            FROM flights f
            WHERE f.flight_date >= '{start_date}'
              AND f.flight_date < '{end_date}'
            GROUP BY f.year
            ORDER BY f.year
        """,
    },
    # ==== Delay Analysis (4 queries) ====
    "delay-causes": {
        "id": "6",
        "name": "Delay Cause Breakdown",
        "description": "Distribution of delay causes across all delayed flights",
        "category": "delay",
        "sql": """
            SELECT
                SUM(CASE WHEN f.carrier_delay > 0 THEN 1 ELSE 0 END) AS carrier_delay_count,
                ROUND(AVG(CASE WHEN f.carrier_delay > 0 THEN f.carrier_delay END), 2) AS avg_carrier_delay,
                SUM(CASE WHEN f.weather_delay > 0 THEN 1 ELSE 0 END) AS weather_delay_count,
                ROUND(AVG(CASE WHEN f.weather_delay > 0 THEN f.weather_delay END), 2) AS avg_weather_delay,
                SUM(CASE WHEN f.nas_delay > 0 THEN 1 ELSE 0 END) AS nas_delay_count,
                ROUND(AVG(CASE WHEN f.nas_delay > 0 THEN f.nas_delay END), 2) AS avg_nas_delay,
                SUM(CASE WHEN f.security_delay > 0 THEN 1 ELSE 0 END) AS security_delay_count,
                ROUND(AVG(CASE WHEN f.security_delay > 0 THEN f.security_delay END), 2) AS avg_security_delay,
                SUM(CASE WHEN f.late_aircraft_delay > 0 THEN 1 ELSE 0 END) AS late_aircraft_count,
                ROUND(AVG(CASE WHEN f.late_aircraft_delay > 0 THEN f.late_aircraft_delay END), 2) AS avg_late_aircraft_delay,
                COUNT(*) AS total_delayed_flights
            FROM flights f
            WHERE f.cancelled = 0
              AND f.arr_delay > 15
              AND f.flight_date >= '{start_date}'
              AND f.flight_date < '{end_date}'
        """,
    },
    "cascade-delays": {
        "id": "7",
        "name": "Late Aircraft (Cascade) Delay Patterns",
        "description": "Flights delayed due to late incoming aircraft by carrier",
        "category": "delay",
        "sql": """
            SELECT
                f.reporting_airline,
                a.name AS airline_name,
                COUNT(*) AS total_flights,
                SUM(CASE WHEN f.late_aircraft_delay > 0 THEN 1 ELSE 0 END) AS cascade_delayed,
                ROUND(100.0 * SUM(CASE WHEN f.late_aircraft_delay > 0 THEN 1 ELSE 0 END) / COUNT(*), 2) AS cascade_rate_pct,
                ROUND(AVG(CASE WHEN f.late_aircraft_delay > 0 THEN f.late_aircraft_delay END), 2) AS avg_cascade_delay,
                ROUND(SUM(CASE WHEN f.late_aircraft_delay > 0 THEN f.late_aircraft_delay ELSE 0 END), 0) AS total_cascade_minutes
            FROM flights f
            LEFT JOIN airlines a ON f.reporting_airline = a.code
            WHERE f.cancelled = 0
              AND f.flight_date >= '{start_date}'
              AND f.flight_date < '{end_date}'
            GROUP BY f.reporting_airline, a.name
            ORDER BY cascade_rate_pct DESC
        """,
    },
    "weather-impact": {
        "id": "8",
        "name": "Weather Delay Impact by Month",
        "description": "Average weather delay by month showing seasonal patterns",
        "category": "delay",
        "sql": """
            SELECT
                f.month,
                COUNT(*) AS total_flights,
                SUM(CASE WHEN f.weather_delay > 0 THEN 1 ELSE 0 END) AS weather_delayed,
                ROUND(100.0 * SUM(CASE WHEN f.weather_delay > 0 THEN 1 ELSE 0 END) / COUNT(*), 2) AS weather_delay_rate_pct,
                ROUND(AVG(CASE WHEN f.weather_delay > 0 THEN f.weather_delay END), 2) AS avg_weather_delay_min,
                ROUND(SUM(COALESCE(f.weather_delay, 0)), 0) AS total_weather_minutes
            FROM flights f
            WHERE f.cancelled = 0
              AND f.flight_date >= '{start_date}'
              AND f.flight_date < '{end_date}'
            GROUP BY f.month
            ORDER BY f.month
        """,
    },
    "recovery-time": {
        "id": "9",
        "name": "Delay Recovery Analysis",
        "description": "How much of departure delay is recovered in flight (dep_delay - arr_delay)",
        "category": "delay",
        "sql": """
            SELECT
                CASE
                    WHEN f.dep_delay <= 0 THEN 'No departure delay'
                    WHEN f.dep_delay <= 15 THEN '1-15 min departure delay'
                    WHEN f.dep_delay <= 30 THEN '16-30 min departure delay'
                    WHEN f.dep_delay <= 60 THEN '31-60 min departure delay'
                    ELSE '60+ min departure delay'
                END AS delay_bucket,
                COUNT(*) AS flight_count,
                ROUND(AVG(f.dep_delay), 2) AS avg_dep_delay,
                ROUND(AVG(f.arr_delay), 2) AS avg_arr_delay,
                ROUND(AVG(f.dep_delay - f.arr_delay), 2) AS avg_minutes_recovered,
                ROUND(100.0 * SUM(CASE WHEN f.arr_delay < f.dep_delay THEN 1 ELSE 0 END) / COUNT(*), 2) AS pct_recovered
            FROM flights f
            WHERE f.cancelled = 0
              AND f.dep_delay IS NOT NULL
              AND f.arr_delay IS NOT NULL
              AND f.flight_date >= '{start_date}'
              AND f.flight_date < '{end_date}'
            GROUP BY CASE
                WHEN f.dep_delay <= 0 THEN 'No departure delay'
                WHEN f.dep_delay <= 15 THEN '1-15 min departure delay'
                WHEN f.dep_delay <= 30 THEN '16-30 min departure delay'
                WHEN f.dep_delay <= 60 THEN '31-60 min departure delay'
                ELSE '60+ min departure delay'
            END
            ORDER BY avg_dep_delay
        """,
    },
    # ==== Route Analytics (4 queries) ====
    "busiest-routes": {
        "id": "10",
        "name": "Busiest Routes by Flight Count",
        "description": "Top 25 routes ranked by total flight count",
        "category": "routes",
        "sql": """
            SELECT
                f.origin,
                f.dest,
                ao.city AS origin_city,
                ao.state AS origin_state,
                ad.city AS dest_city,
                ad.state AS dest_state,
                COUNT(*) AS total_flights,
                ROUND(AVG(f.distance), 0) AS avg_distance_miles,
                ROUND(AVG(f.actual_elapsed_time), 0) AS avg_duration_min,
                ROUND(100.0 * SUM(CASE WHEN f.arr_delay <= 15 THEN 1 ELSE 0 END) / COUNT(*), 2) AS ontime_pct
            FROM flights f
            LEFT JOIN airports ao ON f.origin = ao.code
            LEFT JOIN airports ad ON f.dest = ad.code
            WHERE f.cancelled = 0
              AND f.flight_date >= '{start_date}'
              AND f.flight_date < '{end_date}'
            GROUP BY f.origin, f.dest, ao.city, ao.state, ad.city, ad.state
            ORDER BY total_flights DESC
            LIMIT 25
        """,
    },
    "route-reliability": {
        "id": "11",
        "name": "Route Reliability Ranking",
        "description": "Routes ranked by reliability (on-time + low cancellation)",
        "category": "routes",
        "sql": """
            SELECT
                f.origin,
                f.dest,
                ao.city AS origin_city,
                ad.city AS dest_city,
                COUNT(*) AS total_scheduled,
                SUM(CASE WHEN f.cancelled = 1 THEN 1 ELSE 0 END) AS cancelled_count,
                ROUND(100.0 * SUM(CASE WHEN f.cancelled = 1 THEN 1 ELSE 0 END) / COUNT(*), 2) AS cancellation_rate_pct,
                SUM(CASE WHEN f.cancelled = 0 AND f.arr_delay <= 15 THEN 1 ELSE 0 END) AS ontime_count,
                ROUND(100.0 * SUM(CASE WHEN f.cancelled = 0 AND f.arr_delay <= 15 THEN 1 ELSE 0 END)
                    / NULLIF(SUM(CASE WHEN f.cancelled = 0 THEN 1 ELSE 0 END), 0), 2) AS ontime_pct,
                ROUND(AVG(f.distance), 0) AS distance_miles
            FROM flights f
            LEFT JOIN airports ao ON f.origin = ao.code
            LEFT JOIN airports ad ON f.dest = ad.code
            WHERE f.flight_date >= '{start_date}'
              AND f.flight_date < '{end_date}'
            GROUP BY f.origin, f.dest, ao.city, ad.city
            HAVING COUNT(*) >= 100
            ORDER BY ontime_pct DESC, cancellation_rate_pct ASC
            LIMIT 30
        """,
    },
    "distance-delay": {
        "id": "12",
        "name": "Distance vs Delay Correlation",
        "description": "Average delay grouped by flight distance buckets",
        "category": "routes",
        "sql": """
            SELECT
                CASE
                    WHEN f.distance < 250 THEN 'Short-haul (<250 mi)'
                    WHEN f.distance < 500 THEN 'Medium-haul (250-499 mi)'
                    WHEN f.distance < 1000 THEN 'Long-haul (500-999 mi)'
                    WHEN f.distance < 2000 THEN 'Cross-country (1000-1999 mi)'
                    ELSE 'Ultra-long (2000+ mi)'
                END AS distance_bucket,
                COUNT(*) AS total_flights,
                ROUND(AVG(f.distance), 0) AS avg_distance_miles,
                ROUND(AVG(f.dep_delay), 2) AS avg_dep_delay,
                ROUND(AVG(f.arr_delay), 2) AS avg_arr_delay,
                ROUND(100.0 * SUM(CASE WHEN f.arr_delay <= 15 THEN 1 ELSE 0 END) / COUNT(*), 2) AS ontime_pct
            FROM flights f
            WHERE f.cancelled = 0
              AND f.arr_delay IS NOT NULL
              AND f.flight_date >= '{start_date}'
              AND f.flight_date < '{end_date}'
            GROUP BY CASE
                WHEN f.distance < 250 THEN 'Short-haul (<250 mi)'
                WHEN f.distance < 500 THEN 'Medium-haul (250-499 mi)'
                WHEN f.distance < 1000 THEN 'Long-haul (500-999 mi)'
                WHEN f.distance < 2000 THEN 'Cross-country (1000-1999 mi)'
                ELSE 'Ultra-long (2000+ mi)'
            END
            ORDER BY avg_distance_miles
        """,
    },
    "hub-connectivity": {
        "id": "13",
        "name": "Hub Airport Connectivity",
        "description": "Number of unique destinations served from each origin airport",
        "category": "routes",
        "sql": """
            SELECT
                f.origin,
                ap.name AS airport_name,
                ap.city,
                ap.state,
                COUNT(DISTINCT f.dest) AS unique_destinations,
                COUNT(DISTINCT f.reporting_airline) AS serving_carriers,
                COUNT(*) AS total_departures,
                ROUND(AVG(f.dep_delay), 2) AS avg_dep_delay
            FROM flights f
            LEFT JOIN airports ap ON f.origin = ap.code
            WHERE f.cancelled = 0
              AND f.flight_date >= '{start_date}'
              AND f.flight_date < '{end_date}'
            GROUP BY f.origin, ap.name, ap.city, ap.state
            ORDER BY total_departures DESC
            LIMIT 30
        """,
    },
    # ==== Temporal Patterns (4 queries) ====
    "day-of-week": {
        "id": "14",
        "name": "Flight Patterns by Day of Week",
        "description": "Flight volume and delay patterns by day of week",
        "category": "temporal",
        "sql": """
            SELECT
                f.day_of_week,
                CASE f.day_of_week
                    WHEN 1 THEN 'Monday'
                    WHEN 2 THEN 'Tuesday'
                    WHEN 3 THEN 'Wednesday'
                    WHEN 4 THEN 'Thursday'
                    WHEN 5 THEN 'Friday'
                    WHEN 6 THEN 'Saturday'
                    WHEN 7 THEN 'Sunday'
                END AS day_name,
                COUNT(*) AS total_flights,
                SUM(CASE WHEN f.cancelled = 1 THEN 1 ELSE 0 END) AS cancelled_count,
                ROUND(AVG(CASE WHEN f.cancelled = 0 THEN f.dep_delay END), 2) AS avg_dep_delay,
                ROUND(AVG(CASE WHEN f.cancelled = 0 THEN f.arr_delay END), 2) AS avg_arr_delay,
                ROUND(100.0 * SUM(CASE WHEN f.cancelled = 0 AND f.arr_delay <= 15 THEN 1 ELSE 0 END)
                    / NULLIF(SUM(CASE WHEN f.cancelled = 0 THEN 1 ELSE 0 END), 0), 2) AS ontime_pct
            FROM flights f
            WHERE f.flight_date >= '{start_date}'
              AND f.flight_date < '{end_date}'
            GROUP BY f.day_of_week
            ORDER BY f.day_of_week
        """,
    },
    "seasonal-trends": {
        "id": "15",
        "name": "Seasonal Performance Trends",
        "description": "Monthly flight volume and performance aggregated across all years",
        "category": "temporal",
        "sql": """
            SELECT
                f.month,
                CASE f.month
                    WHEN 1 THEN 'January' WHEN 2 THEN 'February'
                    WHEN 3 THEN 'March' WHEN 4 THEN 'April'
                    WHEN 5 THEN 'May' WHEN 6 THEN 'June'
                    WHEN 7 THEN 'July' WHEN 8 THEN 'August'
                    WHEN 9 THEN 'September' WHEN 10 THEN 'October'
                    WHEN 11 THEN 'November' WHEN 12 THEN 'December'
                END AS month_name,
                COUNT(*) AS total_flights,
                SUM(CASE WHEN f.cancelled = 1 THEN 1 ELSE 0 END) AS cancelled_count,
                ROUND(100.0 * SUM(CASE WHEN f.cancelled = 1 THEN 1 ELSE 0 END) / COUNT(*), 2) AS cancellation_rate_pct,
                ROUND(AVG(CASE WHEN f.cancelled = 0 THEN f.arr_delay END), 2) AS avg_arr_delay,
                ROUND(100.0 * SUM(CASE WHEN f.cancelled = 0 AND f.arr_delay <= 15 THEN 1 ELSE 0 END)
                    / NULLIF(SUM(CASE WHEN f.cancelled = 0 THEN 1 ELSE 0 END), 0), 2) AS ontime_pct
            FROM flights f
            WHERE f.flight_date >= '{start_date}'
              AND f.flight_date < '{end_date}'
            GROUP BY f.month
            ORDER BY f.month
        """,
    },
    "holiday-impact": {
        "id": "16",
        "name": "Holiday Period Delay Impact",
        "description": "Compare performance during major holiday periods vs normal days",
        "category": "temporal",
        "sql": """
            SELECT
                CASE
                    WHEN (f.month = 11 AND f.day_of_month BETWEEN 21 AND 27) THEN 'Thanksgiving Week'
                    WHEN (f.month = 12 AND f.day_of_month BETWEEN 23 AND 27) THEN 'Christmas'
                    WHEN (f.month = 1 AND f.day_of_month BETWEEN 1 AND 2)
                      OR (f.month = 12 AND f.day_of_month = 31) THEN 'New Year'
                    WHEN (f.month = 7 AND f.day_of_month BETWEEN 3 AND 5) THEN 'July 4th'
                    WHEN (f.month = 5 AND f.day_of_week = 1 AND f.day_of_month BETWEEN 25 AND 31) THEN 'Memorial Day'
                    WHEN (f.month = 9 AND f.day_of_week = 1 AND f.day_of_month BETWEEN 1 AND 7) THEN 'Labor Day'
                    ELSE 'Regular Day'
                END AS period,
                COUNT(*) AS total_flights,
                ROUND(AVG(CASE WHEN f.cancelled = 0 THEN f.arr_delay END), 2) AS avg_arr_delay,
                ROUND(100.0 * SUM(CASE WHEN f.cancelled = 1 THEN 1 ELSE 0 END) / COUNT(*), 2) AS cancellation_rate_pct,
                ROUND(100.0 * SUM(CASE WHEN f.cancelled = 0 AND f.arr_delay <= 15 THEN 1 ELSE 0 END)
                    / NULLIF(SUM(CASE WHEN f.cancelled = 0 THEN 1 ELSE 0 END), 0), 2) AS ontime_pct
            FROM flights f
            WHERE f.flight_date >= '{start_date}'
              AND f.flight_date < '{end_date}'
            GROUP BY CASE
                    WHEN (f.month = 11 AND f.day_of_month BETWEEN 21 AND 27) THEN 'Thanksgiving Week'
                    WHEN (f.month = 12 AND f.day_of_month BETWEEN 23 AND 27) THEN 'Christmas'
                    WHEN (f.month = 1 AND f.day_of_month BETWEEN 1 AND 2)
                      OR (f.month = 12 AND f.day_of_month = 31) THEN 'New Year'
                    WHEN (f.month = 7 AND f.day_of_month BETWEEN 3 AND 5) THEN 'July 4th'
                    WHEN (f.month = 5 AND f.day_of_week = 1 AND f.day_of_month BETWEEN 25 AND 31) THEN 'Memorial Day'
                    WHEN (f.month = 9 AND f.day_of_week = 1 AND f.day_of_month BETWEEN 1 AND 7) THEN 'Labor Day'
                    ELSE 'Regular Day'
                END
            ORDER BY avg_arr_delay DESC
        """,
    },
    "time-of-day": {
        "id": "17",
        "name": "Hourly Congestion Pattern",
        "description": "Flight volume and delay by scheduled departure hour of day",
        "category": "temporal",
        "sql": """
            SELECT
                (f.crs_dep_time / 100) AS hour_of_day,
                COUNT(*) AS total_flights,
                ROUND(AVG(CASE WHEN f.cancelled = 0 THEN f.dep_delay END), 2) AS avg_dep_delay,
                ROUND(AVG(CASE WHEN f.cancelled = 0 THEN f.arr_delay END), 2) AS avg_arr_delay,
                SUM(CASE WHEN f.dep_delay > 60 THEN 1 ELSE 0 END) AS severely_delayed,
                ROUND(100.0 * SUM(CASE WHEN f.cancelled = 0 AND f.arr_delay <= 15 THEN 1 ELSE 0 END)
                    / NULLIF(SUM(CASE WHEN f.cancelled = 0 THEN 1 ELSE 0 END), 0), 2) AS ontime_pct
            FROM flights f
            WHERE f.crs_dep_time IS NOT NULL
              AND f.flight_date >= '{start_date}'
              AND f.flight_date < '{end_date}'
            GROUP BY (f.crs_dep_time / 100)
            ORDER BY hour_of_day
        """,
    },
    # ==== Carrier Comparisons (3 queries) ====
    "carrier-ranking": {
        "id": "18",
        "name": "Carrier On-Time Performance Ranking",
        "description": "Full carrier scorecard: on-time, delays, cancellations",
        "category": "carriers",
        "sql": """
            SELECT
                f.reporting_airline,
                a.name AS airline_name,
                COUNT(*) AS total_scheduled,
                SUM(CASE WHEN f.cancelled = 0 THEN 1 ELSE 0 END) AS operated_flights,
                SUM(CASE WHEN f.cancelled = 1 THEN 1 ELSE 0 END) AS cancelled_flights,
                ROUND(100.0 * SUM(CASE WHEN f.cancelled = 1 THEN 1 ELSE 0 END) / COUNT(*), 2) AS cancellation_rate_pct,
                ROUND(AVG(CASE WHEN f.cancelled = 0 THEN f.dep_delay END), 2) AS avg_dep_delay,
                ROUND(AVG(CASE WHEN f.cancelled = 0 THEN f.arr_delay END), 2) AS avg_arr_delay,
                ROUND(100.0 * SUM(CASE WHEN f.cancelled = 0 AND f.arr_delay <= 15 THEN 1 ELSE 0 END)
                    / NULLIF(SUM(CASE WHEN f.cancelled = 0 THEN 1 ELSE 0 END), 0), 2) AS ontime_pct,
                ROUND(AVG(f.distance), 0) AS avg_route_distance_miles
            FROM flights f
            LEFT JOIN airlines a ON f.reporting_airline = a.code
            WHERE f.flight_date >= '{start_date}'
              AND f.flight_date < '{end_date}'
            GROUP BY f.reporting_airline, a.name
            HAVING COUNT(*) >= 1000
            ORDER BY ontime_pct DESC
        """,
    },
    "cancellation-rate": {
        "id": "19",
        "name": "Cancellation Rates by Carrier and Cause",
        "description": "Cancellation frequency and reason breakdown by carrier",
        "category": "carriers",
        "sql": """
            SELECT
                f.reporting_airline,
                a.name AS airline_name,
                COUNT(*) AS total_flights,
                SUM(CASE WHEN f.cancelled = 1 THEN 1 ELSE 0 END) AS total_cancelled,
                ROUND(100.0 * SUM(CASE WHEN f.cancelled = 1 THEN 1 ELSE 0 END) / COUNT(*), 3) AS cancellation_rate_pct,
                SUM(CASE WHEN f.cancellation_code = 'A' THEN 1 ELSE 0 END) AS carrier_cancellations,
                SUM(CASE WHEN f.cancellation_code = 'B' THEN 1 ELSE 0 END) AS weather_cancellations,
                SUM(CASE WHEN f.cancellation_code = 'C' THEN 1 ELSE 0 END) AS nas_cancellations,
                SUM(CASE WHEN f.cancellation_code = 'D' THEN 1 ELSE 0 END) AS security_cancellations
            FROM flights f
            LEFT JOIN airlines a ON f.reporting_airline = a.code
            WHERE f.flight_date >= '{start_date}'
              AND f.flight_date < '{end_date}'
            GROUP BY f.reporting_airline, a.name
            HAVING COUNT(*) >= 100
            ORDER BY cancellation_rate_pct DESC
        """,
    },
    "market-share": {
        "id": "20",
        "name": "Carrier Market Share by Route",
        "description": "Top carriers ranked by flight volume and market share",
        "category": "carriers",
        "sql": """
            WITH carrier_totals AS (
                SELECT
                    f.reporting_airline,
                    a.name AS airline_name,
                    COUNT(*) AS flight_count,
                    COUNT(DISTINCT f.origin || '-' || f.dest) AS routes_served,
                    ROUND(AVG(f.distance), 0) AS avg_distance_miles
                FROM flights f
                LEFT JOIN airlines a ON f.reporting_airline = a.code
                WHERE f.cancelled = 0
                  AND f.flight_date >= '{start_date}'
                  AND f.flight_date < '{end_date}'
                GROUP BY f.reporting_airline, a.name
            ),
            total AS (
                SELECT SUM(flight_count) AS grand_total FROM carrier_totals
            )
            SELECT
                ct.reporting_airline,
                ct.airline_name,
                ct.flight_count,
                ct.routes_served,
                ct.avg_distance_miles,
                ROUND(100.0 * ct.flight_count / t.grand_total, 2) AS market_share_pct
            FROM carrier_totals ct
            CROSS JOIN total t
            ORDER BY ct.flight_count DESC
            LIMIT 20
        """,
    },
}


class FlightDataQueryManager:
    """Manages flight data benchmark queries with parameterization.

    Handles query retrieval, parameter injection, and metadata access
    for the 20 flight data OLAP queries.
    """

    def __init__(self, start_date: str, end_date: str) -> None:
        """Initialize query manager with date range.

        Args:
            start_date: Start date for queries (YYYY-MM-DD format)
            end_date: End date for queries (YYYY-MM-DD format)
        """
        self.start_date = start_date
        self.end_date = end_date

    def get_query(
        self,
        query_key: str,
        params: Optional[dict[str, Any]] = None,
        dialect: str | None = None,
    ) -> str:
        """Get parameterized SQL for a specific query.

        Args:
            query_key: Query identifier (e.g., "ontime-by-carrier")
            params: Optional parameter overrides
            dialect: Optional target SQL dialect.

        Returns:
            Parameterized SQL string

        Raises:
            ValueError: If query_key is not found
        """
        if query_key not in QUERIES:
            # Try by numeric ID
            for key, qdef in QUERIES.items():
                if str(qdef.get("id")) == str(query_key):
                    query_key = key
                    break
            else:
                raise ValueError(f"Unknown query: {query_key!r}. Valid keys: {list(QUERIES.keys())}")

        query_def = QUERIES[query_key]
        sql = query_def["sql"].strip()

        # Apply date range parameters
        effective_params = {
            "start_date": self.start_date,
            "end_date": self.end_date,
        }
        if params:
            effective_params.update(params)

        try:
            rendered = sql.format(**effective_params)
        except KeyError as exc:
            raise ValueError(
                f"Query {query_key!r} requires parameter {exc} not found in: {list(effective_params)}"
            ) from exc

        if dialect in {"postgres", "postgresql"}:
            return sqlglot.transpile(rendered, read="duckdb", write="postgres", identify=True)[0]
        return rendered

    def get_queries(self, dialect: str | None = None) -> dict[str, str]:
        """Get all queries with applied date parameters.

        Returns:
            Dictionary mapping query keys to parameterized SQL strings
        """
        return {key: self.get_query(key, dialect=dialect) for key in QUERIES}

    def get_query_count(self) -> int:
        """Get number of queries."""
        return len(QUERIES)

    def get_categories(self) -> list[str]:
        """Get list of query categories."""
        return sorted(set(q["category"] for q in QUERIES.values()))

    def get_queries_by_category(self, category: str) -> list[str]:
        """Get query keys for a specific category.

        Args:
            category: Category name (ontime, delay, routes, temporal, carriers)

        Returns:
            List of query keys in that category
        """
        return [key for key, q in QUERIES.items() if q["category"] == category]

    def get_query_info(self, query_key: str) -> dict[str, Any]:
        """Get metadata for a specific query.

        Args:
            query_key: Query identifier

        Returns:
            Dictionary with query metadata
        """
        if query_key not in QUERIES:
            raise ValueError(f"Unknown query: {query_key!r}")
        q = QUERIES[query_key]
        return {
            "id": q["id"],
            "name": q["name"],
            "description": q["description"],
            "category": q["category"],
            "key": query_key,
        }
