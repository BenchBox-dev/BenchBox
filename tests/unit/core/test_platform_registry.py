"""Tests for core platform registry functionality.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from benchbox.core.platform_registry import SUPPORT_STATUS_VALUES, PlatformRegistry
from benchbox.core.schemas import LibraryInfo

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]

KNOWN_PAID_PLATFORM_COST_CLASSES = {
    "athena": "paid_credits",
    "athena-spark": "paid_compute",
    "bigquery": "paid_credits",
    "clickhouse-cloud": "paid_compute",
    "databend": "paid_compute",
    "databricks": "paid_credits",
    "databricks-df": "paid_credits",
    "dataproc": "paid_compute",
    "dataproc-serverless": "paid_compute",
    "emr-serverless": "paid_compute",
    "fabric-lakehouse": "paid_compute",
    "fabric-spark": "paid_compute",
    "fabric_dw": "paid_compute",
    "firebolt": "paid_compute",
    "glue": "paid_compute",
    "motherduck": "paid_credits",
    "pg-duckdb": "paid_credits",
    "quanton": "paid_compute",
    "redshift": "paid_compute",
    "singlestore": "paid_compute",
    "snowflake": "paid_credits",
    "snowpark-connect": "paid_credits",
    "starburst": "paid_compute",
    "synapse": "paid_compute",
    "synapse-spark": "paid_compute",
}


class TestPlatformRegistry:
    """Test core PlatformRegistry functionality."""

    def setup_method(self):
        """Clear registry cache before each test."""
        PlatformRegistry.clear_cache()

    def test_get_all_platform_metadata(self):
        """Test getting all platform metadata."""
        metadata = PlatformRegistry.get_all_platform_metadata()

        assert isinstance(metadata, dict)

        # Check that base platforms are present
        # All platforms are now included if their dependencies can be imported
        base_platforms = {"duckdb", "sqlite"}
        assert base_platforms.issubset(set(metadata.keys()))

        # Check structure of one platform
        duckdb_spec = metadata["duckdb"]
        required_keys = [
            "display_name",
            "description",
            "category",
            "libraries",
            "requirements",
            "installation_command",
            "adoption",
            "supports",
        ]
        for key in required_keys:
            assert key in duckdb_spec, f"Missing required key: {key}"

        assert duckdb_spec["support_status"] == "stable"
        assert duckdb_spec["display_name"] == "DuckDB"
        assert duckdb_spec["category"] == "analytical"
        assert duckdb_spec["adoption"] == "mainstream"
        assert isinstance(duckdb_spec["libraries"], list)
        assert len(duckdb_spec["libraries"]) > 0

    def test_get_all_platform_metadata_returns_copy(self):
        """Test that get_all_platform_metadata returns a copy."""
        metadata1 = PlatformRegistry.get_all_platform_metadata()
        metadata2 = PlatformRegistry.get_all_platform_metadata()

        # Should be equal but not the same object
        assert metadata1 == metadata2
        assert metadata1 is not metadata2

        # Modifying one shouldn't affect the other
        metadata1["test"] = "modified"
        assert "test" not in metadata2

    @patch("benchbox.core.platform_registry.importlib.import_module")
    def test_detect_library_success(self, mock_import):
        """Test successful library detection."""
        mock_module = Mock()
        mock_module.__version__ = "1.2.3"
        mock_import.return_value = mock_module

        lib_spec = {"name": "test_lib", "required": True}
        lib_info = PlatformRegistry.detect_library(lib_spec)

        assert isinstance(lib_info, LibraryInfo)
        assert lib_info.name == "test_lib"
        assert lib_info.version == "1.2.3"
        assert lib_info.installed is True
        assert lib_info.import_error is None

    @patch("benchbox.core.platform_registry.importlib.import_module")
    def test_detect_library_failure(self, mock_import):
        """Test library detection failure."""
        mock_import.side_effect = ImportError("No module named 'missing_lib'")

        lib_spec = {"name": "missing_lib", "required": True}
        lib_info = PlatformRegistry.detect_library(lib_spec)

        assert isinstance(lib_info, LibraryInfo)
        assert lib_info.name == "missing_lib"
        assert lib_info.version is None
        assert lib_info.installed is False
        assert "No module named" in lib_info.import_error

    @patch("benchbox.core.platform_registry.importlib.import_module")
    def test_detect_library_with_import_name(self, mock_import):
        """Test library detection with custom import name."""
        mock_module = Mock()
        mock_module.__version__ = "2.0.0"
        mock_import.return_value = mock_module

        lib_spec = {"name": "psycopg", "import_name": "psycopg", "required": True}
        lib_info = PlatformRegistry.detect_library(lib_spec)

        mock_import.assert_called_once_with("psycopg")
        assert lib_info.name == "psycopg"
        assert lib_info.version == "2.0.0"
        assert lib_info.installed is True

    @patch("benchbox.core.platform_registry.importlib.import_module")
    def test_detect_library_no_version(self, mock_import):
        """Test library detection when module has no __version__."""
        mock_module = Mock()
        del mock_module.__version__  # Remove __version__ attribute
        mock_import.return_value = mock_module

        lib_spec = {"name": "sqlite3", "required": True}
        lib_info = PlatformRegistry.detect_library(lib_spec)

        assert lib_info.name == "sqlite3"
        assert lib_info.version is None
        assert lib_info.installed is True
        assert lib_info.import_error is None

    def test_platform_boundary_separation(self):
        """Test that platform boundaries are properly separated."""
        # The CLI should only access public methods, not private ones
        metadata = PlatformRegistry.get_all_platform_metadata()

        # Ensure the metadata contains all the information CLI needs
        for _platform_name, platform_spec in metadata.items():
            # Check that each platform has the required fields
            assert "display_name" in platform_spec
            assert "description" in platform_spec
            assert "category" in platform_spec
            assert "libraries" in platform_spec
            assert "requirements" in platform_spec
            assert "installation_command" in platform_spec
            assert "adoption" in platform_spec
            assert "supports" in platform_spec
            assert "support_status" in platform_spec

            # Check library specifications have required fields
            for lib_spec in platform_spec["libraries"]:
                assert "name" in lib_spec
                assert "required" in lib_spec

    def test_metadata_consistency_with_get_platform_info(self):
        """Test that get_all_platform_metadata is consistent with get_platform_info."""
        metadata = PlatformRegistry.get_all_platform_metadata()

        for platform_name in metadata:
            # get_platform_info should work for all platforms in metadata
            platform_info = PlatformRegistry.get_platform_info(platform_name)

            # If the platform is in our metadata, get_platform_info should return something
            # (it may be None if adapters aren't registered, but at least it shouldn't crash)
            if platform_info:
                assert platform_info.name == platform_name
                assert platform_info.display_name == metadata[platform_name]["display_name"]
                assert platform_info.description == metadata[platform_name]["description"]
                assert platform_info.category == metadata[platform_name]["category"]

    def test_platform_categories(self):
        """Test that platforms are properly categorized."""
        metadata = PlatformRegistry.get_all_platform_metadata()

        # Verify base platforms are correctly categorized
        base_categories = {
            "duckdb": "analytical",
            "sqlite": "embedded",
        }

        for platform_name, expected_category in base_categories.items():
            assert metadata[platform_name]["category"] == expected_category

    def test_adoption_tiers(self):
        """Test that adoption tiers are properly assigned."""
        metadata = PlatformRegistry.get_all_platform_metadata()

        expected_tiers = {
            "mainstream": {"duckdb", "snowflake", "bigquery", "databricks", "spark"},
            "established": {
                "clickhouse",
                "redshift",
                "trino",
                "synapse",
                "athena",
                "polars",
                "postgresql",
                "pyspark",
            },
            "emerging": {"datafusion", "motherduck", "firebolt", "starburst", "pandas"},
            "niche": {
                "sqlite",
                "presto",
                "timescaledb",
                "influxdb",
                "modin",
                "cudf",
                "dask",
                "fabric_dw",
                "glue",
                "emr-serverless",
                "athena-spark",
                "dataproc",
                "dataproc-serverless",
                "fabric-spark",
                "synapse-spark",
                "snowpark-connect",
                "databricks-df",
            },
        }

        valid_tiers = {"mainstream", "established", "emerging", "niche"}

        for platform_name, platform_spec in metadata.items():
            tier = platform_spec.get("adoption", "niche")
            assert tier in valid_tiers, f"{platform_name} has invalid adoption tier: {tier}"

        for tier, platforms in expected_tiers.items():
            for platform_name in platforms:
                if platform_name in metadata:
                    assert metadata[platform_name]["adoption"] == tier, (
                        f"{platform_name} should be '{tier}', got '{metadata[platform_name]['adoption']}'"
                    )

    def test_library_requirements_format(self):
        """Test that library requirements are properly formatted."""
        metadata = PlatformRegistry.get_all_platform_metadata()

        for platform_name, platform_spec in metadata.items():
            libraries = platform_spec["libraries"]
            assert isinstance(libraries, list)
            assert len(libraries) > 0, f"{platform_name} should have at least one library"

            for lib_spec in libraries:
                assert isinstance(lib_spec, dict)
                assert "name" in lib_spec
                assert "required" in lib_spec
                assert isinstance(lib_spec["required"], bool)

                # If import_name is specified, it should be different from name or have a good reason
                if "import_name" in lib_spec:
                    assert isinstance(lib_spec["import_name"], str)

    def test_installation_commands_exist(self):
        """Test that all platforms have installation commands."""
        metadata = PlatformRegistry.get_all_platform_metadata()

        for platform_name, platform_spec in metadata.items():
            install_cmd = platform_spec["installation_command"]
            assert isinstance(install_cmd, str)
            assert len(install_cmd) > 0, f"{platform_name} should have installation command"

            # Most should be uv add commands or built-in, but pip is allowed for special cases (e.g., cudf)
            assert (
                install_cmd.startswith("uv add")
                or install_cmd.startswith("pip install")
                or install_cmd == "Built-in Python library"
            ), f"Unexpected install command for {platform_name}: {install_cmd}"

    def test_pyspark_dual_mode_metadata(self):
        """Ensure PySpark advertises dual SQL/DataFrame capabilities."""
        metadata = PlatformRegistry.get_all_platform_metadata()
        pyspark_spec = metadata["pyspark"]

        assert pyspark_spec["capabilities"]["default_mode"] == "dataframe"
        assert pyspark_spec["capabilities"]["supports_sql"] is True
        assert pyspark_spec["capabilities"]["supports_dataframe"] is True

        caps = PlatformRegistry.get_platform_capabilities("pyspark")
        assert caps.supports_sql
        assert caps.supports_dataframe
        assert caps.default_mode == "dataframe"

    def test_known_paid_platforms_expose_cost_class(self):
        """Prompt safety gates rely on the coarse paid/free registry tag."""
        for platform_name, expected_cost_class in KNOWN_PAID_PLATFORM_COST_CLASSES.items():
            caps = PlatformRegistry.get_platform_capabilities(platform_name)
            assert caps is not None
            assert caps.cost_class == expected_cost_class

        assert PlatformRegistry.get_platform_capabilities("duckdb").cost_class == "free"
        assert PlatformRegistry.get_platform_capabilities("datafusion").cost_class == "free"
        assert PlatformRegistry.get_platform_capabilities("postgresql").cost_class == "free"
        assert PlatformRegistry.get_platform_capabilities("sqlite").cost_class == "free"

    def test_all_platforms_have_exactly_one_valid_support_status(self):
        """Every platform metadata entry must carry the accepted support taxonomy."""
        metadata = PlatformRegistry.get_all_platform_metadata()
        valid = set(SUPPORT_STATUS_VALUES)

        assert len(metadata) == 50
        for platform_name, platform_spec in metadata.items():
            assert set(platform_spec.keys()).intersection({"support_status"}) == {"support_status"}
            assert platform_spec["support_status"] in valid, f"{platform_name} has invalid support_status"

        summary = PlatformRegistry.get_platform_count_summary()
        assert sum(summary["support_status"].values()) == len(metadata)
        assert summary["support_status"] == {
            "stable": 5,
            "beta": 27,
            "experimental": 17,
            "repo_only": 0,
            "deprecated": 1,
            "document_only": 0,
        }

    def test_support_status_is_distinct_from_dependency_availability(self):
        """Support status is a product promise, not local optional dependency state."""
        metadata = PlatformRegistry.get_all_platform_metadata()

        assert metadata["snowflake"]["support_status"] == "beta"
        availability = PlatformRegistry.get_platform_availability()
        if "snowflake" in availability:
            assert isinstance(availability["snowflake"], bool)

    def test_platform_support_status_filtering(self):
        assert PlatformRegistry.get_platform_support_status("fabric-dw") == "beta"
        assert "clickhouse" in PlatformRegistry.get_platforms_by_support_status("deprecated")

        with pytest.raises(ValueError, match="Unknown support_status"):
            PlatformRegistry.get_platforms_by_support_status("unknown")  # type: ignore[arg-type]

    @patch("benchbox.core.platform_registry.importlib.import_module")
    def test_optional_adapter_diagnostics_available(self, mock_import):
        """Diagnostics report available adapters without registering them."""
        adapter_cls = object()
        mock_import.return_value = SimpleNamespace(SnowflakeAdapter=adapter_cls)

        diagnostics = PlatformRegistry.diagnose_optional_adapter_imports(["snowflake"])

        assert diagnostics["snowflake"]["status"] == "available"
        assert diagnostics["snowflake"]["available"] is True
        assert diagnostics["snowflake"]["support_status"] == "beta"
        mock_import.assert_called_once_with("benchbox.platforms.snowflake")

    @patch("benchbox.core.platform_registry.importlib.import_module")
    def test_optional_adapter_diagnostics_missing_dependency(self, mock_import):
        mock_import.side_effect = ModuleNotFoundError("No module named 'snowflake.connector'")

        diagnostics = PlatformRegistry.diagnose_optional_adapter_imports(["snowflake"])

        assert diagnostics["snowflake"]["status"] == "missing_optional_dependency"
        assert diagnostics["snowflake"]["available"] is False
        assert diagnostics["snowflake"]["error_type"] == "ModuleNotFoundError"

    @patch("benchbox.core.platform_registry.importlib.import_module")
    def test_optional_adapter_diagnostics_native_load_failure(self, mock_import):
        mock_import.side_effect = OSError("dlopen(libarrow.dylib): image not found")

        diagnostics = PlatformRegistry.diagnose_optional_adapter_imports(["datafusion"])

        assert diagnostics["datafusion"]["status"] == "native_library_load_failure"
        assert diagnostics["datafusion"]["error_type"] == "OSError"

    @patch("benchbox.core.platform_registry.importlib.import_module")
    def test_optional_adapter_diagnostics_broken_adapter_import(self, mock_import):
        mock_import.return_value = SimpleNamespace()

        diagnostics = PlatformRegistry.diagnose_optional_adapter_imports(["snowflake"])

        assert diagnostics["snowflake"]["status"] == "broken_adapter_import"
        assert "SnowflakeAdapter" in diagnostics["snowflake"]["error_message"]

    @patch("benchbox.core.platform_registry.importlib.import_module")
    def test_optional_adapter_diagnostics_deprecated_platform(self, mock_import):
        diagnostics = PlatformRegistry.diagnose_optional_adapter_imports(["clickhouse"])

        assert diagnostics["clickhouse"]["status"] == "deprecated_platform"
        assert diagnostics["clickhouse"]["support_status"] == "deprecated"
        mock_import.assert_not_called()

    def test_public_docs_platform_and_benchmark_count_markers_match_registries(self):
        """README and comparison matrix exact counts must track registry metadata."""
        from benchbox.core.benchmark_registry import get_all_benchmarks, list_public_benchmark_ids

        summary = PlatformRegistry.get_platform_count_summary()
        platform_marker = (
            f"Platform registry: **{summary['total']}** metadata entries; "
            f"**{summary['sql_capable']}** SQL-capable; "
            f"**{summary['dataframe_capable']}** DataFrame-capable; "
            f"**{summary['dual_mode']}** dual-mode; "
            f"support status counts: stable={summary['support_status']['stable']}, "
            f"beta={summary['support_status']['beta']}, "
            f"experimental={summary['support_status']['experimental']}, "
            f"deprecated={summary['support_status']['deprecated']}."
        )
        benchmark_marker = (
            f"Benchmark registry: **{len(get_all_benchmarks())}** metadata entries; "
            f"**{len(list_public_benchmark_ids())}** public discovery entries."
        )

        readme = Path("README.md").read_text(encoding="utf-8")
        comparison_matrix = Path("docs/platforms/comparison-matrix.md").read_text(encoding="utf-8")

        assert platform_marker in readme
        assert benchmark_marker in readme
        assert platform_marker in comparison_matrix

    def test_requires_cloud_storage_for_cloud_platforms(self):
        """Test that cloud platforms are correctly identified as requiring cloud storage."""
        # Cloud platforms that require cloud storage
        cloud_platforms = ["databricks", "bigquery", "snowflake", "redshift"]

        for platform_name in cloud_platforms:
            assert PlatformRegistry.requires_cloud_storage(platform_name), (
                f"{platform_name} should require cloud storage"
            )

    def test_requires_cloud_storage_for_local_platforms(self):
        """Test that local platforms do not require cloud storage."""
        # Local platforms that don't require cloud storage
        local_platforms = ["duckdb", "sqlite", "clickhouse"]

        for platform_name in local_platforms:
            assert not PlatformRegistry.requires_cloud_storage(platform_name), (
                f"{platform_name} should not require cloud storage"
            )

    def test_requires_cloud_storage_case_insensitive(self):
        """Test that requires_cloud_storage is case-insensitive."""
        assert PlatformRegistry.requires_cloud_storage("databricks")
        assert PlatformRegistry.requires_cloud_storage("Databricks")
        assert PlatformRegistry.requires_cloud_storage("DATABRICKS")

    def test_requires_cloud_storage_unknown_platform(self):
        """Test that unknown platforms return False for cloud storage requirement."""
        assert not PlatformRegistry.requires_cloud_storage("unknown_platform")
        assert not PlatformRegistry.requires_cloud_storage("nonexistent")

    def test_get_cloud_path_examples_databricks(self):
        """Test cloud path examples for Databricks."""
        examples = PlatformRegistry.get_cloud_path_examples("databricks")

        assert isinstance(examples, list)
        assert len(examples) > 0

        # Check that examples include expected patterns
        path_prefixes = [example.split("://")[0] + "://" if "://" in example else "" for example in examples]
        assert any("dbfs:" in example for example in examples), "Should include dbfs: examples"
        assert any("s3://" in prefix for prefix in path_prefixes), "Should include S3 examples"

    def test_get_cloud_path_examples_bigquery(self):
        """Test cloud path examples for BigQuery."""
        examples = PlatformRegistry.get_cloud_path_examples("bigquery")

        assert isinstance(examples, list)
        assert len(examples) > 0

        # BigQuery should only support GCS
        assert all("gs://" in example for example in examples), "BigQuery examples should all use gs://"

    def test_get_cloud_path_examples_snowflake(self):
        """Test cloud path examples for Snowflake."""
        examples = PlatformRegistry.get_cloud_path_examples("snowflake")

        assert isinstance(examples, list)
        assert len(examples) > 0

        # Snowflake supports multiple cloud providers
        path_strings = " ".join(examples)
        assert "s3://" in path_strings, "Should include S3 examples"
        assert "azure://" in path_strings or "gcs://" in path_strings, "Should include other cloud providers"

    def test_get_cloud_path_examples_redshift(self):
        """Test cloud path examples for Redshift."""
        examples = PlatformRegistry.get_cloud_path_examples("redshift")

        assert isinstance(examples, list)
        assert len(examples) > 0

        # Redshift should only support S3
        assert all("s3://" in example for example in examples), "Redshift examples should all use s3://"

    def test_get_cloud_path_examples_case_insensitive(self):
        """Test that get_cloud_path_examples is case-insensitive."""
        examples_lower = PlatformRegistry.get_cloud_path_examples("databricks")
        examples_upper = PlatformRegistry.get_cloud_path_examples("DATABRICKS")
        examples_mixed = PlatformRegistry.get_cloud_path_examples("Databricks")

        assert examples_lower == examples_upper
        assert examples_lower == examples_mixed

    def test_get_cloud_path_examples_local_platform(self):
        """Test that local platforms return empty list for cloud path examples."""
        assert PlatformRegistry.get_cloud_path_examples("duckdb") == []
        assert PlatformRegistry.get_cloud_path_examples("sqlite") == []
        assert PlatformRegistry.get_cloud_path_examples("clickhouse") == []

    def test_get_cloud_path_examples_unknown_platform(self):
        """Test that unknown platforms return empty list."""
        assert PlatformRegistry.get_cloud_path_examples("unknown_platform") == []
        assert PlatformRegistry.get_cloud_path_examples("nonexistent") == []

    def test_all_expected_platforms_register_successfully(self):
        """Regression test: Ensure all expected platforms register without circular import issues.

        This test prevents regression from commit b4ab4d79 where adding
        'from ..cli.exceptions import ConfigurationError' to platform adapters
        created circular imports that prevented Snowflake, Redshift, and ClickHouse
        from registering during auto_register_platforms().

        The fix uses lazy imports to break the circular dependency.
        """
        # Expected platforms that should always register if dependencies are available
        expected_base_platforms = {"duckdb", "sqlite"}
        expected_cloud_platforms = {"databricks", "bigquery", "snowflake", "redshift", "clickhouse"}

        registered = set(PlatformRegistry.get_available_platforms())

        # Base platforms should always be registered (no optional deps)
        assert expected_base_platforms.issubset(registered), (
            f"Base platforms missing: {expected_base_platforms - registered}"
        )

        # Check each cloud platform individually with is_platform_available
        # (they may not be in get_available_platforms if deps aren't installed,
        # but they should be checked without ImportError)
        for platform in expected_cloud_platforms:
            try:
                # This should not raise ImportError due to circular imports
                is_available = PlatformRegistry.is_platform_available(platform)
                # If deps are installed, it should be available
                if is_available:
                    assert platform in registered, f"{platform} reports available but not in registered list"
            except ImportError as e:
                # If there's an ImportError, it should be about missing deps, not circular imports
                assert "circular" not in str(e).lower(), (
                    f"{platform} has circular import issue: {e}. "
                    "This likely means a top-level import was added that creates circular dependency. "
                    "Use lazy imports (import inside functions) to break the cycle."
                )


class TestPlatformRegistryBoundaries:
    """Test platform registry boundaries and CLI integration."""

    def test_cli_uses_public_methods_only(self):
        """Test that CLI should only use public methods."""
        # Import the CLI platform manager
        from benchbox.cli.platform import PlatformManager

        manager = PlatformManager()

        # These calls should work (public API)
        metadata = manager.platform_registry  # Uses get_all_platform_metadata()
        assert isinstance(metadata, dict)

        # Test detect_library through manager
        lib_spec = {"name": "test", "required": True}
        with patch("benchbox.core.platform_registry.importlib.import_module") as mock_import:
            mock_import.side_effect = ImportError("test")
            lib_info = manager._detect_library(lib_spec)  # Uses detect_library()
            assert isinstance(lib_info, LibraryInfo)
            assert not lib_info.installed

    def test_platform_metadata_completeness(self):
        """Test that platform metadata contains everything CLI needs."""
        from benchbox.cli.platform import PlatformManager

        manager = PlatformManager()
        metadata = manager.platform_registry

        # CLI should be able to get all the information it needs
        for platform_name, platform_spec in metadata.items():
            # All the fields the CLI uses should be present
            cli_required_fields = [
                "display_name",
                "description",
                "category",
                "libraries",
                "requirements",
                "installation_command",
                "adoption",
                "supports",
                "support_status",
            ]

            for field in cli_required_fields:
                assert field in platform_spec, f"Platform {platform_name} missing {field}"

            # Library specs should have what CLI needs
            for lib_spec in platform_spec["libraries"]:
                assert "name" in lib_spec
                assert "required" in lib_spec


class TestPlatformDisplayNames:
    """Verify platform display names are correct and consistent."""

    def test_all_display_names_are_non_empty(self):
        """All registered platforms must have a non-empty display_name."""
        metadata = PlatformRegistry.get_all_platform_metadata()
        empty = [k for k, v in metadata.items() if not v.get("display_name")]
        assert not empty, f"Platforms with empty display_name: {empty}"

    def test_fabric_dw_display_name_includes_microsoft(self):
        """Microsoft Fabric Warehouse display name must include 'Microsoft' prefix."""
        registry = PlatformRegistry()
        info = registry.get_platform_info("fabric_dw")
        assert info.display_name == "Microsoft Fabric Warehouse"

    def test_athena_display_name_uses_amazon_not_aws(self):
        """Amazon Athena display name must use 'Amazon', not 'AWS'."""
        registry = PlatformRegistry()
        info = registry.get_platform_info("athena")
        assert info.display_name == "Amazon Athena"
        assert not info.display_name.startswith("AWS")

    def test_dataproc_display_names_use_google_cloud(self):
        """Google Cloud Dataproc display names must use 'Google Cloud', not 'GCP'."""
        registry = PlatformRegistry()
        for key in ("dataproc", "dataproc-serverless"):
            info = registry.get_platform_info(key)
            assert "Google Cloud" in info.display_name, f"{key}: expected 'Google Cloud' in '{info.display_name}'"
            assert "GCP" not in info.display_name, f"{key}: unexpected 'GCP' in '{info.display_name}'"

    def test_synapse_display_names_include_analytics(self):
        """Azure Synapse display names must include full 'Analytics' suffix."""
        registry = PlatformRegistry()
        for key in ("synapse", "synapse-spark"):
            info = registry.get_platform_info(key)
            assert "Analytics" in info.display_name, f"{key}: expected 'Analytics' in '{info.display_name}'"

    def test_databricks_sql_display_name_disambiguates_from_dataframe(self):
        """Databricks SQL display name must be distinct from Databricks DataFrame."""
        registry = PlatformRegistry()
        sql_name = registry.get_platform_info("databricks").display_name
        df_name = registry.get_platform_info("databricks-df").display_name
        assert sql_name != df_name, "databricks and databricks-df should have different display names"
        assert "SQL" in sql_name, f"databricks display_name should contain 'SQL', got '{sql_name}'"


class TestPlatformAliases:
    """Verify platform alias resolution works for renamed CLI keys."""

    def test_fabric_dw_hyphen_alias_resolves_via_cli_normalizer(self):
        """fabric-dw (hyphen form) must resolve to fabric_dw canonical key via CLI layer."""
        from benchbox.cli.platform import normalize_platform_name

        assert normalize_platform_name("fabric-dw") == "fabric_dw"

    def test_fabric_dw_underscore_still_resolves(self):
        """Legacy fabric_dw underscore form must still resolve (backward compat)."""
        from benchbox.cli.platform import normalize_platform_name

        assert normalize_platform_name("fabric_dw") == "fabric_dw"

    def test_fabric_dw_hyphen_resolves_via_registry(self):
        """fabric-dw must resolve to a valid platform via the registry alias layer."""
        registry = PlatformRegistry()
        info = registry.get_platform_info("fabric-dw")
        assert info is not None
        assert info.display_name == "Microsoft Fabric Warehouse"

    def test_fabric_dw_and_fabric_hyphen_dw_return_same_platform(self):
        """fabric_dw and fabric-dw must return the same platform info."""
        registry = PlatformRegistry()
        info_underscore = registry.get_platform_info("fabric_dw")
        info_hyphen = registry.get_platform_info("fabric-dw")
        assert info_underscore.display_name == info_hyphen.display_name
