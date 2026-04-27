"""NYC Taxi OLAP benchmark queries.

Implements representative OLAP analytics queries:
- Temporal aggregations (hourly, daily, monthly)
- Geographic patterns (zone-level analytics)
- Financial analytics (revenue, tips, fares)
- Multi-dimensional analysis

Query sources:
- Todd Schneider's nyc-taxi-data repository
- ClickHouse official documentation
- DuckDB taxi dataset benchmarks
- Mark Litwintschik's database performance analyses

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from datetime import datetime, timedelta
from typing import Any, Optional

import numpy as np

# Query definitions - 25 representative OLAP queries
QUERIES = {
    # ==== Temporal Aggregations ====
    "trips-per-hour": {
        "id": "1",
        "name": "Trips per Hour",
        "description": "Count trips by hour of day",
        "category": "temporal",
        "sql": """
            SELECT
                EXTRACT(HOUR FROM pickup_datetime) as hour,
                COUNT(*) as trip_count
            FROM trips
            WHERE pickup_datetime >= '{start_date}'
              AND pickup_datetime < '{end_date}'
            GROUP BY EXTRACT(HOUR FROM pickup_datetime)
            ORDER BY hour
        """,
        "params": {"duration_days": 30},
    },
    "trips-per-day": {
        "id": "2",
        "name": "Trips per Day",
        "description": "Daily trip counts",
        "category": "temporal",
        "sql": """
            SELECT
                DATE_TRUNC('day', pickup_datetime) as day,
                COUNT(*) as trip_count
            FROM trips
            WHERE pickup_datetime >= '{start_date}'
              AND pickup_datetime < '{end_date}'
            GROUP BY DATE_TRUNC('day', pickup_datetime)
            ORDER BY day
        """,
        "params": {"duration_days": 365},
    },
    "trips-per-month": {
        "id": "3",
        "name": "Trips per Month",
        "description": "Monthly trip counts over time",
        "category": "temporal",
        "sql": """
            SELECT
                DATE_TRUNC('month', pickup_datetime) as month,
                COUNT(*) as trip_count,
                SUM(total_amount) as total_revenue
            FROM trips
            WHERE pickup_datetime >= '{start_date}'
              AND pickup_datetime < '{end_date}'
            GROUP BY DATE_TRUNC('month', pickup_datetime)
            ORDER BY month
        """,
        "params": {"duration_days": 365},
    },
    "trips-by-day-of-week": {
        "id": "4",
        "name": "Trips by Day of Week",
        "description": "Trip patterns by weekday",
        "category": "temporal",
        "sql": """
            SELECT
                EXTRACT(DOW FROM pickup_datetime) as day_of_week,
                COUNT(*) as trip_count,
                AVG(trip_distance) as avg_distance,
                AVG(total_amount) as avg_fare
            FROM trips
            WHERE pickup_datetime >= '{start_date}'
              AND pickup_datetime < '{end_date}'
            GROUP BY EXTRACT(DOW FROM pickup_datetime)
            ORDER BY day_of_week
        """,
        "params": {"duration_days": 90},
    },
    # ==== Geographic Analytics ====
    "top-pickup-zones": {
        "id": "5",
        "name": "Top Pickup Zones",
        "description": "Most popular pickup locations",
        "category": "geographic",
        "sql": """
            SELECT
                t.pickup_location_id,
                z.zone,
                z.borough,
                COUNT(*) as trip_count
            FROM trips t
            LEFT JOIN taxi_zones z ON t.pickup_location_id = z.location_id
            WHERE t.pickup_datetime >= '{start_date}'
              AND t.pickup_datetime < '{end_date}'
            GROUP BY t.pickup_location_id, z.zone, z.borough
            ORDER BY trip_count DESC
            LIMIT 20
        """,
        "params": {"duration_days": 30},
    },
    "top-dropoff-zones": {
        "id": "6",
        "name": "Top Dropoff Zones",
        "description": "Most popular dropoff locations",
        "category": "geographic",
        "sql": """
            SELECT
                t.dropoff_location_id,
                z.zone,
                z.borough,
                COUNT(*) as trip_count
            FROM trips t
            LEFT JOIN taxi_zones z ON t.dropoff_location_id = z.location_id
            WHERE t.pickup_datetime >= '{start_date}'
              AND t.pickup_datetime < '{end_date}'
            GROUP BY t.dropoff_location_id, z.zone, z.borough
            ORDER BY trip_count DESC
            LIMIT 20
        """,
        "params": {"duration_days": 30},
    },
    "top-routes": {
        "id": "7",
        "name": "Top Routes",
        "description": "Most popular pickup-dropoff pairs",
        "category": "geographic",
        "sql": """
            SELECT
                t.pickup_location_id,
                pz.zone as pickup_zone,
                t.dropoff_location_id,
                dz.zone as dropoff_zone,
                COUNT(*) as trip_count,
                AVG(t.trip_distance) as avg_distance,
                AVG(t.total_amount) as avg_fare
            FROM trips t
            LEFT JOIN taxi_zones pz ON t.pickup_location_id = pz.location_id
            LEFT JOIN taxi_zones dz ON t.dropoff_location_id = dz.location_id
            WHERE t.pickup_datetime >= '{start_date}'
              AND t.pickup_datetime < '{end_date}'
            GROUP BY t.pickup_location_id, pz.zone, t.dropoff_location_id, dz.zone
            ORDER BY trip_count DESC
            LIMIT 50
        """,
        "params": {"duration_days": 30},
    },
    "borough-summary": {
        "id": "8",
        "name": "Borough Summary",
        "description": "Trip statistics by borough",
        "category": "geographic",
        "sql": """
            SELECT
                z.borough,
                COUNT(*) as trip_count,
                SUM(t.total_amount) as total_revenue,
                AVG(t.trip_distance) as avg_distance,
                AVG(t.tip_amount) as avg_tip
            FROM trips t
            LEFT JOIN taxi_zones z ON t.pickup_location_id = z.location_id
            WHERE t.pickup_datetime >= '{start_date}'
              AND t.pickup_datetime < '{end_date}'
              AND z.borough IS NOT NULL
            GROUP BY z.borough
            ORDER BY trip_count DESC
        """,
        "params": {"duration_days": 90},
    },
    # ==== Financial Analytics ====
    "revenue-by-payment-type": {
        "id": "9",
        "name": "Revenue by Payment Type",
        "description": "Revenue breakdown by payment method",
        "category": "financial",
        "sql": """
            SELECT
                payment_type,
                COUNT(*) as trip_count,
                SUM(total_amount) as total_revenue,
                SUM(tip_amount) as total_tips,
                AVG(tip_amount / NULLIF(fare_amount, 0)) * 100 as avg_tip_percentage
            FROM trips
            WHERE pickup_datetime >= '{start_date}'
              AND pickup_datetime < '{end_date}'
              AND fare_amount > 0
            GROUP BY payment_type
            ORDER BY total_revenue DESC
        """,
        "params": {"duration_days": 30},
    },
    "fare-distribution": {
        "id": "10",
        "name": "Fare Distribution",
        "description": "Distribution of fare amounts",
        "category": "financial",
        "sql": """
            SELECT
                FLOOR(fare_amount / 5) * 5 as fare_bucket,
                COUNT(*) as trip_count,
                AVG(trip_distance) as avg_distance,
                AVG(tip_amount) as avg_tip
            FROM trips
            WHERE pickup_datetime >= '{start_date}'
              AND pickup_datetime < '{end_date}'
              AND fare_amount BETWEEN 0 AND 100
            GROUP BY FLOOR(fare_amount / 5) * 5
            ORDER BY fare_bucket
        """,
        "params": {"duration_days": 30},
    },
    "tip-analysis": {
        "id": "11",
        "name": "Tip Analysis",
        "description": "Tip patterns by time and location",
        "category": "financial",
        "sql": """
            SELECT
                EXTRACT(HOUR FROM pickup_datetime) as hour,
                COUNT(*) as trip_count,
                AVG(tip_amount) as avg_tip,
                AVG(CASE WHEN fare_amount > 0 THEN tip_amount / fare_amount * 100 END) as avg_tip_pct
            FROM trips
            WHERE pickup_datetime >= '{start_date}'
              AND pickup_datetime < '{end_date}'
              AND payment_type = 1
            GROUP BY EXTRACT(HOUR FROM pickup_datetime)
            ORDER BY hour
        """,
        "params": {"duration_days": 30},
    },
    "surcharge-revenue": {
        "id": "12",
        "name": "Surcharge Revenue",
        "description": "Revenue from surcharges and extras",
        "category": "financial",
        "sql": """
            SELECT
                DATE_TRUNC('month', pickup_datetime) as month,
                SUM(extra) as extra_revenue,
                SUM(mta_tax) as mta_tax_revenue,
                SUM(improvement_surcharge) as improvement_revenue,
                SUM(congestion_surcharge) as congestion_revenue,
                SUM(tolls_amount) as tolls_revenue
            FROM trips
            WHERE pickup_datetime >= '{start_date}'
              AND pickup_datetime < '{end_date}'
            GROUP BY DATE_TRUNC('month', pickup_datetime)
            ORDER BY month
        """,
        "params": {"duration_days": 365},
    },
    # ==== Trip Characteristics ====
    "distance-distribution": {
        "id": "13",
        "name": "Distance Distribution",
        "description": "Distribution of trip distances",
        "category": "characteristics",
        "sql": """
            SELECT
                FLOOR(trip_distance) as distance_miles,
                COUNT(*) as trip_count,
                AVG(total_amount) as avg_fare
            FROM trips
            WHERE pickup_datetime >= '{start_date}'
              AND pickup_datetime < '{end_date}'
              AND trip_distance BETWEEN 0 AND 30
            GROUP BY FLOOR(trip_distance)
            ORDER BY distance_miles
        """,
        "params": {"duration_days": 30},
    },
    "passenger-count-analysis": {
        "id": "14",
        "name": "Passenger Count Analysis",
        "description": "Trip patterns by passenger count",
        "category": "characteristics",
        "sql": """
            SELECT
                passenger_count,
                COUNT(*) as trip_count,
                AVG(trip_distance) as avg_distance,
                AVG(total_amount) as avg_fare,
                AVG(total_amount / NULLIF(trip_distance, 0)) as avg_fare_per_mile
            FROM trips
            WHERE pickup_datetime >= '{start_date}'
              AND pickup_datetime < '{end_date}'
              AND passenger_count BETWEEN 1 AND 6
            GROUP BY passenger_count
            ORDER BY passenger_count
        """,
        "params": {"duration_days": 30},
    },
    "trip-duration-analysis": {
        "id": "15",
        "name": "Trip Duration Analysis",
        "description": "Trip duration patterns",
        "category": "characteristics",
        "sql": """
            SELECT
                FLOOR(EXTRACT(EPOCH FROM (dropoff_datetime - pickup_datetime)) / 60 / 5) * 5 as duration_bucket_min,
                COUNT(*) as trip_count,
                AVG(trip_distance) as avg_distance,
                AVG(total_amount) as avg_fare
            FROM trips
            WHERE pickup_datetime >= '{start_date}'
              AND pickup_datetime < '{end_date}'
              AND dropoff_datetime > pickup_datetime
              AND EXTRACT(EPOCH FROM (dropoff_datetime - pickup_datetime)) BETWEEN 60 AND 7200
            GROUP BY FLOOR(EXTRACT(EPOCH FROM (dropoff_datetime - pickup_datetime)) / 60 / 5) * 5
            ORDER BY duration_bucket_min
        """,
        "params": {"duration_days": 30},
    },
    # ==== Rate Code Analysis ====
    "rate-code-summary": {
        "id": "16",
        "name": "Rate Code Summary",
        "description": "Trip statistics by rate code",
        "category": "rates",
        "sql": """
            SELECT
                rate_code_id,
                COUNT(*) as trip_count,
                AVG(trip_distance) as avg_distance,
                AVG(total_amount) as avg_fare,
                SUM(total_amount) as total_revenue
            FROM trips
            WHERE pickup_datetime >= '{start_date}'
              AND pickup_datetime < '{end_date}'
            GROUP BY rate_code_id
            ORDER BY trip_count DESC
        """,
        "params": {"duration_days": 90},
    },
    "airport-trips": {
        "id": "17",
        "name": "Airport Trips",
        "description": "Analysis of airport trips (rate codes 2, 3)",
        "category": "rates",
        "sql": """
            SELECT
                rate_code_id,
                z.zone as pickup_zone,
                COUNT(*) as trip_count,
                AVG(trip_distance) as avg_distance,
                AVG(total_amount) as avg_fare,
                AVG(tip_amount) as avg_tip
            FROM trips t
            LEFT JOIN taxi_zones z ON t.pickup_location_id = z.location_id
            WHERE t.pickup_datetime >= '{start_date}'
              AND t.pickup_datetime < '{end_date}'
              AND t.rate_code_id IN (2, 3)
            GROUP BY rate_code_id, z.zone
            ORDER BY trip_count DESC
            LIMIT 20
        """,
        "params": {"duration_days": 90},
    },
    # ==== Vendor Analysis ====
    "vendor-comparison": {
        "id": "18",
        "name": "Vendor Comparison",
        "description": "Compare vendors by various metrics",
        "category": "vendor",
        "sql": """
            SELECT
                vendor_id,
                COUNT(*) as trip_count,
                AVG(trip_distance) as avg_distance,
                AVG(total_amount) as avg_fare,
                AVG(tip_amount) as avg_tip,
                SUM(total_amount) as total_revenue
            FROM trips
            WHERE pickup_datetime >= '{start_date}'
              AND pickup_datetime < '{end_date}'
            GROUP BY vendor_id
            ORDER BY trip_count DESC
        """,
        "params": {"duration_days": 30},
    },
    # ==== Complex Analytics ====
    "hourly-zone-heatmap": {
        "id": "19",
        "name": "Hourly Zone Heatmap",
        "description": "Trip density by hour and zone",
        "category": "complex",
        "sql": """
            SELECT
                EXTRACT(HOUR FROM pickup_datetime) as hour,
                pickup_location_id,
                COUNT(*) as trip_count
            FROM trips
            WHERE pickup_datetime >= '{start_date}'
              AND pickup_datetime < '{end_date}'
            GROUP BY EXTRACT(HOUR FROM pickup_datetime), pickup_location_id
            ORDER BY hour, trip_count DESC
        """,
        "params": {"duration_days": 7},
    },
    "weekday-weekend-comparison": {
        "id": "20",
        "name": "Weekday vs Weekend",
        "description": "Compare weekday and weekend patterns",
        "category": "complex",
        "sql": """
            SELECT
                CASE WHEN EXTRACT(DOW FROM pickup_datetime) IN (0, 6) THEN 'weekend' ELSE 'weekday' END as day_type,
                EXTRACT(HOUR FROM pickup_datetime) as hour,
                COUNT(*) as trip_count,
                AVG(trip_distance) as avg_distance,
                AVG(total_amount) as avg_fare
            FROM trips
            WHERE pickup_datetime >= '{start_date}'
              AND pickup_datetime < '{end_date}'
            GROUP BY
                CASE WHEN EXTRACT(DOW FROM pickup_datetime) IN (0, 6) THEN 'weekend' ELSE 'weekday' END,
                EXTRACT(HOUR FROM pickup_datetime)
            ORDER BY day_type, hour
        """,
        "params": {"duration_days": 30},
    },
    "rush-hour-analysis": {
        "id": "21",
        "name": "Rush Hour Analysis",
        "description": "Analysis of rush hour patterns",
        "category": "complex",
        "sql": """
            SELECT
                CASE
                    WHEN EXTRACT(HOUR FROM pickup_datetime) BETWEEN 7 AND 9 THEN 'morning_rush'
                    WHEN EXTRACT(HOUR FROM pickup_datetime) BETWEEN 17 AND 19 THEN 'evening_rush'
                    ELSE 'off_peak'
                END as period,
                COUNT(*) as trip_count,
                AVG(trip_distance) as avg_distance,
                AVG(total_amount) as avg_fare,
                AVG(EXTRACT(EPOCH FROM (dropoff_datetime - pickup_datetime)) / 60) as avg_duration_min
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
            ORDER BY trip_count DESC
        """,
        "params": {"duration_days": 30},
    },
    "monthly-year-over-year": {
        "id": "22",
        "name": "Monthly Year-over-Year",
        "description": "Compare monthly patterns across years",
        "category": "complex",
        "sql": """
            SELECT
                EXTRACT(YEAR FROM pickup_datetime) as year,
                EXTRACT(MONTH FROM pickup_datetime) as month,
                COUNT(*) as trip_count,
                SUM(total_amount) as total_revenue,
                AVG(total_amount) as avg_fare
            FROM trips
            WHERE pickup_datetime >= '{start_date}'
              AND pickup_datetime < '{end_date}'
            GROUP BY EXTRACT(YEAR FROM pickup_datetime), EXTRACT(MONTH FROM pickup_datetime)
            ORDER BY year, month
        """,
        "params": {"duration_days": 730},
    },
    # ==== Point Queries ====
    "single-day-summary": {
        "id": "23",
        "name": "Single Day Summary",
        "description": "Summary statistics for a single day",
        "category": "point",
        "sql": """
            SELECT
                COUNT(*) as trip_count,
                SUM(total_amount) as total_revenue,
                AVG(trip_distance) as avg_distance,
                AVG(total_amount) as avg_fare,
                AVG(tip_amount) as avg_tip,
                MIN(pickup_datetime) as first_trip,
                MAX(pickup_datetime) as last_trip
            FROM trips
            WHERE pickup_datetime >= '{start_date}'
              AND pickup_datetime < '{end_date}'
        """,
        "params": {"duration_days": 1},
    },
    "zone-detail": {
        "id": "24",
        "name": "Zone Detail",
        "description": "Detailed statistics for a specific zone",
        "category": "point",
        "sql": """
            SELECT
                z.zone,
                z.borough,
                COUNT(*) as pickup_count,
                AVG(t.trip_distance) as avg_distance,
                AVG(t.total_amount) as avg_fare,
                SUM(t.total_amount) as total_revenue
            FROM trips t
            JOIN taxi_zones z ON t.pickup_location_id = z.location_id
            WHERE t.pickup_datetime >= '{start_date}'
              AND t.pickup_datetime < '{end_date}'
              AND t.pickup_location_id = {zone_id}
            GROUP BY z.zone, z.borough
        """,
        "params": {"duration_days": 30},
    },
    "full-scan-count": {
        "id": "25",
        "name": "Full Scan Count",
        "description": "Count all trips (baseline scan query)",
        "category": "baseline",
        "sql": """
            SELECT COUNT(*) as total_trips
            FROM trips
        """,
        "params": {},
    },
}

# ==== Green Taxi queries (borough-focused, requires green_trips table) ====
GREEN_QUERIES = {
    "green-borough-trips": {
        "id": "G1",
        "name": "Green Taxi Borough Patterns",
        "description": "Trip patterns by outer borough for Green Taxi (outer-borough specialist)",
        "category": "green-geographic",
        "sql": """
            SELECT
                z.borough,
                COUNT(*) as trip_count,
                AVG(g.trip_distance) as avg_distance,
                AVG(g.total_amount) as avg_fare,
                AVG(g.tip_amount) as avg_tip,
                SUM(g.total_amount) as total_revenue
            FROM green_trips g
            LEFT JOIN taxi_zones z ON g.pickup_location_id = z.location_id
            WHERE g.pickup_datetime >= '{start_date}'
              AND g.pickup_datetime < '{end_date}'
              AND z.borough IS NOT NULL
            GROUP BY z.borough
            ORDER BY trip_count DESC
        """,
        "params": {"duration_days": 90},
    },
    "green-airport-outer-boro": {
        "id": "G2",
        "name": "Green Taxi Airport Pickups from Outer Boroughs",
        "description": "Airport-bound trips originating in outer boroughs (Green Taxi specialty)",
        "category": "green-geographic",
        "sql": """
            SELECT
                pz.borough as pickup_borough,
                pz.zone as pickup_zone,
                dz.zone as dropoff_zone,
                COUNT(*) as trip_count,
                AVG(g.trip_distance) as avg_distance,
                AVG(g.total_amount) as avg_fare
            FROM green_trips g
            LEFT JOIN taxi_zones pz ON g.pickup_location_id = pz.location_id
            LEFT JOIN taxi_zones dz ON g.dropoff_location_id = dz.location_id
            WHERE g.pickup_datetime >= '{start_date}'
              AND g.pickup_datetime < '{end_date}'
              AND dz.service_zone = 'Airports'
              AND pz.borough NOT IN ('Manhattan', 'Unknown')
            GROUP BY pz.borough, pz.zone, dz.zone
            ORDER BY trip_count DESC
            LIMIT 30
        """,
        "params": {"duration_days": 90},
    },
    "green-trip-type-split": {
        "id": "G3",
        "name": "Green Taxi Street-Hail vs Dispatch",
        "description": "Split of Green Taxi trips by type (1=street-hail, 2=dispatch)",
        "category": "green-characteristics",
        "sql": """
            SELECT
                trip_type,
                COUNT(*) as trip_count,
                AVG(trip_distance) as avg_distance,
                AVG(total_amount) as avg_fare,
                AVG(tip_amount) as avg_tip,
                AVG(passenger_count) as avg_passengers
            FROM green_trips
            WHERE pickup_datetime >= '{start_date}'
              AND pickup_datetime < '{end_date}'
              AND trip_type IN (1, 2)
            GROUP BY trip_type
            ORDER BY trip_type
        """,
        "params": {"duration_days": 90},
    },
    "green-top-zones": {
        "id": "G4",
        "name": "Green Taxi Top Pickup Zones",
        "description": "Most popular Green Taxi pickup zones (outer-borough focus)",
        "category": "green-geographic",
        "sql": """
            SELECT
                g.pickup_location_id,
                z.zone,
                z.borough,
                z.service_zone,
                COUNT(*) as trip_count,
                AVG(g.total_amount) as avg_fare
            FROM green_trips g
            LEFT JOIN taxi_zones z ON g.pickup_location_id = z.location_id
            WHERE g.pickup_datetime >= '{start_date}'
              AND g.pickup_datetime < '{end_date}'
            GROUP BY g.pickup_location_id, z.zone, z.borough, z.service_zone
            ORDER BY trip_count DESC
            LIMIT 25
        """,
        "params": {"duration_days": 30},
    },
}

# ==== HVFHV queries (rideshare-specific, requires hvfhv_trips table) ====
HVFHV_QUERIES = {
    "hvfhv-shared-ride-rate": {
        "id": "H1",
        "name": "HVFHV Shared Ride Adoption Rate",
        "description": "Shared ride request and match rates by HVFHV base (Uber/Lyft)",
        "category": "hvfhv-rideshare",
        "sql": """
            SELECT
                hvfhs_license_num,
                COUNT(*) as total_trips,
                SUM(CASE WHEN shared_request_flag = 'Y' THEN 1 ELSE 0 END) as shared_requests,
                SUM(CASE WHEN shared_match_flag = 'Y' THEN 1 ELSE 0 END) as shared_matches,
                ROUND(
                    SUM(CASE WHEN shared_request_flag = 'Y' THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 2
                ) as shared_request_pct,
                ROUND(
                    SUM(CASE WHEN shared_match_flag = 'Y' THEN 1 ELSE 0 END) * 100.0 /
                    NULLIF(SUM(CASE WHEN shared_request_flag = 'Y' THEN 1 ELSE 0 END), 0), 2
                ) as shared_match_rate_pct
            FROM hvfhv_trips
            WHERE pickup_datetime >= '{start_date}'
              AND pickup_datetime < '{end_date}'
            GROUP BY hvfhs_license_num
            ORDER BY total_trips DESC
        """,
        "params": {"duration_days": 30},
    },
    "hvfhv-base-dispatch-patterns": {
        "id": "H2",
        "name": "HVFHV Base Dispatch Patterns",
        "description": "Trip metrics by dispatching base (Uber HV0003, Lyft HV0005, etc.)",
        "category": "hvfhv-rideshare",
        "sql": """
            SELECT
                hvfhs_license_num,
                COUNT(*) as trip_count,
                AVG(trip_miles) as avg_miles,
                AVG(trip_time / 60.0) as avg_duration_min,
                AVG(base_passenger_fare) as avg_passenger_fare,
                AVG(driver_pay) as avg_driver_pay,
                ROUND(AVG(driver_pay / NULLIF(base_passenger_fare, 0)) * 100, 2) as driver_share_pct,
                SUM(base_passenger_fare) as total_revenue
            FROM hvfhv_trips
            WHERE pickup_datetime >= '{start_date}'
              AND pickup_datetime < '{end_date}'
              AND base_passenger_fare > 0
            GROUP BY hvfhs_license_num
            ORDER BY trip_count DESC
        """,
        "params": {"duration_days": 30},
    },
    "hvfhv-driver-pay-analysis": {
        "id": "H3",
        "name": "HVFHV Driver Pay vs Passenger Fare",
        "description": "Distribution of driver pay relative to passenger fare",
        "category": "hvfhv-financial",
        "sql": """
            SELECT
                FLOOR(base_passenger_fare / 5) * 5 as fare_bucket,
                COUNT(*) as trip_count,
                AVG(driver_pay) as avg_driver_pay,
                AVG(tips) as avg_tips,
                AVG(congestion_surcharge) as avg_congestion,
                ROUND(AVG(driver_pay / NULLIF(base_passenger_fare, 0)) * 100, 2) as avg_driver_share_pct
            FROM hvfhv_trips
            WHERE pickup_datetime >= '{start_date}'
              AND pickup_datetime < '{end_date}'
              AND base_passenger_fare BETWEEN 2 AND 100
            GROUP BY FLOOR(base_passenger_fare / 5) * 5
            ORDER BY fare_bucket
        """,
        "params": {"duration_days": 30},
    },
    "hvfhv-wait-time-analysis": {
        "id": "H4",
        "name": "HVFHV Wait Time Analysis",
        "description": "Passenger wait time (request to pickup) by time of day and base",
        "category": "hvfhv-service",
        "sql": """
            SELECT
                hvfhs_license_num,
                EXTRACT(HOUR FROM pickup_datetime) as hour,
                COUNT(*) as trip_count,
                AVG(EXTRACT(EPOCH FROM (pickup_datetime - request_datetime)) / 60) as avg_wait_min,
                PERCENTILE_CONT(0.5) WITHIN GROUP (
                    ORDER BY EXTRACT(EPOCH FROM (pickup_datetime - request_datetime)) / 60
                ) as median_wait_min
            FROM hvfhv_trips
            WHERE pickup_datetime >= '{start_date}'
              AND pickup_datetime < '{end_date}'
              AND request_datetime < pickup_datetime
              AND EXTRACT(EPOCH FROM (pickup_datetime - request_datetime)) BETWEEN 60 AND 1800
            GROUP BY hvfhs_license_num, EXTRACT(HOUR FROM pickup_datetime)
            ORDER BY hvfhs_license_num, hour
        """,
        "params": {"duration_days": 30},
    },
}

# ==== Cross-type comparison queries (requires trips + green_trips + hvfhv_trips) ====
CROSS_TYPE_QUERIES = {
    # w8: Market share, geography, pricing
    "cross-market-share": {
        "id": "X1",
        "name": "Cross-Type Market Share by Month",
        "description": "Monthly trip volume and market share for Yellow, Green, and HVFHV",
        "category": "cross-market",
        "sql": """
            WITH monthly_counts AS (
                SELECT
                    DATE_TRUNC('month', pickup_datetime) as month,
                    'yellow' as taxi_type,
                    COUNT(*) as trip_count
                FROM trips
                WHERE pickup_datetime >= '{start_date}'
                  AND pickup_datetime < '{end_date}'
                GROUP BY DATE_TRUNC('month', pickup_datetime)

                UNION ALL

                SELECT
                    DATE_TRUNC('month', pickup_datetime) as month,
                    'green' as taxi_type,
                    COUNT(*) as trip_count
                FROM green_trips
                WHERE pickup_datetime >= '{start_date}'
                  AND pickup_datetime < '{end_date}'
                GROUP BY DATE_TRUNC('month', pickup_datetime)

                UNION ALL

                SELECT
                    DATE_TRUNC('month', pickup_datetime) as month,
                    'hvfhv' as taxi_type,
                    COUNT(*) as trip_count
                FROM hvfhv_trips
                WHERE pickup_datetime >= '{start_date}'
                  AND pickup_datetime < '{end_date}'
                GROUP BY DATE_TRUNC('month', pickup_datetime)
            ),
            monthly_totals AS (
                SELECT month, SUM(trip_count) as total_trips
                FROM monthly_counts
                GROUP BY month
            )
            SELECT
                mc.month,
                mc.taxi_type,
                mc.trip_count,
                ROUND(mc.trip_count * 100.0 / mt.total_trips, 2) as market_share_pct
            FROM monthly_counts mc
            JOIN monthly_totals mt ON mc.month = mt.month
            ORDER BY mc.month, mc.taxi_type
        """,
        "params": {"duration_days": 365},
    },
    "cross-geographic-coverage": {
        "id": "X2",
        "name": "Cross-Type Geographic Coverage by Borough",
        "description": "Borough-level trip distribution for each taxi type",
        "category": "cross-geographic",
        "sql": """
            SELECT
                z.borough,
                SUM(CASE WHEN src.taxi_type = 'yellow' THEN src.trip_count ELSE 0 END) as yellow_trips,
                SUM(CASE WHEN src.taxi_type = 'green' THEN src.trip_count ELSE 0 END) as green_trips,
                SUM(CASE WHEN src.taxi_type = 'hvfhv' THEN src.trip_count ELSE 0 END) as hvfhv_trips,
                SUM(src.trip_count) as total_trips
            FROM (
                SELECT pickup_location_id, 'yellow' as taxi_type, COUNT(*) as trip_count
                FROM trips
                WHERE pickup_datetime >= '{start_date}'
                  AND pickup_datetime < '{end_date}'
                GROUP BY pickup_location_id

                UNION ALL

                SELECT pickup_location_id, 'green' as taxi_type, COUNT(*) as trip_count
                FROM green_trips
                WHERE pickup_datetime >= '{start_date}'
                  AND pickup_datetime < '{end_date}'
                GROUP BY pickup_location_id

                UNION ALL

                SELECT pickup_location_id, 'hvfhv' as taxi_type, COUNT(*) as trip_count
                FROM hvfhv_trips
                WHERE pickup_datetime >= '{start_date}'
                  AND pickup_datetime < '{end_date}'
                GROUP BY pickup_location_id
            ) src
            JOIN taxi_zones z ON src.pickup_location_id = z.location_id
            GROUP BY z.borough
            ORDER BY total_trips DESC
        """,
        "params": {"duration_days": 30},
    },
    "cross-fare-comparison": {
        "id": "X3",
        "name": "Cross-Type Fare Comparison",
        "description": "Average fare comparison across taxi types (metered vs app-based pricing)",
        "category": "cross-financial",
        "sql": """
            SELECT
                taxi_type,
                COUNT(*) as trip_count,
                AVG(fare) as avg_fare,
                AVG(distance) as avg_distance,
                AVG(fare / NULLIF(distance, 0)) as avg_fare_per_mile,
                PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY fare) as median_fare
            FROM (
                SELECT 'yellow' as taxi_type, total_amount as fare, trip_distance as distance
                FROM trips
                WHERE pickup_datetime >= '{start_date}'
                  AND pickup_datetime < '{end_date}'
                  AND total_amount BETWEEN 2.50 AND 200

                UNION ALL

                SELECT 'green' as taxi_type, total_amount as fare, trip_distance as distance
                FROM green_trips
                WHERE pickup_datetime >= '{start_date}'
                  AND pickup_datetime < '{end_date}'
                  AND total_amount BETWEEN 2.50 AND 200

                UNION ALL

                SELECT 'hvfhv' as taxi_type,
                       base_passenger_fare + tips + tolls + congestion_surcharge as fare,
                       trip_miles as distance
                FROM hvfhv_trips
                WHERE pickup_datetime >= '{start_date}'
                  AND pickup_datetime < '{end_date}'
                  AND base_passenger_fare BETWEEN 2.50 AND 200
            ) all_trips
            WHERE distance > 0
            GROUP BY taxi_type
            ORDER BY avg_fare DESC
        """,
        "params": {"duration_days": 30},
    },
    # w9: Temporal patterns, trends
    "cross-peak-hour-patterns": {
        "id": "X4",
        "name": "Cross-Type Peak Hour Patterns",
        "description": "Hourly trip demand comparison across Yellow, Green, and HVFHV",
        "category": "cross-temporal",
        "sql": """
            SELECT
                hour,
                SUM(CASE WHEN taxi_type = 'yellow' THEN trip_count ELSE 0 END) as yellow_trips,
                SUM(CASE WHEN taxi_type = 'green' THEN trip_count ELSE 0 END) as green_trips,
                SUM(CASE WHEN taxi_type = 'hvfhv' THEN trip_count ELSE 0 END) as hvfhv_trips
            FROM (
                SELECT EXTRACT(HOUR FROM pickup_datetime) as hour, 'yellow' as taxi_type, COUNT(*) as trip_count
                FROM trips
                WHERE pickup_datetime >= '{start_date}'
                  AND pickup_datetime < '{end_date}'
                GROUP BY EXTRACT(HOUR FROM pickup_datetime)

                UNION ALL

                SELECT EXTRACT(HOUR FROM pickup_datetime) as hour, 'green' as taxi_type, COUNT(*) as trip_count
                FROM green_trips
                WHERE pickup_datetime >= '{start_date}'
                  AND pickup_datetime < '{end_date}'
                GROUP BY EXTRACT(HOUR FROM pickup_datetime)

                UNION ALL

                SELECT EXTRACT(HOUR FROM pickup_datetime) as hour, 'hvfhv' as taxi_type, COUNT(*) as trip_count
                FROM hvfhv_trips
                WHERE pickup_datetime >= '{start_date}'
                  AND pickup_datetime < '{end_date}'
                GROUP BY EXTRACT(HOUR FROM pickup_datetime)
            ) hourly
            GROUP BY hour
            ORDER BY hour
        """,
        "params": {"duration_days": 30},
    },
    "cross-weekday-weekend": {
        "id": "X5",
        "name": "Cross-Type Weekday vs Weekend Demand",
        "description": "Weekday vs weekend trip volume shift by taxi type",
        "category": "cross-temporal",
        "sql": """
            SELECT
                CASE WHEN EXTRACT(DOW FROM pickup_datetime) IN (0, 6) THEN 'weekend' ELSE 'weekday' END as day_type,
                taxi_type,
                COUNT(*) as trip_count,
                AVG(distance) as avg_distance
            FROM (
                SELECT pickup_datetime, 'yellow' as taxi_type, trip_distance as distance
                FROM trips
                WHERE pickup_datetime >= '{start_date}'
                  AND pickup_datetime < '{end_date}'

                UNION ALL

                SELECT pickup_datetime, 'green' as taxi_type, trip_distance as distance
                FROM green_trips
                WHERE pickup_datetime >= '{start_date}'
                  AND pickup_datetime < '{end_date}'

                UNION ALL

                SELECT pickup_datetime, 'hvfhv' as taxi_type, trip_miles as distance
                FROM hvfhv_trips
                WHERE pickup_datetime >= '{start_date}'
                  AND pickup_datetime < '{end_date}'
            ) all_trips
            GROUP BY
                CASE WHEN EXTRACT(DOW FROM pickup_datetime) IN (0, 6) THEN 'weekend' ELSE 'weekday' END,
                taxi_type
            ORDER BY day_type, taxi_type
        """,
        "params": {"duration_days": 90},
    },
    "cross-volume-trends": {
        "id": "X6",
        "name": "Cross-Type Volume Trends",
        "description": "Year-over-year volume trends showing Yellow decline vs HVFHV growth",
        "category": "cross-temporal",
        "sql": """
            SELECT
                EXTRACT(YEAR FROM pickup_datetime) as year,
                EXTRACT(MONTH FROM pickup_datetime) as month,
                taxi_type,
                COUNT(*) as trip_count
            FROM (
                SELECT pickup_datetime, 'yellow' as taxi_type
                FROM trips
                WHERE pickup_datetime >= '{start_date}'
                  AND pickup_datetime < '{end_date}'

                UNION ALL

                SELECT pickup_datetime, 'green' as taxi_type
                FROM green_trips
                WHERE pickup_datetime >= '{start_date}'
                  AND pickup_datetime < '{end_date}'

                UNION ALL

                SELECT pickup_datetime, 'hvfhv' as taxi_type
                FROM hvfhv_trips
                WHERE pickup_datetime >= '{start_date}'
                  AND pickup_datetime < '{end_date}'
            ) all_trips
            GROUP BY
                EXTRACT(YEAR FROM pickup_datetime),
                EXTRACT(MONTH FROM pickup_datetime),
                taxi_type
            ORDER BY year, month, taxi_type
        """,
        "params": {"duration_days": 730},
    },
}


class NYCTaxiQueryManager:
    """Manages NYC Taxi benchmark queries.

    By default only exposes the 25 Yellow Taxi queries (QUERIES) for backwards
    compatibility. Pass taxi_type_queries=True to also include Green, HVFHV, and
    cross-type queries.
    """

    def __init__(
        self,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        seed: Optional[int] = None,
        include_green_queries: bool = False,
        include_hvfhv_queries: bool = False,
        include_cross_type_queries: bool = False,
    ) -> None:
        """Initialize query manager.

        Args:
            start_date: Start date for the dataset
            end_date: End date for the dataset
            seed: Random seed for parameter generation
            include_green_queries: Include Green Taxi-specific queries
            include_hvfhv_queries: Include HVFHV-specific queries
            include_cross_type_queries: Include cross-type comparison queries
        """
        self.start_date = start_date or datetime(2019, 1, 1)
        self.end_date = end_date or datetime(2019, 12, 31)
        self.rng = np.random.default_rng(seed)

        # Popular zone IDs for point queries
        self.popular_zones = [132, 138, 161, 162, 163, 164, 186, 230, 234, 236, 237, 239, 261, 262, 263]

        # Build active query registry
        self._active_queries: dict[str, Any] = dict(QUERIES)
        if include_green_queries:
            self._active_queries.update(GREEN_QUERIES)
        if include_hvfhv_queries:
            self._active_queries.update(HVFHV_QUERIES)
        if include_cross_type_queries:
            self._active_queries.update(CROSS_TYPE_QUERIES)

    def get_query(
        self,
        query_id: str,
        params: Optional[dict[str, Any]] = None,
    ) -> str:
        """Get a query with parameters filled in.

        Args:
            query_id: Query identifier
            params: Optional parameter overrides

        Returns:
            Parameterized query string

        Raises:
            ValueError: If query_id is unknown
        """
        if query_id not in self._active_queries:
            raise ValueError(f"Unknown query: {query_id}. Available: {list(self._active_queries.keys())}")

        query_def = self._active_queries[query_id]
        sql = query_def["sql"].strip()

        # Build parameters
        query_params = self._generate_params(query_def, params)

        # Format the query
        return sql.format(**query_params)

    def _generate_params(
        self,
        query_def: dict[str, Any],
        overrides: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Generate query parameters.

        Args:
            query_def: Query definition
            overrides: Parameter overrides

        Returns:
            Dictionary of parameters
        """
        params = {}
        query_params = query_def.get("params", {})
        overrides = overrides or {}

        # Calculate date range
        duration_days = query_params.get("duration_days", 30)

        # Pick a random start point within the dataset
        dataset_days = (self.end_date - self.start_date).days
        max_offset = max(1, dataset_days - duration_days)
        offset_days = int(self.rng.integers(0, max_offset))

        start = self.start_date + timedelta(days=offset_days)
        end = start + timedelta(days=duration_days)

        params["start_date"] = start.strftime("%Y-%m-%d")
        params["end_date"] = end.strftime("%Y-%m-%d")

        # Random zone for point queries
        params["zone_id"] = overrides.get(
            "zone_id",
            self.popular_zones[int(self.rng.integers(0, len(self.popular_zones)))],
        )

        # Apply overrides
        params.update(overrides)

        return params

    def get_queries(self) -> dict[str, str]:
        """Get all active queries with generated parameters.

        Returns:
            Dictionary mapping query IDs to query strings
        """
        return {qid: self.get_query(qid) for qid in self._active_queries}

    def get_query_info(self, query_id: str) -> dict[str, Any]:
        """Get query metadata.

        Args:
            query_id: Query identifier

        Returns:
            Query metadata dictionary
        """
        if query_id not in self._active_queries:
            raise ValueError(f"Unknown query: {query_id}")
        return self._active_queries[query_id]

    def get_queries_by_category(self, category: str) -> list[str]:
        """Get query IDs for a specific category.

        Args:
            category: Query category

        Returns:
            List of query IDs
        """
        return [qid for qid, qdef in self._active_queries.items() if qdef.get("category") == category]

    def get_categories(self) -> list[str]:
        """Get all active query categories.

        Returns:
            List of unique categories
        """
        return list({str(qdef["category"]) for qdef in self._active_queries.values()})

    def get_query_count(self) -> int:
        """Get total number of active queries.

        Returns:
            Number of queries
        """
        return len(self._active_queries)
