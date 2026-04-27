"""Flight Data OLAP benchmark package.

US Bureau of Transportation Statistics On-Time Performance data
for aviation analytics benchmarking.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from benchbox.core.flightdata.benchmark import FlightDataBenchmark
from benchbox.core.flightdata.downloader import FlightDataDownloader
from benchbox.core.flightdata.queries import FlightDataQueryManager
from benchbox.core.flightdata.schema import FLIGHT_SCHEMA, get_create_tables_sql

__all__ = [
    "FlightDataBenchmark",
    "FlightDataDownloader",
    "FlightDataQueryManager",
    "FLIGHT_SCHEMA",
    "get_create_tables_sql",
]
