from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping


class SupportLevel(Enum):
    NATIVE = "native"
    EXTENSION = "extension"
    EXPERIMENTAL = "experimental"
    NOT_SUPPORTED = "not_supported"


@dataclass(frozen=True)
class FormatCapability:
    format_name: str
    display_name: str
    file_extension: str
    features: set[str]
    supported_platforms: dict[str, SupportLevel]


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
        "pg_duckdb": SupportLevel.EXTENSION,
        "sqlite": SupportLevel.EXTENSION,
        "spark": SupportLevel.NATIVE,
        "emr-serverless": SupportLevel.NATIVE,
        "dataproc": SupportLevel.NATIVE,
        "dataproc-serverless": SupportLevel.NATIVE,
        "synapse-spark": SupportLevel.NATIVE,
        "athena-spark": SupportLevel.NATIVE,
        "fabric-spark": SupportLevel.NATIVE,
        "fabric-lakehouse": SupportLevel.NATIVE,
        "fabric_dw": SupportLevel.NATIVE,
        "trino": SupportLevel.NATIVE,
        "presto": SupportLevel.NATIVE,
        "athena": SupportLevel.NATIVE,
        "lakesail": SupportLevel.NATIVE,
        "quanton": SupportLevel.NATIVE,
    },
)

DELTA_CAPABILITY = FormatCapability(
    format_name="delta",
    display_name="Delta Lake",
    file_extension="",
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
        "duckdb": SupportLevel.EXTENSION,
        "datafusion": SupportLevel.EXTENSION,
        "trino": SupportLevel.EXTENSION,
        "presto": SupportLevel.EXTENSION,
        "spark": SupportLevel.EXTENSION,
        "emr-serverless": SupportLevel.EXTENSION,
        "dataproc": SupportLevel.EXTENSION,
        "dataproc-serverless": SupportLevel.EXTENSION,
        "fabric-spark": SupportLevel.NATIVE,
        "synapse-spark": SupportLevel.NATIVE,
        "athena-spark": SupportLevel.EXTENSION,
        "quanton": SupportLevel.EXTENSION,
    },
)

ICEBERG_CAPABILITY = FormatCapability(
    format_name="iceberg",
    display_name="Apache Iceberg",
    file_extension="",
    features={
        "time_travel",
        "partition_evolution",
        "schema_evolution",
        "hidden_partitioning",
        "snapshot_management",
    },
    supported_platforms={
        "duckdb": SupportLevel.EXPERIMENTAL,
        "datafusion": SupportLevel.EXTENSION,
        "trino": SupportLevel.EXTENSION,
        "presto": SupportLevel.EXTENSION,
        "spark": SupportLevel.EXTENSION,
        "emr-serverless": SupportLevel.EXTENSION,
        "dataproc": SupportLevel.EXTENSION,
        "dataproc-serverless": SupportLevel.EXTENSION,
        "synapse-spark": SupportLevel.EXTENSION,
        "fabric-spark": SupportLevel.EXTENSION,
        "athena-spark": SupportLevel.EXTENSION,
        "quanton": SupportLevel.NATIVE,
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
        "duckdb": SupportLevel.EXTENSION,
        "datafusion": SupportLevel.EXPERIMENTAL,
    },
)

HUDI_CAPABILITY = FormatCapability(
    format_name="hudi",
    display_name="Apache Hudi",
    file_extension="",
    features={
        "time_travel",
        "acid_transactions",
        "schema_evolution",
        "compaction",
        "copy_on_write",
        "merge_on_read",
    },
    supported_platforms={
        "spark": SupportLevel.EXTENSION,
        "quanton": SupportLevel.NATIVE,
        "emr-serverless": SupportLevel.EXTENSION,
        "dataproc": SupportLevel.EXTENSION,
        "dataproc-serverless": SupportLevel.EXTENSION,
    },
)

DUCKLAKE_CAPABILITY = FormatCapability(
    format_name="ducklake",
    display_name="DuckLake",
    file_extension="",
    features={
        "time_travel",
        "acid_transactions",
        "schema_evolution",
        "snapshot_isolation",
        "predicate_pushdown",
        "column_pruning",
    },
    supported_platforms={
        "duckdb": SupportLevel.NATIVE,
    },
)

CAPABILITIES_REGISTRY: dict[str, FormatCapability] = {
    "parquet": PARQUET_CAPABILITY,
    "delta": DELTA_CAPABILITY,
    "iceberg": ICEBERG_CAPABILITY,
    "hudi": HUDI_CAPABILITY,
    "vortex": VORTEX_CAPABILITY,
    "ducklake": DUCKLAKE_CAPABILITY,
}

PLATFORM_FORMAT_PREFERENCES: dict[str, list[str]] = {
    "duckdb": ["tbl", "parquet", "csv", "ducklake", "vortex", "delta"],
    "datafusion": ["tbl", "parquet", "csv", "delta", "iceberg", "vortex"],
    "clickhouse": ["tbl", "parquet", "csv"],
    "clickhouse-cloud": ["tbl", "parquet", "csv"],
    "snowflake": ["tbl", "parquet", "csv"],
    "redshift": ["tbl", "parquet", "csv"],
    "postgresql": ["tbl", "parquet", "csv"],
    "pg_duckdb": ["tbl", "parquet", "csv"],
    "sqlite": ["tbl", "parquet", "csv"],
    "athena": ["tbl", "csv"],
    "bigquery": ["parquet", "tbl", "csv"],
    "databricks": ["delta", "parquet", "tbl", "csv"],
    "trino": ["iceberg", "delta", "parquet", "tbl", "csv"],
    "presto": ["iceberg", "delta", "parquet", "tbl", "csv"],
    "spark": ["delta", "iceberg", "hudi", "parquet", "tbl", "csv"],
    "emr-serverless": ["delta", "iceberg", "hudi", "parquet", "tbl", "csv"],
    "dataproc": ["delta", "iceberg", "hudi", "parquet", "tbl", "csv"],
    "dataproc-serverless": ["delta", "iceberg", "hudi", "parquet", "tbl", "csv"],
    "synapse-spark": ["delta", "iceberg", "parquet", "tbl", "csv"],
    "athena-spark": ["delta", "iceberg", "parquet", "tbl", "csv"],
    "fabric-lakehouse": ["parquet", "tbl", "csv"],
    "fabric_dw": ["parquet", "tbl", "csv"],
    "fabric-spark": ["delta", "iceberg", "parquet", "tbl", "csv"],
    "lakesail": ["parquet", "tbl", "csv"],
    "quanton": ["iceberg", "hudi", "delta", "parquet", "tbl", "csv"],
}

PREFER_PLATFORM_FORMAT_ORDER: set[str] = {
    "redshift",
}

EXTERNAL_PLATFORM_FORMAT_PREFERENCES: dict[str, list[str]] = {
    "athena": ["parquet"],
    "clickhouse-cloud": ["iceberg", "parquet", "tbl", "csv"],
    "snowflake": ["iceberg", "delta", "parquet", "tbl", "csv"],
    "bigquery": ["delta", "iceberg", "parquet", "tbl", "csv"],
    "redshift": ["delta", "iceberg", "parquet", "tbl", "csv"],
}


def normalize_platform_key(platform_name: str) -> str:
    import re

    key = platform_name.strip().lower()

    if key in PLATFORM_FORMAT_PREFERENCES:
        return key

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

    if key.endswith("adapter"):
        key = key[: -len("adapter")]

    kebab = re.sub(r"([a-z])([A-Z])", r"\1-\2", platform_name.strip()).lower()
    if kebab.endswith("-adapter"):
        kebab = kebab[: -len("-adapter")]
    if kebab in PLATFORM_FORMAT_PREFERENCES:
        return kebab

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

    hyphenated = key.replace(" ", "-")
    if hyphenated in PLATFORM_FORMAT_PREFERENCES:
        return hyphenated

    if "-" in key:
        underscored = key.replace("-", "_")
        if underscored in PLATFORM_FORMAT_PREFERENCES:
            return underscored

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
        if format_name in {"delta", "iceberg"}:
            return bool(_config_value(platform_config, "biglake_connection"))
        return True

    if platform_key == "redshift":
        if not (_config_value(platform_config, "s3_bucket") or _config_value(platform_config, "staging_root")):
            return False
        if format_name in {"delta", "iceberg"}:
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
        if platform_key in {"bigquery", "redshift"} and format_name in {"delta", "iceberg"}:
            return SupportLevel.EXTENSION
        if platform_key == "clickhouse-cloud" and format_name == "iceberg":
            return SupportLevel.EXTENSION

    return None


def get_supported_formats(
    platform_name: str,
    table_mode: str = "native",
    platform_config: Mapping[str, Any] | None = None,
) -> list[str]:
    key = normalize_platform_key(platform_name)
    supported = []

    preference_order = _get_preference_order(key, table_mode)

    for fmt in preference_order:
        capability = CAPABILITIES_REGISTRY.get(fmt)
        if not capability:
            supported.append(fmt)
            continue

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
    supported = get_supported_formats(platform_name, table_mode=table_mode, platform_config=platform_config)

    if available_formats:
        for fmt in supported:
            if fmt in available_formats:
                return fmt
        return available_formats[0] if available_formats else "tbl"

    return supported[0] if supported else "tbl"


def is_format_supported(
    platform_name: str,
    format_name: str,
    table_mode: str = "native",
    platform_config: Mapping[str, Any] | None = None,
) -> bool:
    if format_name in {"tbl", "csv", "dat"}:
        return True

    capability = CAPABILITIES_REGISTRY.get(format_name)
    if not capability:
        return False

    key = normalize_platform_key(platform_name)
    support_level = _get_support_level(key, format_name, table_mode, platform_config=platform_config)
    return support_level is not None and support_level != SupportLevel.NOT_SUPPORTED


def get_format_capability(format_name: str) -> FormatCapability | None:
    return CAPABILITIES_REGISTRY.get(format_name)


def has_feature(format_name: str, feature: str) -> bool:
    capability = get_format_capability(format_name)
    return capability is not None and feature in capability.features
