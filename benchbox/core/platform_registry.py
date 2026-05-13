"""
Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.

Platform Registry and Factory

This module provides a centralized registry and factory for platform adapters,
enabling dynamic discovery and instantiation of platform adapters.
"""

import argparse
import importlib
from dataclasses import dataclass, field
from typing import Any, Literal, Optional

from benchbox.core.schemas import LibraryInfo, PlatformInfo
from benchbox.platforms.base import PlatformAdapter


@dataclass
class DeploymentCapability:
    """Describes requirements and characteristics of a specific deployment mode.

    Deployment modes represent different ways to run the same database engine:
    - local: Embedded or in-process (DuckDB, chDB, SQLite)
    - self-hosted: User-managed server/cluster (ClickHouse server, Trino)
    - managed: Vendor-managed cloud service (MotherDuck, ClickHouse Cloud, Snowflake)

    Attributes:
        mode: Deployment category (local, self-hosted, or managed)
        requires_credentials: Whether authentication is needed
        requires_cloud_storage: Whether cloud storage staging is required for data loading
        requires_network: Whether network connectivity to a remote service is required
        default_for_platform: Whether this is the platform's default deployment mode
        display_name: Human-readable name for this deployment mode
        description: Description of this deployment mode
        dependencies: Additional package dependencies for this deployment mode
        auth_methods: Supported authentication methods (password, oauth, token, api_key, etc.)
    """

    mode: Literal["local", "self-hosted", "managed"]
    requires_credentials: bool = False
    requires_cloud_storage: bool = False
    requires_network: bool = False
    default_for_platform: bool = False
    display_name: str = ""
    description: str = ""
    dependencies: list[str] = field(default_factory=list)
    auth_methods: list[str] = field(default_factory=list)


@dataclass
class PlatformCapability:
    """Platform execution mode and deployment capabilities.

    Tracks which execution modes (SQL, DataFrame) a platform supports,
    its default mode, and deployment mode information.

    Attributes:
        supports_sql: Whether platform supports SQL execution mode
        supports_dataframe: Whether platform supports DataFrame execution mode
        default_mode: Default execution mode (sql or dataframe)
        deployment_modes: Available deployment modes mapped by name
        default_deployment: Name of the default deployment mode
        platform_family: Platform family for dialect inheritance (e.g., "duckdb", "clickhouse")
        inherits_from: Parent platform name for configuration inheritance
    """

    supports_sql: bool = False
    supports_dataframe: bool = False
    default_mode: Literal["sql", "dataframe"] = "sql"
    deployment_modes: dict[str, DeploymentCapability] = field(default_factory=dict)
    default_deployment: str = "local"
    platform_family: Optional[str] = None
    inherits_from: Optional[str] = None
    unsupported_benchmarks: dict[str, str] = field(default_factory=dict)


class PlatformRegistry:
    """Registry for platform adapters with factory functionality.

    This is the single source of truth for platform definitions, metadata,
    and adapter registration. The get_platform_adapter() function in
    benchbox/platforms/__init__.py delegates to this registry for adapter
    lookup while handling CLI-specific concerns like error messages.

    Alias Support:
        Platform aliases (e.g., 'sqlite3' -> 'sqlite') are resolved via
        resolve_platform_name() before any lookup. This allows users to
        use familiar names while the registry maintains canonical names.
    """

    _adapters: dict[str, type[PlatformAdapter]] = {}
    _availability_cache: Optional[dict[str, bool]] = None
    _platform_metadata: dict[str, dict[str, Any]] = {}
    _auto_registered: bool = False

    # Platform name aliases mapping user-friendly names to canonical names
    _platform_aliases: dict[str, str] = {
        "sqlite3": "sqlite",
        "azure_synapse": "synapse",
        "fabric_lakehouse": "fabric-lakehouse",
        # Fabric Warehouse: hyphen form is preferred CLI key; underscore form is legacy
        "fabric-dw": "fabric_dw",
    }

    @classmethod
    def resolve_platform_name(cls, platform_name: str) -> str:
        """Resolve user input (with possible alias) to canonical platform name.

        This method normalizes platform names and resolves aliases to their
        canonical counterparts. It should be called before any platform lookup.

        Args:
            platform_name: User-provided platform name (may be an alias)

        Returns:
            Canonical platform name (lowercase)

        Examples:
            >>> PlatformRegistry.resolve_platform_name("SQLite3")
            'sqlite'
            >>> PlatformRegistry.resolve_platform_name("azure_synapse")
            'synapse'
            >>> PlatformRegistry.resolve_platform_name("DuckDB")
            'duckdb'
        """
        normalized = platform_name.lower()
        return cls._platform_aliases.get(normalized, normalized)

    @classmethod
    def get_all_aliases(cls) -> dict[str, str]:
        """Get all platform name aliases.

        Returns:
            Dictionary mapping alias names to their canonical platform names.
            Useful for CLI help and documentation.

        Examples:
            >>> PlatformRegistry.get_all_aliases()
            {'sqlite3': 'sqlite', 'azure_synapse': 'synapse'}
        """
        return cls._platform_aliases.copy()

    @classmethod
    def _build_platform_metadata(cls) -> dict[str, dict[str, Any]]:
        """Build comprehensive platform metadata registry."""
        base_metadata: dict[str, dict[str, Any]] = {
            "duckdb": {
                "display_name": "DuckDB",
                "description": "Columnar OLAP engine • Single-node • In-memory",
                "category": "analytical",
                "libraries": [{"name": "duckdb", "required": True}],
                "requirements": ["duckdb>=0.8.0"],
                "installation_command": "uv add duckdb",
                "adoption": "mainstream",
                "supports": ["olap", "in_memory", "columnar"],
                "driver_package": "duckdb",
                "capabilities": {
                    "supports_sql": True,
                    "supports_dataframe": False,
                    "default_mode": "sql",
                    "platform_family": "duckdb",
                    "default_deployment": "local",
                    "deployment_modes": {
                        "local": {
                            "mode": "local",
                            "display_name": "DuckDB Local",
                            "description": "Embedded in-process DuckDB",
                            "requires_credentials": False,
                            "requires_cloud_storage": False,
                            "requires_network": False,
                            "default_for_platform": True,
                            "dependencies": ["duckdb"],
                            "auth_methods": [],
                        },
                    },
                },
            },
            "datafusion": {
                "display_name": "DataFusion",
                "description": "Arrow-based SQL • Single-node • In-memory",
                "category": "analytical",
                "libraries": [{"name": "datafusion", "required": True}],
                "requirements": ["datafusion>=34.0.0"],
                "installation_command": "uv add datafusion",
                "adoption": "emerging",
                "supports": ["olap", "in_memory", "columnar", "arrow", "dataframe"],
                "driver_package": "datafusion",
                "capabilities": {"supports_sql": True, "supports_dataframe": True, "default_mode": "sql"},
            },
            "sqlite": {
                "display_name": "SQLite",
                "description": "Row-based OLTP database • Single-node • File-based",
                "category": "embedded",
                "libraries": [{"name": "sqlite3", "required": True}],
                "requirements": ["sqlite3 (built-in)"],
                "installation_command": "Built-in Python library",
                "adoption": "niche",
                "supports": ["transactional", "file_based"],
                "driver_package": None,
                "capabilities": {"supports_sql": True, "supports_dataframe": False, "default_mode": "sql"},
            },
            "polars": {
                "display_name": "Polars",
                "description": "DataFrame engine • In-memory • Columnar",
                "category": "analytical",
                "libraries": [{"name": "polars", "required": True}],
                "requirements": ["polars>=0.20.0"],
                "installation_command": "uv add polars",
                "adoption": "established",
                "supports": ["olap", "in_memory", "columnar", "dataframe"],
                "driver_package": "polars",
                "capabilities": {"supports_sql": False, "supports_dataframe": True, "default_mode": "dataframe"},
            },
            "motherduck": {
                "display_name": "MotherDuck",
                "description": "Serverless DuckDB cloud • Managed • Cloud storage",
                "category": "cloud",
                "libraries": [{"name": "duckdb", "required": True}],
                "requirements": ["duckdb>=0.9.0"],
                "installation_command": "uv add duckdb",
                "adoption": "emerging",
                "supports": ["olap", "cloud", "columnar", "serverless"],
                "driver_package": "duckdb",
                "capabilities": {
                    "supports_sql": True,
                    "supports_dataframe": False,
                    "default_mode": "sql",
                    "platform_family": "duckdb",
                    "inherits_from": "duckdb",
                    "default_deployment": "managed",
                    "deployment_modes": {
                        "managed": {
                            "mode": "managed",
                            "display_name": "MotherDuck Cloud",
                            "description": "Serverless DuckDB in MotherDuck cloud",
                            "requires_credentials": True,
                            "requires_cloud_storage": False,
                            "requires_network": True,
                            "default_for_platform": True,
                            "dependencies": ["duckdb"],
                            "auth_methods": ["token"],
                        },
                    },
                },
            },
        }

        experimental_metadata = {
            "clickhouse": {
                "display_name": "ClickHouse",
                "description": "Columnar OLAP database • Local/server • Distributed",
                "category": "analytical",
                "libraries": [
                    {"name": "clickhouse_driver", "required": True, "import_name": "clickhouse_driver"},
                    {"name": "chdb", "required": False, "description": "Local ClickHouse"},
                ],
                "requirements": ["clickhouse-driver>=0.2.0"],
                "installation_command": "uv add clickhouse-driver",
                "adoption": "established",
                "supports": ["olap", "columnar", "distributed"],
                "driver_package": "clickhouse-driver",
                "capabilities": {
                    "supports_sql": True,
                    "supports_dataframe": False,
                    "default_mode": "sql",
                    "platform_family": "clickhouse",
                    "default_deployment": "local",
                    "deployment_modes": {
                        "local": {
                            "mode": "local",
                            "display_name": "ClickHouse Local (chDB)",
                            "description": "Embedded ClickHouse via chDB library",
                            "requires_credentials": False,
                            "requires_cloud_storage": False,
                            "requires_network": False,
                            "default_for_platform": True,
                            "dependencies": ["chdb"],
                            "auth_methods": [],
                        },
                        "server": {
                            "mode": "self-hosted",
                            "display_name": "ClickHouse Server",
                            "description": "Self-hosted ClickHouse server or cluster",
                            "requires_credentials": True,
                            "requires_cloud_storage": False,
                            "requires_network": True,
                            "default_for_platform": False,
                            "dependencies": ["clickhouse-driver"],
                            "auth_methods": ["password"],
                        },
                    },
                },
            },
            "clickhouse-local": {
                "display_name": "ClickHouse Local (chDB)",
                "description": "Embedded ClickHouse via chDB • In-process • Zero network",
                "category": "analytical",
                "libraries": [
                    {"name": "chdb", "required": True, "import_name": "chdb"},
                ],
                "requirements": ["chdb>=0.10.0"],
                "installation_command": "uv add benchbox --extra clickhouse-local",
                "adoption": "established",
                "supports": ["olap", "columnar", "embedded", "in-process"],
                "driver_package": "chdb",
                "capabilities": {
                    "supports_sql": True,
                    "supports_dataframe": False,
                    "default_mode": "sql",
                    "platform_family": "clickhouse",
                    "inherits_from": "clickhouse",
                },
            },
            "clickhouse-server": {
                "display_name": "ClickHouse Server",
                "description": "Self-hosted ClickHouse • Docker/dedicated • High-performance columnar",
                "category": "analytical",
                "libraries": [
                    {"name": "clickhouse_driver", "required": True, "import_name": "clickhouse_driver"},
                ],
                "requirements": ["clickhouse-driver>=0.2.0"],
                "installation_command": "uv add benchbox --extra clickhouse-server",
                "adoption": "established",
                "supports": ["olap", "columnar", "distributed", "self-hosted"],
                "driver_package": "clickhouse-driver",
                "capabilities": {
                    "supports_sql": True,
                    "supports_dataframe": False,
                    "default_mode": "sql",
                    "platform_family": "clickhouse",
                    "inherits_from": "clickhouse",
                },
            },
            "clickhouse-cloud": {
                "display_name": "ClickHouse Cloud",
                "description": "Managed ClickHouse • Serverless/dedicated • Cloud analytics",
                "category": "cloud",
                "libraries": [
                    {"name": "clickhouse_connect", "required": True, "import_name": "clickhouse_connect"},
                ],
                "requirements": ["clickhouse-connect>=0.10.0"],
                "installation_command": "uv add benchbox --extra clickhouse-cloud",
                "adoption": "emerging",
                "supports": ["olap", "columnar", "distributed", "serverless", "cloud"],
                "driver_package": "clickhouse-connect",
                "capabilities": {
                    "supports_sql": True,
                    "supports_dataframe": False,
                    "default_mode": "sql",
                    "platform_family": "clickhouse",
                    "inherits_from": "clickhouse",
                    "default_deployment": "managed",
                    "deployment_modes": {
                        "managed": {
                            "mode": "managed",
                            "display_name": "ClickHouse Cloud",
                            "description": "ClickHouse Cloud managed service",
                            "requires_credentials": True,
                            "requires_cloud_storage": True,
                            "requires_network": True,
                            "default_for_platform": True,
                            "dependencies": ["clickhouse-connect"],
                            "auth_methods": ["password", "oauth"],
                        },
                    },
                },
            },
            "bigquery": {
                "display_name": "Google BigQuery",
                "description": "Columnar data warehouse • Serverless • Petabyte-scale",
                "category": "cloud",
                "libraries": [
                    {"name": "google.cloud.bigquery", "required": True, "import_name": "google.cloud.bigquery"},
                    {"name": "google.cloud.storage", "required": True, "import_name": "google.cloud.storage"},
                ],
                "requirements": ["google-cloud-bigquery>=3.0.0", "google-cloud-storage>=2.0.0"],
                "installation_command": "uv add google-cloud-bigquery google-cloud-storage",
                "adoption": "mainstream",
                "supports": ["olap", "serverless", "petabyte_scale"],
                "driver_package": "google-cloud-bigquery",
                "capabilities": {"supports_sql": True, "supports_dataframe": False, "default_mode": "sql"},
            },
            "databricks": {
                "display_name": "Databricks SQL",
                "description": "Lakehouse platform • Distributed • Spark-based",
                "category": "cloud",
                "libraries": [{"name": "databricks.sql", "required": True, "import_name": "databricks.sql"}],
                "requirements": ["databricks-sql-connector>=2.0.0"],
                "installation_command": "uv add databricks-sql-connector",
                "adoption": "mainstream",
                "supports": ["olap", "spark", "lakehouse"],
                "driver_package": "databricks-sql-connector",
                "capabilities": {"supports_sql": True, "supports_dataframe": True, "default_mode": "sql"},
            },
            "databricks-df": {
                "display_name": "Databricks DataFrame",
                "description": "Databricks with PySpark DataFrame API • Databricks Connect",
                "category": "cloud",
                "libraries": [
                    {"name": "databricks.sql", "required": True, "import_name": "databricks.sql"},
                    {"name": "databricks.connect", "required": True, "import_name": "databricks.connect"},
                ],
                "requirements": ["databricks-sql-connector>=2.0.0", "databricks-connect>=14.0.0"],
                "installation_command": "uv add databricks-sql-connector databricks-connect",
                "adoption": "niche",
                "supports": ["olap", "spark", "lakehouse", "dataframe"],
                "driver_package": "databricks-connect",
                "capabilities": {"supports_sql": True, "supports_dataframe": True, "default_mode": "dataframe"},
            },
            "snowflake": {
                "display_name": "Snowflake",
                "description": "Columnar data warehouse • Serverless • Multi-cloud",
                "category": "cloud",
                "libraries": [{"name": "snowflake.connector", "required": True, "import_name": "snowflake.connector"}],
                "requirements": ["snowflake-connector-python>=3.0.0"],
                "installation_command": "uv add snowflake-connector-python",
                "adoption": "mainstream",
                "supports": ["olap", "serverless", "multi_cloud"],
                "driver_package": "snowflake-connector-python",
                "capabilities": {"supports_sql": True, "supports_dataframe": False, "default_mode": "sql"},
            },
            "redshift": {
                "display_name": "Amazon Redshift",
                "description": "Columnar data warehouse • Distributed • AWS MPP",
                "category": "cloud",
                "libraries": [
                    {"name": "redshift_connector", "required": True},
                    {"name": "boto3", "required": True},
                ],
                "requirements": ["redshift-connector>=2.0.0", "boto3>=1.20.0"],
                "installation_command": "uv add redshift-connector boto3",
                "adoption": "established",
                "supports": ["olap", "columnar", "aws"],
                "driver_package": "redshift-connector",
                "capabilities": {"supports_sql": True, "supports_dataframe": False, "default_mode": "sql"},
            },
            "trino": {
                "display_name": "Trino",
                "description": "Distributed SQL • Federated • Multi-source",
                "category": "distributed",
                "libraries": [{"name": "trino", "required": True}],
                "requirements": ["trino>=0.328.0"],
                "installation_command": "uv add trino",
                "adoption": "established",
                "supports": ["olap", "federated", "distributed"],
                "driver_package": "trino",
                "notes": "Supports Trino and Starburst Enterprise. For PrestoDB use presto-python-client. For AWS Athena use the athena adapter.",
                "capabilities": {
                    "supports_sql": True,
                    "supports_dataframe": False,
                    "default_mode": "sql",
                    "platform_family": "trino",
                    "default_deployment": "self-hosted",
                    "deployment_modes": {
                        "self-hosted": {
                            "mode": "self-hosted",
                            "display_name": "Trino Self-Hosted",
                            "description": "Self-hosted Trino cluster",
                            "requires_credentials": True,
                            "requires_cloud_storage": False,
                            "requires_network": True,
                            "default_for_platform": True,
                            "dependencies": ["trino"],
                            "auth_methods": ["password", "oauth"],
                        },
                    },
                },
            },
            "starburst": {
                "display_name": "Starburst",
                "description": "Managed Trino • Starburst Galaxy • Serverless",
                "category": "cloud",
                "libraries": [{"name": "trino", "required": True}],
                "requirements": ["trino>=0.328.0"],
                "installation_command": "uv add trino",
                "adoption": "emerging",
                "supports": ["olap", "federated", "distributed", "serverless", "cloud"],
                "driver_package": "trino",
                "notes": "Starburst Galaxy managed Trino service. Uses trino Python driver with HTTPS. For self-hosted Trino use the trino adapter.",
                "capabilities": {
                    "supports_sql": True,
                    "supports_dataframe": False,
                    "default_mode": "sql",
                    "platform_family": "trino",
                    "inherits_from": "trino",
                    "default_deployment": "managed",
                    "deployment_modes": {
                        "managed": {
                            "mode": "managed",
                            "display_name": "Starburst Galaxy",
                            "description": "Starburst Galaxy managed Trino service",
                            "requires_credentials": True,
                            "requires_cloud_storage": False,
                            "requires_network": True,
                            "default_for_platform": True,
                            "dependencies": ["trino"],
                            "auth_methods": ["password", "api_key"],
                        },
                    },
                },
            },
            "presto": {
                "display_name": "PrestoDB",
                "description": "Distributed SQL • Federated • Meta fork",
                "category": "distributed",
                "libraries": [{"name": "prestodb", "required": True, "import_name": "prestodb"}],
                "requirements": ["presto-python-client>=0.8.4"],
                "installation_command": "uv add presto-python-client",
                "adoption": "niche",
                "supports": ["olap", "federated", "distributed"],
                "driver_package": "presto-python-client",
                "notes": "Supports PrestoDB (Meta's fork) with X-Presto-* headers. For Trino/Starburst use the trino adapter. For AWS Athena use the athena adapter.",
                "capabilities": {"supports_sql": True, "supports_dataframe": False, "default_mode": "sql"},
            },
            "postgresql": {
                "display_name": "PostgreSQL",
                "description": "Relational database • COPY loading",
                "category": "relational",
                "libraries": [{"name": "psycopg", "required": True}],
                "requirements": ["psycopg[binary]>=3.1"],
                "installation_command": "uv add 'psycopg[binary]'",
                "adoption": "established",
                "supports": ["olap", "oltp", "relational"],
                "driver_package": "psycopg",
                "notes": "Supports PostgreSQL 12+. COPY-based bulk loading. For time-series workloads use timescaledb.",
                "capabilities": {"supports_sql": True, "supports_dataframe": False, "default_mode": "sql"},
            },
            "timescaledb": {
                "display_name": "TimescaleDB",
                "description": "Time-series database • Hypertables • Compression",
                "category": "timeseries",
                "libraries": [{"name": "psycopg", "required": True}],
                "requirements": ["psycopg[binary]>=3.1"],
                "installation_command": "uv add 'psycopg[binary]'",
                "adoption": "niche",
                "supports": ["timeseries", "olap", "compression"],
                "driver_package": "psycopg",
                "notes": "PostgreSQL extension for time-series. Automatic hypertables, compression policies. Requires TimescaleDB 2.x on server.",
                "capabilities": {
                    "supports_sql": True,
                    "supports_dataframe": False,
                    "default_mode": "sql",
                    "platform_family": "timescaledb",
                    "default_deployment": "self-hosted",
                    "deployment_modes": {
                        "self-hosted": {
                            "mode": "self-hosted",
                            "display_name": "TimescaleDB Self-Hosted",
                            "description": "Self-hosted TimescaleDB server",
                            "requires_credentials": True,
                            "requires_cloud_storage": False,
                            "requires_network": True,
                            "default_for_platform": True,
                            "dependencies": ["psycopg[binary]"],
                            "auth_methods": ["password"],
                        },
                        "cloud": {
                            "mode": "managed",
                            "display_name": "TigerData",
                            "description": "TigerData managed PostgreSQL service",
                            "requires_credentials": True,
                            "requires_cloud_storage": False,
                            "requires_network": True,
                            "default_for_platform": False,
                            "dependencies": ["psycopg[binary]"],
                            "auth_methods": ["password"],
                        },
                    },
                },
            },
            "pg-mooncake": {
                "display_name": "pg_mooncake",
                "description": "Columnstore PostgreSQL • Parquet/Iceberg • DuckDB Execution",
                "category": "olap",
                "libraries": [{"name": "psycopg", "required": True}],
                "requirements": ["psycopg[binary]>=3.1"],
                "installation_command": "uv add 'psycopg[binary]'",
                "adoption": "emerging",
                "supports": ["olap", "columnstore", "analytics"],
                "driver_package": "psycopg",
                "notes": "PostgreSQL extension adding native columnstore tables (Parquet/Iceberg) with DuckDB execution. Requires pg_mooncake on server. Conflicts with standalone pg_duckdb (shared libduckdb.so).",
                "capabilities": {
                    "supports_sql": True,
                    "supports_dataframe": False,
                    "default_mode": "sql",
                    "platform_family": "pg_mooncake",
                    "conflicts_with": ["pg-duckdb"],
                    "default_deployment": "self-hosted",
                    "deployment_modes": {
                        "self-hosted": {
                            "mode": "self-hosted",
                            "display_name": "pg_mooncake Self-Hosted",
                            "description": "Self-hosted PostgreSQL with pg_mooncake extension",
                            "requires_credentials": True,
                            "requires_cloud_storage": False,
                            "requires_network": True,
                            "default_for_platform": True,
                            "dependencies": ["psycopg[binary]"],
                            "auth_methods": ["password"],
                        },
                    },
                },
            },
            "cedardb": {
                "display_name": "CedarDB",
                "description": "High-performance OLAP/OLTP • PostgreSQL-compatible • Formerly Umbra",
                "category": "olap",
                "libraries": [{"name": "psycopg", "required": True}],
                "requirements": ["psycopg[binary]>=3.1"],
                "installation_command": "uv add 'psycopg[binary]'",
                "adoption": "emerging",
                "supports": ["olap", "oltp", "relational"],
                "driver_package": "psycopg",
                "notes": "CedarDB (formerly Umbra) is a standalone RDBMS with PostgreSQL wire protocol compatibility. Not a PostgreSQL extension - connects via standard psycopg3 (psycopg) drivers.",
                "capabilities": {
                    "supports_sql": True,
                    "supports_dataframe": False,
                    "default_mode": "sql",
                    "platform_family": "cedardb",
                    "default_deployment": "self-hosted",
                    "deployment_modes": {
                        "self-hosted": {
                            "mode": "self-hosted",
                            "display_name": "CedarDB Self-Hosted",
                            "description": "Self-hosted CedarDB server",
                            "requires_credentials": True,
                            "requires_cloud_storage": False,
                            "requires_network": True,
                            "default_for_platform": True,
                            "dependencies": ["psycopg[binary]"],
                            "auth_methods": ["password"],
                        },
                    },
                },
            },
            "pg-duckdb": {
                "display_name": "pg_duckdb",
                "description": "DuckDB-accelerated PostgreSQL • Vectorized OLAP • MotherDuck",
                "category": "olap",
                "libraries": [{"name": "psycopg", "required": True}],
                "requirements": ["psycopg[binary]>=3.1"],
                "installation_command": "uv add 'psycopg[binary]'",
                "adoption": "emerging",
                "supports": ["olap", "analytics"],
                "driver_package": "psycopg",
                "notes": "PostgreSQL extension embedding DuckDB vectorized execution. Requires pg_duckdb 1.0+ on server. Conflicts with pg_mooncake (shared libduckdb.so).",
                "capabilities": {
                    "supports_sql": True,
                    "supports_dataframe": False,
                    "default_mode": "sql",
                    "platform_family": "pg_duckdb",
                    "conflicts_with": ["pg-mooncake"],
                    "default_deployment": "self-hosted",
                    "deployment_modes": {
                        "self-hosted": {
                            "mode": "self-hosted",
                            "display_name": "pg_duckdb Self-Hosted",
                            "description": "Self-hosted PostgreSQL with pg_duckdb extension",
                            "requires_credentials": True,
                            "requires_cloud_storage": False,
                            "requires_network": True,
                            "default_for_platform": True,
                            "dependencies": ["psycopg[binary]"],
                            "auth_methods": ["password"],
                        },
                        "motherduck": {
                            "mode": "managed",
                            "display_name": "pg_duckdb + MotherDuck",
                            "description": "pg_duckdb with MotherDuck cloud offload for hybrid queries",
                            "requires_credentials": True,
                            "requires_cloud_storage": False,
                            "requires_network": True,
                            "default_for_platform": False,
                            "dependencies": ["psycopg[binary]"],
                            "auth_methods": ["token"],
                        },
                    },
                },
            },
            "synapse": {
                "display_name": "Azure Synapse Analytics",
                "description": "Cloud data warehouse • Dedicated SQL Pool • Azure MPP",
                "category": "cloud",
                "libraries": [
                    {"name": "pyodbc", "required": True},
                    {"name": "azure.storage.blob", "required": False, "import_name": "azure.storage.blob"},
                    {"name": "azure.identity", "required": False, "import_name": "azure.identity"},
                ],
                "requirements": ["pyodbc>=4.0.0"],
                "installation_command": "uv add pyodbc azure-storage-blob azure-identity",
                "adoption": "established",
                "supports": ["olap", "columnar", "azure", "distributed"],
                "driver_package": "pyodbc",
                "notes": "Supports Azure Synapse Dedicated SQL Pools. COPY INTO for bulk loading. T-SQL dialect.",
                "capabilities": {"supports_sql": True, "supports_dataframe": False, "default_mode": "sql"},
            },
            "fabric_dw": {
                "display_name": "Microsoft Fabric Warehouse",
                "description": "Microsoft Fabric Warehouse • OneLake • Delta Lake native",
                "category": "cloud",
                "libraries": [
                    {"name": "pyodbc", "required": True},
                    {"name": "azure.identity", "required": True, "import_name": "azure.identity"},
                    {
                        "name": "azure.storage.filedatalake",
                        "required": False,
                        "import_name": "azure.storage.filedatalake",
                    },
                ],
                "requirements": ["pyodbc>=4.0.0", "azure-identity>=1.15.0"],
                "installation_command": "uv add pyodbc azure-identity azure-storage-file-datalake",
                "adoption": "niche",
                "supports": ["olap", "columnar", "azure", "delta_lake", "onelake"],
                "driver_package": "pyodbc",
                "notes": "Supports Fabric Warehouse only (not Lakehouse). Entra ID auth only. OneLake + COPY INTO for bulk loading. T-SQL dialect (subset).",
                "capabilities": {"supports_sql": True, "supports_dataframe": False, "default_mode": "sql"},
            },
            "firebolt": {
                "display_name": "Firebolt",
                "description": "Vectorized analytics • Local/Cloud • PG-wire",
                "category": "cloud",
                "libraries": [
                    {"name": "firebolt.db", "required": True, "import_name": "firebolt.db"},
                ],
                "requirements": ["firebolt-sdk>=1.18.0"],
                "installation_command": "uv add firebolt-sdk",
                "adoption": "emerging",
                "supports": ["olap", "vectorized", "columnar", "local", "cloud"],
                "driver_package": "firebolt-sdk",
                "notes": "Supports Firebolt Core (free, local Docker) and Firebolt Cloud. PostgreSQL-compatible SQL dialect. Vectorized query execution optimized for analytics.",
                "capabilities": {
                    "supports_sql": True,
                    "supports_dataframe": False,
                    "default_mode": "sql",
                    "platform_family": "firebolt",
                    "default_deployment": "core",
                    "deployment_modes": {
                        "core": {
                            "mode": "local",
                            "display_name": "Firebolt Core",
                            "description": "Free local Firebolt via Docker container",
                            "requires_credentials": False,
                            "requires_cloud_storage": False,
                            "requires_network": False,
                            "default_for_platform": True,
                            "dependencies": ["firebolt-sdk"],
                            "auth_methods": [],
                        },
                        "cloud": {
                            "mode": "managed",
                            "display_name": "Firebolt Cloud",
                            "description": "Firebolt Cloud managed service",
                            "requires_credentials": True,
                            "requires_cloud_storage": True,
                            "requires_network": True,
                            "default_for_platform": False,
                            "dependencies": ["firebolt-sdk"],
                            "auth_methods": ["oauth", "service_account"],
                        },
                    },
                },
            },
            "starrocks": {
                "display_name": "StarRocks",
                "description": "Columnar analytics engine • Distributed • Fast OLAP",
                "category": "analytical",
                "libraries": [
                    {"name": "pymysql", "required": True, "import_name": "pymysql"},
                ],
                "requirements": ["pymysql>=1.1.0"],
                "installation_command": "uv add pymysql",
                "adoption": "emerging",
                "supports": ["olap", "columnar", "distributed", "mpp"],
                "driver_package": "pymysql",
                "capabilities": {
                    "supports_sql": True,
                    "supports_dataframe": False,
                    "default_mode": "sql",
                    "platform_family": "starrocks",
                    "default_deployment": "self-hosted",
                    "deployment_modes": {
                        "self-hosted": {
                            "mode": "self-hosted",
                            "display_name": "StarRocks Self-Hosted",
                            "description": "Self-hosted StarRocks cluster",
                            "requires_credentials": True,
                            "requires_cloud_storage": False,
                            "requires_network": True,
                            "default_for_platform": True,
                            "dependencies": ["pymysql"],
                            "auth_methods": ["password"],
                        },
                    },
                },
            },
            "databend": {
                "display_name": "Databend",
                "description": "Cloud-native OLAP • Rust • Snowflake-compatible",
                "category": "cloud",
                "libraries": [
                    {"name": "databend_driver", "required": True, "import_name": "databend_driver"},
                ],
                "requirements": ["databend-driver>=0.28.0"],
                "installation_command": "uv add databend-driver",
                "adoption": "emerging",
                "supports": ["olap", "cloud", "columnar", "object_storage", "snowflake_compatible"],
                "driver_package": "databend-driver",
                "notes": "Cloud-native Rust-based data warehouse with Snowflake-compatible SQL. Compute/storage separation on object storage (S3, GCS, Azure Blob). Uses Snowflake dialect as sqlglot translation proxy.",
                "capabilities": {
                    "supports_sql": True,
                    "supports_dataframe": False,
                    "default_mode": "sql",
                    "platform_family": "databend",
                    "default_deployment": "cloud",
                    "deployment_modes": {
                        "cloud": {
                            "mode": "managed",
                            "display_name": "Databend Cloud",
                            "description": "Databend Cloud managed service",
                            "requires_credentials": True,
                            "requires_cloud_storage": True,
                            "requires_network": True,
                            "default_for_platform": True,
                            "dependencies": ["databend-driver"],
                            "auth_methods": ["password"],
                        },
                        "self-hosted": {
                            "mode": "self-hosted",
                            "display_name": "Databend Self-Hosted",
                            "description": "User-managed Databend cluster with object storage",
                            "requires_credentials": True,
                            "requires_cloud_storage": True,
                            "requires_network": True,
                            "default_for_platform": False,
                            "dependencies": ["databend-driver"],
                            "auth_methods": ["password"],
                        },
                    },
                },
            },
            "doris": {
                "display_name": "Apache Doris",
                "description": "MPP OLAP • Real-time analytics • MySQL protocol",
                "category": "distributed",
                "libraries": [{"name": "pymysql", "required": True}],
                "requirements": ["pymysql>=1.0.0"],
                "installation_command": "uv add pymysql",
                "adoption": "emerging",
                "supports": ["olap", "mpp", "columnar", "real-time", "vectorized"],
                "driver_package": "pymysql",
                "notes": "Apache Doris 2.0+ with vectorized execution. MySQL protocol on port 9030, Stream Load on port 8030. SQLGlot 'doris' dialect.",
                "capabilities": {
                    "supports_sql": True,
                    "supports_dataframe": False,
                    "default_mode": "sql",
                    "platform_family": "doris",
                    "default_deployment": "self-hosted",
                    "deployment_modes": {
                        "self-hosted": {
                            "mode": "self-hosted",
                            "display_name": "Apache Doris Self-Hosted",
                            "description": "Self-hosted Apache Doris cluster",
                            "requires_credentials": True,
                            "requires_cloud_storage": False,
                            "requires_network": True,
                            "default_for_platform": True,
                            "dependencies": ["pymysql"],
                            "auth_methods": ["password"],
                        },
                    },
                },
            },
            "singlestore": {
                "display_name": "SingleStore",
                "description": "Distributed SQL • Real-time analytics • MySQL protocol",
                "category": "distributed",
                "libraries": [{"name": "singlestoredb", "required": True, "import_name": "singlestoredb"}],
                "requirements": ["singlestoredb>=1.0.0"],
                "installation_command": "uv add singlestoredb",
                "adoption": "emerging",
                "supports": ["olap", "htap", "distributed", "columnstore", "real-time", "mysql-compatible"],
                "driver_package": "singlestoredb",
                "notes": "SingleStore 8.0+ with columnstore analytics. MySQL wire protocol on port 3306. SQLGlot 'mysql' dialect. Supports both Helios (cloud) and self-managed deployments.",
                "capabilities": {
                    "supports_sql": True,
                    "supports_dataframe": False,
                    "default_mode": "sql",
                    "platform_family": "singlestore",
                    "default_deployment": "self-hosted",
                    "deployment_modes": {
                        "self-hosted": {
                            "mode": "self-hosted",
                            "display_name": "SingleStore Self-Managed",
                            "description": "Self-managed SingleStore cluster",
                            "requires_credentials": True,
                            "requires_cloud_storage": False,
                            "requires_network": True,
                            "default_for_platform": True,
                            "dependencies": ["singlestoredb"],
                            "auth_methods": ["password"],
                        },
                        "cloud": {
                            "mode": "managed",
                            "display_name": "SingleStore Helios",
                            "description": "SingleStore Helios managed cloud service",
                            "requires_credentials": True,
                            "requires_cloud_storage": False,
                            "requires_network": True,
                            "default_for_platform": False,
                            "dependencies": ["singlestoredb"],
                            "auth_methods": ["password"],
                        },
                    },
                },
            },
            "influxdb": {
                "display_name": "InfluxDB",
                "description": "Time series database • FlightSQL • Arrow-native",
                "category": "timeseries",
                "libraries": [
                    {"name": "influxdb3", "required": True, "import_name": "influxdb3"},
                    {"name": "flightsql", "required": False, "alternative": True, "import_name": "flightsql"},
                ],
                "requirements": ["influxdb3-python>=0.1.0"],
                "installation_command": "uv add influxdb3-python",
                "adoption": "niche",
                "supports": ["timeseries", "olap", "arrow", "flightsql"],
                "driver_package": "influxdb3-python",
                "notes": "InfluxDB 3.x time series database with native SQL support via FlightSQL. Built on Apache Arrow, DataFusion, and Parquet. Optimized for TSBS DevOps workloads.",
                "capabilities": {"supports_sql": True, "supports_dataframe": False, "default_mode": "sql"},
            },
            "questdb": {
                "display_name": "QuestDB",
                "description": "Time-series database • PG wire protocol • High-performance ingestion",
                "category": "timeseries",
                "libraries": [{"name": "psycopg", "required": True}, {"name": "requests", "required": True}],
                "requirements": ["psycopg[binary]>=3.1", "requests>=2.28.0"],
                "installation_command": "uv add benchbox --extra questdb",
                "adoption": "emerging",
                "supports": ["timeseries", "olap", "columnar", "high_throughput"],
                "driver_package": "psycopg",
                "notes": "QuestDB 7.0+ time-series database. PostgreSQL wire protocol for queries, REST API for data import. Optimized for fast ingestion and time-series analytics.",
                "capabilities": {
                    "supports_sql": True,
                    "supports_dataframe": False,
                    "default_mode": "sql",
                    "platform_family": "questdb",
                    "default_deployment": "self-hosted",
                    "deployment_modes": {
                        "self-hosted": {
                            "mode": "self-hosted",
                            "display_name": "QuestDB Self-Hosted",
                            "description": "Self-hosted QuestDB server (Docker recommended)",
                            "requires_credentials": True,
                            "requires_cloud_storage": False,
                            "requires_network": True,
                            "default_for_platform": True,
                            "dependencies": ["psycopg[binary]"],
                            "auth_methods": ["password"],
                        },
                    },
                    "unsupported_benchmarks": {
                        "vector_search": (
                            "QuestDB 9.3.4 has no VECTOR column type. "
                            "Schema creation fails immediately. "
                            "No fix planned: requires QuestDB to add native vector support."
                        ),
                    },
                },
            },
            "athena": {
                "display_name": "Amazon Athena",
                "description": "Serverless SQL • S3 data lake • Pay-per-query",
                "category": "cloud",
                "libraries": [
                    {"name": "pyathena", "required": True},
                    {"name": "boto3", "required": True},
                ],
                "requirements": ["pyathena>=3.0.0", "boto3>=1.20.0"],
                "installation_command": "uv add pyathena boto3",
                "adoption": "established",
                "supports": ["olap", "serverless", "s3", "data_lake"],
                "driver_package": "pyathena",
                "notes": "AWS serverless query service using Trino under the hood. Pay-per-query pricing ($5/TB scanned). Native S3 and Glue Data Catalog integration.",
                "capabilities": {"supports_sql": True, "supports_dataframe": False, "default_mode": "sql"},
            },
            "glue": {
                "display_name": "AWS Glue",
                "description": "Managed Spark • Serverless ETL • Pay-per-DPU",
                "category": "cloud",
                "libraries": [
                    {"name": "boto3", "required": True},
                ],
                "requirements": ["boto3>=1.34.0"],
                "installation_command": "uv add boto3",
                "adoption": "niche",
                "supports": ["olap", "serverless", "spark", "etl", "s3"],
                "driver_package": "boto3",
                "notes": "AWS managed Spark ETL service. Pay-per-DPU pricing (~$0.44/DPU-hour). Uses Glue Data Catalog for metadata. Supports both SQL and DataFrame execution modes.",
                "capabilities": {"supports_sql": True, "supports_dataframe": True, "default_mode": "sql"},
            },
            "emr-serverless": {
                "display_name": "Amazon EMR Serverless",
                "description": "Serverless Spark • Sub-second startup • Pay-per-use",
                "category": "cloud",
                "libraries": [
                    {"name": "boto3", "required": True},
                ],
                "requirements": ["boto3>=1.34.0"],
                "installation_command": "uv add boto3",
                "adoption": "niche",
                "supports": ["olap", "serverless", "spark", "s3"],
                "driver_package": "boto3",
                "notes": "AWS serverless Spark with automatic scaling and sub-second startup. Pay per vCPU-hour and memory-GB-hour. Uses Glue Data Catalog for metadata.",
                "capabilities": {"supports_sql": True, "supports_dataframe": True, "default_mode": "sql"},
            },
            "athena-spark": {
                "display_name": "Amazon Athena for Apache Spark",
                "description": "Interactive Spark • Sub-second startup • Session-based",
                "category": "cloud",
                "libraries": [
                    {"name": "boto3", "required": True},
                ],
                "requirements": ["boto3>=1.34.0"],
                "installation_command": "uv add boto3",
                "adoption": "niche",
                "supports": ["olap", "interactive", "spark", "s3", "sessions"],
                "driver_package": "boto3",
                "notes": "AWS interactive Spark with notebook-style sessions. Sub-second startup with pre-provisioned capacity. Uses Glue Data Catalog for metadata. Pay per DPU-hour.",
                "capabilities": {"supports_sql": True, "supports_dataframe": True, "default_mode": "sql"},
            },
            "dataproc": {
                "display_name": "Google Cloud Dataproc",
                "description": "Managed Spark • Google Cloud clusters • Per-second billing",
                "category": "cloud",
                "libraries": [
                    {"name": "google-cloud-dataproc", "required": True},
                    {"name": "google-cloud-storage", "required": True},
                ],
                "requirements": ["google-cloud-dataproc>=5.0.0", "google-cloud-storage>=2.0.0"],
                "installation_command": "uv add google-cloud-dataproc google-cloud-storage",
                "adoption": "niche",
                "supports": ["olap", "spark", "cluster", "gcs", "hive"],
                "driver_package": "google-cloud-dataproc",
                "notes": "Google Cloud managed Spark service. Per-second billing with preemptible VM support. Supports persistent and ephemeral clusters. Uses Hive Metastore for table metadata.",
                "capabilities": {"supports_sql": True, "supports_dataframe": True, "default_mode": "sql"},
            },
            "dataproc-serverless": {
                "display_name": "Google Cloud Dataproc Serverless",
                "description": "Serverless Spark • No cluster management • Auto-scaling",
                "category": "cloud",
                "libraries": [
                    {"name": "google-cloud-dataproc", "required": True},
                    {"name": "google-cloud-storage", "required": True},
                ],
                "requirements": ["google-cloud-dataproc>=5.0.0", "google-cloud-storage>=2.0.0"],
                "installation_command": "uv add google-cloud-dataproc google-cloud-storage",
                "adoption": "niche",
                "supports": ["olap", "spark", "serverless", "gcs", "hive"],
                "driver_package": "google-cloud-dataproc",
                "notes": "Google Cloud Dataproc Serverless for fully managed Spark. No cluster management required. Sub-minute startup, auto-scaling, per-second billing. Uses Batch Controller API.",
                "capabilities": {"supports_sql": True, "supports_dataframe": True, "default_mode": "sql"},
            },
            "fabric-spark": {
                "display_name": "Microsoft Fabric Spark",
                "description": "SaaS Spark • OneLake storage • Entra ID auth",
                "category": "cloud",
                "libraries": [
                    {"name": "azure-identity", "required": True},
                    {"name": "azure-storage-file-datalake", "required": True},
                    {"name": "requests", "required": True},
                ],
                "requirements": ["azure-identity>=1.15.0", "azure-storage-file-datalake>=12.14.0", "requests>=2.31.0"],
                "installation_command": "uv add azure-identity azure-storage-file-datalake requests",
                "adoption": "niche",
                "supports": ["olap", "spark", "saas", "delta", "onelake"],
                "driver_package": "azure-identity",
                "notes": "Microsoft Fabric SaaS Spark with OneLake storage. Uses Livy API for session management. Entra ID (Azure AD) authentication. Capacity Units billing model.",
                "capabilities": {"supports_sql": True, "supports_dataframe": True, "default_mode": "sql"},
            },
            "fabric-lakehouse": {
                "display_name": "Microsoft Fabric Lakehouse SQL",
                "description": "Read-only T-SQL endpoint • Lakehouse analytics",
                "category": "cloud",
                "libraries": [
                    {"name": "pyodbc", "required": True},
                    {"name": "azure-identity", "required": True},
                ],
                "requirements": ["pyodbc>=4.0.39", "azure-identity>=1.15.0"],
                "installation_command": "uv add benchbox --extra fabric",
                "adoption": "niche",
                "supports": ["olap", "cloud", "read_only", "delta", "onelake"],
                "driver_package": "pyodbc",
                "notes": "Fabric Lakehouse SQL Analytics Endpoint is read-only. Use fabric-spark for generate/load phases and fabric-lakehouse for query phases.",
                "capabilities": {"supports_sql": True, "supports_dataframe": False, "default_mode": "sql"},
            },
            "synapse-spark": {
                "display_name": "Azure Synapse Analytics Spark",
                "description": "Enterprise Spark • ADLS Gen2 • Spark pools",
                "category": "cloud",
                "libraries": [
                    {"name": "azure-identity", "required": True},
                    {"name": "azure-storage-file-datalake", "required": True},
                    {"name": "requests", "required": True},
                ],
                "requirements": ["azure-identity>=1.15.0", "azure-storage-file-datalake>=12.14.0", "requests>=2.31.0"],
                "installation_command": "uv add azure-identity azure-storage-file-datalake requests",
                "adoption": "niche",
                "supports": ["olap", "spark", "enterprise", "adls", "hive"],
                "driver_package": "azure-identity",
                "notes": "Azure Synapse Analytics Spark with ADLS Gen2 storage. Uses Livy API for session management. vCore-hour billing. Supports external Hive Metastore.",
                "capabilities": {"supports_sql": True, "supports_dataframe": True, "default_mode": "sql"},
            },
            "spark": {
                "display_name": "Apache Spark",
                "description": "Distributed SQL • Local/cluster • Spark engine",
                "category": "distributed",
                "libraries": [
                    {"name": "pyspark", "required": True},
                ],
                "requirements": ["pyspark>=3.5.0"],
                "installation_command": "uv add pyspark",
                "adoption": "mainstream",
                "supports": ["olap", "distributed", "spark", "batch"],
                "driver_package": "pyspark",
                "notes": "Apache Spark distributed SQL engine. Supports local, standalone, YARN, and Kubernetes modes. Use 'pyspark' for DataFrame API benchmarking.",
                "capabilities": {"supports_sql": True, "supports_dataframe": False, "default_mode": "sql"},
            },
            "velox": {
                "display_name": "Apache Gluten + Velox",
                "description": "Spark SQL • Native C++ acceleration • Gluten plugin",
                "category": "distributed",
                "libraries": [
                    {"name": "pyspark", "required": True},
                ],
                "requirements": ["pyspark>=3.5.0"],
                "installation_command": "uv add benchbox --extra velox",
                "adoption": "emerging",
                "supports": ["olap", "distributed", "spark", "native", "accelerated", "batch"],
                "driver_package": "pyspark",
                "notes": (
                    "Apache Gluten + Velox accelerates Spark SQL by offloading physical operators "
                    "to a vectorized C++ engine. Requires the Gluten bundle jar on the execution host. "
                    "Linux only for local mode; Docker is the primary path on macOS/Windows. "
                    "See docs/platforms/velox.md and docker/velox/."
                ),
                "capabilities": {
                    "supports_sql": True,
                    "supports_dataframe": False,
                    "default_mode": "sql",
                    "platform_family": "spark",
                    "default_deployment": "local",
                    "deployment_modes": {
                        "local": {
                            "mode": "local",
                            "display_name": "Velox Local",
                            "description": "SparkSession with Gluten jar on local Linux host (or Docker container)",
                            "requires_credentials": False,
                            "requires_cloud_storage": False,
                            "requires_network": False,
                            "default_for_platform": True,
                            "dependencies": ["pyspark"],
                            "auth_methods": [],
                        },
                        "remote": {
                            "mode": "remote",
                            "display_name": "Velox Remote",
                            "description": "Connect to a pre-started Spark-Connect server with Gluten wired",
                            "requires_credentials": False,
                            "requires_cloud_storage": False,
                            "requires_network": True,
                            "default_for_platform": False,
                            "dependencies": ["pyspark"],
                            "auth_methods": [],
                        },
                    },
                },
            },
            "lakesail": {
                "display_name": "LakeSail Sail",
                "description": "Spark-compatible SQL • Rust/DataFusion • Spark Connect",
                "category": "analytical",
                "libraries": [
                    {"name": "pyspark", "required": True},
                ],
                "requirements": ["pyspark>=3.4.0"],
                "installation_command": "uv add pyspark",
                "adoption": "emerging",
                "supports": ["olap", "spark_compatible", "datafusion", "rust", "batch"],
                "driver_package": "pyspark",
                "notes": "LakeSail Sail is a Rust-based drop-in Spark replacement built on DataFusion. Connects via Spark Connect protocol using standard PySpark client. 4x faster than Apache Spark on TPC-H SF100.",
                "capabilities": {
                    "supports_sql": True,
                    "supports_dataframe": True,
                    "default_mode": "sql",
                    "platform_family": "spark",
                    "default_deployment": "local",
                    "deployment_modes": {
                        "local": {
                            "mode": "local",
                            "display_name": "LakeSail Local",
                            "description": "Single-node multi-threaded execution",
                            "requires_credentials": False,
                            "requires_cloud_storage": False,
                            "requires_network": False,
                            "default_for_platform": True,
                            "dependencies": ["pyspark"],
                            "auth_methods": [],
                        },
                        "distributed": {
                            "mode": "self-hosted",
                            "display_name": "LakeSail Distributed",
                            "description": "Distributed cluster of Rust workers",
                            "requires_credentials": False,
                            "requires_cloud_storage": False,
                            "requires_network": True,
                            "default_for_platform": False,
                            "dependencies": ["pyspark"],
                            "auth_methods": [],
                        },
                    },
                },
            },
            "snowpark-connect": {
                "display_name": "Snowpark Connect for Spark",
                "description": "PySpark API • Snowflake native • No cluster required",
                "category": "cloud",
                "libraries": [
                    {"name": "snowflake.snowpark", "required": True, "import_name": "snowflake.snowpark"},
                ],
                "requirements": ["snowflake-snowpark-python>=1.20.0"],
                "installation_command": "uv add snowflake-snowpark-python",
                "adoption": "niche",
                "supports": ["olap", "pyspark_compatible", "snowflake", "dataframe"],
                "driver_package": "snowflake-snowpark-python",
                "notes": "PySpark DataFrame API compatibility layer on Snowflake. NOT Apache Spark - translates DataFrame operations to Snowflake SQL. No Spark cluster required.",
                "capabilities": {"supports_sql": True, "supports_dataframe": True, "default_mode": "dataframe"},
            },
            "quanton": {
                "display_name": "Onehouse Quanton",
                "description": "Serverless Spark • Hudi/Iceberg/Delta • 2-3x faster",
                "category": "cloud",
                "libraries": [
                    {"name": "requests", "required": True},
                    {"name": "boto3", "required": True},
                ],
                "requirements": ["requests>=2.31.0", "boto3>=1.34.0"],
                "installation_command": "uv add requests boto3",
                "adoption": "emerging",
                "supports": ["olap", "serverless", "spark", "hudi", "iceberg", "delta", "s3", "lakehouse"],
                "driver_package": "requests",
                "notes": "Onehouse Quanton serverless Spark. Multi-table-format support (Hudi, Iceberg, Delta). XTable cross-format metadata translation. 2-3x better price-performance than EMR/Databricks.",
                "capabilities": {
                    "supports_sql": True,
                    "supports_dataframe": True,
                    "default_mode": "sql",
                    "platform_family": "spark",
                    "default_deployment": "managed",
                    "deployment_modes": {
                        "managed": {
                            "mode": "managed",
                            "display_name": "Onehouse Quanton",
                            "description": "Serverless managed Spark on Onehouse",
                            "requires_credentials": True,
                            "requires_cloud_storage": True,
                            "requires_network": True,
                            "default_for_platform": True,
                            "dependencies": ["requests", "boto3"],
                            "auth_methods": ["api_key"],
                        },
                    },
                },
            },
        }

        # DataFrame-only platforms (no SQL support)
        dataframe_metadata = {
            "pandas": {
                "display_name": "Pandas",
                "description": "Python DataFrame library • In-memory • Single-node",
                "category": "dataframe",
                "libraries": [{"name": "pandas", "required": True}],
                "requirements": ["pandas>=2.0.0"],
                "installation_command": "uv add pandas",
                "adoption": "emerging",
                "supports": ["dataframe", "in_memory"],
                "driver_package": None,
                "capabilities": {"supports_sql": False, "supports_dataframe": True, "default_mode": "dataframe"},
            },
            "modin": {
                "display_name": "Modin",
                "description": "Distributed Pandas • Ray/Dask backend • Drop-in",
                "category": "dataframe",
                "libraries": [{"name": "modin", "required": True}],
                "requirements": ["modin[ray]>=0.28.0"],
                "installation_command": "uv add modin[ray]",
                "adoption": "niche",
                "supports": ["dataframe", "distributed"],
                "driver_package": None,
                "capabilities": {"supports_sql": False, "supports_dataframe": True, "default_mode": "dataframe"},
            },
            "cudf": {
                "display_name": "cuDF",
                "description": "GPU DataFrame • NVIDIA RAPIDS • CUDA required",
                "category": "dataframe",
                "libraries": [{"name": "cudf", "required": True}],
                "requirements": ["cudf-cu12>=24.0.0"],
                "installation_command": "pip install cudf-cu12 (requires NVIDIA GPU)",
                "adoption": "niche",
                "supports": ["dataframe", "gpu"],
                "driver_package": None,
                "capabilities": {"supports_sql": False, "supports_dataframe": True, "default_mode": "dataframe"},
            },
            "dask": {
                "display_name": "Dask",
                "description": "Distributed DataFrame • Lazy eval • Cluster-scale",
                "category": "dataframe",
                "libraries": [{"name": "dask", "required": True}],
                "requirements": ["dask[distributed]>=2024.0.0"],
                "installation_command": "uv add dask[distributed]",
                "adoption": "niche",
                "supports": ["dataframe", "distributed", "lazy"],
                "driver_package": None,
                "capabilities": {"supports_sql": False, "supports_dataframe": True, "default_mode": "dataframe"},
            },
            "pyspark": {
                "display_name": "PySpark",
                "description": "Spark DataFrame API • Distributed • Java 17+",
                "category": "dataframe",
                "libraries": [{"name": "pyspark", "required": True}],
                "requirements": ["pyspark>=3.5.0"],
                "installation_command": "uv add pyspark",
                "adoption": "established",
                "supports": ["dataframe", "distributed", "spark"],
                "driver_package": None,
                "notes": "Requires Java 17 or 21. Java 23+ not supported by PySpark 4.x.",
                "capabilities": {
                    "supports_sql": True,
                    "supports_dataframe": True,
                    "default_mode": "dataframe",
                    "platform_family": "spark",
                    "default_deployment": "local",
                    "deployment_modes": {
                        "local": {
                            "mode": "local",
                            "display_name": "PySpark Local",
                            "description": "Local PySpark with single-node Spark",
                            "requires_credentials": False,
                            "requires_cloud_storage": False,
                            "requires_network": False,
                            "default_for_platform": True,
                            "dependencies": ["pyspark"],
                            "auth_methods": [],
                        },
                    },
                },
            },
        }

        metadata = dict(base_metadata)
        metadata.update(experimental_metadata)
        metadata.update(dataframe_metadata)

        return metadata

    @classmethod
    def _ensure_registered(cls) -> None:
        """Lazily trigger auto_register_platforms() on first registry access.

        This avoids eagerly importing every platform adapter (and their heavy
        native dependencies like chdb/polars/datafusion/duckdb) at module load
        time.  Instead, the imports are deferred until something actually queries
        the registry, which most unit tests never do.
        """
        if not cls._auto_registered:
            cls._auto_registered = True
            auto_register_platforms()

    @classmethod
    def register_adapter(cls, platform_name: str, adapter_class: type[PlatformAdapter]) -> None:
        """Register a platform adapter class.

        Args:
            platform_name: Name of the platform (e.g., 'duckdb', 'databricks')
            adapter_class: Platform adapter class
        """
        cls._adapters[platform_name] = adapter_class
        # Clear availability cache when new adapter is registered
        cls._availability_cache = None
        # Initialize metadata if not present
        if not cls._platform_metadata:
            cls._platform_metadata = cls._build_platform_metadata()

    @classmethod
    def get_adapter_class(cls, platform_name: str) -> type[PlatformAdapter]:
        """Get platform adapter class by name.

        Args:
            platform_name: Name of the platform (aliases are resolved automatically)

        Returns:
            Platform adapter class

        Raises:
            ValueError: If platform is not registered
        """
        cls._ensure_registered()
        # Resolve aliases to canonical name
        canonical_name = cls.resolve_platform_name(platform_name)

        if canonical_name not in cls._adapters:
            available = ", ".join(cls.get_available_platforms())
            raise ValueError(f"Platform '{platform_name}' not registered. Available: {available}")
        return cls._adapters[canonical_name]

    @classmethod
    def create_adapter(cls, platform_name: str, config: dict[str, Any]) -> PlatformAdapter:
        """Create platform adapter instance from configuration.

        Args:
            platform_name: Name of the platform
            config: Unified configuration dictionary

        Returns:
            Platform adapter instance
        """
        adapter_class = cls.get_adapter_class(platform_name)
        return adapter_class.from_config(config)

    @classmethod
    def add_platform_arguments(cls, parser: argparse.ArgumentParser, platform_name: str) -> None:
        """Add platform-specific arguments to parser.

        Args:
            parser: Argument parser to add arguments to
            platform_name: Name of the platform
        """
        adapter_class = cls.get_adapter_class(platform_name)
        adapter_class.add_cli_arguments(parser)

    @classmethod
    def get_available_platforms(cls) -> list[str]:
        """Get list of available platform names.

        Returns:
            List of registered platform names
        """
        cls._ensure_registered()
        return list(cls._adapters.keys())

    @classmethod
    def _detect_library(cls, lib_spec: dict[str, Any]) -> LibraryInfo:
        """Detect a single library."""
        lib_name = lib_spec["name"]
        import_name = lib_spec.get("import_name", lib_name)

        try:
            module = importlib.import_module(import_name)
            version = getattr(module, "__version__", None)
            # Handle edge cases where __version__ is not a string
            # (e.g., clickhouse_connect has __version__ as a module)
            if version is not None and not isinstance(version, str):
                # Try common patterns for version submodules/attributes
                if hasattr(version, "version"):
                    version = version.version
                elif hasattr(version, "VERSION"):
                    version = version.VERSION
                else:
                    version = None
            # Ensure version is a string or None
            if version is not None and not isinstance(version, str):
                version = str(version) if version else None
            return LibraryInfo(name=lib_name, version=version, installed=True)
        except ImportError as e:
            return LibraryInfo(name=lib_name, version=None, installed=False, import_error=str(e))

    @staticmethod
    def _extract_requirement_package(requirement: str) -> Optional[str]:
        """Extract distribution name from a requirement string."""

        if not requirement:
            return None

        requirement = requirement.strip()
        # Ignore descriptive requirements (e.g. "sqlite3 (built-in)")
        if "(" in requirement and ")" in requirement and " " in requirement:
            return requirement.split(" ", 1)[0]

        separators = [" ", "<", ">", "=", "!", "~"]
        package = requirement
        for sep in separators:
            if sep in package:
                package = package.split(sep, 1)[0]
        package = package.strip()
        return package or None

    @classmethod
    def get_platform_availability(cls) -> dict[str, bool]:
        """Get availability status for all registered platforms.

        Returns:
            Dictionary mapping platform names to availability status
        """
        cls._ensure_registered()
        if cls._availability_cache is not None:
            return cls._availability_cache.copy()

        if not cls._platform_metadata:
            cls._platform_metadata = cls._build_platform_metadata()

        availability = {}
        for platform_name in cls._adapters:
            if platform_name in cls._platform_metadata:
                # Use detailed library detection
                platform_spec = cls._platform_metadata[platform_name]
                available = True

                for lib_spec in platform_spec.get("libraries", []):
                    lib_info = cls._detect_library(lib_spec)
                    if (
                        lib_spec.get("required", True)
                        and not lib_info.installed
                        and not lib_spec.get("alternative", False)
                    ):
                        available = False
                        break

                availability[platform_name] = available
            else:
                # Fallback to old method
                try:
                    adapter_class = cls._adapters[platform_name]
                    test_config = {"database_path": ":memory:"} if platform_name == "duckdb" else {}
                    adapter_class(**test_config)
                    availability[platform_name] = True
                except ImportError:
                    availability[platform_name] = False
                except Exception:
                    availability[platform_name] = True

        cls._availability_cache = availability
        return availability.copy()

    @classmethod
    def is_platform_available(cls, platform_name: str) -> bool:
        """Check if a specific platform is available.

        Args:
            platform_name: Name of the platform to check

        Returns:
            True if platform is available
        """
        availability = cls.get_platform_availability()
        return availability.get(platform_name, False)

    @classmethod
    def get_platform_info(cls, platform_name: str) -> Optional[PlatformInfo]:
        """Get comprehensive platform information.

        Args:
            platform_name: Name of the platform (aliases are resolved automatically)

        Returns:
            Platform information or None if not found
        """
        cls._ensure_registered()
        if not cls._platform_metadata:
            cls._platform_metadata = cls._build_platform_metadata()

        # Resolve aliases to canonical name
        canonical_name = cls.resolve_platform_name(platform_name)

        if canonical_name not in cls._platform_metadata:
            return None

        platform_spec = cls._platform_metadata[canonical_name]

        # Detect libraries
        libraries = []
        available = True

        for lib_spec in platform_spec.get("libraries", []):
            lib_info = cls._detect_library(lib_spec)
            libraries.append(lib_info)

            if lib_spec.get("required", True) and not lib_info.installed and not lib_spec.get("alternative", False):
                available = False

        # Check if driver_package is explicitly set in metadata
        if "driver_package" in platform_spec:
            driver_package = platform_spec["driver_package"]
        else:
            # Fallback: extract from requirements if not explicitly specified
            requirements = platform_spec.get("requirements", [])
            driver_package = cls._extract_requirement_package(requirements[0]) if requirements else None

        return PlatformInfo(
            name=canonical_name,
            display_name=platform_spec["display_name"],
            description=platform_spec["description"],
            libraries=libraries,
            available=available,
            enabled=available and canonical_name in cls._adapters,
            requirements=platform_spec["requirements"],
            installation_command=platform_spec["installation_command"],
            adoption=platform_spec.get("adoption", "niche"),
            category=platform_spec.get("category", "database"),
            supports=platform_spec.get("supports", []),
            driver_package=driver_package,
        )

    @classmethod
    def get_platform_requirements(cls, platform_name: str) -> str:
        """Get installation requirements for a platform.

        Args:
            platform_name: Name of the platform

        Returns:
            Installation requirements string
        """
        info = cls.get_platform_info(platform_name)
        if info:
            return info.installation_command

        # Fallback to old static mapping
        requirements_map = {
            "duckdb": "uv add duckdb",
            "databricks": "uv add databricks-sql-connector",
            "clickhouse": "uv add benchbox --extra clickhouse",
            "clickhouse-local": "uv add benchbox --extra clickhouse-local",
            "clickhouse-server": "uv add benchbox --extra clickhouse-server",
            "clickhouse-cloud": "uv add benchbox --extra clickhouse-cloud",
            "sqlite": "Built-in (no additional requirements)",
            "bigquery": "uv add google-cloud-bigquery",
            "redshift": "uv add redshift-connector",
            "snowflake": "uv add snowflake-connector-python",
        }
        return requirements_map.get(platform_name, "Unknown requirements")

    @classmethod
    def get_platforms_by_category(cls, category: str) -> list[str]:
        """Get platforms filtered by category.

        Args:
            category: Platform category ('analytical', 'cloud', 'embedded', etc.)

        Returns:
            List of platform names in the category
        """
        cls._ensure_registered()
        if not cls._platform_metadata:
            cls._platform_metadata = cls._build_platform_metadata()

        return [
            name
            for name, spec in cls._platform_metadata.items()
            if spec.get("category") == category and name in cls._adapters
        ]

    @classmethod
    def get_platforms_by_adoption(cls, tier: str) -> list[str]:
        """Get platforms by adoption tier.

        Args:
            tier: Adoption tier ('mainstream', 'established', 'emerging', 'niche')

        Returns:
            List of platform names in the specified tier
        """
        cls._ensure_registered()
        if not cls._platform_metadata:
            cls._platform_metadata = cls._build_platform_metadata()

        return [
            name
            for name, spec in cls._platform_metadata.items()
            if spec.get("adoption", "niche") == tier and name in cls._adapters
        ]

    @classmethod
    def requires_cloud_storage(cls, platform_name: str) -> bool:
        """Check if a platform requires cloud storage for data loading.

        Cloud platforms (Databricks, BigQuery, Snowflake, Redshift) require
        a cloud storage staging location for loading benchmark data.

        Args:
            platform_name: Name of the platform

        Returns:
            True if platform requires cloud storage staging location
        """
        if not cls._platform_metadata:
            cls._platform_metadata = cls._build_platform_metadata()

        metadata = cls._platform_metadata.get(platform_name.lower(), {})
        # Cloud platforms require staging locations for data loading
        return metadata.get("category") == "cloud"

    @classmethod
    def get_cloud_path_examples(cls, platform_name: str) -> list[str]:
        """Get example cloud paths for a platform.

        Args:
            platform_name: Name of the platform

        Returns:
            List of example cloud path formats for the platform
        """
        examples = {
            "databricks": [
                "dbfs:/Volumes/catalog/schema/volume/benchbox",
                "s3://my-bucket/benchbox/data",
                "abfss://container@storage.dfs.core.windows.net/benchbox",
                "gs://my-bucket/benchbox/data",
            ],
            "bigquery": [
                "gs://my-bucket/benchbox/data",
            ],
            "snowflake": [
                "s3://my-bucket/benchbox/data",
                "azure://my-container/benchbox/data",
                "gcs://my-bucket/benchbox/data",
            ],
            "redshift": [
                "s3://my-bucket/benchbox/data",
            ],
            "trino": [
                "s3://my-bucket/benchbox/data",
                "gs://my-bucket/benchbox/data",
                "abfss://container@storage.dfs.core.windows.net/benchbox",
            ],
        }
        return examples.get(platform_name.lower(), [])

    @classmethod
    def clear_cache(cls) -> None:
        """Clear the availability cache."""
        cls._availability_cache = None

    @classmethod
    def get_all_platform_metadata(cls) -> dict[str, dict[str, Any]]:
        """Get all platform metadata for CLI use.

        Returns:
            Dictionary mapping platform names to their metadata
        """
        if not cls._platform_metadata:
            cls._platform_metadata = cls._build_platform_metadata()
        return cls._platform_metadata.copy()

    @classmethod
    def detect_library(cls, lib_spec: dict[str, Any]) -> LibraryInfo:
        """Detect a single library for CLI use.

        Args:
            lib_spec: Library specification dictionary

        Returns:
            LibraryInfo object with detection results
        """
        return cls._detect_library(lib_spec)

    @classmethod
    def get_platform_capabilities(cls, platform_name: str) -> Optional[PlatformCapability]:
        """Get capability information for a platform.

        Args:
            platform_name: Name of the platform (aliases are resolved automatically)

        Returns:
            PlatformCapability object or None if platform not found
        """
        if not cls._platform_metadata:
            cls._platform_metadata = cls._build_platform_metadata()

        # Resolve aliases to canonical name
        canonical_name = cls.resolve_platform_name(platform_name)
        metadata = cls._platform_metadata.get(canonical_name)
        if metadata is None:
            return None

        caps = metadata.get("capabilities", {})

        # Parse deployment modes from metadata
        deployment_modes: dict[str, DeploymentCapability] = {}
        deployment_data = caps.get("deployment_modes", {})
        for mode_name, mode_spec in deployment_data.items():
            deployment_modes[mode_name] = DeploymentCapability(
                mode=mode_spec.get("mode", "local"),
                requires_credentials=mode_spec.get("requires_credentials", False),
                requires_cloud_storage=mode_spec.get("requires_cloud_storage", False),
                requires_network=mode_spec.get("requires_network", False),
                default_for_platform=mode_spec.get("default_for_platform", False),
                display_name=mode_spec.get("display_name", ""),
                description=mode_spec.get("description", ""),
                dependencies=mode_spec.get("dependencies", []),
                auth_methods=mode_spec.get("auth_methods", []),
            )

        # unsupported_benchmarks is computed from registry benchmark_gate rules;
        # the hardcoded dict in metadata is the legacy source and is ignored post-w16.
        import benchbox.sql_compat.rules.benchmark_gate.lakesail_gate  # noqa: F401
        import benchbox.sql_compat.rules.benchmark_gate.pg_family_gate  # noqa: F401
        import benchbox.sql_compat.rules.benchmark_gate.questdb_gate  # noqa: F401
        from benchbox.sql_compat.actions import CompatAction
        from benchbox.sql_compat.context import Phase
        from benchbox.sql_compat.registry import REGISTRY

        unsupported: dict[str, str] = {}
        for (phase, platform, benchmark, _query_id), entry in REGISTRY.all_rules():
            if (
                phase is Phase.BENCHMARK_GATE
                and platform == canonical_name
                and benchmark is not None
                and entry.decision.action is CompatAction.BLOCK_BENCHMARK
            ):
                reason = getattr(entry.decision.payload, "reason", None) or entry.decision.reason or ""
                unsupported[benchmark] = reason

        return PlatformCapability(
            supports_sql=caps.get("supports_sql", False),
            supports_dataframe=caps.get("supports_dataframe", False),
            default_mode=caps.get("default_mode", "sql"),
            deployment_modes=deployment_modes,
            default_deployment=caps.get("default_deployment", "local"),
            platform_family=caps.get("platform_family"),
            inherits_from=caps.get("inherits_from"),
            unsupported_benchmarks=unsupported,
        )

    @classmethod
    def get_platform_conflicts(cls, platform_name: str) -> list[str]:
        """Get list of platforms that conflict with the given platform.

        Some PostgreSQL extensions share libraries (e.g., pg_duckdb and
        pg_mooncake share libduckdb.so) and cannot coexist in the same
        PostgreSQL instance.

        Args:
            platform_name: Name of the platform (aliases are resolved automatically)

        Returns:
            List of conflicting platform names, or empty list if none.
        """
        if not cls._platform_metadata:
            cls._platform_metadata = cls._build_platform_metadata()

        canonical_name = cls.resolve_platform_name(platform_name)
        metadata = cls._platform_metadata.get(canonical_name)
        if metadata is None:
            return []

        caps = metadata.get("capabilities", {})
        return list(caps.get("conflicts_with", []))

    @classmethod
    def supports_mode(cls, platform_name: str, mode: str) -> bool:
        """Check if platform supports a specific execution mode.

        Args:
            platform_name: Name of the platform
            mode: Execution mode ('sql' or 'dataframe')

        Returns:
            True if platform supports the mode
        """
        caps = cls.get_platform_capabilities(platform_name)
        if caps is None:
            return False

        if mode == "sql":
            return caps.supports_sql
        elif mode == "dataframe":
            return caps.supports_dataframe
        return False

    @classmethod
    def get_default_mode(cls, platform_name: str) -> str:
        """Get default execution mode for a platform.

        Args:
            platform_name: Name of the platform

        Returns:
            Default mode ('sql' or 'dataframe'), defaults to 'sql' if unknown
        """
        caps = cls.get_platform_capabilities(platform_name)
        if caps is None:
            return "sql"
        return caps.default_mode

    @classmethod
    def get_dual_mode_platforms(cls) -> list[str]:
        """Get platforms that support both SQL and DataFrame modes.

        Returns:
            List of platform names with dual-mode support
        """
        if not cls._platform_metadata:
            cls._platform_metadata = cls._build_platform_metadata()

        dual_mode = []
        for name, metadata in cls._platform_metadata.items():
            caps = metadata.get("capabilities", {})
            if caps.get("supports_sql") and caps.get("supports_dataframe"):
                dual_mode.append(name)
        return dual_mode

    @classmethod
    def get_deployment_capability(cls, platform_name: str, deployment_mode: str) -> Optional[DeploymentCapability]:
        """Get deployment capability information for a specific deployment mode.

        Args:
            platform_name: Name of the platform (aliases are resolved automatically)
            deployment_mode: Deployment mode name (e.g., 'local', 'server', 'cloud')

        Returns:
            DeploymentCapability object or None if deployment mode not found
        """
        caps = cls.get_platform_capabilities(platform_name)
        if caps is None or not caps.deployment_modes:
            return None
        return caps.deployment_modes.get(deployment_mode)

    @classmethod
    def get_default_deployment(cls, platform_name: str) -> Optional[str]:
        """Get default deployment mode for a platform.

        Args:
            platform_name: Name of the platform (aliases are resolved automatically)

        Returns:
            Default deployment mode name, or None if platform has no deployment modes
        """
        caps = cls.get_platform_capabilities(platform_name)
        if caps is None or not caps.deployment_modes:
            return None
        return caps.default_deployment

    @classmethod
    def get_platform_family(cls, platform_name: str) -> Optional[str]:
        """Get platform family for dialect/configuration inheritance.

        Platform families group related platforms that share SQL dialect,
        benchmark compatibility, and data type mappings. For example:
        - 'duckdb' family: duckdb, motherduck
        - 'clickhouse' family: clickhouse (local, server, cloud modes)
        - 'trino' family: trino, starburst, athena

        Args:
            platform_name: Name of the platform (aliases are resolved automatically)

        Returns:
            Platform family name or None if no family defined
        """
        caps = cls.get_platform_capabilities(platform_name)
        if caps is None:
            return None
        return caps.platform_family

    @classmethod
    def get_inherited_platform(cls, platform_name: str) -> Optional[str]:
        """Get parent platform for configuration inheritance.

        Child platforms inherit SQL dialect, benchmark compatibility, and
        data type mappings from their parent. For example:
        - motherduck inherits from duckdb
        - starburst inherits from trino

        Args:
            platform_name: Name of the platform (aliases are resolved automatically)

        Returns:
            Parent platform name or None if no inheritance defined
        """
        caps = cls.get_platform_capabilities(platform_name)
        if caps is None:
            return None
        return caps.inherits_from

    @classmethod
    def requires_cloud_storage_for_deployment(cls, platform_name: str, deployment_mode: Optional[str] = None) -> bool:
        """Check if a specific deployment mode requires cloud storage.

        Args:
            platform_name: Name of the platform
            deployment_mode: Specific deployment mode to check, or None for default

        Returns:
            True if deployment mode requires cloud storage staging location
        """
        if deployment_mode is None:
            deployment_mode = cls.get_default_deployment(platform_name)

        # If no deployment mode available, fallback to platform-level check
        if deployment_mode is None:
            return cls.requires_cloud_storage(platform_name)

        dep_cap = cls.get_deployment_capability(platform_name, deployment_mode)
        if dep_cap is not None:
            return dep_cap.requires_cloud_storage

        # Fallback to existing requires_cloud_storage method
        return cls.requires_cloud_storage(platform_name)

    @classmethod
    def get_available_deployment_modes(cls, platform_name: str) -> list[str]:
        """Get list of available deployment modes for a platform.

        Args:
            platform_name: Name of the platform (aliases are resolved automatically)

        Returns:
            List of deployment mode names, empty if none defined
        """
        caps = cls.get_platform_capabilities(platform_name)
        if caps is None or not caps.deployment_modes:
            return []
        return list(caps.deployment_modes.keys())

    @classmethod
    def supports_deployment_mode(cls, platform_name: str, deployment_mode: str) -> bool:
        """Check if platform supports a specific deployment mode.

        Args:
            platform_name: Name of the platform
            deployment_mode: Deployment mode to check

        Returns:
            True if platform supports the deployment mode
        """
        caps = cls.get_platform_capabilities(platform_name)
        if caps is None or not caps.deployment_modes:
            # Platform has no deployment modes defined - only supports default
            return deployment_mode == "local"
        return deployment_mode in caps.deployment_modes


# (name, module_path, class_name) - each entry becomes one optional import+register.
# pg-mooncake historically co-registered questdb in the same try/except; that
# coupling is now explicit (two separate entries).
_OPTIONAL_ADAPTERS: tuple[tuple[str, str, str], ...] = (
    ("duckdb", "benchbox.platforms.duckdb", "DuckDBAdapter"),
    ("motherduck", "benchbox.platforms.motherduck", "MotherDuckAdapter"),
    ("datafusion", "benchbox.platforms.datafusion", "DataFusionAdapter"),
    ("databricks", "benchbox.platforms.databricks", "DatabricksAdapter"),
    ("databricks-df", "benchbox.platforms.databricks", "DatabricksDataFrameAdapter"),
    ("clickhouse", "benchbox.platforms.clickhouse", "ClickHouseAdapter"),
    ("clickhouse-local", "benchbox.platforms.clickhouse_local", "ClickHouseLocalAdapter"),
    ("clickhouse-server", "benchbox.platforms.clickhouse_server", "ClickHouseServerAdapter"),
    ("clickhouse-cloud", "benchbox.platforms.clickhouse_cloud", "ClickHouseCloudAdapter"),
    ("starrocks", "benchbox.platforms.starrocks", "StarRocksAdapter"),
    ("sqlite", "benchbox.platforms.sqlite", "SQLiteAdapter"),
    ("bigquery", "benchbox.platforms.bigquery", "BigQueryAdapter"),
    ("redshift", "benchbox.platforms.redshift", "RedshiftAdapter"),
    ("snowflake", "benchbox.platforms.snowflake", "SnowflakeAdapter"),
    ("trino", "benchbox.platforms.trino", "TrinoAdapter"),
    ("starburst", "benchbox.platforms.starburst", "StarburstAdapter"),
    ("presto", "benchbox.platforms.presto", "PrestoAdapter"),
    ("postgresql", "benchbox.platforms.postgresql", "PostgreSQLAdapter"),
    ("timescaledb", "benchbox.platforms.timescaledb", "TimescaleDBAdapter"),
    ("pg-duckdb", "benchbox.platforms.pg_duckdb", "PgDuckDBAdapter"),
    ("pg-mooncake", "benchbox.platforms.pg_mooncake", "PgMooncakeAdapter"),
    ("questdb", "benchbox.platforms.questdb", "QuestDBAdapter"),
    ("cedardb", "benchbox.platforms.cedardb", "CedarDBAdapter"),
    ("synapse", "benchbox.platforms.azure_synapse", "AzureSynapseAdapter"),
    ("pyspark", "benchbox.platforms.pyspark", "PySparkSQLAdapter"),
    ("firebolt", "benchbox.platforms.firebolt", "FireboltAdapter"),
    ("databend", "benchbox.platforms.databend", "DatabendAdapter"),
    ("doris", "benchbox.platforms.doris", "DorisAdapter"),
    ("singlestore", "benchbox.platforms.singlestore", "SingleStoreAdapter"),
    ("influxdb", "benchbox.platforms.influxdb", "InfluxDBAdapter"),
    ("fabric_dw", "benchbox.platforms.fabric_warehouse", "FabricWarehouseAdapter"),
    ("athena", "benchbox.platforms.athena", "AthenaAdapter"),
    ("glue", "benchbox.platforms.aws", "AWSGlueAdapter"),
    ("emr-serverless", "benchbox.platforms.aws", "EMRServerlessAdapter"),
    ("athena-spark", "benchbox.platforms.aws", "AthenaSparkAdapter"),
    ("dataproc", "benchbox.platforms.gcp", "DataprocAdapter"),
    ("dataproc-serverless", "benchbox.platforms.gcp", "DataprocServerlessAdapter"),
    ("fabric-spark", "benchbox.platforms.azure", "FabricSparkAdapter"),
    ("fabric-lakehouse", "benchbox.platforms.fabric_lakehouse", "FabricLakehouseAdapter"),
    ("synapse-spark", "benchbox.platforms.azure", "SynapseSparkAdapter"),
    ("spark", "benchbox.platforms.spark", "SparkAdapter"),
    ("lakesail", "benchbox.platforms.lakesail", "LakeSailAdapter"),
    ("velox", "benchbox.platforms.velox", "VeloxAdapter"),
    ("polars", "benchbox.platforms.polars_platform", "PolarsAdapter"),
    ("snowpark-connect", "benchbox.platforms.snowpark_connect", "SnowparkConnectAdapter"),
    ("quanton", "benchbox.platforms.onehouse", "QuantonAdapter"),
)


def _try_register_adapter(name: str, module_path: str, class_name: str) -> None:
    """Import ``class_name`` from ``module_path`` and register as ``name``.

    Missing optional dependencies are silently skipped - adapters whose driver
    packages aren't installed simply don't appear in the registry.
    """
    try:
        module = importlib.import_module(module_path)
        adapter_cls = getattr(module, class_name)
        PlatformRegistry.register_adapter(name, adapter_cls)
    except ImportError:
        pass


def auto_register_platforms() -> None:
    """Automatically register all available platform adapters.

    Platforms are registered if their dependencies can be successfully imported.
    The BENCHBOX_ENABLE_EXPERIMENTAL environment variable is reserved for future
    truly-experimental features but is not currently used.
    """
    for name, module_path, class_name in _OPTIONAL_ADAPTERS:
        _try_register_adapter(name, module_path, class_name)


# NOTE: auto_register_platforms() is no longer called at module level.
# It is deferred to first access via PlatformRegistry._ensure_registered()
# to avoid eagerly loading ~600 MB of native libraries (chdb, polars,
# datafusion, duckdb, databend_driver) into every xdist worker process.
# See: https://github.com/benchbox/benchbox/issues/XXXX
