"""NYC Taxi geospatial extensions for advanced spatial analytics.

Provides platform-specific spatial query implementations for:
- DuckDB Spatial extension
- PostgreSQL/PostGIS
- ClickHouse native geo functions

These queries require spatial extensions that are not portable via SQLGlot,
so each platform has its own implementation.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from typing import Any

from benchbox.sql_compat.local_exemptions import compat_local

# NYC Taxi Zone centroids (representative points for each zone)
# Source: NYC TLC Zone Shapefiles processed to centroids
# Format: (location_id, longitude, latitude)
TAXI_ZONE_CENTROIDS = {
    # EWR (Newark Airport)
    1: (-74.1745, 40.6895),
    # Queens - Jamaica Bay
    2: (-73.8200, 40.6100),
    # Bronx - Allerton/Pelham Gardens
    3: (-73.8500, 40.8650),
    # Manhattan - Alphabet City
    4: (-73.9800, 40.7250),
    # Manhattan - Battery Park
    12: (-74.0170, 40.7030),
    # Manhattan - Battery Park City
    13: (-74.0160, 40.7110),
    # Manhattan - Central Park
    43: (-73.9654, 40.7829),
    # Manhattan - Chinatown
    45: (-73.9970, 40.7150),
    # Manhattan - East Village
    79: (-73.9850, 40.7280),
    # Manhattan - Financial District North
    86: (-74.0090, 40.7100),
    # Manhattan - Financial District South
    87: (-74.0130, 40.7050),
    # Manhattan - Flatiron
    89: (-73.9900, 40.7400),
    # Manhattan - Gramercy
    112: (-73.9830, 40.7370),
    # Manhattan - Greenwich Village North
    116: (-74.0000, 40.7330),
    # Manhattan - Hell's Kitchen South
    125: (-73.9950, 40.7580),
    # Manhattan - Lincoln Square East
    142: (-73.9840, 40.7720),
    # Manhattan - Lincoln Square West
    143: (-73.9880, 40.7740),
    # Manhattan - Midtown Center
    161: (-73.9850, 40.7550),
    # Manhattan - Midtown East
    162: (-73.9730, 40.7560),
    # Manhattan - Midtown North
    163: (-73.9810, 40.7620),
    # Manhattan - Midtown South
    164: (-73.9870, 40.7510),
    # Manhattan - Murray Hill
    170: (-73.9780, 40.7470),
    # Manhattan - Penn Station/Madison Sq West
    186: (-73.9930, 40.7500),
    # Manhattan - SoHo
    209: (-74.0000, 40.7230),
    # Manhattan - Times Sq/Theatre District
    230: (-73.9870, 40.7580),
    # Manhattan - Tribeca/Civic Center
    231: (-74.0070, 40.7160),
    # Manhattan - Upper East Side North
    236: (-73.9550, 40.7750),
    # Manhattan - Upper East Side South
    237: (-73.9630, 40.7680),
    # Manhattan - Upper West Side North
    238: (-73.9700, 40.7880),
    # Manhattan - Upper West Side South
    239: (-73.9780, 40.7810),
    # Manhattan - World Trade Center
    261: (-74.0130, 40.7110),
    # Queens - JFK Airport
    132: (-73.7781, 40.6413),
    # Queens - LaGuardia Airport
    138: (-73.8740, 40.7769),
    # Brooklyn - Downtown Brooklyn/MetroTech
    65: (-73.9860, 40.6930),
    # Brooklyn - Williamsburg (North Side)
    249: (-73.9570, 40.7180),
}

# Extended schema with spatial columns
SPATIAL_SCHEMA_EXTENSION = {
    "taxi_zones_spatial": {
        "description": "NYC TLC taxi zones with polygon geometries",
        "columns": {
            "location_id": {"type": "INTEGER", "description": "Unique zone identifier"},
            "borough": {"type": "VARCHAR(64)", "description": "NYC borough name"},
            "zone": {"type": "VARCHAR(128)", "description": "Zone name"},
            "service_zone": {"type": "VARCHAR(64)", "description": "Service zone type"},
            "centroid_lon": {"type": "DOUBLE", "description": "Centroid longitude"},
            "centroid_lat": {"type": "DOUBLE", "description": "Centroid latitude"},
            # Platform-specific geometry columns added dynamically
        },
        "primary_key": ["location_id"],
    },
}


# =============================================================================
# DuckDB Spatial Queries
# =============================================================================

DUCKDB_SPATIAL_QUERIES = {
    "spatial-distance-top-routes": {
        "id": "S1",
        "name": "Distance-Based Top Routes",
        "description": "Top routes by straight-line distance using ST_Distance",
        "category": "spatial",
        "platform": "duckdb",
        "requires": ["spatial"],
        "sql": """
            SELECT
                t.pickup_location_id,
                t.dropoff_location_id,
                p.zone as pickup_zone,
                d.zone as dropoff_zone,
                COUNT(*) as trip_count,
                AVG(t.trip_distance) as avg_trip_distance,
                AVG(ST_Distance(
                    ST_Point(p.centroid_lon, p.centroid_lat),
                    ST_Point(d.centroid_lon, d.centroid_lat)
                ) * 111.32) as avg_straight_line_km
            FROM trips t
            JOIN taxi_zones_spatial p ON t.pickup_location_id = p.location_id
            JOIN taxi_zones_spatial d ON t.dropoff_location_id = d.location_id
            WHERE t.pickup_datetime >= '{start_date}'
              AND t.pickup_datetime < '{end_date}'
            GROUP BY t.pickup_location_id, t.dropoff_location_id, p.zone, d.zone
            HAVING COUNT(*) > 100
            ORDER BY avg_straight_line_km DESC
            LIMIT 20
        """,
        "params": {"duration_days": 30},
    },
    "spatial-borough-centroids": {
        "id": "S2",
        "name": "Borough Centroid Analysis",
        "description": "Average pickup/dropoff centroids by borough",
        "category": "spatial",
        "platform": "duckdb",
        "requires": ["spatial"],
        "sql": """
            SELECT
                z.borough,
                COUNT(*) as trip_count,
                AVG(z.centroid_lon) as avg_pickup_lon,
                AVG(z.centroid_lat) as avg_pickup_lat,
                ST_AsText(ST_Centroid(ST_Collect(
                    ST_Point(z.centroid_lon, z.centroid_lat)
                ))) as borough_centroid_wkt
            FROM trips t
            JOIN taxi_zones_spatial z ON t.pickup_location_id = z.location_id
            WHERE t.pickup_datetime >= '{start_date}'
              AND t.pickup_datetime < '{end_date}'
            GROUP BY z.borough
            ORDER BY trip_count DESC
        """,
        "params": {"duration_days": 30},
    },
    "spatial-radius-search": {
        "id": "S3",
        "name": "Radius Search from Times Square",
        "description": "Find trips within radius of Times Square",
        "category": "spatial",
        "platform": "duckdb",
        "requires": ["spatial"],
        "sql": """
            SELECT
                z.zone,
                z.borough,
                COUNT(*) as trip_count,
                ST_Distance(
                    ST_Point(z.centroid_lon, z.centroid_lat),
                    ST_Point(-73.9857, 40.7580)
                ) * 111.32 as distance_from_times_sq_km
            FROM trips t
            JOIN taxi_zones_spatial z ON t.pickup_location_id = z.location_id
            WHERE t.pickup_datetime >= '{start_date}'
              AND t.pickup_datetime < '{end_date}'
              AND ST_Distance(
                  ST_Point(z.centroid_lon, z.centroid_lat),
                  ST_Point(-73.9857, 40.7580)
              ) * 111.32 < 5.0
            GROUP BY z.zone, z.borough, z.centroid_lon, z.centroid_lat
            ORDER BY distance_from_times_sq_km
        """,
        "params": {"duration_days": 7},
    },
    "spatial-airport-distance": {
        "id": "S4",
        "name": "Airport Distance Analysis",
        "description": "Trip distances to/from airports (JFK, LGA, EWR)",
        "category": "spatial",
        "platform": "duckdb",
        "requires": ["spatial"],
        "sql": """
            WITH airport_zones AS (
                SELECT location_id, zone, centroid_lon, centroid_lat
                FROM taxi_zones_spatial
                WHERE location_id IN (1, 132, 138)  -- EWR, JFK, LGA
            )
            SELECT
                a.zone as airport,
                z.borough as origin_borough,
                COUNT(*) as trip_count,
                AVG(t.trip_distance) as avg_trip_miles,
                AVG(ST_Distance(
                    ST_Point(z.centroid_lon, z.centroid_lat),
                    ST_Point(a.centroid_lon, a.centroid_lat)
                ) * 111.32) as avg_straight_line_km,
                AVG(t.total_amount) as avg_fare
            FROM trips t
            JOIN taxi_zones_spatial z ON t.pickup_location_id = z.location_id
            JOIN airport_zones a ON t.dropoff_location_id = a.location_id
            WHERE t.pickup_datetime >= '{start_date}'
              AND t.pickup_datetime < '{end_date}'
            GROUP BY a.zone, z.borough
            ORDER BY trip_count DESC
            LIMIT 20
        """,
        "params": {"duration_days": 30},
    },
    "spatial-cross-borough": {
        "id": "S5",
        "name": "Cross-Borough Trip Distances",
        "description": "Analyze trips crossing borough boundaries",
        "category": "spatial",
        "platform": "duckdb",
        "requires": ["spatial"],
        "sql": """
            SELECT
                p.borough as pickup_borough,
                d.borough as dropoff_borough,
                COUNT(*) as trip_count,
                AVG(t.trip_distance) as avg_trip_miles,
                AVG(ST_Distance(
                    ST_Point(p.centroid_lon, p.centroid_lat),
                    ST_Point(d.centroid_lon, d.centroid_lat)
                ) * 111.32) as avg_straight_line_km,
                AVG(t.trip_distance / NULLIF(ST_Distance(
                    ST_Point(p.centroid_lon, p.centroid_lat),
                    ST_Point(d.centroid_lon, d.centroid_lat)
                ) * 111.32 * 0.621371, 0)) as route_efficiency
            FROM trips t
            JOIN taxi_zones_spatial p ON t.pickup_location_id = p.location_id
            JOIN taxi_zones_spatial d ON t.dropoff_location_id = d.location_id
            WHERE t.pickup_datetime >= '{start_date}'
              AND t.pickup_datetime < '{end_date}'
              AND p.borough != d.borough
            GROUP BY p.borough, d.borough
            HAVING COUNT(*) > 1000
            ORDER BY trip_count DESC
        """,
        "params": {"duration_days": 30},
    },
    "spatial-zone-clustering": {
        "id": "S6",
        "name": "Zone Spatial Clustering",
        "description": "Cluster zones by geographic proximity and trip patterns",
        "category": "spatial",
        "platform": "duckdb",
        "requires": ["spatial"],
        "sql": """
            WITH zone_stats AS (
                SELECT
                    z.location_id,
                    z.zone,
                    z.borough,
                    z.centroid_lon,
                    z.centroid_lat,
                    COUNT(*) as pickup_count,
                    AVG(t.total_amount) as avg_fare
                FROM trips t
                JOIN taxi_zones_spatial z ON t.pickup_location_id = z.location_id
                WHERE t.pickup_datetime >= '{start_date}'
                  AND t.pickup_datetime < '{end_date}'
                GROUP BY z.location_id, z.zone, z.borough, z.centroid_lon, z.centroid_lat
            )
            SELECT
                z1.zone as zone1,
                z2.zone as zone2,
                z1.borough,
                ST_Distance(
                    ST_Point(z1.centroid_lon, z1.centroid_lat),
                    ST_Point(z2.centroid_lon, z2.centroid_lat)
                ) * 111.32 as distance_km,
                ABS(z1.pickup_count - z2.pickup_count) as pickup_diff,
                ABS(z1.avg_fare - z2.avg_fare) as fare_diff
            FROM zone_stats z1
            JOIN zone_stats z2 ON z1.location_id < z2.location_id
                AND z1.borough = z2.borough
            WHERE ST_Distance(
                ST_Point(z1.centroid_lon, z1.centroid_lat),
                ST_Point(z2.centroid_lon, z2.centroid_lat)
            ) * 111.32 < 2.0
            ORDER BY distance_km
            LIMIT 50
        """,
        "params": {"duration_days": 30},
    },
    "spatial-manhattan-grid": {
        "id": "S7",
        "name": "Manhattan Grid Analysis",
        "description": "Spatial grid analysis of Manhattan pickups",
        "category": "spatial",
        "platform": "duckdb",
        "requires": ["spatial"],
        "sql": """
            SELECT
                FLOOR(z.centroid_lon * 100) / 100 as lon_bucket,
                FLOOR(z.centroid_lat * 100) / 100 as lat_bucket,
                COUNT(*) as trip_count,
                AVG(t.total_amount) as avg_fare,
                AVG(t.tip_amount) as avg_tip,
                SUM(t.total_amount) as total_revenue
            FROM trips t
            JOIN taxi_zones_spatial z ON t.pickup_location_id = z.location_id
            WHERE t.pickup_datetime >= '{start_date}'
              AND t.pickup_datetime < '{end_date}'
              AND z.borough = 'Manhattan'
            GROUP BY FLOOR(z.centroid_lon * 100) / 100, FLOOR(z.centroid_lat * 100) / 100
            ORDER BY trip_count DESC
            LIMIT 50
        """,
        "params": {"duration_days": 30},
    },
    "spatial-boundary-box": {
        "id": "S8",
        "name": "Bounding Box Query",
        "description": "Find trips within a bounding box (Midtown)",
        "category": "spatial",
        "platform": "duckdb",
        "requires": ["spatial"],
        "sql": """
            SELECT
                z.zone,
                COUNT(*) as trip_count,
                AVG(t.total_amount) as avg_fare,
                AVG(t.trip_distance) as avg_distance
            FROM trips t
            JOIN taxi_zones_spatial z ON t.pickup_location_id = z.location_id
            WHERE t.pickup_datetime >= '{start_date}'
              AND t.pickup_datetime < '{end_date}'
              AND z.centroid_lon BETWEEN -74.01 AND -73.97
              AND z.centroid_lat BETWEEN 40.75 AND 40.77
            GROUP BY z.zone
            ORDER BY trip_count DESC
        """,
        "params": {"duration_days": 7},
    },
    "spatial-nearest-zones": {
        "id": "S9",
        "name": "Nearest Zone Analysis",
        "description": "Find nearest zones to each high-traffic zone",
        "category": "spatial",
        "platform": "duckdb",
        "requires": ["spatial"],
        "sql": """
            WITH high_traffic AS (
                SELECT
                    z.location_id,
                    z.zone,
                    z.centroid_lon,
                    z.centroid_lat,
                    COUNT(*) as trip_count
                FROM trips t
                JOIN taxi_zones_spatial z ON t.pickup_location_id = z.location_id
                WHERE t.pickup_datetime >= '{start_date}'
                  AND t.pickup_datetime < '{end_date}'
                GROUP BY z.location_id, z.zone, z.centroid_lon, z.centroid_lat
                HAVING COUNT(*) > 10000
            )
            SELECT
                h.zone as source_zone,
                h.trip_count as source_trips,
                z.zone as nearest_zone,
                ST_Distance(
                    ST_Point(h.centroid_lon, h.centroid_lat),
                    ST_Point(z.centroid_lon, z.centroid_lat)
                ) * 111.32 as distance_km
            FROM high_traffic h
            JOIN taxi_zones_spatial z ON h.location_id != z.location_id
            WHERE ST_Distance(
                ST_Point(h.centroid_lon, h.centroid_lat),
                ST_Point(z.centroid_lon, z.centroid_lat)
            ) * 111.32 < 1.0
            ORDER BY h.trip_count DESC, distance_km
            LIMIT 50
        """,
        "params": {"duration_days": 30},
    },
    "spatial-trip-direction": {
        "id": "S10",
        "name": "Trip Direction Analysis",
        "description": "Analyze trip directions (N/S/E/W) by time of day",
        "category": "spatial",
        "platform": "duckdb",
        "requires": ["spatial"],
        "sql": """
            SELECT
                EXTRACT(HOUR FROM t.pickup_datetime) as hour,
                CASE
                    WHEN d.centroid_lat > p.centroid_lat + 0.01 THEN 'north'
                    WHEN d.centroid_lat < p.centroid_lat - 0.01 THEN 'south'
                    WHEN d.centroid_lon > p.centroid_lon + 0.01 THEN 'east'
                    WHEN d.centroid_lon < p.centroid_lon - 0.01 THEN 'west'
                    ELSE 'local'
                END as direction,
                COUNT(*) as trip_count,
                AVG(t.trip_distance) as avg_distance,
                AVG(t.total_amount) as avg_fare
            FROM trips t
            JOIN taxi_zones_spatial p ON t.pickup_location_id = p.location_id
            JOIN taxi_zones_spatial d ON t.dropoff_location_id = d.location_id
            WHERE t.pickup_datetime >= '{start_date}'
              AND t.pickup_datetime < '{end_date}'
            GROUP BY EXTRACT(HOUR FROM t.pickup_datetime),
                CASE
                    WHEN d.centroid_lat > p.centroid_lat + 0.01 THEN 'north'
                    WHEN d.centroid_lat < p.centroid_lat - 0.01 THEN 'south'
                    WHEN d.centroid_lon > p.centroid_lon + 0.01 THEN 'east'
                    WHEN d.centroid_lon < p.centroid_lon - 0.01 THEN 'west'
                    ELSE 'local'
                END
            ORDER BY hour, trip_count DESC
        """,
        "params": {"duration_days": 7},
    },
}


# =============================================================================
# PostgreSQL/PostGIS Spatial Queries
# =============================================================================

POSTGIS_SPATIAL_QUERIES = {
    "spatial-distance-top-routes": {
        "id": "S1",
        "name": "Distance-Based Top Routes",
        "description": "Top routes by straight-line distance using ST_Distance",
        "category": "spatial",
        "platform": "postgres",
        "requires": ["postgis"],
        "sql": """
            SELECT
                t.pickup_location_id,
                t.dropoff_location_id,
                p.zone as pickup_zone,
                d.zone as dropoff_zone,
                COUNT(*) as trip_count,
                AVG(t.trip_distance) as avg_trip_distance,
                AVG(ST_Distance(
                    ST_SetSRID(ST_MakePoint(p.centroid_lon, p.centroid_lat), 4326)::geography,
                    ST_SetSRID(ST_MakePoint(d.centroid_lon, d.centroid_lat), 4326)::geography
                ) / 1000) as avg_straight_line_km
            FROM trips t
            JOIN taxi_zones_spatial p ON t.pickup_location_id = p.location_id
            JOIN taxi_zones_spatial d ON t.dropoff_location_id = d.location_id
            WHERE t.pickup_datetime >= '{start_date}'
              AND t.pickup_datetime < '{end_date}'
            GROUP BY t.pickup_location_id, t.dropoff_location_id, p.zone, d.zone
            HAVING COUNT(*) > 100
            ORDER BY avg_straight_line_km DESC
            LIMIT 20
        """,
        "params": {"duration_days": 30},
    },
    "spatial-radius-search": {
        "id": "S3",
        "name": "Radius Search from Times Square",
        "description": "Find trips within radius of Times Square using ST_DWithin",
        "category": "spatial",
        "platform": "postgres",
        "requires": ["postgis"],
        "sql": """
            SELECT
                z.zone,
                z.borough,
                COUNT(*) as trip_count,
                ST_Distance(
                    ST_SetSRID(ST_MakePoint(z.centroid_lon, z.centroid_lat), 4326)::geography,
                    ST_SetSRID(ST_MakePoint(-73.9857, 40.7580), 4326)::geography
                ) / 1000 as distance_from_times_sq_km
            FROM trips t
            JOIN taxi_zones_spatial z ON t.pickup_location_id = z.location_id
            WHERE t.pickup_datetime >= '{start_date}'
              AND t.pickup_datetime < '{end_date}'
              AND ST_DWithin(
                  ST_SetSRID(ST_MakePoint(z.centroid_lon, z.centroid_lat), 4326)::geography,
                  ST_SetSRID(ST_MakePoint(-73.9857, 40.7580), 4326)::geography,
                  5000
              )
            GROUP BY z.zone, z.borough, z.centroid_lon, z.centroid_lat
            ORDER BY distance_from_times_sq_km
        """,
        "params": {"duration_days": 7},
    },
    "spatial-airport-distance": {
        "id": "S4",
        "name": "Airport Distance Analysis",
        "description": "Trip distances to/from airports using PostGIS geography",
        "category": "spatial",
        "platform": "postgres",
        "requires": ["postgis"],
        "sql": """
            WITH airport_zones AS (
                SELECT location_id, zone, centroid_lon, centroid_lat
                FROM taxi_zones_spatial
                WHERE location_id IN (1, 132, 138)
            )
            SELECT
                a.zone as airport,
                z.borough as origin_borough,
                COUNT(*) as trip_count,
                AVG(t.trip_distance) as avg_trip_miles,
                AVG(ST_Distance(
                    ST_SetSRID(ST_MakePoint(z.centroid_lon, z.centroid_lat), 4326)::geography,
                    ST_SetSRID(ST_MakePoint(a.centroid_lon, a.centroid_lat), 4326)::geography
                ) / 1000) as avg_straight_line_km,
                AVG(t.total_amount) as avg_fare
            FROM trips t
            JOIN taxi_zones_spatial z ON t.pickup_location_id = z.location_id
            JOIN airport_zones a ON t.dropoff_location_id = a.location_id
            WHERE t.pickup_datetime >= '{start_date}'
              AND t.pickup_datetime < '{end_date}'
            GROUP BY a.zone, z.borough
            ORDER BY trip_count DESC
            LIMIT 20
        """,
        "params": {"duration_days": 30},
    },
    "spatial-convex-hull": {
        "id": "S11",
        "name": "Borough Convex Hull",
        "description": "Calculate convex hull of pickup locations per borough",
        "category": "spatial",
        "platform": "postgres",
        "requires": ["postgis"],
        "sql": """
            SELECT
                z.borough,
                COUNT(*) as trip_count,
                ST_AsText(ST_ConvexHull(ST_Collect(
                    ST_SetSRID(ST_MakePoint(z.centroid_lon, z.centroid_lat), 4326)
                ))) as convex_hull_wkt,
                ST_Area(ST_ConvexHull(ST_Collect(
                    ST_SetSRID(ST_MakePoint(z.centroid_lon, z.centroid_lat), 4326)::geography
                ))) / 1000000 as area_sq_km
            FROM trips t
            JOIN taxi_zones_spatial z ON t.pickup_location_id = z.location_id
            WHERE t.pickup_datetime >= '{start_date}'
              AND t.pickup_datetime < '{end_date}'
            GROUP BY z.borough
            ORDER BY trip_count DESC
        """,
        "params": {"duration_days": 30},
    },
}


# =============================================================================
# ClickHouse Spatial Queries
# =============================================================================

CLICKHOUSE_SPATIAL_QUERIES = {
    "spatial-distance-top-routes": {
        "id": "S1",
        "name": "Distance-Based Top Routes",
        "description": "Top routes by great-circle distance using geoDistance",
        "category": "spatial",
        "platform": "clickhouse",
        "requires": [],
        "sql": """
            SELECT
                t.pickup_location_id,
                t.dropoff_location_id,
                p.zone as pickup_zone,
                d.zone as dropoff_zone,
                COUNT(*) as trip_count,
                AVG(t.trip_distance) as avg_trip_distance,
                AVG(geoDistance(p.centroid_lon, p.centroid_lat, d.centroid_lon, d.centroid_lat) / 1000) as avg_straight_line_km
            FROM trips t
            JOIN taxi_zones_spatial p ON t.pickup_location_id = p.location_id
            JOIN taxi_zones_spatial d ON t.dropoff_location_id = d.location_id
            WHERE t.pickup_datetime >= '{start_date}'
              AND t.pickup_datetime < '{end_date}'
            GROUP BY t.pickup_location_id, t.dropoff_location_id, p.zone, d.zone
            HAVING COUNT(*) > 100
            ORDER BY avg_straight_line_km DESC
            LIMIT 20
        """,
        "params": {"duration_days": 30},
    },
    "spatial-radius-search": {
        "id": "S3",
        "name": "Radius Search from Times Square",
        "description": "Find trips within radius using greatCircleDistance",
        "category": "spatial",
        "platform": "clickhouse",
        "requires": [],
        "sql": """
            SELECT
                z.zone,
                z.borough,
                COUNT(*) as trip_count,
                geoDistance(-73.9857, 40.7580, z.centroid_lon, z.centroid_lat) / 1000 as distance_from_times_sq_km
            FROM trips t
            JOIN taxi_zones_spatial z ON t.pickup_location_id = z.location_id
            WHERE t.pickup_datetime >= '{start_date}'
              AND t.pickup_datetime < '{end_date}'
              AND geoDistance(-73.9857, 40.7580, z.centroid_lon, z.centroid_lat) < 5000
            GROUP BY z.zone, z.borough, z.centroid_lon, z.centroid_lat
            ORDER BY distance_from_times_sq_km
        """,
        "params": {"duration_days": 7},
    },
    "spatial-geohash-aggregation": {
        "id": "S12",
        "name": "GeoHash Aggregation",
        "description": "Aggregate trips by geohash for efficient spatial bucketing",
        "category": "spatial",
        "platform": "clickhouse",
        "requires": [],
        "sql": """
            SELECT
                geohashEncode(z.centroid_lon, z.centroid_lat, 5) as geohash,
                COUNT(*) as trip_count,
                AVG(t.total_amount) as avg_fare,
                AVG(t.trip_distance) as avg_distance,
                uniq(z.zone) as zone_count
            FROM trips t
            JOIN taxi_zones_spatial z ON t.pickup_location_id = z.location_id
            WHERE t.pickup_datetime >= '{start_date}'
              AND t.pickup_datetime < '{end_date}'
            GROUP BY geohashEncode(z.centroid_lon, z.centroid_lat, 5)
            ORDER BY trip_count DESC
            LIMIT 50
        """,
        "params": {"duration_days": 30},
    },
    "spatial-h3-aggregation": {
        "id": "S13",
        "name": "H3 Index Aggregation",
        "description": "Aggregate trips using Uber's H3 hexagonal indexing",
        "category": "spatial",
        "platform": "clickhouse",
        "requires": [],
        "sql": """
            SELECT
                geoToH3(z.centroid_lon, z.centroid_lat, 7) as h3_index,
                COUNT(*) as trip_count,
                AVG(t.total_amount) as avg_fare,
                SUM(t.total_amount) as total_revenue,
                uniq(z.zone) as zone_count
            FROM trips t
            JOIN taxi_zones_spatial z ON t.pickup_location_id = z.location_id
            WHERE t.pickup_datetime >= '{start_date}'
              AND t.pickup_datetime < '{end_date}'
            GROUP BY geoToH3(z.centroid_lon, z.centroid_lat, 7)
            ORDER BY trip_count DESC
            LIMIT 50
        """,
        "params": {"duration_days": 30},
    },
}


def get_spatial_queries(platform: str) -> dict[str, dict[str, Any]]:
    """Get spatial queries for a specific platform.

    Args:
        platform: Platform name (duckdb, postgres, clickhouse)

    Returns:
        Dictionary of spatial query definitions
    """
    platform_lower = platform.lower()

    if platform_lower == "duckdb":
        return DUCKDB_SPATIAL_QUERIES
    elif platform_lower in ("postgres", "postgresql", "postgis"):
        return POSTGIS_SPATIAL_QUERIES
    elif platform_lower in {"clickhouse", "clickhouse-local", "clickhouse-server"}:
        return CLICKHOUSE_SPATIAL_QUERIES
    else:
        return {}


def get_all_spatial_queries() -> dict[str, dict[str, dict[str, Any]]]:
    """Get all spatial queries organized by platform.

    Returns:
        Dictionary mapping platform -> query_id -> query_definition
    """
    return {
        "duckdb": DUCKDB_SPATIAL_QUERIES,
        "postgres": POSTGIS_SPATIAL_QUERIES,
        "clickhouse": CLICKHOUSE_SPATIAL_QUERIES,
    }


@compat_local(
    kind="storage_layout",
    platform_specific=True,
    reason=(
        "Returns a wholly different DDL body per dialect: DuckDB uses standard types+PK, "
        "PostgreSQL/PostGIS adds a GEOMETRY generated column + GIST index, "
        "ClickHouse uses MergeTree with ClickHouse-native types. "
        "Each dialect requires a distinct table definition - not a policy decision."
    ),
)
def get_spatial_create_table_sql(dialect: str = "duckdb") -> str:
    """Generate CREATE TABLE SQL for the spatial zones table.

    Args:
        dialect: SQL dialect (duckdb, postgres, clickhouse)

    Returns:
        CREATE TABLE statement
    """
    if dialect == "duckdb":
        return """
CREATE TABLE taxi_zones_spatial (
    location_id INTEGER PRIMARY KEY,
    borough VARCHAR,
    zone VARCHAR,
    service_zone VARCHAR,
    centroid_lon DOUBLE,
    centroid_lat DOUBLE
);
        """.strip()

    elif dialect in ("postgres", "postgresql"):
        return """
CREATE TABLE taxi_zones_spatial (
    location_id INTEGER PRIMARY KEY,
    borough TEXT,
    zone TEXT,
    service_zone TEXT,
    centroid_lon DOUBLE PRECISION,
    centroid_lat DOUBLE PRECISION,
    geom GEOMETRY(POINT, 4326) GENERATED ALWAYS AS (
        ST_SetSRID(ST_MakePoint(centroid_lon, centroid_lat), 4326)
    ) STORED
);
CREATE INDEX idx_taxi_zones_spatial_geom ON taxi_zones_spatial USING GIST (geom);
        """.strip()

    elif dialect == "clickhouse":
        return """
CREATE TABLE taxi_zones_spatial (
    location_id Int32,
    borough String,
    zone String,
    service_zone String,
    centroid_lon Float64,
    centroid_lat Float64
)
ENGINE = MergeTree()
ORDER BY location_id;
        """.strip()

    else:
        # Standard SQL fallback
        return """
CREATE TABLE taxi_zones_spatial (
    location_id INTEGER PRIMARY KEY,
    borough VARCHAR(64),
    zone VARCHAR(128),
    service_zone VARCHAR(64),
    centroid_lon DOUBLE,
    centroid_lat DOUBLE
);
        """.strip()


def check_spatial_support(platform: str) -> dict[str, bool]:
    """Check what spatial features are available for a platform.

    Args:
        platform: Platform name

    Returns:
        Dictionary of feature -> supported status
    """
    platform_lower = platform.lower()

    if platform_lower == "duckdb":
        return {
            "basic_spatial": True,
            "st_distance": True,
            "st_point": True,
            "st_centroid": True,
            "st_collect": True,
            "geohash": False,
            "h3": False,
            "geography": False,
        }
    elif platform_lower in ("postgres", "postgresql"):
        return {
            "basic_spatial": True,
            "st_distance": True,
            "st_point": True,
            "st_centroid": True,
            "st_collect": True,
            "st_convexhull": True,
            "st_dwithin": True,
            "geohash": True,
            "h3": False,  # Requires extension
            "geography": True,
        }
    elif platform_lower in {"clickhouse", "clickhouse-local", "clickhouse-server"}:
        return {
            "basic_spatial": True,
            "geo_distance": True,
            "geohash": True,
            "h3": True,
            "st_distance": False,
            "st_point": False,
            "geography": False,
        }
    else:
        return {
            "basic_spatial": False,
        }
