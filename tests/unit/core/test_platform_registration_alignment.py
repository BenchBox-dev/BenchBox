"""Tests for platform registration alignment between systems.

This test module ensures that the two platform registration systems stay synchronized:
1. get_platform_adapter() in benchbox/platforms/__init__.py - CLI adapter factory
2. PlatformRegistry in benchbox/core/platform_registry.py - metadata and discovery

These tests prevent drift between the systems that has caused bugs in the past
where platforms were added to one system but not the other.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import pytest

from benchbox.core.platform_registry import PlatformRegistry

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


# Define canonical platform names and their aliases
# This is the source of truth for what platforms should exist
CANONICAL_SQL_PLATFORMS = {
    "duckdb",
    "motherduck",
    "sqlite",
    "datafusion",
    "clickhouse",
    "clickhouse-local",  # First-class embedded chDB platform
    "clickhouse-server",  # First-class self-hosted ClickHouse platform
    "clickhouse-cloud",  # First-class ClickHouse Cloud platform (refactored from clickhouse:cloud)
    "databricks",
    "bigquery",
    "redshift",
    "snowflake",
    "trino",
    "starburst",
    "athena",
    "spark",
    "pyspark",
    "firebolt",
    "presto",
    "postgresql",
    "synapse",
    "fabric_dw",
    "influxdb",
    "starrocks",
    "doris",
    "databend",
    "questdb",
    "lakesail",
    "velox",
    "fabric-lakehouse",
}
# Note: polars was removed from CANONICAL_SQL_PLATFORMS as SQL mode is no longer supported

# Aliases that map to canonical names (alias -> canonical)
PLATFORM_ALIASES = {
    "sqlite3": "sqlite",
    "azure_synapse": "synapse",
}

# DataFrame-only platforms that should NOT be in get_platform_adapter()
# These platforms only support DataFrame execution mode, not SQL
DATAFRAME_ONLY_PLATFORMS = {
    "pandas",
    "modin",
    "cudf",
    "dask",
}

# Platforms that have adapters but don't support SQL mode
# These have adapters for data loading only, SQL execution will raise NotImplementedError
HYBRID_DATAFRAME_PLATFORMS = {
    "polars",  # SQL mode removed due to TPC benchmark incompatibility
}

# Platforms registered in PlatformRegistry but not yet implemented in get_platform_adapter()
# These platforms use remote job submission (Livy API, Connect API, etc.) rather than
# direct SQL adapters. They're excluded from the adapter mapping test.
PLATFORMS_NOT_YET_IN_ADAPTER_MAPPING = {
    # Cloud Spark DataFrame platforms (submit via Livy/Connect)
    "databricks-df",
    "fabric-spark",
    "synapse-spark",
    "athena-spark",
    "glue",
    "emr-serverless",
    "dataproc",
    "dataproc-serverless",
    "snowpark-connect",
    # Onehouse Quanton - managed serverless Spark (submit via Onehouse API)
    "quanton",
    # PostgreSQL extensions - use postgresql adapter with extension-specific tuning
    "timescaledb",
    "pg-duckdb",
    "pg-mooncake",
    # Newly added - adapter class exists but not yet wired into platform_mapping
    "cedardb",
    "singlestore",
}


class TestPlatformRegistrationAlignment:
    """Tests ensuring platform registration systems stay synchronized."""

    def setup_method(self):
        """Clear registry cache before each test."""
        PlatformRegistry.clear_cache()

    def _get_platform_adapter_mapping(self) -> dict:
        """Extract the platform_mapping dict from get_platform_adapter().

        This uses the same logic as the function to get the mapping.
        """
        # Import adapters the same way get_platform_adapter does
        from benchbox.platforms import (
            AthenaAdapter,
            AzureSynapseAdapter,
            BigQueryAdapter,
            ClickHouseAdapter,
            ClickHouseCloudAdapter,
            ClickHouseLocalAdapter,
            ClickHouseServerAdapter,
            DatabricksAdapter,
            DataFusionAdapter,
            DuckDBAdapter,
            FabricLakehouseAdapter,
            FabricWarehouseAdapter,
            FireboltAdapter,
            InfluxDBAdapter,
            MotherDuckAdapter,
            PolarsAdapter,
            PostgreSQLAdapter,
            PrestoAdapter,
            PySparkSQLAdapter,
            RedshiftAdapter,
            SnowflakeAdapter,
            SparkAdapter,
            SQLiteAdapter,
            TrinoAdapter,
        )
        from benchbox.platforms.databend import DatabendAdapter
        from benchbox.platforms.doris import DorisAdapter
        from benchbox.platforms.lakesail import LakeSailAdapter
        from benchbox.platforms.questdb import QuestDBAdapter
        from benchbox.platforms.starburst import StarburstAdapter
        from benchbox.platforms.starrocks import StarRocksAdapter
        from benchbox.platforms.velox import VeloxAdapter

        return {
            "duckdb": DuckDBAdapter,
            "motherduck": MotherDuckAdapter,
            "sqlite": SQLiteAdapter,
            "sqlite3": SQLiteAdapter,
            "datafusion": DataFusionAdapter,
            "polars": PolarsAdapter,
            "clickhouse": ClickHouseAdapter,
            "clickhouse-local": ClickHouseLocalAdapter,
            "clickhouse-server": ClickHouseServerAdapter,
            "clickhouse-cloud": ClickHouseCloudAdapter,
            "databricks": DatabricksAdapter,
            "bigquery": BigQueryAdapter,
            "redshift": RedshiftAdapter,
            "snowflake": SnowflakeAdapter,
            "trino": TrinoAdapter,
            "starburst": StarburstAdapter,
            "athena": AthenaAdapter,
            "spark": SparkAdapter,
            "pyspark": PySparkSQLAdapter,
            "firebolt": FireboltAdapter,
            "presto": PrestoAdapter,
            "postgresql": PostgreSQLAdapter,
            "synapse": AzureSynapseAdapter,
            "azure_synapse": AzureSynapseAdapter,
            "fabric_dw": FabricWarehouseAdapter,
            "fabric-lakehouse": FabricLakehouseAdapter,
            "influxdb": InfluxDBAdapter,
            "starrocks": StarRocksAdapter,
            "doris": DorisAdapter,
            "databend": DatabendAdapter,
            "questdb": QuestDBAdapter,
            "lakesail": LakeSailAdapter,
            "velox": VeloxAdapter,
        }

    def test_all_canonical_platforms_in_registry_metadata(self):
        """All canonical SQL platforms must have metadata in PlatformRegistry."""
        metadata = PlatformRegistry.get_all_platform_metadata()

        missing = CANONICAL_SQL_PLATFORMS - set(metadata.keys())
        assert not missing, f"Platforms missing from PlatformRegistry metadata: {missing}"

    def test_all_canonical_platforms_registered_in_registry(self):
        """All canonical SQL platforms must be registered in PlatformRegistry._adapters."""
        registered = set(PlatformRegistry.get_available_platforms())

        missing = CANONICAL_SQL_PLATFORMS - registered
        assert not missing, (
            f"Platforms missing from PlatformRegistry._adapters: {missing}. "
            "Add registration in auto_register_platforms()."
        )

    def test_all_canonical_platforms_in_adapter_mapping(self):
        """All canonical SQL platforms must be in get_platform_adapter() mapping."""
        mapping = self._get_platform_adapter_mapping()
        mapping_platforms = {k for k in mapping.keys() if k not in PLATFORM_ALIASES}

        missing = CANONICAL_SQL_PLATFORMS - mapping_platforms
        assert not missing, (
            f"Platforms missing from get_platform_adapter() mapping: {missing}. Add entry in platform_mapping dict."
        )

    def test_adapter_mapping_platforms_exist_in_registry(self):
        """All platforms in get_platform_adapter() must exist in PlatformRegistry."""
        mapping = self._get_platform_adapter_mapping()
        registered = set(PlatformRegistry.get_available_platforms())

        # Get canonical names from mapping (resolve aliases)
        mapping_canonical = set()
        for name in mapping.keys():
            if name in PLATFORM_ALIASES:
                mapping_canonical.add(PLATFORM_ALIASES[name])
            else:
                mapping_canonical.add(name)

        missing = mapping_canonical - registered
        assert not missing, (
            f"Platforms in get_platform_adapter() but not in PlatformRegistry: {missing}. "
            "Add registration in auto_register_platforms()."
        )

    def test_registry_platforms_exist_in_adapter_mapping(self):
        """All registered SQL platforms in PlatformRegistry must be in get_platform_adapter()."""
        mapping = self._get_platform_adapter_mapping()
        registered = set(PlatformRegistry.get_available_platforms())

        # Exclude DataFrame-only platforms and platforms not yet implemented
        excluded = DATAFRAME_ONLY_PLATFORMS | PLATFORMS_NOT_YET_IN_ADAPTER_MAPPING
        sql_registered = registered - excluded

        mapping_canonical = set()
        for name in mapping.keys():
            if name in PLATFORM_ALIASES:
                mapping_canonical.add(PLATFORM_ALIASES[name])
            else:
                mapping_canonical.add(name)

        missing = sql_registered - mapping_canonical
        assert not missing, (
            f"Platforms in PlatformRegistry but not in get_platform_adapter(): {missing}. "
            "Add entry in platform_mapping dict or add to PLATFORMS_NOT_YET_IN_ADAPTER_MAPPING."
        )

    def test_dataframe_only_platforms_not_in_adapter_mapping(self):
        """DataFrame-only platforms should NOT be in get_platform_adapter()."""
        mapping = self._get_platform_adapter_mapping()

        wrongly_included = DATAFRAME_ONLY_PLATFORMS & set(mapping.keys())
        assert not wrongly_included, (
            f"DataFrame-only platforms should not be in get_platform_adapter(): {wrongly_included}. "
            "These platforms don't support SQL mode and should only be accessed via get_dataframe_adapter()."
        )

    def test_aliases_resolve_to_canonical_names(self):
        """All defined aliases must resolve to valid canonical platforms."""
        for alias, canonical in PLATFORM_ALIASES.items():
            assert canonical in CANONICAL_SQL_PLATFORMS, (
                f"Alias '{alias}' points to '{canonical}' which is not a canonical platform"
            )

    def test_alias_targets_have_same_adapter_class(self):
        """Aliases must map to the same adapter class as their canonical name."""
        mapping = self._get_platform_adapter_mapping()

        for alias, canonical in PLATFORM_ALIASES.items():
            if alias in mapping and canonical in mapping:
                assert mapping[alias] is mapping[canonical], (
                    f"Alias '{alias}' maps to different adapter than canonical '{canonical}'"
                )


class TestPlatformRequirementsAlignment:
    """Tests ensuring platform requirements are consistent between systems."""

    def setup_method(self):
        """Clear registry cache before each test."""
        PlatformRegistry.clear_cache()

    def test_all_platforms_have_metadata_requirements(self):
        """All canonical platforms must have installation requirements in metadata."""
        metadata = PlatformRegistry.get_all_platform_metadata()

        for platform in CANONICAL_SQL_PLATFORMS:
            if platform in metadata:
                spec = metadata[platform]
                assert "installation_command" in spec, f"Platform '{platform}' missing installation_command in metadata"
                assert spec["installation_command"], f"Platform '{platform}' has empty installation_command"

    def test_all_platforms_have_driver_package(self):
        """All canonical platforms should have driver_package defined or be built-in."""
        metadata = PlatformRegistry.get_all_platform_metadata()

        for platform in CANONICAL_SQL_PLATFORMS:
            if platform in metadata:
                spec = metadata[platform]
                # driver_package can be None for built-in (sqlite) or platforms without drivers (polars)
                assert "driver_package" in spec, f"Platform '{platform}' missing driver_package key in metadata"


class TestPlatformCapabilitiesAlignment:
    """Tests ensuring platform capabilities are correctly defined."""

    def setup_method(self):
        """Clear registry cache before each test."""
        PlatformRegistry.clear_cache()

    def test_all_sql_platforms_support_sql_mode(self):
        """All canonical SQL platforms must have supports_sql=True."""
        for platform in CANONICAL_SQL_PLATFORMS:
            caps = PlatformRegistry.get_platform_capabilities(platform)
            assert caps is not None, f"Platform '{platform}' has no capabilities defined"
            assert caps.supports_sql, f"Platform '{platform}' is a SQL platform but supports_sql=False"

    def test_dataframe_only_platforms_dont_support_sql(self):
        """DataFrame-only platforms should have supports_sql=False."""
        for platform in DATAFRAME_ONLY_PLATFORMS:
            caps = PlatformRegistry.get_platform_capabilities(platform)
            if caps is not None:  # May not be registered if deps not installed
                assert not caps.supports_sql, f"DataFrame-only platform '{platform}' should have supports_sql=False"
                assert caps.supports_dataframe, (
                    f"DataFrame-only platform '{platform}' should have supports_dataframe=True"
                )

    def test_hybrid_dataframe_platforms_dont_support_sql(self):
        """Hybrid platforms (have adapters but no SQL) should have supports_sql=False."""
        for platform in HYBRID_DATAFRAME_PLATFORMS:
            caps = PlatformRegistry.get_platform_capabilities(platform)
            if caps is not None:
                assert not caps.supports_sql, (
                    f"Hybrid platform '{platform}' should have supports_sql=False "
                    "(adapter exists for data loading only)"
                )
                assert caps.supports_dataframe, f"Hybrid platform '{platform}' should have supports_dataframe=True"

    def test_dual_mode_platforms_support_both(self):
        """Platforms that support both modes must have both flags True."""
        dual_mode = PlatformRegistry.get_dual_mode_platforms()

        for platform in dual_mode:
            caps = PlatformRegistry.get_platform_capabilities(platform)
            assert caps.supports_sql, f"Dual-mode platform '{platform}' missing supports_sql"
            assert caps.supports_dataframe, f"Dual-mode platform '{platform}' missing supports_dataframe"

    def test_dataframe_adapter_mapping_matches_registry_capabilities(self):
        """Platforms with DataFrame adapters in adapter_factory must have supports_dataframe=True.

        This catches the bug where a DataFrame adapter exists but the registry
        declares supports_dataframe=False, causing runtime errors like:
        "Platform 'datafusion' does not support dataframe mode"
        """
        import inspect
        import re

        from benchbox.platforms.adapter_factory import _get_dataframe_adapter

        # Get the adapter mapping from adapter_factory by inspecting _get_dataframe_adapter
        # The mapping is defined inside the function, so we extract it via the source
        source = inspect.getsource(_get_dataframe_adapter)

        # Extract platform names from the adapter_mapping dict in the source
        # Looking for patterns like: "polars": (PolarsDataFrameAdapter, ...
        pattern = r'"(\w+)":\s*\('
        mapped_platforms = set(re.findall(pattern, source))

        # Each mapped platform must have supports_dataframe=True in the registry
        for platform in mapped_platforms:
            caps = PlatformRegistry.get_platform_capabilities(platform)
            assert caps is not None, (
                f"Platform '{platform}' has DataFrame adapter in adapter_factory but no capabilities in registry"
            )
            assert caps.supports_dataframe, (
                f"Platform '{platform}' has DataFrame adapter in adapter_factory "
                f"but registry declares supports_dataframe=False. "
                f"Fix: Set supports_dataframe=True in platform_registry.py metadata."
            )


class TestPlatformRegistryAliasResolution:
    """Tests for PlatformRegistry alias resolution."""

    def setup_method(self):
        """Clear registry cache before each test."""
        PlatformRegistry.clear_cache()

    def test_resolve_platform_name_canonical(self):
        """Canonical names should resolve to themselves."""
        assert PlatformRegistry.resolve_platform_name("duckdb") == "duckdb"
        assert PlatformRegistry.resolve_platform_name("sqlite") == "sqlite"
        assert PlatformRegistry.resolve_platform_name("synapse") == "synapse"

    def test_resolve_platform_name_aliases(self):
        """Aliases should resolve to canonical names."""
        assert PlatformRegistry.resolve_platform_name("sqlite3") == "sqlite"
        assert PlatformRegistry.resolve_platform_name("azure_synapse") == "synapse"

    def test_resolve_platform_name_case_insensitive(self):
        """Alias resolution should be case-insensitive."""
        assert PlatformRegistry.resolve_platform_name("SQLITE3") == "sqlite"
        assert PlatformRegistry.resolve_platform_name("SQLite3") == "sqlite"
        assert PlatformRegistry.resolve_platform_name("Azure_Synapse") == "synapse"
        assert PlatformRegistry.resolve_platform_name("AZURE_SYNAPSE") == "synapse"

    def test_resolve_platform_name_unknown(self):
        """Unknown names should return the normalized input."""
        assert PlatformRegistry.resolve_platform_name("unknown") == "unknown"
        assert PlatformRegistry.resolve_platform_name("UNKNOWN") == "unknown"

    def test_get_all_aliases(self):
        """get_all_aliases should return a copy of all aliases."""
        aliases = PlatformRegistry.get_all_aliases()
        assert isinstance(aliases, dict)
        assert "sqlite3" in aliases
        assert aliases["sqlite3"] == "sqlite"
        assert "azure_synapse" in aliases
        assert aliases["azure_synapse"] == "synapse"

    def test_get_all_aliases_returns_copy(self):
        """get_all_aliases should return a copy, not the original."""
        aliases1 = PlatformRegistry.get_all_aliases()
        aliases2 = PlatformRegistry.get_all_aliases()
        assert aliases1 == aliases2
        assert aliases1 is not aliases2
        # Modifying one shouldn't affect the other
        aliases1["test"] = "value"
        assert "test" not in aliases2

    def test_get_platform_info_with_alias(self):
        """get_platform_info should work with aliases."""
        info = PlatformRegistry.get_platform_info("sqlite3")
        assert info is not None
        assert info.name == "sqlite"  # Returns canonical name
        assert info.display_name == "SQLite"

        info = PlatformRegistry.get_platform_info("azure_synapse")
        assert info is not None
        assert info.name == "synapse"  # Returns canonical name

    def test_get_platform_capabilities_with_alias(self):
        """get_platform_capabilities should work with aliases."""
        caps = PlatformRegistry.get_platform_capabilities("sqlite3")
        assert caps is not None
        assert caps.supports_sql is True

        caps = PlatformRegistry.get_platform_capabilities("azure_synapse")
        assert caps is not None
        assert caps.supports_sql is True

    def test_get_adapter_class_with_alias(self):
        """get_adapter_class should work with aliases."""
        # This will work if sqlite adapter is registered
        try:
            adapter_class = PlatformRegistry.get_adapter_class("sqlite3")
            assert adapter_class is not None
            # Verify it's the same as getting by canonical name
            canonical_class = PlatformRegistry.get_adapter_class("sqlite")
            assert adapter_class is canonical_class
        except ValueError:
            # If adapter not registered, that's expected in some test environments
            pass


class TestMetadataConsistency:
    """Tests for metadata consistency across systems."""

    def setup_method(self):
        """Clear registry cache before each test."""
        PlatformRegistry.clear_cache()

    def test_registered_platforms_have_metadata(self):
        """All registered platforms must have corresponding metadata."""
        registered = PlatformRegistry.get_available_platforms()
        metadata = PlatformRegistry.get_all_platform_metadata()

        for platform in registered:
            assert platform in metadata, (
                f"Registered platform '{platform}' has no metadata. Add entry in _build_platform_metadata()."
            )

    def test_metadata_platforms_can_get_info(self):
        """get_platform_info() must work for all platforms with metadata."""
        metadata = PlatformRegistry.get_all_platform_metadata()

        for platform in metadata:
            info = PlatformRegistry.get_platform_info(platform)
            # May be None if not registered, but should not raise
            if info is not None:
                assert info.name == platform
                assert info.display_name == metadata[platform]["display_name"]

    def test_no_orphaned_registrations(self):
        """No platform should be registered without metadata."""
        registered = set(PlatformRegistry.get_available_platforms())
        metadata_platforms = set(PlatformRegistry.get_all_platform_metadata().keys())

        orphaned = registered - metadata_platforms
        assert not orphaned, (
            f"Platforms registered but missing metadata: {orphaned}. Add metadata in _build_platform_metadata()."
        )
