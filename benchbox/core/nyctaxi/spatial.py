# Copyright 2026 Joe Harris / BenchBox Project

# Licensed under the MIT License. See LICENSE file in the project root for details.

from pathlib import Path
from typing import Any

import yaml

from benchbox.sql_compat.local_exemptions import compat_local


def _load_spatial_specs() -> dict[str, Any]:
    with (Path(__file__).with_name("spatial_specs.yaml")).open(encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


_SPATIAL_SPECS = _load_spatial_specs()
_SPATIAL_QUERIES = _SPATIAL_SPECS["spatial_queries"]

TAXI_ZONE_CENTROIDS = {
    int(location_id): tuple(coordinates) for location_id, coordinates in _SPATIAL_SPECS["taxi_zone_centroids"].items()
}

SPATIAL_SCHEMA_EXTENSION = _SPATIAL_SPECS["spatial_schema_extension"]

DUCKDB_SPATIAL_QUERIES = _SPATIAL_QUERIES["duckdb"]
POSTGIS_SPATIAL_QUERIES = _SPATIAL_QUERIES["postgres"]
CLICKHOUSE_SPATIAL_QUERIES = _SPATIAL_QUERIES["clickhouse"]


def get_spatial_queries(platform: str) -> dict[str, dict[str, Any]]:
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
            "h3": False,
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
