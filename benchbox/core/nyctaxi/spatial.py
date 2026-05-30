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

from pathlib import Path
from typing import Any

import yaml

from benchbox.sql_compat.local_exemptions import compat_local


def _load_spatial_specs() -> dict[str, Any]:
    with (Path(__file__).with_name("spatial_specs.yaml")).open(encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


_SPATIAL_SPECS = _load_spatial_specs()
_SPATIAL_QUERIES = _SPATIAL_SPECS["spatial_queries"]

# NYC Taxi Zone centroids (representative points for each zone)
# Source: NYC TLC Zone Shapefiles processed to centroids
# Format: (location_id, longitude, latitude)
TAXI_ZONE_CENTROIDS = {
    int(location_id): tuple(coordinates) for location_id, coordinates in _SPATIAL_SPECS["taxi_zone_centroids"].items()
}

# Extended schema with spatial columns
SPATIAL_SCHEMA_EXTENSION = _SPATIAL_SPECS["spatial_schema_extension"]

# Platform-specific spatial queries
DUCKDB_SPATIAL_QUERIES = _SPATIAL_QUERIES["duckdb"]
POSTGIS_SPATIAL_QUERIES = _SPATIAL_QUERIES["postgres"]
CLICKHOUSE_SPATIAL_QUERIES = _SPATIAL_QUERIES["clickhouse"]


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
