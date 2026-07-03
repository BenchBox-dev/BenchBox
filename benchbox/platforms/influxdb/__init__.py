"""InfluxDB platform package.

Provides InfluxDB 3.x support for time series benchmarking via FlightSQL.

InfluxDB 3.x is built on Apache Arrow, DataFusion, and Parquet (FDAP stack),
supporting native SQL queries through the FlightSQL protocol.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from benchbox.utils.dependencies import check_platform_dependencies, get_dependency_error_message

from ._dependencies import (
    FLIGHTSQL_AVAILABLE,
    INFLUXDB3_AVAILABLE,
    INFLUXDB_AVAILABLE,
)
from .adapter import InfluxDBAdapter
from .client import InfluxDBConnection, to_line_protocol
from .metadata import InfluxDBMetadataMixin
from .setup import InfluxDBSetupMixin

__all__ = [
    "InfluxDBAdapter",
    "InfluxDBConnection",
    "InfluxDBMetadataMixin",
    "InfluxDBSetupMixin",
    "INFLUXDB_AVAILABLE",
    "INFLUXDB3_AVAILABLE",
    "FLIGHTSQL_AVAILABLE",
    "to_line_protocol",
    "check_platform_dependencies",
    "get_dependency_error_message",
]

# Register CLI platform options
try:
    from benchbox.core.hooks.platform_hooks import PlatformHookRegistry, PlatformOptionSpec

    PlatformHookRegistry.register_option_specs(
        "influxdb",
        PlatformOptionSpec(
            name="mode",
            choices=["core", "cloud"],
            default="cloud",
            help="InfluxDB deployment mode: 'core' for self-hosted OSS, 'cloud' for managed service",
        ),
        PlatformOptionSpec(
            name="host",
            default="localhost",
            help="InfluxDB server hostname",
        ),
        PlatformOptionSpec(
            name="port",
            default="8086",
            help="InfluxDB server port",
        ),
        PlatformOptionSpec(
            name="token",
            help="InfluxDB authentication token (or set INFLUXDB_TOKEN env var)",
        ),
        PlatformOptionSpec(
            name="org",
            help="InfluxDB organization name",
        ),
        PlatformOptionSpec(
            name="database",
            default="benchbox",
            help="InfluxDB database (bucket) name",
        ),
        PlatformOptionSpec(
            name="ssl",
            default="true",
            help="Use SSL/TLS connection (true/false)",
        ),
    )
except ImportError:
    # CLI module not available (e.g., when using core modules without CLI)
    pass
