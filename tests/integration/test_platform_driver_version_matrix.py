"""Integration matrix tests for multi-version supported adapters and unsupported path regression."""

from __future__ import annotations

import pytest

from benchbox.platforms.base.adapter import DriverIsolationCapability, check_isolation_capability

pytestmark = [
    pytest.mark.integration,
    pytest.mark.fast,
]


# --------------------------------------------------------------------------- #
# Matrix: verify every adapter that declares a non-default capability actually
# has the class attribute set correctly at import time.
# --------------------------------------------------------------------------- #

_SUPPORTED_ADAPTERS = [
    ("benchbox.platforms.duckdb", "DuckDBAdapter", DriverIsolationCapability.SUPPORTED),
    ("benchbox.platforms.datafusion", "DataFusionAdapter", DriverIsolationCapability.SUPPORTED),
    ("benchbox.platforms.dataframe.datafusion_df", "DataFusionDataFrameAdapter", DriverIsolationCapability.SUPPORTED),
]

_FEASIBLE_CLIENT_ONLY_ADAPTERS = [
    ("benchbox.platforms.snowflake", "SnowflakeAdapter"),
    ("benchbox.platforms.bigquery", "BigQueryAdapter"),
    ("benchbox.platforms.redshift", "RedshiftAdapter"),
    ("benchbox.platforms.clickhouse_cloud", "ClickHouseCloudAdapter"),
    ("benchbox.platforms.databricks.adapter", "DatabricksAdapter"),
    ("benchbox.platforms.firebolt", "FireboltAdapter"),
    ("benchbox.platforms.databend.adapter", "DatabendAdapter"),
    ("benchbox.platforms.trino", "TrinoAdapter"),
    ("benchbox.platforms.starburst", "StarburstAdapter"),
    ("benchbox.platforms.presto", "PrestoAdapter"),
    ("benchbox.platforms.athena", "AthenaAdapter"),
    ("benchbox.platforms.influxdb.adapter", "InfluxDBAdapter"),
    ("benchbox.platforms.postgresql", "PostgreSQLAdapter"),
    ("benchbox.platforms.doris", "DorisAdapter"),
    ("benchbox.platforms.starrocks.adapter", "StarRocksAdapter"),
    ("benchbox.platforms.questdb", "QuestDBAdapter"),
    ("benchbox.platforms.timescaledb", "TimescaleDBAdapter"),
    ("benchbox.platforms.snowpark_connect", "SnowparkConnectAdapter"),
    ("benchbox.platforms.motherduck", "MotherDuckAdapter"),
]

_NOT_FEASIBLE_ADAPTERS = [
    ("benchbox.platforms.spark", "SparkAdapter"),
    ("benchbox.platforms.lakesail", "LakeSailAdapter"),
    ("benchbox.platforms.clickhouse.adapter", "ClickHouseAdapter"),
    ("benchbox.platforms.azure_synapse", "AzureSynapseAdapter"),
    ("benchbox.platforms.fabric_warehouse", "FabricWarehouseAdapter"),
    ("benchbox.platforms.fabric_lakehouse", "FabricLakehouseAdapter"),
    ("benchbox.platforms.aws.emr_serverless_adapter", "EMRServerlessAdapter"),
    ("benchbox.platforms.aws.athena_spark_adapter", "AthenaSparkAdapter"),
    ("benchbox.platforms.aws.glue_adapter", "AWSGlueAdapter"),
    ("benchbox.platforms.gcp.dataproc_adapter", "DataprocAdapter"),
    ("benchbox.platforms.gcp.dataproc_serverless_adapter", "DataprocServerlessAdapter"),
    ("benchbox.platforms.azure.fabric_spark_adapter", "FabricSparkAdapter"),
    ("benchbox.platforms.azure.synapse_spark_adapter", "SynapseSparkAdapter"),
    ("benchbox.platforms.cudf", "CuDFAdapter"),
]

_NOT_APPLICABLE_ADAPTERS = [
    ("benchbox.platforms.sqlite", "SQLiteAdapter"),
    ("benchbox.platforms.polars_platform", "PolarsAdapter"),
]


def _import_adapter(module_path: str, class_name: str):
    """Dynamically import an adapter class."""
    import importlib

    mod = importlib.import_module(module_path)
    return getattr(mod, class_name)


@pytest.mark.parametrize(
    "module_path,class_name,expected",
    _SUPPORTED_ADAPTERS,
    ids=[t[1] for t in _SUPPORTED_ADAPTERS],
)
def test_supported_adapters_declare_supported(module_path, class_name, expected):
    adapter_cls = _import_adapter(module_path, class_name)
    assert adapter_cls.driver_isolation_capability == expected


@pytest.mark.parametrize(
    "module_path,class_name",
    _FEASIBLE_CLIENT_ONLY_ADAPTERS,
    ids=[t[1] for t in _FEASIBLE_CLIENT_ONLY_ADAPTERS],
)
def test_feasible_client_only_adapters(module_path, class_name):
    adapter_cls = _import_adapter(module_path, class_name)
    assert adapter_cls.driver_isolation_capability == DriverIsolationCapability.FEASIBLE_CLIENT_ONLY


@pytest.mark.parametrize(
    "module_path,class_name",
    _NOT_FEASIBLE_ADAPTERS,
    ids=[t[1] for t in _NOT_FEASIBLE_ADAPTERS],
)
def test_not_feasible_adapters(module_path, class_name):
    adapter_cls = _import_adapter(module_path, class_name)
    assert adapter_cls.driver_isolation_capability == DriverIsolationCapability.NOT_FEASIBLE


@pytest.mark.parametrize(
    "module_path,class_name",
    _NOT_APPLICABLE_ADAPTERS,
    ids=[t[1] for t in _NOT_APPLICABLE_ADAPTERS],
)
def test_not_applicable_adapters(module_path, class_name):
    adapter_cls = _import_adapter(module_path, class_name)
    assert adapter_cls.driver_isolation_capability == DriverIsolationCapability.NOT_APPLICABLE


# --------------------------------------------------------------------------- #
# Regression: unsupported isolation requests fail fast with actionable errors
# --------------------------------------------------------------------------- #


class TestUnsupportedIsolationFailFast:
    """Verify that requesting isolation on non-SUPPORTED adapters fails with correct messages."""

    @pytest.mark.parametrize(
        "module_path,class_name",
        _FEASIBLE_CLIENT_ONLY_ADAPTERS,
        ids=[t[1] for t in _FEASIBLE_CLIENT_ONLY_ADAPTERS],
    )
    def test_feasible_client_only_rejects_isolation(self, module_path, class_name):
        adapter_cls = _import_adapter(module_path, class_name)
        with pytest.raises(RuntimeError, match="independent from the engine"):
            check_isolation_capability(adapter_cls, class_name, "isolated-site-packages")

    @pytest.mark.parametrize(
        "module_path,class_name",
        _NOT_FEASIBLE_ADAPTERS,
        ids=[t[1] for t in _NOT_FEASIBLE_ADAPTERS],
    )
    def test_not_feasible_rejects_isolation(self, module_path, class_name):
        adapter_cls = _import_adapter(module_path, class_name)
        with pytest.raises(RuntimeError, match="technical constraints"):
            check_isolation_capability(adapter_cls, class_name, "isolated-site-packages")

    @pytest.mark.parametrize(
        "module_path,class_name,_expected",
        _SUPPORTED_ADAPTERS,
        ids=[t[1] for t in _SUPPORTED_ADAPTERS],
    )
    def test_supported_adapters_allow_isolation(self, module_path, class_name, _expected):
        adapter_cls = _import_adapter(module_path, class_name)
        # Should not raise
        check_isolation_capability(adapter_cls, class_name, "isolated-site-packages")


# --------------------------------------------------------------------------- #
# DataFusion: verify driver_version_actual is populated from live module
# --------------------------------------------------------------------------- #


def test_datafusion_sql_adapter_populates_driver_version_actual():
    """Verify DataFusion SQL adapter sets driver_version_actual from live import."""
    from benchbox.platforms.datafusion import DataFusionAdapter

    adapter = DataFusionAdapter(database_path=":memory:")
    info = adapter.get_platform_info()
    assert info.get("driver_version_actual") is not None
    assert info["driver_version_actual"] == info["platform_version"]


def test_datafusion_df_adapter_populates_driver_version_actual():
    """Verify DataFusion DataFrame adapter sets driver_version_actual from live import."""
    from benchbox.platforms.dataframe.datafusion_df import DataFusionDataFrameAdapter

    adapter = DataFusionDataFrameAdapter()
    info = adapter.get_platform_info()
    assert info.get("driver_version_actual") is not None
    assert info["driver_version_actual"] == info["version"]


# --------------------------------------------------------------------------- #
# DuckDB: verify driver_version_actual is populated from live module (L1)
# --------------------------------------------------------------------------- #


def test_duckdb_adapter_populates_driver_version_actual():
    """Verify DuckDB adapter sets driver_version_actual from live import."""
    from benchbox.platforms.duckdb import DuckDBAdapter

    adapter = DuckDBAdapter(database_path=":memory:")
    info = adapter.get_platform_info()
    assert info.get("driver_version_actual") is not None
    assert info["driver_version_actual"] == info["platform_version"]


# --------------------------------------------------------------------------- #
# Auto-discovery: ensure every registered adapter declares an explicit
# driver_isolation_capability (catches new platforms that forget).
# --------------------------------------------------------------------------- #

# Collect all adapters from the hardcoded lists for the known-set
_ALL_KNOWN_ADAPTERS = (
    {class_name for _, class_name, *_ in _SUPPORTED_ADAPTERS}
    | {class_name for _, class_name in _FEASIBLE_CLIENT_ONLY_ADAPTERS}
    | {class_name for _, class_name in _NOT_FEASIBLE_ADAPTERS}
    | {class_name for _, class_name in _NOT_APPLICABLE_ADAPTERS}
)


def test_all_registered_adapters_declare_capability():
    """Every registered adapter must have a driver_isolation_capability (own or inherited).

    Adapters that inherit from a parent with an explicit declaration (e.g.
    PgDuckDBAdapter → PostgreSQLAdapter) are valid - the capability propagates
    through MRO.  Only adapters whose MRO chain never sets the attribute beyond
    the base PlatformAdapter default are flagged.
    """
    from benchbox.core.platform_registry import PlatformRegistry

    missing = []
    for platform_name in PlatformRegistry.get_available_platforms():
        try:
            adapter_cls = PlatformRegistry.get_adapter_class(platform_name)
        except (ValueError, ImportError):
            continue
        # Walk the MRO (skip PlatformAdapter and object) to find an explicit declaration.
        has_explicit = any(
            "driver_isolation_capability" in vars(cls)
            for cls in type.mro(adapter_cls)
            if cls.__name__ not in ("PlatformAdapter", "object")
        )
        if not has_explicit:
            missing.append(f"{platform_name} ({adapter_cls.__name__})")

    assert not missing, (
        f"Adapters missing driver_isolation_capability declaration (own or inherited): "
        f"{', '.join(missing)}. See docs/development/adding-new-platforms.md for guidance."
    )
