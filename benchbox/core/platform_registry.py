"""
Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.

Platform Registry and Factory

This module provides a centralized registry and factory for platform adapters,
enabling dynamic discovery and instantiation of platform adapters.
"""

import argparse
import importlib
import json
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any, Literal, Optional

from benchbox.core.schemas import LibraryInfo, PlatformInfo
from benchbox.platforms.base import PlatformAdapter

CostClass = Literal["free", "paid_credits", "paid_compute"]
SupportStatus = Literal["stable", "beta", "experimental", "repo_only", "deprecated", "document_only"]
OptionalAdapterImportStatus = Literal[
    "available",
    "missing_optional_dependency",
    "native_library_load_failure",
    "broken_adapter_import",
    "deprecated_platform",
    "intentionally_disabled",
    "not_configured",
]

SUPPORT_STATUS_VALUES: tuple[SupportStatus, ...] = (
    "stable",
    "beta",
    "experimental",
    "repo_only",
    "deprecated",
    "document_only",
)

_PLATFORM_SUPPORT_STATUS: dict[str, SupportStatus] = {
    # Local/core platforms with broad fast-test and docs coverage.
    "duckdb": "stable",
    "sqlite": "stable",
    "datafusion": "stable",
    "polars": "stable",
    "pandas": "stable",
    # Supported beta product surface. Local dependency availability remains separate.
    "motherduck": "beta",
    "clickhouse-local": "beta",
    "clickhouse-server": "beta",
    "clickhouse-cloud": "beta",
    "databricks": "beta",
    "bigquery": "beta",
    "redshift": "beta",
    "snowflake": "beta",
    "trino": "beta",
    "starburst": "beta",
    "athena": "beta",
    "spark": "beta",
    "pyspark": "beta",
    "firebolt": "beta",
    "presto": "beta",
    "postgresql": "beta",
    "timescaledb": "beta",
    "synapse": "beta",
    "fabric_dw": "beta",
    "fabric-lakehouse": "beta",
    "influxdb": "beta",
    "starrocks": "beta",
    "doris": "beta",
    "databend": "beta",
    "questdb": "beta",
    "dask": "beta",
    "singlestore": "beta",
    # Shipped for evaluation, migration work, or ecosystem breadth.
    "cedardb": "experimental",
    "ducklake": "experimental",
    "pg-duckdb": "experimental",
    "pg-mooncake": "experimental",
    "databricks-df": "experimental",
    "glue": "experimental",
    "emr-serverless": "experimental",
    "athena-spark": "experimental",
    "dataproc": "experimental",
    "dataproc-serverless": "experimental",
    "fabric-spark": "experimental",
    "synapse-spark": "experimental",
    "snowpark-connect": "experimental",
    "lakesail": "experimental",
    "velox": "experimental",
    "quanton": "experimental",
    "modin": "experimental",
    "cudf": "experimental",
    # Legacy selector retained while users migrate to first-class ClickHouse names.
    "clickhouse": "deprecated",
}

_NATIVE_IMPORT_ERROR_MARKERS = (
    "dlopen",
    "dylib",
    "cannot open shared object file",
    "image not found",
    "library not loaded",
    "undefined symbol",
    "symbol not found",
    "dll load failed",
    "failed to map segment",
)


def _is_internal_module_miss(missing_name: str, module_path: str | None = None) -> bool:
    """Return whether a ModuleNotFoundError names BenchBox code, not an SDK dependency."""
    if module_path is not None and (missing_name == module_path or missing_name.startswith(f"{module_path}.")):
        return True
    return missing_name == "benchbox" or missing_name.startswith("benchbox.")


_PLATFORM_METADATA_JSON = """{
"duckdb": {"display_name": "DuckDB", "description": "Columnar OLAP engine • Single-node • In-memory", "category": "analytical", "libraries": [{"name": "duckdb", "required": true}], "requirements": ["duckdb>=0.8.0"], "installation_command": "uv add duckdb", "adoption": "mainstream", "supports": ["olap", "in_memory", "columnar"], "driver_package": "duckdb", "capabilities": {"supports_sql": true, "supports_dataframe": false, "default_mode": "sql", "platform_family": "duckdb", "default_deployment": "local", "deployment_modes": {"local": {"mode": "local", "display_name": "DuckDB Local", "description": "Embedded in-process DuckDB", "requires_credentials": false, "requires_cloud_storage": false, "requires_network": false, "default_for_platform": true, "dependencies": ["duckdb"], "auth_methods": []}}}, "support_status": "stable"},
"datafusion": {"display_name": "DataFusion", "description": "Arrow-based SQL • Single-node • In-memory", "category": "analytical", "libraries": [{"name": "datafusion", "required": true}], "requirements": ["datafusion>=34.0.0"], "installation_command": "uv add datafusion", "adoption": "emerging", "supports": ["olap", "in_memory", "columnar", "arrow", "dataframe"], "driver_package": "datafusion", "capabilities": {"supports_sql": true, "supports_dataframe": true, "default_mode": "sql"}, "support_status": "stable"},
"sqlite": {"display_name": "SQLite", "description": "Row-based OLTP database • Single-node • File-based", "category": "embedded", "libraries": [{"name": "sqlite3", "required": true}], "requirements": ["sqlite3 (built-in)"], "installation_command": "Built-in Python library", "adoption": "niche", "supports": ["transactional", "file_based"], "driver_package": null, "capabilities": {"supports_sql": true, "supports_dataframe": false, "default_mode": "sql"}, "support_status": "stable"},
"polars": {"display_name": "Polars", "description": "DataFrame engine • In-memory • Columnar", "category": "analytical", "libraries": [{"name": "polars", "required": true}], "requirements": ["polars>=0.20.0"], "installation_command": "uv add polars", "adoption": "established", "supports": ["olap", "in_memory", "columnar", "dataframe"], "driver_package": "polars", "capabilities": {"supports_sql": false, "supports_dataframe": true, "default_mode": "dataframe"}, "support_status": "stable"},
"motherduck": {"display_name": "MotherDuck", "description": "Serverless DuckDB cloud • Managed • Cloud storage", "category": "cloud", "libraries": [{"name": "duckdb", "required": true}], "requirements": ["duckdb>=0.9.0"], "installation_command": "uv add duckdb", "adoption": "emerging", "supports": ["olap", "cloud", "columnar", "serverless"], "driver_package": "duckdb", "capabilities": {"supports_sql": true, "supports_dataframe": false, "default_mode": "sql", "platform_family": "duckdb", "inherits_from": "duckdb", "cost_class": "paid_credits", "default_deployment": "managed", "deployment_modes": {"managed": {"mode": "managed", "display_name": "MotherDuck Cloud", "description": "Serverless DuckDB in MotherDuck cloud", "requires_credentials": true, "requires_cloud_storage": false, "requires_network": true, "default_for_platform": true, "dependencies": ["duckdb"], "auth_methods": ["token"]}}}, "support_status": "beta"},
"ducklake": {"display_name": "DuckLake", "description": "Open lakehouse format • DuckDB engine • Parquet + SQL catalog", "category": "olap", "libraries": [{"name": "duckdb", "required": true}], "requirements": ["duckdb>=1.3.0"], "installation_command": "uv add duckdb", "adoption": "emerging", "supports": ["olap", "lakehouse", "columnar", "parquet"], "driver_package": "duckdb", "notes": "MVP: DuckDB-file catalog metadata + local Parquet DATA_PATH only. Requires a live DuckDB runtime >= 1.3 for the ducklake extension; SQLite/Postgres catalogs and S3 DATA_PATH are a follow-on.", "capabilities": {"supports_sql": true, "supports_dataframe": false, "default_mode": "sql", "platform_family": "duckdb", "inherits_from": "duckdb", "default_deployment": "local", "deployment_modes": {"local": {"mode": "local", "display_name": "DuckLake Local", "description": "Local DuckDB-file catalog with Parquet on local disk", "requires_credentials": false, "requires_cloud_storage": false, "requires_network": false, "default_for_platform": true, "dependencies": ["duckdb"], "auth_methods": []}}}, "support_status": "experimental"},
"clickhouse": {"display_name": "ClickHouse", "description": "Columnar OLAP database • Local/server • Distributed", "category": "analytical", "libraries": [{"name": "clickhouse_driver", "required": true, "import_name": "clickhouse_driver"}, {"name": "chdb", "required": false, "description": "Local ClickHouse"}], "requirements": ["clickhouse-driver>=0.2.0"], "installation_command": "uv add clickhouse-driver", "adoption": "established", "supports": ["olap", "columnar", "distributed"], "driver_package": "clickhouse-driver", "capabilities": {"supports_sql": true, "supports_dataframe": false, "default_mode": "sql", "platform_family": "clickhouse", "default_deployment": "local", "deployment_modes": {"local": {"mode": "local", "display_name": "ClickHouse Local (chDB)", "description": "Embedded ClickHouse via chDB library", "requires_credentials": false, "requires_cloud_storage": false, "requires_network": false, "default_for_platform": true, "dependencies": ["chdb"], "auth_methods": []}, "server": {"mode": "self-hosted", "display_name": "ClickHouse Server", "description": "Self-hosted ClickHouse server or cluster", "requires_credentials": true, "requires_cloud_storage": false, "requires_network": true, "default_for_platform": false, "dependencies": ["clickhouse-driver"], "auth_methods": ["password"]}}}, "support_status": "deprecated"},
"clickhouse-local": {"display_name": "ClickHouse Local (chDB)", "description": "Embedded ClickHouse via chDB • In-process • Zero network", "category": "analytical", "libraries": [{"name": "chdb", "required": true, "import_name": "chdb"}], "requirements": ["chdb>=0.10.0"], "installation_command": "uv add benchbox --extra clickhouse-local", "adoption": "established", "supports": ["olap", "columnar", "embedded", "in-process"], "driver_package": "chdb", "capabilities": {"supports_sql": true, "supports_dataframe": false, "default_mode": "sql", "platform_family": "clickhouse", "inherits_from": "clickhouse"}, "support_status": "beta"},
"clickhouse-server": {"display_name": "ClickHouse Server", "description": "Self-hosted ClickHouse • Docker/dedicated • High-performance columnar", "category": "analytical", "libraries": [{"name": "clickhouse_driver", "required": true, "import_name": "clickhouse_driver"}], "requirements": ["clickhouse-driver>=0.2.0"], "installation_command": "uv add benchbox --extra clickhouse-server", "adoption": "established", "supports": ["olap", "columnar", "distributed", "self-hosted"], "driver_package": "clickhouse-driver", "capabilities": {"supports_sql": true, "supports_dataframe": false, "default_mode": "sql", "platform_family": "clickhouse", "inherits_from": "clickhouse", "default_deployment": "self-hosted", "deployment_modes": {"self-hosted": {"mode": "self-hosted", "display_name": "ClickHouse Server Self-Hosted", "description": "Self-hosted ClickHouse Server server", "requires_credentials": true, "requires_cloud_storage": false, "requires_network": true, "default_for_platform": true, "dependencies": ["clickhouse_driver"], "auth_methods": ["password"]}}}, "support_status": "beta"},
"clickhouse-cloud": {"display_name": "ClickHouse Cloud", "description": "Managed ClickHouse • Serverless/dedicated • Cloud analytics", "category": "cloud", "libraries": [{"name": "clickhouse_connect", "required": true, "import_name": "clickhouse_connect"}], "requirements": ["clickhouse-connect>=0.10.0"], "installation_command": "uv add benchbox --extra clickhouse-cloud", "adoption": "emerging", "supports": ["olap", "columnar", "distributed", "serverless", "cloud"], "driver_package": "clickhouse-connect", "capabilities": {"supports_sql": true, "supports_dataframe": false, "default_mode": "sql", "platform_family": "clickhouse", "inherits_from": "clickhouse", "cost_class": "paid_compute", "default_deployment": "managed", "deployment_modes": {"managed": {"mode": "managed", "display_name": "ClickHouse Cloud", "description": "ClickHouse Cloud managed service", "requires_credentials": true, "requires_cloud_storage": true, "requires_network": true, "default_for_platform": true, "dependencies": ["clickhouse-connect"], "auth_methods": ["password", "oauth"]}}}, "support_status": "beta"},
"bigquery": {"display_name": "Google BigQuery", "description": "Columnar data warehouse • Serverless • Petabyte-scale", "category": "cloud", "libraries": [{"name": "google.cloud.bigquery", "required": true, "import_name": "google.cloud.bigquery"}, {"name": "google.cloud.storage", "required": true, "import_name": "google.cloud.storage"}], "requirements": ["google-cloud-bigquery>=3.0.0", "google-cloud-storage>=2.0.0"], "installation_command": "uv add google-cloud-bigquery google-cloud-storage", "adoption": "mainstream", "supports": ["olap", "serverless", "petabyte_scale"], "driver_package": "google-cloud-bigquery", "capabilities": {"supports_sql": true, "supports_dataframe": false, "default_mode": "sql", "cost_class": "paid_credits"}, "support_status": "beta"},
"databricks": {"display_name": "Databricks SQL", "description": "Lakehouse platform • Distributed • Spark-based", "category": "cloud", "libraries": [{"name": "databricks.sql", "required": true, "import_name": "databricks.sql"}], "requirements": ["databricks-sql-connector>=2.0.0"], "installation_command": "uv add databricks-sql-connector", "adoption": "mainstream", "supports": ["olap", "spark", "lakehouse"], "driver_package": "databricks-sql-connector", "capabilities": {"supports_sql": true, "supports_dataframe": true, "default_mode": "sql", "cost_class": "paid_credits"}, "support_status": "beta"},
"databricks-df": {"display_name": "Databricks DataFrame", "description": "Databricks with PySpark DataFrame API • Databricks Connect", "category": "cloud", "libraries": [{"name": "databricks.sql", "required": true, "import_name": "databricks.sql"}, {"name": "databricks.connect", "required": true, "import_name": "databricks.connect"}], "requirements": ["databricks-sql-connector>=2.0.0", "databricks-connect>=14.0.0"], "installation_command": "uv add databricks-sql-connector databricks-connect", "adoption": "niche", "supports": ["olap", "spark", "lakehouse", "dataframe"], "driver_package": "databricks-connect", "capabilities": {"supports_sql": true, "supports_dataframe": true, "default_mode": "dataframe", "cost_class": "paid_credits"}, "support_status": "experimental"},
"snowflake": {"display_name": "Snowflake", "description": "Columnar data warehouse • Serverless • Multi-cloud", "category": "cloud", "libraries": [{"name": "snowflake.connector", "required": true, "import_name": "snowflake.connector"}], "requirements": ["snowflake-connector-python>=3.0.0"], "installation_command": "uv add snowflake-connector-python", "adoption": "mainstream", "supports": ["olap", "serverless", "multi_cloud"], "driver_package": "snowflake-connector-python", "capabilities": {"supports_sql": true, "supports_dataframe": false, "default_mode": "sql", "cost_class": "paid_credits"}, "support_status": "beta"},
"redshift": {"display_name": "Amazon Redshift", "description": "Columnar data warehouse • Distributed • AWS MPP", "category": "cloud", "libraries": [{"name": "redshift_connector", "required": true}, {"name": "boto3", "required": true}], "requirements": ["redshift-connector>=2.0.0", "boto3>=1.20.0"], "installation_command": "uv add redshift-connector boto3", "adoption": "established", "supports": ["olap", "columnar", "aws"], "driver_package": "redshift-connector", "capabilities": {"supports_sql": true, "supports_dataframe": false, "default_mode": "sql", "cost_class": "paid_compute"}, "support_status": "beta"},
"trino": {"display_name": "Trino", "description": "Distributed SQL • Federated • Multi-source", "category": "distributed", "libraries": [{"name": "trino", "required": true}], "requirements": ["trino>=0.328.0"], "installation_command": "uv add trino", "adoption": "established", "supports": ["olap", "federated", "distributed"], "driver_package": "trino", "notes": "Supports Trino and Starburst Enterprise. For PrestoDB use presto-python-client. For AWS Athena use the athena adapter.", "capabilities": {"supports_sql": true, "supports_dataframe": false, "default_mode": "sql", "platform_family": "trino", "default_deployment": "self-hosted", "deployment_modes": {"self-hosted": {"mode": "self-hosted", "display_name": "Trino Self-Hosted", "description": "Self-hosted Trino cluster", "requires_credentials": true, "requires_cloud_storage": false, "requires_network": true, "default_for_platform": true, "dependencies": ["trino"], "auth_methods": ["password", "oauth"]}}}, "support_status": "beta"},
"starburst": {"display_name": "Starburst", "description": "Managed Trino • Starburst Galaxy • Serverless", "category": "cloud", "libraries": [{"name": "trino", "required": true}], "requirements": ["trino>=0.328.0"], "installation_command": "uv add trino", "adoption": "emerging", "supports": ["olap", "federated", "distributed", "serverless", "cloud"], "driver_package": "trino", "notes": "Starburst Galaxy managed Trino service. Uses trino Python driver with HTTPS. For self-hosted Trino use the trino adapter.", "capabilities": {"supports_sql": true, "supports_dataframe": false, "default_mode": "sql", "platform_family": "trino", "inherits_from": "trino", "cost_class": "paid_compute", "default_deployment": "managed", "deployment_modes": {"managed": {"mode": "managed", "display_name": "Starburst Galaxy", "description": "Starburst Galaxy managed Trino service", "requires_credentials": true, "requires_cloud_storage": false, "requires_network": true, "default_for_platform": true, "dependencies": ["trino"], "auth_methods": ["password", "api_key"]}}}, "support_status": "beta"},
"presto": {"display_name": "PrestoDB", "description": "Distributed SQL • Federated • Meta fork", "category": "distributed", "libraries": [{"name": "prestodb", "required": true, "import_name": "prestodb"}], "requirements": ["presto-python-client>=0.8.4"], "installation_command": "uv add presto-python-client", "adoption": "niche", "supports": ["olap", "federated", "distributed"], "driver_package": "presto-python-client", "notes": "Supports PrestoDB (Meta's fork) with X-Presto-* headers. For Trino/Starburst use the trino adapter. For AWS Athena use the athena adapter.", "capabilities": {"supports_sql": true, "supports_dataframe": false, "default_mode": "sql", "default_deployment": "self-hosted", "deployment_modes": {"self-hosted": {"mode": "self-hosted", "display_name": "PrestoDB Self-Hosted", "description": "Self-hosted PrestoDB server", "requires_credentials": true, "requires_cloud_storage": false, "requires_network": true, "default_for_platform": true, "dependencies": ["prestodb"], "auth_methods": ["password"]}}}, "support_status": "beta"},
"postgresql": {"display_name": "PostgreSQL", "description": "Relational database • COPY loading", "category": "relational", "libraries": [{"name": "psycopg", "required": true}], "requirements": ["psycopg[binary]>=3.1"], "installation_command": "uv add 'psycopg[binary]'", "adoption": "established", "supports": ["olap", "oltp", "relational"], "driver_package": "psycopg", "notes": "Supports PostgreSQL 12+. COPY-based bulk loading. For time-series workloads use timescaledb.", "capabilities": {"supports_sql": true, "supports_dataframe": false, "default_mode": "sql", "default_deployment": "self-hosted", "deployment_modes": {"self-hosted": {"mode": "self-hosted", "display_name": "PostgreSQL Self-Hosted", "description": "Self-hosted PostgreSQL server", "requires_credentials": true, "requires_cloud_storage": false, "requires_network": true, "default_for_platform": true, "dependencies": ["psycopg"], "auth_methods": ["password"]}}}, "support_status": "beta"},
"timescaledb": {"display_name": "TimescaleDB", "description": "Time-series database • Hypertables • Compression", "category": "timeseries", "libraries": [{"name": "psycopg", "required": true}], "requirements": ["psycopg[binary]>=3.1"], "installation_command": "uv add 'psycopg[binary]'", "adoption": "niche", "supports": ["timeseries", "olap", "compression"], "driver_package": "psycopg", "notes": "PostgreSQL extension for time-series. Automatic hypertables, compression policies. Requires TimescaleDB 2.x on server.", "capabilities": {"supports_sql": true, "supports_dataframe": false, "default_mode": "sql", "platform_family": "timescaledb", "default_deployment": "self-hosted", "deployment_modes": {"self-hosted": {"mode": "self-hosted", "display_name": "TimescaleDB Self-Hosted", "description": "Self-hosted TimescaleDB server", "requires_credentials": true, "requires_cloud_storage": false, "requires_network": true, "default_for_platform": true, "dependencies": ["psycopg[binary]"], "auth_methods": ["password"]}, "cloud": {"mode": "managed", "display_name": "TigerData", "description": "TigerData managed PostgreSQL service", "requires_credentials": true, "requires_cloud_storage": false, "requires_network": true, "default_for_platform": false, "dependencies": ["psycopg[binary]"], "auth_methods": ["password"]}}}, "support_status": "beta"},
"pg-mooncake": {"display_name": "pg_mooncake", "description": "Columnstore PostgreSQL • Parquet/Iceberg • DuckDB Execution", "category": "olap", "libraries": [{"name": "psycopg", "required": true}], "requirements": ["psycopg[binary]>=3.1"], "installation_command": "uv add 'psycopg[binary]'", "adoption": "emerging", "supports": ["olap", "columnstore", "analytics"], "driver_package": "psycopg", "notes": "PostgreSQL extension adding native columnstore tables (Parquet/Iceberg) with DuckDB execution. Requires pg_mooncake on server. Conflicts with standalone pg_duckdb (shared libduckdb.so).", "capabilities": {"supports_sql": true, "supports_dataframe": false, "default_mode": "sql", "platform_family": "pg_mooncake", "conflicts_with": ["pg-duckdb"], "default_deployment": "self-hosted", "deployment_modes": {"self-hosted": {"mode": "self-hosted", "display_name": "pg_mooncake Self-Hosted", "description": "Self-hosted PostgreSQL with pg_mooncake extension", "requires_credentials": true, "requires_cloud_storage": false, "requires_network": true, "default_for_platform": true, "dependencies": ["psycopg[binary]"], "auth_methods": ["password"]}}}, "support_status": "experimental"},
"cedardb": {"display_name": "CedarDB", "description": "High-performance OLAP/OLTP • PostgreSQL-compatible • Formerly Umbra", "category": "olap", "libraries": [{"name": "psycopg", "required": true}], "requirements": ["psycopg[binary]>=3.1"], "installation_command": "uv add 'psycopg[binary]'", "adoption": "emerging", "supports": ["olap", "oltp", "relational"], "driver_package": "psycopg", "notes": "CedarDB (formerly Umbra) is a standalone RDBMS with PostgreSQL wire protocol compatibility. Not a PostgreSQL extension - connects via standard psycopg3 (psycopg) drivers.", "capabilities": {"supports_sql": true, "supports_dataframe": false, "default_mode": "sql", "platform_family": "cedardb", "default_deployment": "self-hosted", "deployment_modes": {"self-hosted": {"mode": "self-hosted", "display_name": "CedarDB Self-Hosted", "description": "Self-hosted CedarDB server", "requires_credentials": true, "requires_cloud_storage": false, "requires_network": true, "default_for_platform": true, "dependencies": ["psycopg[binary]"], "auth_methods": ["password"]}}}, "support_status": "experimental"},
"pg-duckdb": {"display_name": "pg_duckdb", "description": "DuckDB-accelerated PostgreSQL • Vectorized OLAP • MotherDuck", "category": "olap", "libraries": [{"name": "psycopg", "required": true}], "requirements": ["psycopg[binary]>=3.1"], "installation_command": "uv add 'psycopg[binary]'", "adoption": "emerging", "supports": ["olap", "analytics"], "driver_package": "psycopg", "notes": "PostgreSQL extension embedding DuckDB vectorized execution. Requires pg_duckdb 1.0+ on server. Conflicts with pg_mooncake (shared libduckdb.so).", "capabilities": {"supports_sql": true, "supports_dataframe": false, "default_mode": "sql", "platform_family": "pg_duckdb", "conflicts_with": ["pg-mooncake"], "cost_class": "paid_credits", "default_deployment": "self-hosted", "deployment_modes": {"self-hosted": {"mode": "self-hosted", "display_name": "pg_duckdb Self-Hosted", "description": "Self-hosted PostgreSQL with pg_duckdb extension", "requires_credentials": true, "requires_cloud_storage": false, "requires_network": true, "default_for_platform": true, "dependencies": ["psycopg[binary]"], "auth_methods": ["password"]}, "motherduck": {"mode": "managed", "display_name": "pg_duckdb + MotherDuck", "description": "pg_duckdb with MotherDuck cloud offload for hybrid queries", "requires_credentials": true, "requires_cloud_storage": false, "requires_network": true, "default_for_platform": false, "dependencies": ["psycopg[binary]"], "auth_methods": ["token"]}}}, "support_status": "experimental"},
"synapse": {"display_name": "Azure Synapse Analytics", "description": "Cloud data warehouse • Dedicated SQL Pool • Azure MPP", "category": "cloud", "libraries": [{"name": "pyodbc", "required": true}, {"name": "azure.storage.blob", "required": false, "import_name": "azure.storage.blob"}, {"name": "azure.identity", "required": false, "import_name": "azure.identity"}], "requirements": ["pyodbc>=4.0.0"], "installation_command": "uv add pyodbc azure-storage-blob azure-identity", "adoption": "established", "supports": ["olap", "columnar", "azure", "distributed"], "driver_package": "pyodbc", "notes": "Supports Azure Synapse Dedicated SQL Pools. COPY INTO for bulk loading. T-SQL dialect.", "capabilities": {"supports_sql": true, "supports_dataframe": false, "default_mode": "sql", "cost_class": "paid_compute"}, "support_status": "beta"},
"fabric_dw": {"display_name": "Microsoft Fabric Warehouse", "description": "Microsoft Fabric Warehouse • OneLake • Delta Lake native", "category": "cloud", "libraries": [{"name": "pyodbc", "required": true}, {"name": "azure.identity", "required": true, "import_name": "azure.identity"}, {"name": "azure.storage.filedatalake", "required": false, "import_name": "azure.storage.filedatalake"}], "requirements": ["pyodbc>=4.0.0", "azure-identity>=1.15.0"], "installation_command": "uv add pyodbc azure-identity azure-storage-file-datalake", "adoption": "niche", "supports": ["olap", "columnar", "azure", "delta_lake", "onelake"], "driver_package": "pyodbc", "notes": "Supports Fabric Warehouse only (not Lakehouse). Entra ID auth only. OneLake + COPY INTO for bulk loading. T-SQL dialect (subset).", "capabilities": {"supports_sql": true, "supports_dataframe": false, "default_mode": "sql", "cost_class": "paid_compute"}, "support_status": "beta"},
"firebolt": {"display_name": "Firebolt", "description": "Vectorized analytics • Local/Cloud • PG-wire", "category": "cloud", "libraries": [{"name": "firebolt.db", "required": true, "import_name": "firebolt.db"}], "requirements": ["firebolt-sdk>=1.18.0"], "installation_command": "uv add firebolt-sdk", "adoption": "emerging", "supports": ["olap", "vectorized", "columnar", "local", "cloud"], "driver_package": "firebolt-sdk", "notes": "Supports Firebolt Core (free, local Docker) and Firebolt Cloud. PostgreSQL-compatible SQL dialect. Vectorized query execution optimized for analytics.", "capabilities": {"supports_sql": true, "supports_dataframe": false, "default_mode": "sql", "platform_family": "firebolt", "cost_class": "paid_compute", "default_deployment": "core", "deployment_modes": {"core": {"mode": "local", "display_name": "Firebolt Core", "description": "Free local Firebolt via Docker container", "requires_credentials": false, "requires_cloud_storage": false, "requires_network": false, "default_for_platform": true, "dependencies": ["firebolt-sdk"], "auth_methods": []}, "cloud": {"mode": "managed", "display_name": "Firebolt Cloud", "description": "Firebolt Cloud managed service", "requires_credentials": true, "requires_cloud_storage": true, "requires_network": true, "default_for_platform": false, "dependencies": ["firebolt-sdk"], "auth_methods": ["oauth", "service_account"]}}}, "support_status": "beta"},
"starrocks": {"display_name": "StarRocks", "description": "Columnar analytics engine • Distributed • Fast OLAP", "category": "analytical", "libraries": [{"name": "pymysql", "required": true, "import_name": "pymysql"}], "requirements": ["pymysql>=1.1.0"], "installation_command": "uv add pymysql", "adoption": "emerging", "supports": ["olap", "columnar", "distributed", "mpp"], "driver_package": "pymysql", "capabilities": {"supports_sql": true, "supports_dataframe": false, "default_mode": "sql", "platform_family": "starrocks", "default_deployment": "self-hosted", "deployment_modes": {"self-hosted": {"mode": "self-hosted", "display_name": "StarRocks Self-Hosted", "description": "Self-hosted StarRocks cluster", "requires_credentials": true, "requires_cloud_storage": false, "requires_network": true, "default_for_platform": true, "dependencies": ["pymysql"], "auth_methods": ["password"]}}}, "support_status": "beta"},
"databend": {"display_name": "Databend", "description": "Cloud-native OLAP • Rust • Snowflake-compatible", "category": "cloud", "libraries": [{"name": "databend_driver", "required": true, "import_name": "databend_driver"}], "requirements": ["databend-driver>=0.28.0"], "installation_command": "uv add databend-driver", "adoption": "emerging", "supports": ["olap", "cloud", "columnar", "object_storage", "snowflake_compatible"], "driver_package": "databend-driver", "notes": "Cloud-native Rust-based data warehouse with Snowflake-compatible SQL. Compute/storage separation on object storage (S3, GCS, Azure Blob). Uses Snowflake dialect as sqlglot translation proxy.", "capabilities": {"supports_sql": true, "supports_dataframe": false, "default_mode": "sql", "platform_family": "databend", "cost_class": "paid_compute", "default_deployment": "cloud", "deployment_modes": {"cloud": {"mode": "managed", "display_name": "Databend Cloud", "description": "Databend Cloud managed service", "requires_credentials": true, "requires_cloud_storage": true, "requires_network": true, "default_for_platform": true, "dependencies": ["databend-driver"], "auth_methods": ["password"]}, "self-hosted": {"mode": "self-hosted", "display_name": "Databend Self-Hosted", "description": "User-managed Databend cluster with object storage", "requires_credentials": true, "requires_cloud_storage": true, "requires_network": true, "default_for_platform": false, "dependencies": ["databend-driver"], "auth_methods": ["password"]}}}, "support_status": "beta"},
"doris": {"display_name": "Apache Doris", "description": "MPP OLAP • Real-time analytics • MySQL protocol", "category": "distributed", "libraries": [{"name": "pymysql", "required": true}], "requirements": ["pymysql>=1.0.0"], "installation_command": "uv add pymysql", "adoption": "emerging", "supports": ["olap", "mpp", "columnar", "real-time", "vectorized"], "driver_package": "pymysql", "notes": "Apache Doris 2.0+ with vectorized execution. MySQL protocol on port 9030, Stream Load on port 8030. SQLGlot 'doris' dialect.", "capabilities": {"supports_sql": true, "supports_dataframe": false, "default_mode": "sql", "platform_family": "doris", "default_deployment": "self-hosted", "deployment_modes": {"self-hosted": {"mode": "self-hosted", "display_name": "Apache Doris Self-Hosted", "description": "Self-hosted Apache Doris cluster", "requires_credentials": true, "requires_cloud_storage": false, "requires_network": true, "default_for_platform": true, "dependencies": ["pymysql"], "auth_methods": ["password"]}}}, "support_status": "beta"},
"singlestore": {"display_name": "SingleStore", "description": "Distributed SQL • Real-time analytics • MySQL protocol", "category": "distributed", "libraries": [{"name": "singlestoredb", "required": true, "import_name": "singlestoredb"}], "requirements": ["singlestoredb>=1.0.0"], "installation_command": "uv add singlestoredb", "adoption": "emerging", "supports": ["olap", "htap", "distributed", "columnstore", "real-time", "mysql-compatible"], "driver_package": "singlestoredb", "notes": "SingleStore 8.0+ with columnstore analytics. MySQL wire protocol on port 3306. SQLGlot 'mysql' dialect. Supports both Helios (cloud) and self-managed deployments.", "capabilities": {"supports_sql": true, "supports_dataframe": false, "default_mode": "sql", "platform_family": "singlestore", "cost_class": "paid_compute", "default_deployment": "self-hosted", "deployment_modes": {"self-hosted": {"mode": "self-hosted", "display_name": "SingleStore Self-Managed", "description": "Self-managed SingleStore cluster", "requires_credentials": true, "requires_cloud_storage": false, "requires_network": true, "default_for_platform": true, "dependencies": ["singlestoredb"], "auth_methods": ["password"]}, "cloud": {"mode": "managed", "display_name": "SingleStore Helios", "description": "SingleStore Helios managed cloud service", "requires_credentials": true, "requires_cloud_storage": false, "requires_network": true, "default_for_platform": false, "dependencies": ["singlestoredb"], "auth_methods": ["password"]}}}, "support_status": "beta"},
"influxdb": {"display_name": "InfluxDB", "description": "Time series database • FlightSQL • Arrow-native", "category": "timeseries", "libraries": [{"name": "influxdb3", "required": true, "import_name": "influxdb3"}, {"name": "flightsql", "required": false, "alternative": true, "import_name": "flightsql"}], "requirements": ["influxdb3-python>=0.1.0"], "installation_command": "uv add influxdb3-python", "adoption": "niche", "supports": ["timeseries", "olap", "arrow", "flightsql"], "driver_package": "influxdb3-python", "notes": "InfluxDB 3.x time series database with native SQL support via FlightSQL. Built on Apache Arrow, DataFusion, and Parquet. Optimized for TSBS DevOps workloads.", "capabilities": {"supports_sql": true, "supports_dataframe": false, "default_mode": "sql", "default_deployment": "self-hosted", "deployment_modes": {"self-hosted": {"mode": "self-hosted", "display_name": "InfluxDB Self-Hosted", "description": "Self-hosted InfluxDB server", "requires_credentials": true, "requires_cloud_storage": false, "requires_network": true, "default_for_platform": true, "dependencies": ["influxdb3"], "auth_methods": ["password"]}}}, "support_status": "beta"},
"questdb": {"display_name": "QuestDB", "description": "Time-series database • PG wire protocol • High-performance ingestion", "category": "timeseries", "libraries": [{"name": "psycopg", "required": true}, {"name": "requests", "required": true}], "requirements": ["psycopg[binary]>=3.1", "requests>=2.28.0"], "installation_command": "uv add benchbox --extra questdb", "adoption": "emerging", "supports": ["timeseries", "olap", "columnar", "high_throughput"], "driver_package": "psycopg", "notes": "QuestDB 7.0+ time-series database. PostgreSQL wire protocol for queries, REST API for data import. Optimized for fast ingestion and time-series analytics.", "capabilities": {"supports_sql": true, "supports_dataframe": false, "default_mode": "sql", "platform_family": "questdb", "default_deployment": "self-hosted", "deployment_modes": {"self-hosted": {"mode": "self-hosted", "display_name": "QuestDB Self-Hosted", "description": "Self-hosted QuestDB server (Docker recommended)", "requires_credentials": true, "requires_cloud_storage": false, "requires_network": true, "default_for_platform": true, "dependencies": ["psycopg[binary]"], "auth_methods": ["password"]}}, "unsupported_benchmarks": {"vector_search": "QuestDB 9.3.4 has no VECTOR column type. Schema creation fails immediately. No fix planned: requires QuestDB to add native vector support."}}, "support_status": "beta"},
"athena": {"display_name": "Amazon Athena", "description": "Serverless SQL • S3 data lake • Pay-per-query", "category": "cloud", "libraries": [{"name": "pyathena", "required": true}, {"name": "boto3", "required": true}], "requirements": ["pyathena>=3.0.0", "boto3>=1.20.0"], "installation_command": "uv add pyathena boto3", "adoption": "established", "supports": ["olap", "serverless", "s3", "data_lake"], "driver_package": "pyathena", "notes": "AWS serverless query service using Trino under the hood. Pay-per-query pricing ($5/TB scanned). Native S3 and Glue Data Catalog integration.", "capabilities": {"supports_sql": true, "supports_dataframe": false, "default_mode": "sql", "cost_class": "paid_credits"}, "support_status": "beta"},
"glue": {"display_name": "AWS Glue", "description": "Managed Spark • Serverless ETL • Pay-per-DPU", "category": "cloud", "libraries": [{"name": "boto3", "required": true}], "requirements": ["boto3>=1.34.0"], "installation_command": "uv add boto3", "adoption": "niche", "supports": ["olap", "serverless", "spark", "etl", "s3"], "driver_package": "boto3", "notes": "AWS managed Spark ETL service. Pay-per-DPU pricing (~$0.44/DPU-hour). Uses Glue Data Catalog for metadata. Supports both SQL and DataFrame execution modes.", "capabilities": {"supports_sql": true, "supports_dataframe": true, "default_mode": "sql", "cost_class": "paid_compute"}, "support_status": "experimental"},
"emr-serverless": {"display_name": "Amazon EMR Serverless", "description": "Serverless Spark • Sub-second startup • Pay-per-use", "category": "cloud", "libraries": [{"name": "boto3", "required": true}], "requirements": ["boto3>=1.34.0"], "installation_command": "uv add boto3", "adoption": "niche", "supports": ["olap", "serverless", "spark", "s3"], "driver_package": "boto3", "notes": "AWS serverless Spark with automatic scaling and sub-second startup. Pay per vCPU-hour and memory-GB-hour. Uses Glue Data Catalog for metadata.", "capabilities": {"supports_sql": true, "supports_dataframe": true, "default_mode": "sql", "cost_class": "paid_compute"}, "support_status": "experimental"},
"athena-spark": {"display_name": "Amazon Athena for Apache Spark", "description": "Interactive Spark • Sub-second startup • Session-based", "category": "cloud", "libraries": [{"name": "boto3", "required": true}], "requirements": ["boto3>=1.34.0"], "installation_command": "uv add boto3", "adoption": "niche", "supports": ["olap", "interactive", "spark", "s3", "sessions"], "driver_package": "boto3", "notes": "AWS interactive Spark with notebook-style sessions. Sub-second startup with pre-provisioned capacity. Uses Glue Data Catalog for metadata. Pay per DPU-hour.", "capabilities": {"supports_sql": true, "supports_dataframe": true, "default_mode": "sql", "cost_class": "paid_compute"}, "support_status": "experimental"},
"dataproc": {"display_name": "Google Cloud Dataproc", "description": "Managed Spark • Google Cloud clusters • Per-second billing", "category": "cloud", "libraries": [{"name": "google-cloud-dataproc", "required": true}, {"name": "google-cloud-storage", "required": true}], "requirements": ["google-cloud-dataproc>=5.0.0", "google-cloud-storage>=2.0.0"], "installation_command": "uv add google-cloud-dataproc google-cloud-storage", "adoption": "niche", "supports": ["olap", "spark", "cluster", "gcs", "hive"], "driver_package": "google-cloud-dataproc", "notes": "Google Cloud managed Spark service. Per-second billing with preemptible VM support. Supports persistent and ephemeral clusters. Uses Hive Metastore for table metadata.", "capabilities": {"supports_sql": true, "supports_dataframe": true, "default_mode": "sql", "cost_class": "paid_compute"}, "support_status": "experimental"},
"dataproc-serverless": {"display_name": "Google Cloud Dataproc Serverless", "description": "Serverless Spark • No cluster management • Auto-scaling", "category": "cloud", "libraries": [{"name": "google-cloud-dataproc", "required": true}, {"name": "google-cloud-storage", "required": true}], "requirements": ["google-cloud-dataproc>=5.0.0", "google-cloud-storage>=2.0.0"], "installation_command": "uv add google-cloud-dataproc google-cloud-storage", "adoption": "niche", "supports": ["olap", "spark", "serverless", "gcs", "hive"], "driver_package": "google-cloud-dataproc", "notes": "Google Cloud Dataproc Serverless for fully managed Spark. No cluster management required. Sub-minute startup, auto-scaling, per-second billing. Uses Batch Controller API.", "capabilities": {"supports_sql": true, "supports_dataframe": true, "default_mode": "sql", "cost_class": "paid_compute"}, "support_status": "experimental"},
"fabric-spark": {"display_name": "Microsoft Fabric Spark", "description": "SaaS Spark • OneLake storage • Entra ID auth", "category": "cloud", "libraries": [{"name": "azure-identity", "required": true}, {"name": "azure-storage-file-datalake", "required": true}, {"name": "requests", "required": true}], "requirements": ["azure-identity>=1.15.0", "azure-storage-file-datalake>=12.14.0", "requests>=2.31.0"], "installation_command": "uv add azure-identity azure-storage-file-datalake requests", "adoption": "niche", "supports": ["olap", "spark", "saas", "delta", "onelake"], "driver_package": "azure-identity", "notes": "Microsoft Fabric SaaS Spark with OneLake storage. Uses Livy API for session management. Entra ID (Azure AD) authentication. Capacity Units billing model.", "capabilities": {"supports_sql": true, "supports_dataframe": true, "default_mode": "sql", "cost_class": "paid_compute"}, "support_status": "experimental"},
"fabric-lakehouse": {"display_name": "Microsoft Fabric Lakehouse SQL", "description": "Read-only T-SQL endpoint • Lakehouse analytics", "category": "cloud", "libraries": [{"name": "pyodbc", "required": true}, {"name": "azure-identity", "required": true}], "requirements": ["pyodbc>=4.0.39", "azure-identity>=1.15.0"], "installation_command": "uv add benchbox --extra fabric", "adoption": "niche", "supports": ["olap", "cloud", "read_only", "delta", "onelake"], "driver_package": "pyodbc", "notes": "Fabric Lakehouse SQL Analytics Endpoint is read-only. Use fabric-spark for generate/load phases and fabric-lakehouse for query phases.", "capabilities": {"supports_sql": true, "supports_dataframe": false, "default_mode": "sql", "cost_class": "paid_compute"}, "support_status": "beta"},
"synapse-spark": {"display_name": "Azure Synapse Analytics Spark", "description": "Enterprise Spark • ADLS Gen2 • Spark pools", "category": "cloud", "libraries": [{"name": "azure-identity", "required": true}, {"name": "azure-storage-file-datalake", "required": true}, {"name": "requests", "required": true}], "requirements": ["azure-identity>=1.15.0", "azure-storage-file-datalake>=12.14.0", "requests>=2.31.0"], "installation_command": "uv add azure-identity azure-storage-file-datalake requests", "adoption": "niche", "supports": ["olap", "spark", "enterprise", "adls", "hive"], "driver_package": "azure-identity", "notes": "Azure Synapse Analytics Spark with ADLS Gen2 storage. Uses Livy API for session management. vCore-hour billing. Supports external Hive Metastore.", "capabilities": {"supports_sql": true, "supports_dataframe": true, "default_mode": "sql", "cost_class": "paid_compute"}, "support_status": "experimental"},
"spark": {"display_name": "Apache Spark", "description": "Distributed SQL • Local/cluster • Spark engine", "category": "distributed", "libraries": [{"name": "pyspark", "required": true}], "requirements": ["pyspark>=3.5.0"], "installation_command": "uv add pyspark", "adoption": "mainstream", "supports": ["olap", "distributed", "spark", "batch"], "driver_package": "pyspark", "notes": "Apache Spark distributed SQL engine. Supports local, standalone, YARN, and Kubernetes modes. Use 'pyspark' for DataFrame API benchmarking.", "capabilities": {"supports_sql": true, "supports_dataframe": false, "default_mode": "sql"}, "support_status": "beta"},
"velox": {"display_name": "Apache Gluten + Velox", "description": "Spark SQL • Native C++ acceleration • Gluten plugin", "category": "distributed", "libraries": [{"name": "pyspark", "required": true}], "requirements": ["pyspark>=3.5.0"], "installation_command": "uv add benchbox --extra velox", "adoption": "emerging", "supports": ["olap", "distributed", "spark", "native", "accelerated", "batch"], "driver_package": "pyspark", "notes": "Apache Gluten + Velox accelerates Spark SQL by offloading physical operators to a vectorized C++ engine. Requires the Gluten bundle jar on the execution host. Linux only for local mode; Docker is the primary path on macOS/Windows. See docs/platforms/velox.md and docker/velox/.", "capabilities": {"supports_sql": true, "supports_dataframe": false, "default_mode": "sql", "platform_family": "spark", "default_deployment": "local", "deployment_modes": {"local": {"mode": "local", "display_name": "Velox Local", "description": "SparkSession with Gluten jar on local Linux host (or Docker container)", "requires_credentials": false, "requires_cloud_storage": false, "requires_network": false, "default_for_platform": true, "dependencies": ["pyspark"], "auth_methods": []}, "remote": {"mode": "self-hosted", "display_name": "Velox Remote", "description": "Connect to a pre-started Spark-Connect server with Gluten wired", "requires_credentials": false, "requires_cloud_storage": false, "requires_network": true, "default_for_platform": false, "dependencies": ["pyspark"], "auth_methods": []}}}, "support_status": "experimental"},
"lakesail": {"display_name": "LakeSail Sail", "description": "Spark-compatible SQL • Rust/DataFusion • Spark Connect", "category": "analytical", "libraries": [{"name": "pyspark", "required": true}], "requirements": ["pyspark>=3.4.0"], "installation_command": "uv add pyspark", "adoption": "emerging", "supports": ["olap", "spark_compatible", "datafusion", "rust", "batch"], "driver_package": "pyspark", "notes": "LakeSail Sail is a Rust-based drop-in Spark replacement built on DataFusion. Connects via Spark Connect protocol using standard PySpark client. 4x faster than Apache Spark on TPC-H SF100.", "capabilities": {"supports_sql": true, "supports_dataframe": true, "default_mode": "sql", "platform_family": "spark", "default_deployment": "local", "deployment_modes": {"local": {"mode": "local", "display_name": "LakeSail Local", "description": "Single-node multi-threaded execution", "requires_credentials": false, "requires_cloud_storage": false, "requires_network": false, "default_for_platform": true, "dependencies": ["pyspark"], "auth_methods": []}, "distributed": {"mode": "self-hosted", "display_name": "LakeSail Distributed", "description": "Distributed cluster of Rust workers", "requires_credentials": false, "requires_cloud_storage": false, "requires_network": true, "default_for_platform": false, "dependencies": ["pyspark"], "auth_methods": []}}}, "support_status": "experimental"},
"snowpark-connect": {"display_name": "Snowpark Connect for Spark", "description": "PySpark API • Snowflake native • No cluster required", "category": "cloud", "libraries": [{"name": "snowflake.snowpark", "required": true, "import_name": "snowflake.snowpark"}], "requirements": ["snowflake-snowpark-python>=1.20.0"], "installation_command": "uv add snowflake-snowpark-python", "adoption": "niche", "supports": ["olap", "pyspark_compatible", "snowflake", "dataframe"], "driver_package": "snowflake-snowpark-python", "notes": "PySpark DataFrame API compatibility layer on Snowflake. NOT Apache Spark - translates DataFrame operations to Snowflake SQL. No Spark cluster required.", "capabilities": {"supports_sql": true, "supports_dataframe": true, "default_mode": "dataframe", "cost_class": "paid_credits"}, "support_status": "experimental"},
"quanton": {"display_name": "Onehouse Quanton", "description": "Serverless Spark • Hudi/Iceberg/Delta • 2-3x faster", "category": "cloud", "libraries": [{"name": "requests", "required": true}, {"name": "boto3", "required": true}], "requirements": ["requests>=2.31.0", "boto3>=1.34.0"], "installation_command": "uv add requests boto3", "adoption": "emerging", "supports": ["olap", "serverless", "spark", "hudi", "iceberg", "delta", "s3", "lakehouse"], "driver_package": "requests", "notes": "Onehouse Quanton serverless Spark. Multi-table-format support (Hudi, Iceberg, Delta). XTable cross-format metadata translation. 2-3x better price-performance than EMR/Databricks.", "capabilities": {"supports_sql": true, "supports_dataframe": true, "default_mode": "sql", "platform_family": "spark", "cost_class": "paid_compute", "default_deployment": "managed", "deployment_modes": {"managed": {"mode": "managed", "display_name": "Onehouse Quanton", "description": "Serverless managed Spark on Onehouse", "requires_credentials": true, "requires_cloud_storage": true, "requires_network": true, "default_for_platform": true, "dependencies": ["requests", "boto3"], "auth_methods": ["api_key"]}}}, "support_status": "experimental"},
"pandas": {"display_name": "Pandas", "description": "Python DataFrame library • In-memory • Single-node", "category": "dataframe", "libraries": [{"name": "pandas", "required": true}], "requirements": ["pandas>=2.0.0"], "installation_command": "uv add pandas", "adoption": "emerging", "supports": ["dataframe", "in_memory"], "driver_package": null, "capabilities": {"supports_sql": false, "supports_dataframe": true, "default_mode": "dataframe"}, "support_status": "stable"},
"modin": {"display_name": "Modin", "description": "Distributed Pandas • Ray/Dask backend • Drop-in", "category": "dataframe", "libraries": [{"name": "modin", "required": true}], "requirements": ["modin[ray]>=0.28.0"], "installation_command": "uv add modin[ray]", "adoption": "niche", "supports": ["dataframe", "distributed"], "driver_package": null, "capabilities": {"supports_sql": false, "supports_dataframe": true, "default_mode": "dataframe"}, "support_status": "experimental"},
"cudf": {"display_name": "cuDF", "description": "GPU DataFrame • NVIDIA RAPIDS • CUDA required", "category": "dataframe", "libraries": [{"name": "cudf", "required": true}], "requirements": ["cudf-cu12>=24.0.0"], "installation_command": "pip install cudf-cu12 (requires NVIDIA GPU)", "adoption": "niche", "supports": ["dataframe", "gpu"], "driver_package": null, "capabilities": {"supports_sql": false, "supports_dataframe": true, "default_mode": "dataframe"}, "support_status": "experimental"},
"dask": {"display_name": "Dask", "description": "Distributed DataFrame • Lazy eval • Cluster-scale", "category": "dataframe", "libraries": [{"name": "dask", "required": true}], "requirements": ["dask[distributed]>=2024.0.0"], "installation_command": "uv add dask[distributed]", "adoption": "niche", "supports": ["dataframe", "distributed", "lazy"], "driver_package": null, "capabilities": {"supports_sql": false, "supports_dataframe": true, "default_mode": "dataframe"}, "support_status": "beta"},
"pyspark": {"display_name": "PySpark", "description": "Spark DataFrame API • Distributed • Java 17+", "category": "dataframe", "libraries": [{"name": "pyspark", "required": true}], "requirements": ["pyspark>=3.5.0"], "installation_command": "uv add pyspark", "adoption": "established", "supports": ["dataframe", "distributed", "spark"], "driver_package": null, "notes": "Requires Java 17 or 21. Java 23+ not supported by PySpark 4.x.", "capabilities": {"supports_sql": true, "supports_dataframe": true, "default_mode": "dataframe", "platform_family": "spark", "default_deployment": "local", "deployment_modes": {"local": {"mode": "local", "display_name": "PySpark Local", "description": "Local PySpark with single-node Spark", "requires_credentials": false, "requires_cloud_storage": false, "requires_network": false, "default_for_platform": true, "dependencies": ["pyspark"], "auth_methods": []}}}, "support_status": "beta"}
}"""


def _load_platform_metadata() -> dict[str, dict[str, Any]]:
    data = json.loads(_PLATFORM_METADATA_JSON)
    if not isinstance(data, dict):
        raise ValueError("platform metadata payload must contain a mapping")
    return data


@dataclass(frozen=True)
class OptionalAdapterDiagnostic:
    """Diagnostic detail for an optional adapter import attempt."""

    platform_name: str
    module_path: str
    class_name: str
    status: OptionalAdapterImportStatus
    support_status: Optional[SupportStatus] = None
    available: bool = False
    error_type: Optional[str] = None
    error_message: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-friendly representation for CLI/tests/docs tooling."""
        return {
            "platform_name": self.platform_name,
            "module_path": self.module_path,
            "class_name": self.class_name,
            "status": self.status,
            "support_status": self.support_status,
            "available": self.available,
            "error_type": self.error_type,
            "error_message": self.error_message,
        }


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
        cost_class: Coarse cost model for prompt safety gates
    """

    supports_sql: bool = False
    supports_dataframe: bool = False
    default_mode: Literal["sql", "dataframe"] = "sql"
    deployment_modes: dict[str, DeploymentCapability] = field(default_factory=dict)
    default_deployment: str = "local"
    platform_family: Optional[str] = None
    inherits_from: Optional[str] = None
    cost_class: CostClass = "free"
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
    _self_hosted_deployment_platforms: tuple[str, ...] = (
        "clickhouse-server",
        "postgresql",
        "presto",
        "influxdb",
    )

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
        metadata = _load_platform_metadata()
        cls._apply_self_hosted_deployment_defaults(metadata)
        cls._apply_support_status(metadata)
        return metadata

    @classmethod
    def _apply_self_hosted_deployment_defaults(cls, metadata: dict[str, dict[str, Any]]) -> None:
        """Add explicit self-hosted deployment metadata for server-style platforms."""
        for platform_name in cls._self_hosted_deployment_platforms:
            spec = metadata.get(platform_name)
            if spec is None:
                continue
            caps = spec.setdefault("capabilities", {})
            caps.setdefault("default_deployment", "self-hosted")
            deployment_modes = caps.setdefault("deployment_modes", {})
            deployment_modes.setdefault(
                "self-hosted",
                {
                    "mode": "self-hosted",
                    "display_name": f"{spec['display_name']} Self-Hosted",
                    "description": f"Self-hosted {spec['display_name']} server",
                    "requires_credentials": True,
                    "requires_cloud_storage": False,
                    "requires_network": True,
                    "default_for_platform": True,
                    "dependencies": [lib["name"] for lib in spec.get("libraries", []) if lib.get("required")],
                    "auth_methods": ["password"],
                },
            )

        velox = metadata.get("velox", {}).get("capabilities", {}).get("deployment_modes", {}).get("remote")
        if velox is not None:
            velox["mode"] = "self-hosted"

    @staticmethod
    def _apply_support_status(metadata: dict[str, dict[str, Any]]) -> None:
        """Attach and validate product support status for every platform."""
        missing = sorted(set(metadata) - set(_PLATFORM_SUPPORT_STATUS))
        orphaned = sorted(set(_PLATFORM_SUPPORT_STATUS) - set(metadata))
        invalid = sorted(
            name for name, status in _PLATFORM_SUPPORT_STATUS.items() if status not in SUPPORT_STATUS_VALUES
        )
        if missing or orphaned or invalid:
            details = []
            if missing:
                details.append(f"missing support_status for: {', '.join(missing)}")
            if orphaned:
                details.append(f"support_status entries without metadata: {', '.join(orphaned)}")
            if invalid:
                details.append(f"invalid support_status entries: {', '.join(invalid)}")
            raise ValueError("Invalid platform support_status metadata: " + "; ".join(details))

        for platform_name, platform_spec in metadata.items():
            existing = platform_spec.get("support_status")
            status = _PLATFORM_SUPPORT_STATUS[platform_name]
            if existing is not None and existing != status:
                raise ValueError(
                    f"Platform {platform_name!r} has conflicting support_status values: "
                    f"{existing!r} in metadata and {status!r} in registry map"
                )
            platform_spec["support_status"] = status

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
        except (ImportError, OSError) as e:
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
                except (ImportError, OSError):
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
    def get_platform_support_status(cls, platform_name: str) -> Optional[SupportStatus]:
        """Return the registry support status for a platform."""
        metadata = cls.get_all_platform_metadata()
        canonical_name = cls.resolve_platform_name(platform_name)
        platform_spec = metadata.get(canonical_name)
        if platform_spec is None:
            return None
        return platform_spec["support_status"]

    @classmethod
    def get_platforms_by_support_status(cls, status: SupportStatus) -> list[str]:
        """Get platforms filtered by product support status."""
        if status not in SUPPORT_STATUS_VALUES:
            raise ValueError(f"Unknown support_status {status!r}. Expected one of: {', '.join(SUPPORT_STATUS_VALUES)}")

        metadata = cls.get_all_platform_metadata()
        return sorted(name for name, spec in metadata.items() if spec["support_status"] == status)

    @classmethod
    def get_platform_count_summary(cls) -> dict[str, Any]:
        """Return registry-derived platform counts for docs drift checks."""
        metadata = cls.get_all_platform_metadata()
        status_counts = Counter(spec["support_status"] for spec in metadata.values())
        category_counts = Counter(spec.get("category", "unknown") for spec in metadata.values())
        sql_capable = sum(1 for spec in metadata.values() if spec.get("capabilities", {}).get("supports_sql", False))
        dataframe_capable = sum(
            1 for spec in metadata.values() if spec.get("capabilities", {}).get("supports_dataframe", False)
        )
        dual_mode = sum(
            1
            for spec in metadata.values()
            if spec.get("capabilities", {}).get("supports_sql", False)
            and spec.get("capabilities", {}).get("supports_dataframe", False)
        )
        dataframe_only = sum(
            1
            for spec in metadata.values()
            if not spec.get("capabilities", {}).get("supports_sql", False)
            and spec.get("capabilities", {}).get("supports_dataframe", False)
        )

        return {
            "total": len(metadata),
            "sql_capable": sql_capable,
            "dataframe_capable": dataframe_capable,
            "dual_mode": dual_mode,
            "dataframe_only": dataframe_only,
            "support_status": {status: status_counts.get(status, 0) for status in SUPPORT_STATUS_VALUES},
            "category": dict(sorted(category_counts.items())),
        }

    @classmethod
    def classify_optional_import_error(
        cls,
        exc: BaseException,
        *,
        module_path: str | None = None,
    ) -> OptionalAdapterImportStatus:
        """Classify an optional adapter import failure without raising it."""
        message = str(exc).lower()
        if isinstance(exc, ModuleNotFoundError):
            missing_name = exc.name or ""
            if _is_internal_module_miss(missing_name, module_path):
                return "broken_adapter_import"
            return "missing_optional_dependency"
        if "no module named" in message:
            return "missing_optional_dependency"
        if isinstance(exc, OSError) or any(marker in message for marker in _NATIVE_IMPORT_ERROR_MARKERS):
            return "native_library_load_failure"
        return "broken_adapter_import"

    @classmethod
    def diagnose_optional_adapter_imports(
        cls,
        platform_names: Optional[Iterable[str]] = None,
    ) -> dict[str, dict[str, Any]]:
        """Diagnose optional adapter import health on demand.

        Normal registry discovery remains fail-open for missing optional
        dependencies. This explicit diagnostic path imports selected adapters
        and reports whether a failure is dependency, native-library, broken
        adapter, deprecated, or intentionally disabled status.
        """
        requested = None
        if platform_names is not None:
            requested = {cls.resolve_platform_name(platform_name) for platform_name in platform_names}

        diagnostics: dict[str, dict[str, Any]] = {}
        for name, module_path, class_name in _OPTIONAL_ADAPTERS:
            if requested is not None and name not in requested:
                continue
            diagnostics[name] = _diagnose_optional_adapter_entry(name, module_path, class_name).to_dict()

        if requested is not None:
            missing = requested - set(diagnostics)
            for name in sorted(missing):
                diagnostics[name] = OptionalAdapterDiagnostic(
                    platform_name=name,
                    module_path="",
                    class_name="",
                    status="not_configured",
                    support_status=cls.get_platform_support_status(name),
                    error_message="Platform is not configured for optional adapter registration.",
                ).to_dict()

        return diagnostics

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
            cost_class=caps.get("cost_class", "free"),
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
    def get_sql_platforms(cls, *, include_deprecated: bool = False) -> list[str]:
        """Return registry platforms that support SQL execution."""
        return cls._get_platforms_matching_capability("supports_sql", include_deprecated=include_deprecated)

    @classmethod
    def get_dataframe_platforms(cls, *, include_deprecated: bool = False) -> list[str]:
        """Return registry platforms that support DataFrame execution."""
        return cls._get_platforms_matching_capability("supports_dataframe", include_deprecated=include_deprecated)

    @classmethod
    def get_self_hosted_platforms(cls, *, include_deprecated: bool = False) -> list[str]:
        """Return platforms with at least one self-hosted deployment mode."""
        metadata = cls.get_all_platform_metadata()
        out: list[str] = []
        for name, spec in metadata.items():
            if not include_deprecated and spec.get("support_status") in {"deprecated", "document_only"}:
                continue
            deployment_modes = spec.get("capabilities", {}).get("deployment_modes", {})
            if any(mode.get("mode") == "self-hosted" for mode in deployment_modes.values()):
                out.append(name)
        return out

    @classmethod
    def _get_platforms_matching_capability(
        cls,
        capability: str,
        *,
        include_deprecated: bool = False,
    ) -> list[str]:
        metadata = cls.get_all_platform_metadata()
        out: list[str] = []
        for name, spec in metadata.items():
            if not include_deprecated and spec.get("support_status") in {"deprecated", "document_only"}:
                continue
            if spec.get("capabilities", {}).get(capability, False):
                out.append(name)
        return out

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
        - 'duckdb' family: duckdb, motherduck, ducklake
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
        - motherduck, ducklake inherit from duckdb
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
    ("ducklake", "benchbox.platforms.ducklake", "DuckLakeAdapter"),
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

_OPTIONAL_ADAPTER_REGISTRATION_DIAGNOSTICS: dict[str, dict[str, Any]] = {}


def _diagnose_optional_adapter_entry(
    name: str,
    module_path: str,
    class_name: str,
) -> OptionalAdapterDiagnostic:
    """Import one optional adapter and return a structured diagnostic."""
    support_status = PlatformRegistry.get_platform_support_status(name)
    if support_status == "deprecated":
        return OptionalAdapterDiagnostic(
            platform_name=name,
            module_path=module_path,
            class_name=class_name,
            status="deprecated_platform",
            support_status=support_status,
            error_message="Platform selector is deprecated; use the documented replacement.",
        )
    if support_status in {"repo_only", "document_only"}:
        return OptionalAdapterDiagnostic(
            platform_name=name,
            module_path=module_path,
            class_name=class_name,
            status="intentionally_disabled",
            support_status=support_status,
            error_message=f"Platform support_status is {support_status}; it is not a default runtime adapter.",
        )

    try:
        module = importlib.import_module(module_path)
        adapter_cls = getattr(module, class_name)
    except AttributeError as exc:
        return OptionalAdapterDiagnostic(
            platform_name=name,
            module_path=module_path,
            class_name=class_name,
            status="broken_adapter_import",
            support_status=support_status,
            error_type=type(exc).__name__,
            error_message=f"{module_path} does not expose {class_name}",
        )
    except (ImportError, OSError) as exc:
        return OptionalAdapterDiagnostic(
            platform_name=name,
            module_path=module_path,
            class_name=class_name,
            status=PlatformRegistry.classify_optional_import_error(exc, module_path=module_path),
            support_status=support_status,
            error_type=type(exc).__name__,
            error_message=str(exc),
        )

    return OptionalAdapterDiagnostic(
        platform_name=name,
        module_path=module_path,
        class_name=class_name,
        status="available",
        support_status=support_status,
        available=adapter_cls is not None,
    )


def _try_register_adapter(name: str, module_path: str, class_name: str) -> None:
    """Import ``class_name`` from ``module_path`` and register as ``name``.

    Missing optional dependencies are silently skipped - adapters whose driver
    packages aren't installed simply don't appear in the registry.
    """
    support_status = PlatformRegistry.get_platform_support_status(name)
    try:
        module = importlib.import_module(module_path)
        adapter_cls = getattr(module, class_name)
        PlatformRegistry.register_adapter(name, adapter_cls)
        _OPTIONAL_ADAPTER_REGISTRATION_DIAGNOSTICS[name] = OptionalAdapterDiagnostic(
            platform_name=name,
            module_path=module_path,
            class_name=class_name,
            status="available",
            support_status=support_status,
            available=True,
        ).to_dict()
    except AttributeError as exc:
        _OPTIONAL_ADAPTER_REGISTRATION_DIAGNOSTICS[name] = OptionalAdapterDiagnostic(
            platform_name=name,
            module_path=module_path,
            class_name=class_name,
            status="broken_adapter_import",
            support_status=support_status,
            error_type=type(exc).__name__,
            error_message=f"{module_path} does not expose {class_name}",
        ).to_dict()
    except (ImportError, OSError) as exc:
        _OPTIONAL_ADAPTER_REGISTRATION_DIAGNOSTICS[name] = OptionalAdapterDiagnostic(
            platform_name=name,
            module_path=module_path,
            class_name=class_name,
            status=PlatformRegistry.classify_optional_import_error(exc, module_path=module_path),
            support_status=support_status,
            error_type=type(exc).__name__,
            error_message=str(exc),
        ).to_dict()


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
