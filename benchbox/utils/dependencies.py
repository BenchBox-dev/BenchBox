"""Dependency management utilities for BenchBox platform adapters.

Provides centralized dependency checking, error messages, and installation guidance
for optional platform dependencies.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import sys
from collections.abc import Sequence
from functools import lru_cache
from pathlib import Path
from typing import Optional


@lru_cache(maxsize=1)
def is_development_install() -> bool:
    """Detect if BenchBox is running from a development install.

    Returns True if running from source (editable install), False if installed as a package.
    """
    import benchbox

    # Get the package location
    package_path = Path(benchbox.__file__).parent

    # Check if pyproject.toml exists in parent (development install)
    project_root = package_path.parent
    if (project_root / "pyproject.toml").exists():
        # Verify it's actually the benchbox project
        try:
            content = (project_root / "pyproject.toml").read_text()
            if 'name = "benchbox"' in content:
                return True
        except Exception:
            pass

    # Check if we're in site-packages (package install)
    # Default to dev install if uncertain
    return "site-packages" not in str(package_path)


@lru_cache(maxsize=1)
def is_uv_tool_environment() -> bool:
    """Detect whether BenchBox is running inside a uv tool virtual environment."""
    normalized_executable = str(Path(sys.executable)).replace("\\", "/").lower()
    return "/uv/tools/" in normalized_executable


# Map platform names to their pyproject.toml extra names
PLATFORM_TO_EXTRA: dict[str, str] = {
    # DataFrame platforms - plain-name extras (dataframe-* aliases also exist)
    "polars": "polars",
    "polars-df": "polars",
    "modin": "modin",
    "modin-df": "modin",
    "dask": "dask",
    "dask-df": "dask",
    "pandas": "pandas",
    "pandas-df": "pandas",
    "cudf": "cudf",
    "cudf-df": "cudf",
    "pyspark": "pyspark",
    "pyspark-df": "pyspark",
    "spark": "spark",
    "lakesail": "lakesail",
    "velox": "velox",
    "gluten-velox": "velox",
    "datafusion": "datafusion",
    "datafusion-df": "datafusion",
    # Cloud/SQL platforms
    "athena": "athena",
    "bigquery": "bigquery",
    "snowflake": "snowflake",
    "databricks": "databricks",
    "databricks-connect": "databricks-connect",
    "redshift": "redshift",
    "synapse": "synapse",
    "fabric": "fabric",
    "fabric-lakehouse": "fabric",
    "fabric_lakehouse": "fabric",
    "fabric-spark": "fabric-spark",
    "trino": "trino",
    "presto": "presto",
    "clickhouse": "clickhouse",
    "clickhouse-local": "clickhouse-local",
    "clickhouse-server": "clickhouse-server",
    "clickhouse-cloud": "clickhouse-cloud",
    "firebolt": "firebolt",
    "databend": "databend",
    "influxdb": "influxdb",
    "doris": "doris",
    "singlestore": "singlestore",
    "postgresql": "postgresql",
    "postgres": "postgresql",
    "questdb": "questdb",
}


def get_install_command(extra: str) -> str:
    """Get the appropriate install command for an extra based on install type.

    Args:
        extra: The extra name or platform name (e.g., 'athena', 'modin', 'cloud')

    Returns:
        The appropriate install command string
    """
    # Map platform names to their actual extra names
    resolved_extra = PLATFORM_TO_EXTRA.get(extra.lower(), extra)

    if is_development_install():
        if is_uv_tool_environment():
            # uv tool environments are isolated from project .venv state.
            # Target the running interpreter explicitly so users install
            # into the same environment that executes `benchbox`.
            return f'uv pip install --python "{sys.executable}" "benchbox[{resolved_extra}]"'
        return f"uv sync --extra {resolved_extra}"
    else:
        return f'uv pip install "benchbox[{resolved_extra}]"'


def get_package_install_message(packages: str, description: str = "") -> str:
    """Generate a user-friendly install message for raw Python packages.

    Provides both standalone (pip) and project (uv add) installation options.

    Args:
        packages: Space-separated package names (e.g., 'boto3' or 'azure-storage-blob azure-identity')
        description: Optional description of what the packages are for

    Returns:
        Multi-line install message with both options
    """
    prefix = f"{description} " if description else ""
    return (
        f"{prefix}Install with:\n  pip install {packages}  # standalone\n  uv add {packages}       # inside a project"
    )


def get_extra_install_message(extra_name: str, description: str = "") -> str:
    """Generate a user-friendly install message for BenchBox extras.

    Provides both standalone (pip install) and project (uv add) installation options.

    Args:
        extra_name: The BenchBox extra name (e.g., 'cloud', 'mcp', 'databricks')
        description: Optional description prefix

    Returns:
        Multi-line install message with both options
    """
    prefix = f"{description}\n" if description else ""
    return (
        f"{prefix}Install with:\n"
        f"  pip install 'benchbox[{extra_name}]'  # pip/venv\n"
        f"  uv add benchbox --extra {extra_name}  # uv project"
    )


class DependencyInfo:
    """Information about a platform dependency group."""

    def __init__(
        self,
        name: str,
        description: str,
        packages: list[str],
        install_command: str,
        use_cases: list[str],
        platforms: list[str],
    ):
        self.name = name
        self.description = description
        self.packages = packages
        self.install_command = install_command
        self.use_cases = use_cases
        self.platforms = platforms

    def get_install_message(self) -> str:
        """Get a context-aware install message with both standalone and project options.

        Returns:
            Multi-line install message showing both installation options.
        """
        return get_extra_install_message(self.name)


# Structured installation guidance for documentation and CLI matrix output
class InstallationScenario:
    """Represents a documented installation path for BenchBox."""

    def __init__(
        self,
        name: str,
        description: str,
        platforms: Sequence[str],
        dependency_groups: Sequence[str],
        notes: Optional[str] = None,
    ):
        self.name = name
        self.description = description
        self.platforms = list(platforms)
        self.dependency_groups = list(dependency_groups)
        self.notes = notes or ""

    def _extras_spec(self) -> str:
        if not self.dependency_groups:
            return ""
        return ",".join(self.dependency_groups)

    @property
    def extras_label(self) -> str:
        return self._extras_spec() or "core"

    @property
    def uv_command(self) -> str:
        """Modern uv add command (recommended)."""
        extras = self._extras_spec()
        if extras:
            extra_flags = " ".join(f"--extra {e}" for e in extras.split(","))
            return f"uv add benchbox {extra_flags}"
        return "uv add benchbox"

    @property
    def uv_pip_command(self) -> str:
        """Alternative pip-compatible uv command."""
        extras = self._extras_spec()
        if extras:
            return f'uv pip install "benchbox[{extras}]"'
        return "uv pip install benchbox"

    @property
    def pip_command(self) -> str:
        extras = self._extras_spec()
        if extras:
            return f'python -m pip install "benchbox[{extras}]"'
        return "python -m pip install benchbox"

    @property
    def pipx_command(self) -> str:
        extras = self._extras_spec()
        if extras:
            return f'pipx install "benchbox[{extras}]"'
        return "pipx install benchbox"


# Platform dependency information
# DataFrame platform dependency information
DATAFRAME_DEPENDENCY_GROUPS: dict[str, DependencyInfo] = {
    "pandas": DependencyInfo(
        name="pandas",
        description="Pandas DataFrame library for data analysis",
        packages=["pandas"],
        install_command="uv add benchbox --extra pandas",
        use_cases=["Data analysis", "Data manipulation", "DataFrame benchmarking"],
        platforms=["Pandas"],
    ),
    "modin": DependencyInfo(
        name="modin",
        description="Modin distributed Pandas replacement",
        packages=["modin", "pandas"],
        install_command="uv add benchbox --extra modin",
        use_cases=["Distributed Pandas", "Large datasets", "Multi-core processing"],
        platforms=["Modin (Ray backend)"],
    ),
    "dask": DependencyInfo(
        name="dask",
        description="Dask parallel computing library",
        packages=["dask", "pandas"],
        install_command="uv add benchbox --extra dask",
        use_cases=["Parallel computing", "Out-of-core processing", "Large datasets"],
        platforms=["Dask"],
    ),
    "pyspark": DependencyInfo(
        name="pyspark",
        description="Apache Spark Python interface",
        packages=["pyspark"],
        install_command="uv add benchbox --extra pyspark",
        use_cases=["Distributed computing", "Big data processing", "Spark SQL"],
        platforms=["Apache Spark (PySpark)"],
    ),
    "polars": DependencyInfo(
        name="polars",
        description="Polars high-performance DataFrame library",
        packages=["polars"],
        install_command="uv add benchbox --extra polars",
        use_cases=["High-performance analytics", "Lazy evaluation", "Rust-powered DataFrame"],
        platforms=["Polars"],
    ),
    "datafusion": DependencyInfo(
        name="datafusion",
        description="Apache DataFusion query engine",
        packages=["datafusion"],
        install_command="uv add benchbox --extra datafusion",
        use_cases=["SQL on DataFrames", "Arrow-native processing", "Query optimization"],
        platforms=["Apache DataFusion"],
    ),
    "dataframe-pandas-family": DependencyInfo(
        name="dataframe-pandas-family",
        description="All Pandas-family DataFrame platforms",
        packages=["pandas", "modin", "dask"],
        install_command="uv add benchbox --extra dataframe-pandas-family",
        use_cases=["Pandas ecosystem benchmarking", "Pandas API comparison"],
        platforms=["Pandas", "Modin", "Dask"],
    ),
    "dataframe-expression-family": DependencyInfo(
        name="dataframe-expression-family",
        description="All expression-based DataFrame platforms",
        packages=["polars", "pyspark", "datafusion"],
        install_command="uv add benchbox --extra dataframe-expression-family",
        use_cases=["Expression API benchmarking", "Lazy evaluation comparison"],
        platforms=["Polars", "PySpark", "DataFusion"],
    ),
    "dataframe-all": DependencyInfo(
        name="dataframe-all",
        description="All DataFrame platforms",
        packages=["pandas", "modin", "dask", "polars", "pyspark", "datafusion"],
        install_command="uv add benchbox --extra dataframe-all",
        use_cases=["Complete DataFrame benchmarking", "Platform comparison"],
        platforms=["Pandas", "Modin", "Dask", "Polars", "PySpark", "DataFusion"],
    ),
}

# SQL platform dependency information
DEPENDENCY_GROUPS: dict[str, DependencyInfo] = {
    "clickhouse": DependencyInfo(
        name="clickhouse",
        description="ClickHouse server driver (clickhouse-driver TCP protocol)",
        packages=["clickhouse-driver"],
        install_command="uv add benchbox --extra clickhouse",
        use_cases=["Columnar analytics", "High-performance aggregation", "Self-hosted ClickHouse"],
        platforms=["ClickHouse Server (clickhouse-server)"],
    ),
    "clickhouse-local": DependencyInfo(
        name="clickhouse-local",
        description="Embedded ClickHouse via chDB (in-process, no server required)",
        packages=["chdb"],
        install_command="uv add benchbox --extra clickhouse-local",
        use_cases=["Embedded ClickHouse", "Local analytics", "Zero-infrastructure benchmarking"],
        platforms=["ClickHouse Local (clickhouse-local)"],
    ),
    "clickhouse-server": DependencyInfo(
        name="clickhouse-server",
        description="Self-hosted ClickHouse server driver (clickhouse-driver TCP protocol)",
        packages=["clickhouse-driver"],
        install_command="uv add benchbox --extra clickhouse-server",
        use_cases=["Self-hosted ClickHouse", "Docker ClickHouse", "High-performance columnar analytics"],
        platforms=["ClickHouse Server (clickhouse-server)"],
    ),
    "clickhouse-cloud": DependencyInfo(
        name="clickhouse-cloud",
        description="ClickHouse Cloud via HTTP connector (clickhouse-connect)",
        packages=["clickhouse-connect"],
        install_command="uv add benchbox --extra clickhouse-cloud",
        use_cases=["Managed ClickHouse", "Serverless analytics", "Cloud OLAP"],
        platforms=["ClickHouse Cloud (clickhouse-cloud)"],
    ),
    "databricks": DependencyInfo(
        name="databricks",
        description="Databricks SQL Warehouse connector with Unity Catalog",
        packages=["databricks-sql-connector", "cloudpathlib"],
        install_command="uv add benchbox --extra databricks",
        use_cases=["Lakehouse analytics", "Delta Lake workloads", "Spark SQL"],
        platforms=["Databricks SQL Warehouses", "Databricks Clusters"],
    ),
    "databricks-df": DependencyInfo(
        name="databricks-df",
        description="Databricks DataFrame mode with Databricks Connect",
        packages=["databricks-sql-connector", "databricks-connect", "cloudpathlib"],
        install_command="uv add benchbox --extra databricks-connect",
        use_cases=["PySpark DataFrame API", "Interactive development", "DataFrame benchmarks"],
        platforms=["Databricks Clusters (via Databricks Connect)"],
    ),
    "databricks-connect": DependencyInfo(
        name="databricks-connect",
        description="Databricks Connect for remote PySpark DataFrame execution",
        packages=["databricks-sql-connector", "databricks-connect", "cloudpathlib"],
        install_command="uv add benchbox --extra databricks-connect",
        use_cases=["Remote Spark execution", "Local IDE development", "DataFrame API"],
        platforms=["Databricks Clusters"],
    ),
    "cloud-spark": DependencyInfo(
        name="cloud-spark",
        description="All managed cloud Spark platforms with DataFrame support",
        packages=["databricks-sql-connector", "databricks-connect", "cloudpathlib"],
        install_command="uv add benchbox --extra cloud-spark",
        use_cases=["Managed Spark platforms", "DataFrame benchmarks", "Cloud analytics"],
        platforms=["Databricks", "EMR (future)", "Dataproc (future)", "Synapse Spark (future)"],
    ),
    "bigquery": DependencyInfo(
        name="bigquery",
        description="Google BigQuery and Cloud Storage integration",
        packages=["google-cloud-bigquery", "google-cloud-storage", "cloudpathlib"],
        install_command="uv add benchbox --extra bigquery",
        use_cases=["Serverless analytics", "BigQuery datasets", "Google Cloud workflows"],
        platforms=["Google BigQuery", "Google Cloud Storage"],
    ),
    "redshift": DependencyInfo(
        name="redshift",
        description="Amazon Redshift data warehouse connector",
        packages=["redshift-connector", "boto3", "cloudpathlib"],
        install_command="uv add benchbox --extra redshift",
        use_cases=["Data warehouse analytics", "AWS analytics", "Redshift Spectrum"],
        platforms=["Amazon Redshift", "Redshift Serverless"],
    ),
    "snowflake": DependencyInfo(
        name="snowflake",
        description="Snowflake cloud data platform connector",
        packages=["snowflake-connector-python", "cloudpathlib"],
        install_command="uv add benchbox --extra snowflake",
        use_cases=["Cloud data warehouse", "Multi-cloud analytics", "Zero-maintenance DW"],
        platforms=["Snowflake"],
    ),
    "trino": DependencyInfo(
        name="trino",
        description="Trino distributed SQL query engine connector (Trino only, not PrestoDB)",
        packages=["trino", "cloudpathlib"],
        install_command="uv add benchbox --extra trino",
        use_cases=["Federated queries", "Data lake analytics", "Distributed SQL"],
        platforms=["Trino", "Starburst Enterprise"],
    ),
    "presto": DependencyInfo(
        name="presto",
        description="PrestoDB distributed SQL query engine connector (Meta's Presto, not Trino)",
        packages=["presto-python-client", "cloudpathlib"],
        install_command="uv add benchbox --extra presto",
        use_cases=["Federated queries", "Legacy PrestoDB clusters", "Distributed SQL"],
        platforms=["PrestoDB"],
    ),
    "firebolt": DependencyInfo(
        name="firebolt",
        description="Firebolt vectorized analytics database (Core + Cloud)",
        packages=["firebolt-sdk", "cloudpathlib"],
        install_command="uv add benchbox --extra firebolt",
        use_cases=["Vectorized analytics", "Cloud data warehouse", "Local development", "S3 staging"],
        platforms=["Firebolt Core (local)", "Firebolt Cloud"],
    ),
    "databend": DependencyInfo(
        name="databend",
        description="Databend cloud-native OLAP data warehouse",
        packages=["databend-driver"],
        install_command="uv add benchbox --extra databend",
        use_cases=["Cloud-native OLAP", "Snowflake-compatible analytics", "Object storage backend"],
        platforms=["Databend Cloud", "Databend Self-Hosted"],
    ),
    "influxdb": DependencyInfo(
        name="influxdb",
        description="InfluxDB time series database with FlightSQL support",
        packages=["influxdb3-python", "pyarrow"],
        install_command="uv add benchbox --extra influxdb",
        use_cases=["Time series analytics", "TSBS DevOps benchmarks", "FlightSQL queries"],
        platforms=["InfluxDB Core (OSS)", "InfluxDB Cloud"],
    ),
    "starrocks": DependencyInfo(
        name="starrocks",
        description="StarRocks columnar analytics engine via MySQL protocol",
        packages=["pymysql"],
        install_command="uv add benchbox --extra starrocks",
        use_cases=["Columnar analytics", "Fast OLAP queries", "Distributed MPP"],
        platforms=["StarRocks"],
    ),
    "singlestore": DependencyInfo(
        name="singlestore",
        description="SingleStore distributed SQL database (Helios + self-managed)",
        packages=["singlestoredb"],
        install_command="uv add benchbox --extra singlestore",
        use_cases=["Real-time analytics", "HTAP workloads", "Distributed OLAP", "MySQL-compatible analytics"],
        platforms=["SingleStore Helios", "SingleStore Self-Managed"],
    ),
    "postgresql": DependencyInfo(
        name="postgresql",
        description="PostgreSQL open-source relational database connector",
        packages=["psycopg"],
        install_command="uv add benchbox --extra postgresql",
        use_cases=["Row-store baseline", "OLTP benchmarks", "TimescaleDB time-series"],
        platforms=["PostgreSQL", "TimescaleDB"],
    ),
    "questdb": DependencyInfo(
        name="questdb",
        description="QuestDB time-series database connector (via PostgreSQL wire protocol)",
        packages=["psycopg", "requests"],
        install_command="uv add benchbox --extra questdb",
        use_cases=["Time-series analytics", "High-throughput ingestion", "Columnar OLAP"],
        platforms=["QuestDB"],
    ),
    "synapse": DependencyInfo(
        name="synapse",
        description="Azure Synapse Analytics (Dedicated SQL Pool) connector",
        packages=["pyodbc"],
        install_command="uv add benchbox --extra synapse",
        use_cases=["Cloud data warehouse", "Azure analytics", "Enterprise OLAP"],
        platforms=["Azure Synapse Dedicated SQL Pool"],
    ),
    "fabric": DependencyInfo(
        name="fabric",
        description="Microsoft Fabric Data Warehouse connector with OneLake integration",
        packages=["pyodbc", "azure-identity"],
        install_command="uv add benchbox --extra fabric",
        use_cases=["Cloud data warehouse", "Microsoft analytics", "OneLake storage", "Delta Lake"],
        platforms=["Microsoft Fabric Warehouse"],
    ),
    "fabric-spark": DependencyInfo(
        name="fabric-spark",
        description="Microsoft Fabric Spark with Livy API and OneLake storage",
        packages=["azure-identity", "azure-storage-file-datalake", "requests"],
        install_command="uv add benchbox --extra fabric-spark",
        use_cases=["SaaS Spark", "Microsoft analytics", "OneLake storage", "Livy API"],
        platforms=["Microsoft Fabric Spark"],
    ),
    "synapse-spark": DependencyInfo(
        name="synapse-spark",
        description="Azure Synapse Spark with Livy API and ADLS Gen2 storage",
        packages=["azure-identity", "azure-storage-file-datalake", "requests"],
        install_command="uv add benchbox --extra synapse-spark",
        use_cases=["Enterprise Spark", "Azure analytics", "ADLS Gen2 storage", "Livy API"],
        platforms=["Azure Synapse Spark"],
    ),
    "athena": DependencyInfo(
        name="athena",
        description="AWS Athena serverless query-on-S3 connector",
        packages=["pyathena", "boto3"],
        install_command="uv add benchbox --extra athena",
        use_cases=["Serverless analytics", "S3 data lake queries", "AWS analytics"],
        platforms=["AWS Athena"],
    ),
    "glue": DependencyInfo(
        name="glue",
        description="AWS Glue managed Spark ETL service",
        packages=["boto3"],
        install_command="uv add benchbox --extra glue",
        use_cases=["Serverless ETL", "Managed Spark", "AWS analytics", "Data pipeline"],
        platforms=["AWS Glue"],
    ),
    "emr-serverless": DependencyInfo(
        name="emr-serverless",
        description="Amazon EMR Serverless managed Spark service",
        packages=["boto3"],
        install_command="uv add benchbox --extra emr-serverless",
        use_cases=["Serverless Spark", "AWS analytics", "Auto-scaling", "Sub-second startup"],
        platforms=["Amazon EMR Serverless"],
    ),
    "athena-spark": DependencyInfo(
        name="athena-spark",
        description="Amazon Athena for Apache Spark interactive sessions",
        packages=["boto3"],
        install_command="uv add benchbox --extra athena-spark",
        use_cases=["Interactive Spark", "AWS analytics", "Session-based", "Sub-second startup"],
        platforms=["Amazon Athena for Apache Spark"],
    ),
    "dataproc": DependencyInfo(
        name="dataproc",
        description="GCP Dataproc managed Spark service",
        packages=["google-cloud-dataproc", "google-cloud-storage"],
        install_command="uv add benchbox --extra dataproc",
        use_cases=["Managed Spark", "GCP analytics", "Data pipeline", "Cluster computing"],
        platforms=["GCP Dataproc"],
    ),
    "dataproc-serverless": DependencyInfo(
        name="dataproc-serverless",
        description="GCP Dataproc Serverless fully managed Spark",
        packages=["google-cloud-dataproc", "google-cloud-storage"],
        install_command="uv add benchbox --extra dataproc-serverless",
        use_cases=["Serverless Spark", "GCP analytics", "Auto-scaling", "No cluster management"],
        platforms=["GCP Dataproc Serverless"],
    ),
    "spark": DependencyInfo(
        name="spark",
        description="Apache Spark distributed SQL engine",
        packages=["pyspark"],
        install_command="uv add benchbox --extra spark",
        use_cases=["Distributed SQL", "Big data processing", "Spark SQL"],
        platforms=["Apache Spark", "Spark on YARN", "Spark on Kubernetes"],
    ),
    "lakesail": DependencyInfo(
        name="lakesail",
        description="LakeSail Sail Spark-compatible engine (uses PySpark Spark Connect client)",
        packages=["pyspark", "grpcio", "grpcio-status"],
        install_command="uv add benchbox --extra lakesail",
        use_cases=["Spark-compatible SQL", "High-performance analytics", "DataFusion-based"],
        platforms=["LakeSail Sail"],
    ),
    "velox": DependencyInfo(
        name="velox",
        description="Apache Gluten + Velox Spark acceleration (native C++ engine via Gluten plugin)",
        packages=["pyspark", "grpcio", "grpcio-status"],
        install_command="uv add benchbox --extra velox",
        use_cases=[
            "Spark-compatible SQL",
            "Native C++ acceleration",
            "TPC-H/TPC-DS benchmarking",
            "Accelerated-Spark tier comparison",
        ],
        platforms=["Apache Gluten + Velox"],
    ),
    "snowpark-connect": DependencyInfo(
        name="snowpark-connect",
        description="Snowpark Connect PySpark-compatible API on Snowflake",
        packages=["snowflake-snowpark-python"],
        install_command="uv add benchbox --extra snowpark-connect",
        use_cases=["PySpark API", "Snowflake DataFrame", "No cluster required", "Snowflake native"],
        platforms=["Snowflake (via Snowpark)"],
    ),
    "cloudstorage": DependencyInfo(
        name="cloudstorage",
        description="Cloud storage helpers for remote paths (cloudpathlib)",
        packages=["cloudpathlib"],
        install_command="uv add benchbox --extra cloudstorage",
        use_cases=["Remote output directories", "Cloud staging areas", "Unity Catalog volumes"],
        platforms=["AWS S3", "Google Cloud Storage", "Azure Storage"],
    ),
    "cloud": DependencyInfo(
        name="cloud",
        description="All major cloud data platforms (excludes ClickHouse)",
        packages=[
            "databricks-sql-connector",
            "firebolt-sdk",
            "google-cloud-bigquery",
            "google-cloud-dataproc",
            "google-cloud-storage",
            "redshift-connector",
            "snowflake-connector-python",
            "trino",
            "pyathena",
            "boto3",
            "cloudpathlib",
        ],
        install_command="uv add benchbox --extra cloud",
        use_cases=["Multi-cloud benchmarking", "Cloud platform comparison", "Enterprise analytics"],
        platforms=[
            "Databricks",
            "BigQuery",
            "Redshift",
            "Snowflake",
            "Trino",
            "Athena",
            "Firebolt",
            "Dataproc",
            "Glue",
            "EMR Serverless",
        ],
    ),
    "all": DependencyInfo(
        name="all",
        description="All supported database platforms and features",
        packages=[
            "clickhouse-driver",
            "databricks-sql-connector",
            "databricks-connect",  # Databricks DataFrame mode
            "firebolt-sdk",
            "google-cloud-bigquery",
            "google-cloud-storage",
            "google-cloud-dataproc",  # GCP Dataproc platforms
            "redshift-connector",
            "snowflake-connector-python",
            "snowflake-snowpark-python",  # Snowpark Connect
            "trino",
            "presto-python-client",
            "psycopg",
            "pyodbc",
            "pyathena",
            "pyspark",
            "grpcio",
            "grpcio-status",
            "boto3",
            "cloudpathlib",
            # Fabric Warehouse (Azure)
            "azure-identity",
            "azure-storage-file-datalake",
            "requests",  # For Fabric/Synapse Spark Livy API
            # InfluxDB 3.0
            "influxdb3-python",
            "pyarrow",  # For InfluxDB and DataFusion
            # ClickHouse Local (chDB embedded) & Cloud (clickhouse-connect)
            "chdb",
            "clickhouse-connect",
            # Databend
            "databend-driver",
            # MySQL-protocol platforms (StarRocks, Doris)
            "pymysql",
            # SingleStore
            "singlestoredb",
        ],
        install_command="uv add benchbox --extra all",
        use_cases=["Complete platform coverage", "Testing all adapters", "Maximum flexibility"],
        platforms=["All supported platforms"],
    ),
}


# Curated installation scenarios for documentation and CLI matrix
INSTALLATION_SCENARIOS: tuple[InstallationScenario, ...] = (
    InstallationScenario(
        name="Local development (core)",
        description="DuckDB + SQLite workflows without external services",
        platforms=["DuckDB", "SQLite"],
        dependency_groups=[],
        notes="Includes embedded DuckDB engine and local file outputs.",
    ),
    InstallationScenario(
        name="Cloud storage helpers",
        description="Enable cloud path handling without database adapters",
        platforms=["S3", "GCS", "Azure"],
        dependency_groups=["cloudstorage"],
        notes="Install when you need remote output directories or UC volume staging.",
    ),
    InstallationScenario(
        name="Cloud platforms bundle",
        description="All managed warehouses except ClickHouse",
        platforms=["Databricks", "BigQuery", "Redshift", "Snowflake", "Trino", "Athena", "Firebolt"],
        dependency_groups=["cloud"],
        notes="Recommended starting point for cloud benchmarking.",
    ),
    InstallationScenario(
        name="Full platform coverage",
        description="Everything BenchBox supports",
        platforms=["All platforms"],
        dependency_groups=["all"],
        notes="Installs every optional adapter including ClickHouse.",
    ),
    InstallationScenario(
        name="Distributed SQL (Presto vs Trino)",
        description="Compare PrestoDB and Trino/Starburst with native drivers",
        platforms=["PrestoDB", "Trino"],
        dependency_groups=["presto", "trino"],
        notes="PrestoDB uses presto-python-client with X-Presto-* headers; Trino uses the trino package and X-Trino-* headers.",
    ),
    InstallationScenario(
        name="Databricks Lakehouse",
        description="Databricks SQL Warehouses and Unity Catalog",
        platforms=["Databricks"],
        dependency_groups=["databricks"],
    ),
    InstallationScenario(
        name="Google BigQuery",
        description="BigQuery analytics and Cloud Storage integration",
        platforms=["BigQuery", "Cloud Storage"],
        dependency_groups=["bigquery"],
    ),
    InstallationScenario(
        name="Amazon Redshift",
        description="Redshift data warehouse and S3 access",
        platforms=["Redshift", "Amazon S3"],
        dependency_groups=["redshift"],
    ),
    InstallationScenario(
        name="AWS Athena",
        description="Serverless query-on-S3 analytics",
        platforms=["AWS Athena", "Amazon S3"],
        dependency_groups=["athena"],
        notes="Pay-per-query pricing based on data scanned ($5/TB). No infrastructure to manage.",
    ),
    InstallationScenario(
        name="AWS Glue",
        description="Managed Spark ETL service",
        platforms=["AWS Glue", "Amazon S3"],
        dependency_groups=["glue"],
        notes="Pay-per-DPU pricing (~$0.44/DPU-hour). Serverless Spark with Glue Data Catalog.",
    ),
    InstallationScenario(
        name="Snowflake Cloud",
        description="Snowflake cloud data platform",
        platforms=["Snowflake"],
        dependency_groups=["snowflake"],
    ),
    InstallationScenario(
        name="ClickHouse Analytics",
        description="ClickHouse clusters or local server",
        platforms=["ClickHouse"],
        dependency_groups=["clickhouse"],
    ),
    InstallationScenario(
        name="Firebolt Analytics",
        description="Firebolt Core (local Docker) or Firebolt Cloud",
        platforms=["Firebolt Core", "Firebolt Cloud"],
        dependency_groups=["firebolt"],
        notes="Firebolt Core is free and runs locally via Docker.",
    ),
    InstallationScenario(
        name="Cloud + ClickHouse combo",
        description="Multi-cloud benchmarks plus ClickHouse parity",
        platforms=["Databricks", "BigQuery", "Redshift", "Snowflake", "ClickHouse"],
        dependency_groups=["cloud", "clickhouse"],
        notes="Combines managed warehouses with self-hosted ClickHouse.",
    ),
)


# Mapping from package names (as used in pyproject.toml) to their actual import names
# This is needed because many packages have different names when installed vs imported
PACKAGE_IMPORT_NAMES: dict[str, str] = {
    "databricks-sql-connector": "databricks.sql",
    "google-cloud-bigquery": "google.cloud.bigquery",
    "google-cloud-storage": "google.cloud.storage",
    "snowflake-connector-python": "snowflake.connector",
    "snowflake-snowpark-python": "snowflake.snowpark",
    "presto-python-client": "prestodb",
    "grpcio": "grpc",
    "grpcio-status": "grpc_status",
    # These packages have import names that match the package name with hyphens replaced by underscores
    # (documented here for completeness, but handled by fallback logic):
    # "redshift-connector": "redshift_connector",
    # "clickhouse-driver": "clickhouse_driver",
    # "cloudpathlib": "cloudpathlib",
    # "boto3": "boto3",
}


def check_platform_dependencies(platform: str, packages: Optional[Sequence[str]] = None) -> tuple[bool, list[str]]:
    """Check if required packages are available for a platform.

    Args:
        platform: Platform name (e.g., 'databricks', 'clickhouse')
        packages: Optional explicit list of required package names

    Returns:
        Tuple of (all_available, missing_packages)
    """
    if packages is None:
        dep_info = DEPENDENCY_GROUPS.get(platform.lower())
        platforms_packages: Sequence[str] = dep_info.packages if dep_info else ()
    else:
        platforms_packages = packages

    missing: list[str] = []
    for package in platforms_packages:
        try:
            # Use mapping if available, otherwise fall back to simple hyphen-to-underscore replacement
            import_name = PACKAGE_IMPORT_NAMES.get(package, package.replace("-", "_"))
            __import__(import_name)
        except ImportError:
            missing.append(package)

    return len(missing) == 0, missing


def get_dependency_error_message(platform: str, missing_packages: list[str]) -> str:
    """Generate a helpful error message for missing platform dependencies.

    Args:
        platform: Platform name
        missing_packages: List of missing package names

    Returns:
        Formatted error message with installation instructions
    """
    platform_lower = platform.lower()
    dep_info = DEPENDENCY_GROUPS.get(platform_lower)

    if not dep_info:
        # Fallback for unknown platforms
        packages_str = ", ".join(missing_packages)
        return (
            f"Missing required dependencies for {platform}: {packages_str}\n"
            f"Install with: uv pip install {' '.join(missing_packages)}"
        )

    message_parts = [
        f"Missing dependencies for {platform} platform:",
        f"  Extra: benchbox[{dep_info.name}]",
        f"  Required packages: {', '.join(missing_packages)}",
        "",
        dep_info.get_install_message(),
        "",
        "This extra provides:",
        f"  • {dep_info.description}",
    ]

    if dep_info.use_cases:
        message_parts.extend(
            [
                f"  • Use cases: {', '.join(dep_info.use_cases)}",
            ]
        )

    if dep_info.platforms:
        message_parts.extend(
            [
                f"  • Supports: {', '.join(dep_info.platforms)}",
            ]
        )

    # Add alternative installation suggestions
    message_parts.extend(
        [
            "",
            "Bundle installations (recommended):",
            "  • For all cloud platforms: uv add benchbox --extra cloud",
            "  • For everything: uv add benchbox --extra all",
            "",
            "Alternative (pip-compatible):",
            '  • For all cloud platforms: uv pip install "benchbox[cloud]"',
            '  • For everything: uv pip install "benchbox[all]"',
            "",
            f"Need more guidance? Run: benchbox check-deps --platform {platform_lower}",
        ]
    )

    return "\n".join(message_parts)


def get_installation_recommendations(use_case: Optional[str] = None) -> list[str]:
    """Get installation recommendations based on use case.

    Args:
        use_case: Optional use case description

    Returns:
        List of recommended installation commands
    """
    recommendations = []

    if use_case:
        use_case_lower = use_case.lower()
        if "cloud" in use_case_lower or "multi" in use_case_lower:
            recommendations.append("uv add benchbox --extra cloud  # All major cloud platforms")
        elif "databricks" in use_case_lower or "delta" in use_case_lower:
            recommendations.append("uv add benchbox --extra databricks  # Databricks + Unity Catalog")
        elif "bigquery" in use_case_lower or "google" in use_case_lower:
            recommendations.append("uv add benchbox --extra bigquery  # Google BigQuery + Cloud Storage")
        elif "redshift" in use_case_lower or "aws" in use_case_lower:
            recommendations.append("uv add benchbox --extra redshift  # Amazon Redshift + S3")
        elif "snowflake" in use_case_lower:
            recommendations.append("uv add benchbox --extra snowflake  # Snowflake cloud DW")
        elif "clickhouse" in use_case_lower:
            recommendations.append("uv add benchbox --extra clickhouse  # ClickHouse analytics")
        elif "presto" in use_case_lower:
            recommendations.append("uv add benchbox --extra presto  # PrestoDB distributed SQL")
        elif "trino" in use_case_lower:
            recommendations.append("uv add benchbox --extra trino  # Trino/Starburst distributed SQL")

    # Always include general recommendations
    if not recommendations:
        recommendations.extend(
            [
                "uv add benchbox --extra cloud          # Major cloud platforms (recommended)",
                "uv add benchbox --extra all            # All platforms + features",
                "uv add benchbox --extra cloudstorage   # Cloud storage helpers only",
                "uv add benchbox --extra databricks     # Databricks only",
                "uv add benchbox --extra bigquery       # BigQuery only",
                "uv add benchbox --extra redshift       # Redshift only",
                "uv add benchbox --extra snowflake      # Snowflake only",
                "uv add benchbox --extra clickhouse     # ClickHouse only",
            ]
        )

    return recommendations


def list_available_dependency_groups() -> dict[str, DependencyInfo]:
    """Get all available dependency groups with their information."""
    return DEPENDENCY_GROUPS.copy()


def get_dependency_group_packages(platform: str) -> list[str]:
    """Return package names associated with a dependency group."""

    dep_info = DEPENDENCY_GROUPS.get(platform.lower())
    return list(dep_info.packages) if dep_info else []


def get_installation_scenarios() -> tuple[InstallationScenario, ...]:
    """Return curated installation scenarios."""
    return INSTALLATION_SCENARIOS


def get_installation_matrix_rows() -> list[tuple[str, str, str, str, str, str]]:
    """Build rows for installation matrix presentation.

    Returns:
        List of tuples: (scenario, platforms, extras, uv, pip, pipx)
    """

    rows: list[tuple[str, str, str, str, str, str]] = []
    for scenario in INSTALLATION_SCENARIOS:
        platforms = ", ".join(scenario.platforms)
        rows.append(
            (
                scenario.name,
                platforms,
                scenario.extras_label,
                scenario.uv_command,
                scenario.pip_command,
                scenario.pipx_command,
            )
        )
    return rows


def validate_dependency_group(group_name: str) -> bool:
    """Check if a dependency group name is valid."""
    return group_name.lower() in DEPENDENCY_GROUPS


def get_dependency_decision_tree() -> str:
    """Generate a decision tree for choosing dependency groups."""
    return """
BenchBox Dependency Installation Guide
=====================================

Choose your installation based on your needs:

Quick Start (Recommended)
   └── uv add benchbox --extra cloud
       • Includes: Databricks, BigQuery, Redshift, Snowflake
       • Best for: Most users, cloud platform comparison
       • Excludes: ClickHouse (add [all] if needed)
       Alternative: uv pip install "benchbox[cloud]"

Cloud Storage Paths
   └── uv add benchbox --extra cloudstorage
       • Enables: AWS S3, Google Cloud Storage, Azure Data Lake paths
       • Best for: Remote output directories or data staging without new adapters
       Alternative: uv pip install "benchbox[cloudstorage]"

Cloud Platform Specific
   ├── Databricks/Spark  → uv add benchbox --extra databricks
   ├── Google BigQuery   → uv add benchbox --extra bigquery
   ├── Amazon Redshift   → uv add benchbox --extra redshift
   └── Snowflake        → uv add benchbox --extra snowflake

Analytics Database
   └── ClickHouse       → uv add benchbox --extra clickhouse

Development/Testing
   ├── Everything       → uv add benchbox --extra all
   └── Core only        → uv add benchbox

Scenarios:
   • Multi-cloud comparison     → [cloud]
   • Single platform focus     → [platform-name]
   • Local development         → [all]
   • Minimal footprint        → benchbox (core only)
   • Maximum compatibility     → [all]

ℹ️  Core installation (just 'benchbox') includes DuckDB and works for:
   • Local benchmarking and testing
   • Data generation and query development
   • SQLite-based workflows

💡 Note: Add 'Alternative: uv pip install "benchbox[...]"' for pip-compatible syntax
"""
