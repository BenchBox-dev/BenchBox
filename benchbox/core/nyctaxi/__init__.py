"""NYC Taxi OLAP benchmark package.

Provides access to NYC Taxi & Limousine Commission trip data for OLAP benchmarking.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from benchbox.core.nyctaxi.benchmark import NYCTaxiBenchmark
from benchbox.core.nyctaxi.downloader import GreenTaxiDataDownloader, HVFHVDataDownloader, NYCTaxiDataDownloader
from benchbox.core.nyctaxi.queries import NYCTaxiQueryManager
from benchbox.core.nyctaxi.schema import NYC_TAXI_SCHEMA, TaxiType, get_create_tables_sql
from benchbox.core.nyctaxi.spatial import (
    TAXI_ZONE_CENTROIDS,
    check_spatial_support,
    get_all_spatial_queries,
    get_spatial_create_table_sql,
    get_spatial_queries,
)

__all__ = [
    "NYCTaxiBenchmark",
    "NYCTaxiDataDownloader",
    "GreenTaxiDataDownloader",
    "HVFHVDataDownloader",
    "TaxiType",
    "NYCTaxiQueryManager",
    "NYC_TAXI_SCHEMA",
    "get_create_tables_sql",
    # Spatial extensions
    "TAXI_ZONE_CENTROIDS",
    "get_spatial_queries",
    "get_all_spatial_queries",
    "get_spatial_create_table_sql",
    "check_spatial_support",
]
