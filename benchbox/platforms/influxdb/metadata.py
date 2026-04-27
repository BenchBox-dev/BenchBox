"""Metadata helpers for the InfluxDB adapter.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

from typing import Any


class InfluxDBMetadataMixin:
    """Provide metadata and configuration helpers for InfluxDB."""

    @property
    def platform_name(self) -> str:
        """Return human-readable platform name."""
        mode = getattr(self, "mode", "cloud")
        return f"InfluxDB ({mode.title()})"

    @staticmethod
    def add_cli_arguments(parser) -> None:
        """Add InfluxDB-specific CLI arguments."""
        influx_group = parser.add_argument_group("InfluxDB Arguments")
        influx_group.add_argument(
            "--host",
            type=str,
            default="localhost",
            help="InfluxDB server hostname",
        )
        influx_group.add_argument(
            "--port",
            type=int,
            default=8086,
            help="InfluxDB server port",
        )
        influx_group.add_argument(
            "--token",
            type=str,
            help="InfluxDB authentication token",
        )
        influx_group.add_argument(
            "--org",
            type=str,
            help="InfluxDB organization name",
        )
        influx_group.add_argument(
            "--database",
            type=str,
            default="benchbox",
            help="InfluxDB database (bucket) name",
        )
        influx_group.add_argument(
            "--ssl",
            action="store_true",
            default=True,
            help="Use SSL/TLS connection",
        )
        influx_group.add_argument(
            "--no-ssl",
            dest="ssl",
            action="store_false",
            help="Disable SSL/TLS connection",
        )
        influx_group.add_argument(
            "--mode",
            type=str,
            choices=["core", "cloud"],
            default="cloud",
            help="InfluxDB deployment mode: 'core' for local/OSS, 'cloud' for managed",
        )

    @classmethod
    def from_config(cls, config: dict[str, Any]):
        """Create InfluxDB adapter from unified configuration."""
        adapter_config = {
            "host": config.get("host", "localhost"),
            "port": config.get("port", 8086),
            "token": config.get("token"),
            "org": config.get("org"),
            "database": config.get("database", "benchbox"),
            "ssl": config.get("ssl", True),
            "verify_ssl": config.get("verify_ssl", True),
            "ca_cert_path": config.get("ca_cert_path"),
            "mode": config.get("mode", "cloud"),
        }

        # Pass through other relevant config
        for key in ["tuning_config", "verbose_enabled", "very_verbose"]:
            if key in config:
                adapter_config[key] = config[key]

        return cls(**adapter_config)

    def get_target_dialect(self) -> str:
        """Return the target SQL dialect for InfluxDB.

        InfluxDB 3.x uses standard SQL via FlightSQL, with some extensions
        for time-series operations.
        """
        return "influxdb"

    def get_platform_info(self, connection: Any = None) -> dict[str, Any]:
        """Get InfluxDB platform information.

        Captures InfluxDB configuration including:
        - Connection mode (core/cloud)
        - Database (bucket) name
        - Server version (if available)

        Args:
            connection: Optional InfluxDB connection for querying version

        Returns:
            Platform information dictionary
        """
        mode = getattr(self, "mode", "cloud")

        platform_info = {
            "platform_type": "influxdb",
            "platform_name": f"InfluxDB ({mode.title()})",
            "connection_mode": mode,
            "configuration": {
                "mode": mode,
                "host": getattr(self, "host", None),
                "port": getattr(self, "port", None),
                "database": getattr(self, "database", None),
                "ssl": getattr(self, "ssl", True),
                "org": getattr(self, "org", None),
            },
        }

        # Get client library version
        try:
            from ._dependencies import FLIGHTSQL_AVAILABLE, INFLUXDB3_AVAILABLE

            if INFLUXDB3_AVAILABLE:
                try:
                    import influxdb3

                    platform_info["client_library"] = "influxdb3-python"
                    platform_info["client_library_version"] = getattr(influxdb3, "__version__", None)
                except (ImportError, AttributeError):
                    pass
            elif FLIGHTSQL_AVAILABLE:
                platform_info["client_library"] = "flightsql-dbapi"
                # flightsql-dbapi doesn't expose version easily
                platform_info["client_library_version"] = None
        except ImportError:
            platform_info["client_library_version"] = None

        # Try to get InfluxDB version
        if connection is not None:
            try:
                # InfluxDB 3.x doesn't have a simple version() function
                # Version info is typically in HTTP headers or metadata
                platform_info["platform_version"] = None
            except Exception:
                platform_info["platform_version"] = None
        else:
            platform_info["platform_version"] = None

        return platform_info


__all__ = ["InfluxDBMetadataMixin"]
