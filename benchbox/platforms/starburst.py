"""Starburst platform adapter for managed Trino (Starburst Galaxy).

Starburst Galaxy is a managed Trino service providing serverless distributed
SQL query execution. This adapter inherits from the Trino adapter with
Starburst-specific authentication and connection handling.

Key differences from self-hosted Trino:
- HTTPS on port 443 by default
- Basic authentication with email/role username format
- Starburst Galaxy-specific catalogs and configuration
- No local server management required

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

from benchbox.platforms.base.adapter import DriverIsolationCapability

from .trino import TrinoAdapter

if TYPE_CHECKING:
    pass


class StarburstAdapter(TrinoAdapter):
    """Starburst platform adapter for Starburst Galaxy (managed Trino).

    Starburst Galaxy is a managed Trino service that provides:
    - Serverless distributed SQL query execution
    - Automatic scaling and resource management
    - Built-in data catalogs and connectors
    - Enterprise security and governance

    Connection Configuration:
    - Host: {cluster-name}.trino.galaxy.starburst.io
    - Port: 443 (HTTPS)
    - Username: email/role (e.g., joe@example.com/accountadmin)
    - Password: API key or password

    Environment Variables:
    - STARBURST_HOST: Galaxy cluster hostname
    - STARBURST_USER or STARBURST_USERNAME: User email or email/role
    - STARBURST_PASSWORD: Authentication password or API key
    - STARBURST_ROLE: Role name (appended to username if not already included)
    - STARBURST_CATALOG: Default catalog name

    Example:
        # Using environment variables
        export STARBURST_HOST="my-cluster.trino.galaxy.starburst.io"
        export STARBURST_USER="joe@example.com/accountadmin"
        export STARBURST_PASSWORD="my-password"
        benchbox run --platform starburst --benchmark tpch --scale 0.01

        # Using explicit configuration
        benchbox run --platform starburst --benchmark tpch \\
            --platform-option host=my-cluster.trino.galaxy.starburst.io \\
            --platform-option username=joe@example.com/accountadmin \\
            --platform-option password=my-password
    """

    driver_isolation_capability = DriverIsolationCapability.FEASIBLE_CLIENT_ONLY

    def __init__(self, **config):
        # Configure Starburst Galaxy defaults before calling parent __init__
        self._configure_starburst_defaults(config)

        # Call parent Trino adapter initialization
        super().__init__(**config)

        # Store Starburst-specific attributes
        self.role = config.get("role") or os.environ.get("STARBURST_ROLE")
        self._dialect = "trino"  # Starburst uses Trino SQL dialect

    def _configure_starburst_defaults(self, config: dict[str, Any]) -> None:
        """Configure Starburst Galaxy-specific defaults.

        Reads environment variables and sets Starburst-specific defaults
        for host, port, authentication, and SSL configuration.

        Args:
            config: Configuration dictionary to update with defaults
        """
        # Host configuration (required for Starburst Galaxy)
        if "host" not in config or not config["host"]:
            config["host"] = os.environ.get("STARBURST_HOST")

        # Port defaults to 443 for Starburst Galaxy (HTTPS)
        if "port" not in config or config["port"] is None:
            env_port = os.environ.get("STARBURST_PORT")
            config["port"] = int(env_port) if env_port else 443

        # Username with email/role format
        if "username" not in config or not config["username"]:
            config["username"] = os.environ.get("STARBURST_USER") or os.environ.get("STARBURST_USERNAME")

        # Append role to username if provided separately and not already in username
        role = config.get("role") or os.environ.get("STARBURST_ROLE")
        if role and config.get("username") and "/" not in (config.get("username") or ""):
            config["username"] = f"{config['username']}/{role}"

        # Password for authentication
        if "password" not in config or not config["password"]:
            config["password"] = os.environ.get("STARBURST_PASSWORD")

        # Default catalog from environment
        if "catalog" not in config or not config["catalog"]:
            config["catalog"] = os.environ.get("STARBURST_CATALOG")

        # HTTPS is required for Starburst Galaxy
        if "http_scheme" not in config:
            config["http_scheme"] = "https"

        # SSL verification defaults to True for production security
        if "verify_ssl" not in config:
            config["verify_ssl"] = True

        # Validate required configuration for Starburst Galaxy
        if not config.get("host"):
            raise ValueError(
                "Starburst Galaxy requires host configuration.\n"
                "Provide via:\n"
                "  - Environment variable: STARBURST_HOST\n"
                "  - Config option: --platform-option host=<cluster>.trino.galaxy.starburst.io"
            )

        if not config.get("username"):
            raise ValueError(
                "Starburst Galaxy requires username configuration.\n"
                "Provide via:\n"
                "  - Environment variable: STARBURST_USER or STARBURST_USERNAME\n"
                "  - Config option: --platform-option username=<email>/<role>\n"
                "Example format: joe@example.com/accountadmin"
            )

        if not config.get("password"):
            raise ValueError(
                "Starburst Galaxy requires password configuration.\n"
                "Provide via:\n"
                "  - Environment variable: STARBURST_PASSWORD\n"
                "  - Config option: --platform-option password=<password>"
            )

    @property
    def platform_name(self) -> str:
        return "Starburst"

    def get_platform_info(self, connection: Any = None) -> dict[str, Any]:
        """Get Starburst Galaxy platform information.

        Extends Trino platform info with Starburst-specific details.
        """
        info = super().get_platform_info(connection)
        info["platform_type"] = "starburst"
        info["platform_name"] = "Starburst Galaxy"
        info["connection_mode"] = "cloud"
        info["configuration"]["deployment"] = "managed"
        return info

    def get_target_dialect(self) -> str:
        """Return the target SQL dialect for Starburst (Trino-compatible)."""
        return "trino"

    def _build_friendly_connection_error(self, exc: Exception) -> str | None:
        """Build user-friendly error message for Starburst connection failures."""
        error_str = str(exc).lower()

        # Authentication errors
        if "401" in error_str or "unauthorized" in error_str:
            return (
                "Starburst Galaxy authentication failed.\n"
                "Check your credentials:\n"
                "  - Username format: email/role (e.g., joe@example.com/accountadmin)\n"
                "  - Password: Your Starburst Galaxy password or API key\n"
                "  - Verify credentials at: https://galaxy.starburst.io"
            )

        # Connection errors
        if "connection refused" in error_str or "could not connect" in error_str:
            return (
                f"Cannot connect to Starburst Galaxy at {self.host}:{self.port}.\n"
                "Check:\n"
                "  - Host is correct: {cluster-name}.trino.galaxy.starburst.io\n"
                "  - Network connectivity to Starburst Galaxy\n"
                "  - Any firewall or proxy restrictions"
            )

        # Certificate errors
        if "ssl" in error_str or "certificate" in error_str:
            return (
                "SSL certificate error connecting to Starburst Galaxy.\n"
                "Options:\n"
                "  - Check network proxy settings\n"
                "  - Verify SSL certificate chain\n"
                "  - Use --platform-option verify_ssl=false (not recommended for production)"
            )

        return None

    @staticmethod
    def add_cli_arguments(parser) -> None:
        """Add Starburst-specific CLI arguments."""
        starburst_group = parser.add_argument_group("Starburst Arguments")
        starburst_group.add_argument(
            "--host", type=str, help="Starburst Galaxy hostname (e.g., my-cluster.trino.galaxy.starburst.io)"
        )
        starburst_group.add_argument("--port", type=int, default=443, help="Starburst Galaxy port (default: 443)")
        starburst_group.add_argument("--catalog", type=str, help="Default catalog for queries")
        starburst_group.add_argument("--schema", type=str, default="default", help="Default schema within the catalog")
        starburst_group.add_argument(
            "--username", type=str, help="Username in email/role format (e.g., joe@example.com/accountadmin)"
        )
        starburst_group.add_argument("--password", type=str, help="Password for Starburst Galaxy authentication")
        starburst_group.add_argument(
            "--role", type=str, help="Role name (appended to username if not already included)"
        )
        starburst_group.add_argument(
            "--table-format",
            type=str,
            choices=["memory", "hive", "iceberg", "delta"],
            default="iceberg",
            help="Table format for creating benchmark tables (default: iceberg)",
        )

    @classmethod
    def from_config(cls, config: dict[str, Any]):
        """Create Starburst adapter from unified configuration."""
        from benchbox.platforms.base.config_utils import build_adapter_config

        return cls(
            **build_adapter_config(
                config,
                platform="starburst",
                generated_key="schema",
                fields=[
                    "host",
                    "port",
                    "catalog",
                    "username",
                    "password",
                    "role",
                    "http_scheme",
                    "verify_ssl",
                    "ssl_cert_path",
                    "session_properties",
                    "query_timeout",
                    "timezone",
                    "encoding",
                    "disable_result_cache",
                    "table_format",
                    "staging_root",
                    "source_catalog",
                ],
            )
        )


def _build_starburst_config(
    platform: str,
    options: dict[str, Any],
    overrides: dict[str, Any],
    info: Any,
) -> Any:
    from benchbox.platforms.base.config_utils import build_platform_config

    return build_platform_config(
        platform_type="starburst",
        credential_key="starburst",
        default_display_name="Starburst",
        default_driver_package="trino",
        platform_fields=[
            "host",
            "port",
            "catalog",
            "username",
            "password",
            "role",
            "http_scheme",
            "verify_ssl",
            "ssl_cert_path",
            "session_properties",
            "query_timeout",
            "timezone",
            "table_format",
            "staging_root",
            "schema",
        ],
        options=options,
        overrides=overrides,
        info=info,
    )


# Register the config builder with the platform hook registry
try:
    from benchbox.cli.platform_hooks import PlatformHookRegistry

    PlatformHookRegistry.register_config_builder("starburst", _build_starburst_config)
except ImportError:
    # Platform hooks may not be available in all contexts
    pass
