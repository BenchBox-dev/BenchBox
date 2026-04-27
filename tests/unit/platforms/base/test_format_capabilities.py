"""Tests for format capabilities system."""

import pytest

from benchbox.platforms.base.format_capabilities import (
    CAPABILITIES_REGISTRY,
    DELTA_CAPABILITY,
    HUDI_CAPABILITY,
    ICEBERG_CAPABILITY,
    PARQUET_CAPABILITY,
    PLATFORM_FORMAT_PREFERENCES,
    SupportLevel,
    get_format_capability,
    get_preferred_format,
    get_supported_formats,
    has_feature,
    is_format_supported,
    normalize_platform_key,
)

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


class TestSupportLevel:
    """Tests for SupportLevel enum."""

    def test_support_levels_exist(self):
        """Test that all support levels exist."""
        assert SupportLevel.NATIVE.value == "native"
        assert SupportLevel.EXTENSION.value == "extension"
        assert SupportLevel.EXPERIMENTAL.value == "experimental"
        assert SupportLevel.NOT_SUPPORTED.value == "not_supported"


class TestNormalizePlatformKey:
    """Tests for normalize_platform_key function."""

    def test_direct_match(self):
        """Test registry keys pass through unchanged."""
        assert normalize_platform_key("duckdb") == "duckdb"
        assert normalize_platform_key("datafusion") == "datafusion"
        assert normalize_platform_key("emr-serverless") == "emr-serverless"

    def test_case_insensitive(self):
        """Test case-insensitive matching for simple names."""
        assert normalize_platform_key("DuckDB") == "duckdb"
        assert normalize_platform_key("Snowflake") == "snowflake"
        assert normalize_platform_key("BigQuery") == "bigquery"
        assert normalize_platform_key("Redshift") == "redshift"
        assert normalize_platform_key("Trino") == "trino"
        assert normalize_platform_key("Presto") == "presto"
        assert normalize_platform_key("Spark") == "spark"
        assert normalize_platform_key("LakeSail") == "lakesail"

    def test_clickhouse_display_names(self):
        """Test ClickHouse display name variants normalize to the correct key."""
        assert normalize_platform_key("ClickHouse Cloud") == "clickhouse-cloud"
        assert normalize_platform_key("ClickHouse (Cloud)") == "clickhouse-cloud"
        assert normalize_platform_key("ClickHouse (Local)") == "clickhouse"

    def test_fabric_display_names(self):
        """Test Fabric display names normalize correctly."""
        assert normalize_platform_key("Fabric Lakehouse") == "fabric-lakehouse"
        assert normalize_platform_key("Fabric Warehouse") == "fabric_dw"

    def test_class_name_normalization(self):
        """Test adapter class names normalize to registry keys."""
        assert normalize_platform_key("EMRServerlessAdapter") == "emr-serverless"
        assert normalize_platform_key("DataprocAdapter") == "dataproc"
        assert normalize_platform_key("DataprocServerlessAdapter") == "dataproc-serverless"
        assert normalize_platform_key("SynapseSparkAdapter") == "synapse-spark"
        assert normalize_platform_key("FabricSparkAdapter") == "fabric-spark"
        assert normalize_platform_key("FabricLakehouseAdapter") == "fabric-lakehouse"
        assert normalize_platform_key("AthenaSparkAdapter") == "athena-spark"

    def test_unknown_platform(self):
        """Test unknown platform names pass through lowercased."""
        assert normalize_platform_key("SomeNewPlatform") == "somenewplatform"

    def test_normalization_used_by_get_supported_formats(self):
        """Test that get_supported_formats works with display names."""
        formats = get_supported_formats("ClickHouse Cloud")
        assert "parquet" in formats
        assert "iceberg" not in formats

    def test_normalization_used_by_is_format_supported(self):
        """Test that is_format_supported works with display names."""
        assert is_format_supported("ClickHouse Cloud", "parquet") is True
        assert (
            is_format_supported(
                "ClickHouse Cloud",
                "iceberg",
                table_mode="external",
                platform_config={"s3_staging_url": "s3://bucket/prefix/"},
            )
            is True
        )


class TestFormatCapabilities:
    """Tests for format capability definitions."""

    def test_parquet_capability(self):
        """Test Parquet capability definition."""
        assert PARQUET_CAPABILITY.format_name == "parquet"
        assert PARQUET_CAPABILITY.display_name == "Apache Parquet"
        assert PARQUET_CAPABILITY.file_extension == ".parquet"
        assert "predicate_pushdown" in PARQUET_CAPABILITY.features
        assert "column_pruning" in PARQUET_CAPABILITY.features

    def test_parquet_platform_support(self):
        """Test Parquet platform support."""
        assert PARQUET_CAPABILITY.supported_platforms.get("duckdb") == SupportLevel.NATIVE
        assert PARQUET_CAPABILITY.supported_platforms.get("datafusion") == SupportLevel.NATIVE
        assert PARQUET_CAPABILITY.supported_platforms.get("athena") == SupportLevel.NATIVE
        assert PARQUET_CAPABILITY.supported_platforms.get("postgresql") == SupportLevel.EXTENSION

    def test_parquet_spark_platform_support(self):
        """Test Parquet support for Spark-based platforms."""
        for platform in [
            "spark",
            "emr-serverless",
            "dataproc",
            "dataproc-serverless",
            "synapse-spark",
            "athena-spark",
            "fabric-spark",
            "fabric-lakehouse",
        ]:
            assert PARQUET_CAPABILITY.supported_platforms[platform] == SupportLevel.NATIVE, (
                f"Expected NATIVE parquet support for {platform}"
            )
        assert PARQUET_CAPABILITY.supported_platforms["fabric_dw"] == SupportLevel.NATIVE

    def test_parquet_presto_trino_support(self):
        """Test Parquet support for Presto and Trino."""
        assert PARQUET_CAPABILITY.supported_platforms["trino"] == SupportLevel.NATIVE
        assert PARQUET_CAPABILITY.supported_platforms["presto"] == SupportLevel.NATIVE

    def test_delta_capability(self):
        """Test Delta Lake capability definition."""
        assert DELTA_CAPABILITY.format_name == "delta"
        assert DELTA_CAPABILITY.display_name == "Delta Lake"
        assert "time_travel" in DELTA_CAPABILITY.features
        assert "z_order" in DELTA_CAPABILITY.features

    def test_delta_platform_support(self):
        """Test Delta Lake platform support across all registered platforms."""
        expected = {
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
            "quanton": SupportLevel.EXTENSION,
        }
        for platform, level in expected.items():
            assert DELTA_CAPABILITY.supported_platforms[platform] == level, (
                f"Expected {level} delta support for {platform}"
            )
        # synapse-spark now has native delta support via table_format parameter
        assert DELTA_CAPABILITY.supported_platforms["synapse-spark"] == SupportLevel.NATIVE
        # Platforms that require mode-aware external handling stay out of the native registry
        for platform in ["snowflake", "clickhouse", "redshift", "bigquery", "fabric-lakehouse"]:
            assert platform not in DELTA_CAPABILITY.supported_platforms, (
                f"{platform} should not be registered in native capabilities"
            )
        # LakeSail adapter only supports parquet/orc - not registered for delta
        assert "lakesail" not in DELTA_CAPABILITY.supported_platforms

    def test_iceberg_capability(self):
        """Test Iceberg capability definition."""
        assert ICEBERG_CAPABILITY.format_name == "iceberg"
        assert ICEBERG_CAPABILITY.display_name == "Apache Iceberg"
        assert "partition_evolution" in ICEBERG_CAPABILITY.features
        assert "hidden_partitioning" in ICEBERG_CAPABILITY.features

    def test_iceberg_platform_support(self):
        """Test Iceberg platform support across all registered platforms."""
        expected = {
            "duckdb": SupportLevel.EXPERIMENTAL,
            "datafusion": SupportLevel.EXTENSION,
            "trino": SupportLevel.EXTENSION,
            "presto": SupportLevel.EXTENSION,
            "spark": SupportLevel.EXTENSION,
            "emr-serverless": SupportLevel.EXTENSION,
            "dataproc": SupportLevel.EXTENSION,
            "dataproc-serverless": SupportLevel.EXTENSION,
            "quanton": SupportLevel.NATIVE,
        }
        for platform, level in expected.items():
            assert ICEBERG_CAPABILITY.supported_platforms[platform] == level, (
                f"Expected {level} iceberg support for {platform}"
            )
        # LakeSail adapter only supports parquet/orc - not registered for iceberg
        assert "lakesail" not in ICEBERG_CAPABILITY.supported_platforms

    def test_hudi_capability(self):
        """Test Hudi capability definition."""
        assert HUDI_CAPABILITY.format_name == "hudi"
        assert HUDI_CAPABILITY.display_name == "Apache Hudi"
        assert "time_travel" in HUDI_CAPABILITY.features
        assert "compaction" in HUDI_CAPABILITY.features
        assert "copy_on_write" in HUDI_CAPABILITY.features
        assert "merge_on_read" in HUDI_CAPABILITY.features

    def test_hudi_platform_support(self):
        """Test Hudi platform support."""
        expected = {
            "spark": SupportLevel.EXTENSION,
            "quanton": SupportLevel.NATIVE,
            "emr-serverless": SupportLevel.EXTENSION,
            "dataproc": SupportLevel.EXTENSION,
            "dataproc-serverless": SupportLevel.EXTENSION,
        }
        for platform, level in expected.items():
            assert HUDI_CAPABILITY.supported_platforms[platform] == level, (
                f"Expected {level} hudi support for {platform}"
            )
        # Hudi should NOT be registered for Databricks (no adapter code)
        assert "databricks" not in HUDI_CAPABILITY.supported_platforms

    def test_hudi_in_registry(self):
        """Test Hudi is registered in CAPABILITIES_REGISTRY."""
        assert "hudi" in CAPABILITIES_REGISTRY
        assert CAPABILITIES_REGISTRY["hudi"] is HUDI_CAPABILITY

    def test_all_formats_in_registry(self):
        """Test all expected formats are in the registry."""
        expected_formats = {"parquet", "delta", "iceberg", "hudi", "vortex", "ducklake"}
        assert set(CAPABILITIES_REGISTRY.keys()) == expected_formats


class TestPlatformFormatPreferences:
    """Tests for PLATFORM_FORMAT_PREFERENCES entries."""

    def test_trino_preferences(self):
        """Test Trino prefers iceberg over delta."""
        prefs = PLATFORM_FORMAT_PREFERENCES["trino"]
        assert prefs.index("iceberg") < prefs.index("delta")
        assert prefs.index("delta") < prefs.index("parquet")

    def test_presto_preferences(self):
        """Test Presto preferences match Trino."""
        assert PLATFORM_FORMAT_PREFERENCES["presto"] == PLATFORM_FORMAT_PREFERENCES["trino"]

    def test_spark_preferences(self):
        """Test Spark prefers delta, includes hudi."""
        prefs = PLATFORM_FORMAT_PREFERENCES["spark"]
        assert prefs[0] == "delta"
        assert "hudi" in prefs
        assert "iceberg" in prefs

    def test_emr_serverless_preferences(self):
        """Test EMR Serverless includes hudi."""
        prefs = PLATFORM_FORMAT_PREFERENCES["emr-serverless"]
        assert "delta" in prefs
        assert "iceberg" in prefs
        assert "hudi" in prefs

    def test_synapse_spark_preferences(self):
        """Test Synapse Spark supports delta and iceberg via table_format parameter."""
        prefs = PLATFORM_FORMAT_PREFERENCES["synapse-spark"]
        assert prefs[0] == "delta"
        assert "iceberg" in prefs
        assert "parquet" in prefs

    def test_athena_spark_preferences(self):
        """Test Athena Spark supports delta and iceberg via table_format parameter."""
        prefs = PLATFORM_FORMAT_PREFERENCES["athena-spark"]
        assert prefs[0] == "delta"
        assert "iceberg" in prefs
        assert "parquet" in prefs

    def test_fabric_lakehouse_preferences(self):
        """Test Fabric Lakehouse prefers parquet (read-only SQL endpoint, data loaded via Spark)."""
        prefs = PLATFORM_FORMAT_PREFERENCES["fabric-lakehouse"]
        assert prefs[0] == "parquet"
        assert "delta" not in prefs

    def test_fabric_warehouse_preferences(self):
        """Test Fabric Warehouse prefers parquet and excludes lakehouse-only formats."""
        prefs = PLATFORM_FORMAT_PREFERENCES["fabric_dw"]
        assert prefs[0] == "parquet"
        assert "delta" not in prefs
        assert "iceberg" not in prefs

    def test_quanton_preferences(self):
        """Test Quanton includes iceberg, hudi, delta."""
        prefs = PLATFORM_FORMAT_PREFERENCES["quanton"]
        assert "iceberg" in prefs
        assert "hudi" in prefs
        assert "delta" in prefs

    def test_lakesail_preferences(self):
        """Test LakeSail prefers parquet (Spark-based, parquet/orc are native table formats)."""
        prefs = PLATFORM_FORMAT_PREFERENCES["lakesail"]
        assert prefs[0] == "parquet"
        assert "delta" not in prefs
        assert "iceberg" not in prefs
        assert "hudi" not in prefs

    def test_snowflake_native_preferences_exclude_delta_or_iceberg(self):
        """Test Snowflake native preferences stay conservative."""
        prefs = PLATFORM_FORMAT_PREFERENCES["snowflake"]
        assert "parquet" in prefs
        assert "delta" not in prefs
        assert "iceberg" not in prefs

    def test_bigquery_native_preferences_exclude_delta(self):
        """Test BigQuery native preferences stay conservative."""
        prefs = PLATFORM_FORMAT_PREFERENCES["bigquery"]
        assert prefs[0] == "parquet"
        assert prefs.index("tbl") < prefs.index("csv")
        assert "parquet" in prefs
        assert "delta" not in prefs

    def test_redshift_native_preferences_exclude_delta(self):
        """Test Redshift native preferences stay conservative."""
        prefs = PLATFORM_FORMAT_PREFERENCES["redshift"]
        assert prefs.index("tbl") < prefs.index("parquet")
        assert "parquet" in prefs
        assert "delta" not in prefs

    def test_clickhouse_native_preferences_exclude_delta_or_iceberg(self):
        """Test ClickHouse native preferences stay conservative."""
        prefs = PLATFORM_FORMAT_PREFERENCES["clickhouse"]
        assert "parquet" in prefs
        assert "delta" not in prefs
        assert "iceberg" not in prefs


class TestGetSupportedFormats:
    """Tests for get_supported_formats function."""

    def test_duckdb_supported_formats(self):
        """Test DuckDB supported formats."""
        formats = get_supported_formats("duckdb")
        assert "parquet" in formats
        assert "delta" in formats
        assert "tbl" in formats
        # Text files preferred over binary formats for native loading
        assert formats.index("tbl") < formats.index("parquet")

    def test_datafusion_supported_formats(self):
        """Test DataFusion supported formats."""
        formats = get_supported_formats("datafusion")
        assert "parquet" in formats
        assert "delta" in formats
        assert "iceberg" in formats
        assert "tbl" in formats

    def test_databricks_supported_formats(self):
        """Test Databricks supported formats."""
        formats = get_supported_formats("databricks")
        assert "delta" in formats
        assert "parquet" in formats
        # Delta should be preferred over Parquet for Databricks
        assert formats.index("delta") < formats.index("parquet")

    def test_trino_supported_formats(self):
        """Test Trino supported formats include delta and iceberg."""
        formats = get_supported_formats("trino")
        assert "iceberg" in formats
        assert "delta" in formats
        assert "parquet" in formats

    def test_spark_supported_formats(self):
        """Test Spark supported formats include hudi."""
        formats = get_supported_formats("spark")
        assert "delta" in formats
        assert "iceberg" in formats
        assert "hudi" in formats
        assert "parquet" in formats

    def test_quanton_supported_formats(self):
        """Test Quanton supported formats."""
        formats = get_supported_formats("quanton")
        assert "iceberg" in formats
        assert "hudi" in formats
        assert "delta" in formats

    def test_snowflake_supported_formats(self):
        """Test Snowflake native mode remains parquet-only."""
        formats = get_supported_formats("snowflake")
        assert "parquet" in formats
        assert "delta" not in formats
        assert "iceberg" not in formats

    def test_snowflake_external_supported_formats(self):
        """Test Snowflake external mode exposes Iceberg and Delta."""
        formats = get_supported_formats(
            "snowflake",
            table_mode="external",
            platform_config={
                "staging_root": "s3://bucket/prefix",
                "iceberg_external_volume": "BENCHBOX_VOL",
            },
        )
        assert formats[:3] == ["iceberg", "delta", "parquet"]

    def test_bigquery_external_supported_formats(self):
        """Test BigQuery external mode exposes Delta."""
        formats = get_supported_formats(
            "bigquery",
            table_mode="external",
            platform_config={
                "staging_root": "gs://bucket/prefix",
                "biglake_connection": "project.us.conn",
            },
        )
        assert formats[:2] == ["delta", "parquet"]

    def test_redshift_external_supported_formats(self):
        """Test Redshift external mode exposes Delta."""
        formats = get_supported_formats(
            "redshift",
            table_mode="external",
            platform_config={
                "staging_root": "s3://bucket/prefix",
                "iam_role": "arn:aws:iam::123456789012:role/benchbox",
            },
        )
        assert formats[:2] == ["delta", "parquet"]

    def test_clickhouse_cloud_external_supported_formats(self):
        """Test ClickHouse Cloud external mode exposes Iceberg without affecting local ClickHouse."""
        formats = get_supported_formats(
            "ClickHouse Cloud",
            table_mode="external",
            platform_config={"s3_staging_url": "s3://bucket/prefix/"},
        )
        assert formats[:2] == ["iceberg", "parquet"]
        assert "iceberg" not in get_supported_formats("ClickHouse (Local)", table_mode="external")

    def test_bigquery_external_without_biglake_connection_falls_back_to_parquet(self):
        """Test BigQuery external mode does not advertise Delta without BigLake connection config."""
        formats = get_supported_formats(
            "bigquery",
            table_mode="external",
            platform_config={"staging_root": "gs://bucket/prefix"},
        )
        assert formats == ["parquet", "tbl", "csv"]

    def test_snowflake_external_without_iceberg_volume_falls_back_to_delta_then_parquet(self):
        """Test Snowflake external mode does not advertise Iceberg without external volume config."""
        formats = get_supported_formats(
            "snowflake",
            table_mode="external",
            platform_config={"staging_root": "s3://bucket/prefix"},
        )
        assert formats[:2] == ["delta", "parquet"]

    def test_athena_native_supported_formats_stay_text_only(self):
        """Athena native loading only advertises text source files for staging/CTAS."""
        assert get_supported_formats("Athena") == ["tbl", "csv"]

    def test_athena_external_supported_formats_require_parquet(self):
        """Athena external mode only advertises Parquet-backed sources."""
        assert get_supported_formats("Athena", table_mode="external") == ["parquet"]

    def test_unknown_platform(self):
        """Test unknown platform returns empty list."""
        formats = get_supported_formats("unknown_platform")
        assert formats == []


class TestGetPreferredFormat:
    """Tests for get_preferred_format function."""

    def test_duckdb_preferred_format(self):
        """Test DuckDB preferred format."""
        # No available formats specified - returns most preferred (text files)
        preferred = get_preferred_format("duckdb")
        assert preferred == "tbl"

    def test_duckdb_with_available_formats(self):
        """Test DuckDB with specific available formats."""
        # When only tbl available
        preferred = get_preferred_format("duckdb", ["tbl", "csv"])
        assert preferred == "tbl"

        # When both available, text files preferred
        preferred = get_preferred_format("duckdb", ["tbl", "parquet"])
        assert preferred == "tbl"

    def test_databricks_preferred_format(self):
        """Test Databricks preferred format."""
        preferred = get_preferred_format("databricks")
        assert preferred == "delta"

    def test_athena_native_preferred_format_avoids_parquet(self):
        """Test Athena native mode keeps staged text files ahead of direct Parquet input."""
        preferred = get_preferred_format("Athena", ["parquet", "tbl"])
        assert preferred == "tbl"

    def test_athena_external_preferred_format_requires_parquet(self):
        """Test Athena external mode prefers Parquet-backed sources."""
        preferred = get_preferred_format("Athena", ["tbl", "parquet"], table_mode="external")
        assert preferred == "parquet"

    def test_snowflake_external_preferred_format(self):
        """Test Snowflake external mode prefers Iceberg."""
        preferred = get_preferred_format(
            "snowflake",
            table_mode="external",
            platform_config={
                "staging_root": "s3://bucket/prefix",
                "iceberg_external_volume": "BENCHBOX_VOL",
            },
        )
        assert preferred == "iceberg"

    def test_trino_preferred_format(self):
        """Test Trino prefers iceberg."""
        preferred = get_preferred_format("trino")
        assert preferred == "iceberg"

    def test_fallback_to_tbl(self):
        """Test fallback to most preferred when no available formats specified."""
        # When no available formats specified, returns most preferred supported format
        preferred = get_preferred_format("duckdb", [])
        assert preferred == "tbl"  # DuckDB's most preferred format (text files)

    def test_fallback_to_first_available(self):
        """Test fallback to first available format."""
        # If none of the supported formats are available
        preferred = get_preferred_format("unknown_platform", ["custom_format"])
        assert preferred == "custom_format"


class TestIsFormatSupported:
    """Tests for is_format_supported function."""

    def test_parquet_support(self):
        """Test Parquet support detection."""
        assert is_format_supported("duckdb", "parquet") is True
        assert is_format_supported("datafusion", "parquet") is True
        assert is_format_supported("unknown_platform", "parquet") is False

    def test_delta_support(self):
        """Test Delta Lake support detection."""
        assert is_format_supported("databricks", "delta") is True
        assert is_format_supported("duckdb", "delta") is True
        assert is_format_supported("datafusion", "delta") is True
        assert is_format_supported("trino", "delta") is True
        assert is_format_supported("snowflake", "delta") is False
        assert is_format_supported("bigquery", "delta") is False
        assert is_format_supported("redshift", "delta") is False
        assert (
            is_format_supported(
                "snowflake",
                "delta",
                table_mode="external",
                platform_config={"staging_root": "s3://bucket/prefix"},
            )
            is True
        )
        assert (
            is_format_supported(
                "bigquery",
                "delta",
                table_mode="external",
                platform_config={
                    "staging_root": "gs://bucket/prefix",
                    "biglake_connection": "project.us.conn",
                },
            )
            is True
        )
        assert (
            is_format_supported(
                "redshift",
                "delta",
                table_mode="external",
                platform_config={
                    "staging_root": "s3://bucket/prefix",
                    "iam_role": "arn:aws:iam::123456789012:role/benchbox",
                },
            )
            is True
        )
        assert is_format_supported("bigquery", "delta", table_mode="external") is False
        assert is_format_supported("sqlite", "delta") is False

    def test_iceberg_support(self):
        """Test Iceberg support detection."""
        assert is_format_supported("duckdb", "iceberg") is True
        assert is_format_supported("trino", "iceberg") is True
        assert is_format_supported("snowflake", "iceberg") is False
        assert is_format_supported("clickhouse", "iceberg") is False
        assert (
            is_format_supported(
                "snowflake",
                "iceberg",
                table_mode="external",
                platform_config={
                    "staging_root": "s3://bucket/prefix",
                    "iceberg_external_volume": "BENCHBOX_VOL",
                },
            )
            is True
        )
        assert is_format_supported("snowflake", "iceberg", table_mode="external") is False
        assert (
            is_format_supported(
                "ClickHouse Cloud",
                "iceberg",
                table_mode="external",
                platform_config={"s3_staging_url": "s3://bucket/prefix/"},
            )
            is True
        )
        assert is_format_supported("sqlite", "iceberg") is False
        assert is_format_supported("postgresql", "iceberg") is False

    def test_hudi_support(self):
        """Test Hudi support detection."""
        assert is_format_supported("spark", "hudi") is True
        assert is_format_supported("quanton", "hudi") is True
        assert is_format_supported("emr-serverless", "hudi") is True
        assert is_format_supported("lakesail", "hudi") is False
        assert is_format_supported("databricks", "hudi") is False
        assert is_format_supported("duckdb", "hudi") is False

    def test_legacy_formats_always_supported(self):
        """Test that legacy formats (tbl, csv) are always supported."""
        assert is_format_supported("any_platform", "tbl") is True
        assert is_format_supported("any_platform", "csv") is True
        assert is_format_supported("any_platform", "dat") is True

    def test_unknown_format(self):
        """Test unknown format returns False."""
        assert is_format_supported("duckdb", "unknown_format") is False


class TestGetFormatCapability:
    """Tests for get_format_capability function."""

    def test_get_parquet_capability(self):
        """Test getting Parquet capability."""
        cap = get_format_capability("parquet")
        assert cap is not None
        assert cap.format_name == "parquet"

    def test_get_delta_capability(self):
        """Test getting Delta capability."""
        cap = get_format_capability("delta")
        assert cap is not None
        assert cap.format_name == "delta"

    def test_get_hudi_capability(self):
        """Test getting Hudi capability."""
        cap = get_format_capability("hudi")
        assert cap is not None
        assert cap.format_name == "hudi"
        assert cap.display_name == "Apache Hudi"

    def test_get_unknown_capability(self):
        """Test getting unknown capability returns None."""
        cap = get_format_capability("unknown")
        assert cap is None


class TestHasFeature:
    """Tests for has_feature function."""

    def test_parquet_features(self):
        """Test Parquet features."""
        assert has_feature("parquet", "predicate_pushdown") is True
        assert has_feature("parquet", "column_pruning") is True
        assert has_feature("parquet", "time_travel") is False

    def test_delta_features(self):
        """Test Delta Lake features."""
        assert has_feature("delta", "time_travel") is True
        assert has_feature("delta", "z_order") is True
        assert has_feature("delta", "predicate_pushdown") is False

    def test_iceberg_features(self):
        """Test Iceberg features."""
        assert has_feature("iceberg", "partition_evolution") is True
        assert has_feature("iceberg", "time_travel") is True
        assert has_feature("iceberg", "z_order") is False

    def test_hudi_features(self):
        """Test Hudi features."""
        assert has_feature("hudi", "time_travel") is True
        assert has_feature("hudi", "compaction") is True
        assert has_feature("hudi", "copy_on_write") is True
        assert has_feature("hudi", "merge_on_read") is True
        assert has_feature("hudi", "z_order") is False

    def test_unknown_format_features(self):
        """Test unknown format has no features."""
        assert has_feature("unknown", "any_feature") is False
