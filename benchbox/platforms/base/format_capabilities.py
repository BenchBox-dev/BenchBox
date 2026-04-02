"""Format capability detection and platform compatibility mappings.

This module defines which table formats are supported by each platform and provides
utilities for format selection and capability queries.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping


class SupportLevel(Enum):
    """Level of support for a table format on a platform."""

    NATIVE = "native"  # Full native support
    EXTENSION = "extension"  # Requires extension/plugin
    EXPERIMENTAL = "experimental"  # Experimental support, may be unstable
    NOT_SUPPORTED = "not_supported"  # Format not supported


@dataclass(frozen=True)
class FormatCapability:
    """Capability information for a table format.

    Attributes:
        format_name: Name of the format (e.g., 'parquet', 'delta', 'iceberg')
        display_name: Human-readable name (e.g., 'Apache Parquet', 'Delta Lake')
        file_extension: File extension or directory marker
        features: Set of supported features
        supported_platforms: Dict mapping platform name to support level
    """

    format_name: str
    display_name: str
    file_extension: str
    features: set[str]
    supported_platforms: dict[str, SupportLevel]


# Define format capabilities
PARQUET_CAPABILITY = FormatCapability(
    format_name="parquet",
    display_name="Apache Parquet",
    file_extension=".parquet",
    features={
        "predicate_pushdown",
        "column_pruning",
        "partition_pruning",
        "compression",
        "statistics",
    },
    supported_platforms={
        "duckdb": SupportLevel.NATIVE,
        "datafusion": SupportLevel.NATIVE,
        "clickhouse": SupportLevel.NATIVE,
        "clickhouse-cloud": SupportLevel.NATIVE,
        "databricks": SupportLevel.NATIVE,
        "snowflake": SupportLevel.NATIVE,
        "bigquery": SupportLevel.NATIVE,
        "redshift": SupportLevel.NATIVE,
        "postgresql": SupportLevel.EXTENSION,
        "sqlite": SupportLevel.EXTENSION,
        "spark": SupportLevel.NATIVE,
        "emr-serverless": SupportLevel.NATIVE,
        "dataproc": SupportLevel.NATIVE,
        "dataproc-serverless": SupportLevel.NATIVE,
        "synapse-spark": SupportLevel.NATIVE,
        "athena-spark": SupportLevel.NATIVE,
        "fabric-spark": SupportLevel.NATIVE,
        "fabric-lakehouse": SupportLevel.NATIVE,
        "trino": SupportLevel.NATIVE,
        "presto": SupportLevel.NATIVE,
        "lakesail": SupportLevel.NATIVE,
        "quanton": SupportLevel.NATIVE,
    },
)

DELTA_CAPABILITY = FormatCapability(
    format_name="delta",
    display_name="Delta Lake",
    file_extension="",  # Delta is directory-based
    features={
        "time_travel",
        "acid_transactions",
        "schema_evolution",
        "optimize",
        "vacuum",
        "z_order",
    },
    supported_platforms={
        "databricks": SupportLevel.NATIVE,
        "duckdb": SupportLevel.EXTENSION,  # delta extension
        "datafusion": SupportLevel.EXTENSION,  # via deltalake Python library
        "trino": SupportLevel.EXTENSION,  # via delta catalog connector
        "presto": SupportLevel.EXTENSION,  # via delta catalog connector
        "spark": SupportLevel.EXTENSION,  # via delta-spark package
        "emr-serverless": SupportLevel.EXTENSION,  # via delta-spark on EMR
        "dataproc": SupportLevel.EXTENSION,  # via delta-spark on Dataproc
        "dataproc-serverless": SupportLevel.EXTENSION,  # via delta-spark on Dataproc Serverless
        "fabric-spark": SupportLevel.NATIVE,  # delta native on Fabric
        "synapse-spark": SupportLevel.NATIVE,  # delta native on Synapse Spark pools
        "athena-spark": SupportLevel.EXTENSION,  # via delta-spark on Athena Spark
        "quanton": SupportLevel.EXTENSION,  # via delta-spark on Quanton
        # NOTE: snowflake, clickhouse, redshift, bigquery, fabric-lakehouse
        # support delta on the platform but BenchBox default loading flows still lack
        # safe end-to-end format selection for those adapters.
    },
)

ICEBERG_CAPABILITY = FormatCapability(
    format_name="iceberg",
    display_name="Apache Iceberg",
    file_extension="",  # Iceberg is directory-based
    features={
        "time_travel",
        "partition_evolution",
        "schema_evolution",
        "hidden_partitioning",
        "snapshot_management",
    },
    supported_platforms={
        "duckdb": SupportLevel.EXPERIMENTAL,  # iceberg extension
        "datafusion": SupportLevel.EXTENSION,  # via pyiceberg Python library
        "trino": SupportLevel.EXTENSION,  # via iceberg catalog connector
        "presto": SupportLevel.EXTENSION,  # via iceberg catalog connector
        "spark": SupportLevel.EXTENSION,  # via iceberg-spark-runtime
        "emr-serverless": SupportLevel.EXTENSION,  # via iceberg-spark-runtime on EMR
        "dataproc": SupportLevel.EXTENSION,  # via iceberg-spark-runtime on Dataproc
        "dataproc-serverless": SupportLevel.EXTENSION,  # via iceberg-spark-runtime on Dataproc Serverless
        "synapse-spark": SupportLevel.EXTENSION,  # via iceberg-spark-runtime on Synapse
        "fabric-spark": SupportLevel.EXTENSION,  # via iceberg-spark-runtime on Fabric
        "athena-spark": SupportLevel.EXTENSION,  # via iceberg-spark-runtime on Athena Spark
        "quanton": SupportLevel.NATIVE,  # Iceberg is primary format
        # NOTE: snowflake, clickhouse support iceberg on the platform but BenchBox
        # does not yet expose mode-aware format selection for those adapters.
    },
)

VORTEX_CAPABILITY = FormatCapability(
    format_name="vortex",
    display_name="Vortex",
    file_extension=".vortex",
    features={
        "compression",
        "column_pruning",
        "predicate_pushdown",
        "statistics",
    },
    supported_platforms={
        "duckdb": SupportLevel.EXTENSION,  # vortex extension
        "datafusion": SupportLevel.EXPERIMENTAL,
    },
)

HUDI_CAPABILITY = FormatCapability(
    format_name="hudi",
    display_name="Apache Hudi",
    file_extension="",  # Hudi is directory-based
    features={
        "time_travel",
        "acid_transactions",
        "schema_evolution",
        "compaction",
        "copy_on_write",
        "merge_on_read",
    },
    supported_platforms={
        "spark": SupportLevel.EXTENSION,  # via hudi-spark-bundle
        "quanton": SupportLevel.NATIVE,  # Hudi is primary format
        "emr-serverless": SupportLevel.EXTENSION,  # via hudi-spark-bundle
        "dataproc": SupportLevel.EXTENSION,  # via hudi-spark-bundle
        "dataproc-serverless": SupportLevel.EXTENSION,  # via hudi-spark-bundle
    },
)

DUCKLAKE_CAPABILITY = FormatCapability(
    format_name="ducklake",
    display_name="DuckLake",
    file_extension="",  # DuckLake is directory-based
    features={
        "time_travel",
        "acid_transactions",
        "schema_evolution",
        "snapshot_isolation",
        "predicate_pushdown",
        "column_pruning",
    },
    supported_platforms={
        "duckdb": SupportLevel.NATIVE,  # DuckLake is DuckDB's native table format
    },
)

# Registry of all format capabilities
CAPABILITIES_REGISTRY: dict[str, FormatCapability] = {
    "parquet": PARQUET_CAPABILITY,
    "delta": DELTA_CAPABILITY,
    "iceberg": ICEBERG_CAPABILITY,
    "hudi": HUDI_CAPABILITY,
    "vortex": VORTEX_CAPABILITY,
    "ducklake": DUCKLAKE_CAPABILITY,
}

# Platform format preferences (which format to prefer when multiple available)
PLATFORM_FORMAT_PREFERENCES: dict[str, list[str]] = {
    # SQL databases: text files (tbl) preferred — always available from TPC generators,
    # no conversion step required. Parquet preferred over csv as fallback (faster,
    # schema-aware). Users can override via platform config.
    "duckdb": ["tbl", "parquet", "csv", "ducklake", "vortex", "delta"],
    "datafusion": ["tbl", "parquet", "csv", "delta", "iceberg", "vortex"],
    "clickhouse": ["tbl", "parquet", "csv"],
    "clickhouse-cloud": ["tbl", "parquet", "csv"],
    "snowflake": ["tbl", "parquet", "csv"],
    "redshift": ["tbl", "parquet", "csv"],
    "postgresql": ["tbl", "parquet", "csv"],
    "sqlite": ["tbl", "parquet", "csv"],
    # Cloud warehouses: parquet preferred — BigQuery native load jobs support parquet,
    # and columnar input avoids text parsing / schema inference overhead.
    "bigquery": ["parquet", "tbl", "csv"],
    # Catalog/lakehouse platforms: columnar formats required or strongly preferred
    "databricks": ["delta", "parquet", "tbl", "csv"],
    "trino": ["iceberg", "delta", "parquet", "tbl", "csv"],
    "presto": ["iceberg", "delta", "parquet", "tbl", "csv"],
    "spark": ["delta", "iceberg", "hudi", "parquet", "tbl", "csv"],
    "emr-serverless": ["delta", "iceberg", "hudi", "parquet", "tbl", "csv"],
    "dataproc": ["delta", "iceberg", "hudi", "parquet", "tbl", "csv"],
    "dataproc-serverless": ["delta", "iceberg", "hudi", "parquet", "tbl", "csv"],
    "synapse-spark": ["delta", "iceberg", "parquet", "tbl", "csv"],
    "athena-spark": ["delta", "iceberg", "parquet", "tbl", "csv"],
    # fabric-lakehouse is read-only (SQL endpoint); data loaded via fabric-spark
    "fabric-lakehouse": ["parquet", "tbl", "csv"],
    "fabric-spark": ["delta", "iceberg", "parquet", "tbl", "csv"],
    # lakesail uses Spark-based loading; parquet/orc are its native table formats
    "lakesail": ["parquet", "tbl", "csv"],
    "quanton": ["iceberg", "hudi", "delta", "parquet", "tbl", "csv"],
}

# Platforms whose native loaders have strong operational requirements for
# platform-preferred format order (e.g., Redshift COPY is most reliable with
# delimited text).  For these platforms in native mode, PLATFORM_FORMAT_PREFERENCES
# takes priority over manifest format_preference when selecting data files.
PREFER_PLATFORM_FORMAT_ORDER: set[str] = {
    "redshift",
}

EXTERNAL_PLATFORM_FORMAT_PREFERENCES: dict[str, list[str]] = {
    "clickhouse-cloud": ["iceberg", "parquet", "tbl", "csv"],
    "snowflake": ["iceberg", "delta", "parquet", "tbl", "csv"],
    "bigquery": ["delta", "parquet", "tbl", "csv"],
    "redshift": ["delta", "parquet", "tbl", "csv"],
}


def normalize_platform_key(platform_name: str) -> str:
    """Normalize a platform display name to a registry key.

    Adapters return display names like 'ClickHouse Cloud' or class names like
    'EMRServerlessAdapter'. This function maps them to the registry keys used
    in PLATFORM_FORMAT_PREFERENCES (e.g., 'clickhouse', 'emr-serverless').

    Args:
        platform_name: Display name or class name from an adapter

    Returns:
        Normalized registry key
    """
    import re

    key = platform_name.strip().lower()

    # Direct match — most common case
    if key in PLATFORM_FORMAT_PREFERENCES:
        return key

    # Explicit overrides for display names that don't normalize cleanly
    _DISPLAY_NAME_MAP: dict[str, str] = {
        "clickhouse cloud": "clickhouse-cloud",
        "clickhouse (cloud)": "clickhouse-cloud",
        "clickhouse (local)": "clickhouse",
        "fabric lakehouse": "fabric-lakehouse",
        "fabric warehouse": "fabric_dw",
        "azure synapse": "synapse",
        "pyspark sql": "pyspark",
    }
    if key in _DISPLAY_NAME_MAP:
        return _DISPLAY_NAME_MAP[key]

    # Strip "Adapter" suffix from class names
    if key.endswith("adapter"):
        key = key[: -len("adapter")]

    # Try CamelCase → kebab-case (e.g., "SynapseSpark" → "synapse-spark")
    kebab = re.sub(r"([a-z])([A-Z])", r"\1-\2", platform_name.strip()).lower()
    if kebab.endswith("-adapter"):
        kebab = kebab[: -len("-adapter")]
    if kebab in PLATFORM_FORMAT_PREFERENCES:
        return kebab

    # Handle class names with all-caps prefixes (e.g., "EMRServerlessAdapter")
    _CLASS_NAME_MAP: dict[str, str] = {
        "emrserverless": "emr-serverless",
        "dataprocserverless": "dataproc-serverless",
        "synapsespark": "synapse-spark",
        "fabricspark": "fabric-spark",
        "fabriclakehouse": "fabric-lakehouse",
        "athenaspark": "athena-spark",
    }
    if key in _CLASS_NAME_MAP:
        return _CLASS_NAME_MAP[key]

    # Replace spaces with hyphens as last resort
    hyphenated = key.replace(" ", "-")
    if hyphenated in PLATFORM_FORMAT_PREFERENCES:
        return hyphenated

    return key


def _get_preference_order(platform_key: str, table_mode: str) -> list[str]:
    normalized_mode = (table_mode or "native").strip().lower()
    if normalized_mode == "external":
        external = EXTERNAL_PLATFORM_FORMAT_PREFERENCES.get(platform_key)
        if external is not None:
            return external
    return PLATFORM_FORMAT_PREFERENCES.get(platform_key, [])


def _config_value(platform_config: Mapping[str, Any] | None, key: str) -> Any:
    if not platform_config:
        return None
    return platform_config.get(key)


def _has_required_external_config(
    platform_key: str,
    format_name: str,
    platform_config: Mapping[str, Any] | None,
) -> bool:
    if platform_key == "snowflake":
        if not _config_value(platform_config, "staging_root"):
            return False
        if format_name == "iceberg":
            return bool(_config_value(platform_config, "iceberg_external_volume"))
        return True

    if platform_key == "bigquery":
        if not (_config_value(platform_config, "storage_bucket") or _config_value(platform_config, "staging_root")):
            return False
        if format_name == "delta":
            return bool(_config_value(platform_config, "biglake_connection"))
        return True

    if platform_key == "redshift":
        if not (_config_value(platform_config, "s3_bucket") or _config_value(platform_config, "staging_root")):
            return False
        if format_name == "delta":
            return bool(_config_value(platform_config, "iam_role"))
        return True

    if platform_key == "clickhouse-cloud":
        return bool(
            _config_value(platform_config, "s3_staging_url") or _config_value(platform_config, "gcs_staging_url")
        )

    return True


def _get_support_level(
    platform_key: str,
    format_name: str,
    table_mode: str,
    platform_config: Mapping[str, Any] | None = None,
) -> SupportLevel | None:
    capability = CAPABILITIES_REGISTRY.get(format_name)
    if capability is None:
        return None

    support_level = capability.supported_platforms.get(platform_key)
    if support_level is not None:
        return support_level

    normalized_mode = (table_mode or "native").strip().lower()
    if normalized_mode == "external":
        if not _has_required_external_config(platform_key, format_name, platform_config):
            return None
        if platform_key == "snowflake" and format_name in {"delta", "iceberg"}:
            return SupportLevel.EXTENSION
        if platform_key in {"bigquery", "redshift"} and format_name == "delta":
            return SupportLevel.EXTENSION
        if platform_key == "clickhouse-cloud" and format_name == "iceberg":
            return SupportLevel.EXTENSION

    return None


def get_supported_formats(
    platform_name: str,
    table_mode: str = "native",
    platform_config: Mapping[str, Any] | None = None,
) -> list[str]:
    """Get list of formats supported by a platform.

    Args:
        platform_name: Name of the platform (e.g., 'duckdb', 'databricks')

    Returns:
        List of supported format names, ordered by preference
    """
    key = normalize_platform_key(platform_name)
    supported = []

    # Get platform's format preference order
    preference_order = _get_preference_order(key, table_mode)

    # Check each format in preference order
    for fmt in preference_order:
        capability = CAPABILITIES_REGISTRY.get(fmt)
        if not capability:
            # Unknown format (tbl, csv handled separately)
            supported.append(fmt)
            continue

        # Check if platform supports this format
        support_level = _get_support_level(key, fmt, table_mode, platform_config=platform_config)
        if support_level and support_level != SupportLevel.NOT_SUPPORTED:
            supported.append(fmt)

    return supported


def get_preferred_format(
    platform_name: str,
    available_formats: list[str] | None = None,
    table_mode: str = "native",
    platform_config: Mapping[str, Any] | None = None,
) -> str:
    """Get the preferred format for a platform.

    Args:
        platform_name: Name of the platform
        available_formats: Optional list of available formats to choose from.
                         If None, returns the most preferred supported format.

    Returns:
        Preferred format name, or 'tbl' if no formats available
    """
    supported = get_supported_formats(platform_name, table_mode=table_mode, platform_config=platform_config)

    if available_formats:
        # Find first supported format that's also available
        for fmt in supported:
            if fmt in available_formats:
                return fmt
        # Fallback to first available format
        return available_formats[0] if available_formats else "tbl"

    # Return most preferred supported format
    return supported[0] if supported else "tbl"


def is_format_supported(
    platform_name: str,
    format_name: str,
    table_mode: str = "native",
    platform_config: Mapping[str, Any] | None = None,
) -> bool:
    """Check if a format is supported on a platform.

    Args:
        platform_name: Name of the platform
        format_name: Name of the format

    Returns:
        True if format is supported (at any level except NOT_SUPPORTED)
    """
    # Legacy formats (tbl, csv) are always supported
    if format_name in {"tbl", "csv", "dat"}:
        return True

    capability = CAPABILITIES_REGISTRY.get(format_name)
    if not capability:
        return False

    key = normalize_platform_key(platform_name)
    support_level = _get_support_level(key, format_name, table_mode, platform_config=platform_config)
    return support_level is not None and support_level != SupportLevel.NOT_SUPPORTED


def get_format_capability(format_name: str) -> FormatCapability | None:
    """Get capability information for a format.

    Args:
        format_name: Name of the format

    Returns:
        FormatCapability if format is known, None otherwise
    """
    return CAPABILITIES_REGISTRY.get(format_name)


def has_feature(format_name: str, feature: str) -> bool:
    """Check if a format supports a specific feature.

    Args:
        format_name: Name of the format
        feature: Feature name (e.g., 'time_travel', 'predicate_pushdown')

    Returns:
        True if format supports the feature
    """
    capability = get_format_capability(format_name)
    return capability is not None and feature in capability.features
