"""Tests for database naming utilities with configuration characteristics.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import pytest

from benchbox.utils.database_naming import (
    _get_config_hash,
    _get_constraints_suffix,
    _get_optimizations_suffix,
    _get_tuning_mode,
    generate_database_filename,
    generate_database_name,
    list_database_configurations,
    parse_database_name,
    validate_database_name,
)

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


class TestDatabaseNameGeneration:
    """Test database name generation with configuration characteristics."""

    def test_basic_name_generation(self):
        """Test basic database name generation without tuning."""
        name = generate_database_name("tpch", 1.0, "duckdb")
        assert name == "tpch_sf1_notuning_noconstraints"

    def test_scale_factor_formatting(self):
        """Test scale factor formatting in database names."""
        # Integer scale factors
        assert "sf1" in generate_database_name("tpch", 1.0, "duckdb")
        assert "sf10" in generate_database_name("tpch", 10.0, "duckdb")

        # Decimal scale factors
        assert "sf01" in generate_database_name("tpch", 0.1, "duckdb")
        assert "sf001" in generate_database_name("tpch", 0.01, "duckdb")
        assert "sf0001" in generate_database_name("tpch", 0.001, "duckdb")

    def test_custom_name_override(self):
        """Test custom name override functionality."""
        custom_name = "my_custom_database"
        name = generate_database_name("tpch", 1.0, "duckdb", custom_name=custom_name)
        assert name == "mycustomdatabase"  # Cleaned version

    def test_tuning_config_metadata_name(self):
        """Test database name from tuning configuration metadata."""
        tuning_config = {"_metadata": {"database_name": "metadata_db_name"}}
        name = generate_database_name("tpch", 1.0, "duckdb", tuning_config=tuning_config)
        assert name == "metadatadbname"  # Cleaned version

    def test_tuning_mode_detection(self):
        """Test different tuning mode detection."""
        # No tuning configuration
        name = generate_database_name("tpch", 1.0, "duckdb")
        assert "notuning" in name

        # Empty tuning configuration
        empty_config = {}
        name = generate_database_name("tpch", 1.0, "duckdb", empty_config)
        assert "notuning" in name

        # Standard no-tuning configuration
        notuning_config = {
            "primary_keys": {"enabled": False},
            "foreign_keys": {"enabled": False},
            "platform_optimizations": {},
            "table_tunings": {},
        }
        name = generate_database_name("tpch", 1.0, "duckdb", notuning_config)
        assert "notuning" in name

        # Custom tuning configuration
        custom_config = {
            "primary_keys": {"enabled": True},
            "foreign_keys": {"enabled": False},
            "platform_optimizations": {},
            "table_tunings": {},
        }
        name = generate_database_name("tpch", 1.0, "duckdb", custom_config)
        assert "custom" in name

    def test_constraints_suffix_generation(self):
        """Test constraints suffix generation."""
        # No constraints
        config = {
            "primary_keys": {"enabled": False},
            "foreign_keys": {"enabled": False},
        }
        name = generate_database_name("tpch", 1.0, "duckdb", config)
        assert "noconstraints" in name

        # Primary keys only
        config = {"primary_keys": {"enabled": True}, "foreign_keys": {"enabled": False}}
        name = generate_database_name("tpch", 1.0, "duckdb", config)
        assert "pk" in name and "fk" not in name

        # Both primary and foreign keys
        config = {"primary_keys": {"enabled": True}, "foreign_keys": {"enabled": True}}
        name = generate_database_name("tpch", 1.0, "duckdb", config)
        assert "pk" in name and "fk" in name

    def test_optimizations_suffix_generation(self):
        """Test platform optimizations suffix generation."""
        # No optimizations
        config = {"platform_optimizations": {}, "table_tunings": {}}
        name = generate_database_name("tpch", 1.0, "duckdb", config)
        # Should not have optimization suffixes
        assert "part" not in name

        # Platform optimizations
        config = {
            "platform_optimizations": {
                "z_ordering_enabled": True,
            },
            "table_tunings": {},
        }
        name = generate_database_name("tpch", 1.0, "duckdb", config)
        assert "zorder" in name

        # Table-level optimizations
        config = {
            "platform_optimizations": {},
            "table_tunings": {
                "orders": {
                    "partitioning": [{"name": "order_date", "type": "DATE"}],
                    "sorting": [{"name": "orderkey", "type": "INTEGER"}],
                }
            },
        }
        name = generate_database_name("tpch", 1.0, "duckdb", config)
        assert "part" in name and "sort" in name

    def test_filename_generation(self):
        """Test database filename generation with extensions."""
        # DuckDB extension
        filename = generate_database_filename("tpch", 1.0, "duckdb")
        assert filename.endswith(".duckdb")
        assert filename.startswith("tpch_sf1")

        # SQLite extension (changed from .db to .sqlite)
        filename = generate_database_filename("tpch", 1.0, "sqlite")
        assert filename.endswith(".sqlite")

        # Unknown platform (gets unique extension from platform name)
        filename = generate_database_filename("tpch", 1.0, "unknown")
        assert filename.endswith(".unknown")

    def test_platform_extensions_unique(self):
        """Test that each platform gets a unique extension to prevent collisions."""
        platforms = {
            "duckdb": ".duckdb",
            "sqlite": ".sqlite",
            "sqlite3": ".sqlite",
            "clickhouse": ".chdb",
            "datafusion": ".datafusion",
            "polars": ".polars",
            "pandas": ".pandas",
            "polars-df": ".polars-df",
            "pandas-df": ".pandas-df",
            "cudf-df": ".cudf-df",
            "dask-df": ".dask-df",
            "cudf": ".cudf",
            "spark": ".spark",
        }

        for platform, expected_ext in platforms.items():
            filename = generate_database_filename("tpch", 1.0, platform)
            assert filename.endswith(expected_ext), (
                f"Platform '{platform}' should have extension '{expected_ext}', but got: {filename}"
            )

    def test_no_db_extension_collision(self):
        """Test that no platform uses .db extension (prevents SQLite collision)."""
        common_platforms = ["duckdb", "sqlite", "clickhouse", "datafusion", "polars", "pandas", "cudf", "spark"]

        for platform in common_platforms:
            filename = generate_database_filename("tpch", 1.0, platform)
            # None of the known platforms should use .db anymore
            assert not filename.endswith(".db"), f"Platform '{platform}' uses .db extension which can cause collisions"

    def test_complex_configuration_naming(self):
        """Test naming with complex configuration."""
        complex_config = {
            "primary_keys": {"enabled": True},
            "foreign_keys": {"enabled": True},
            "unique_constraints": {"enabled": True},
            "platform_optimizations": {
                "z_ordering_enabled": True,
            },
            "table_tunings": {
                "orders": {
                    "partitioning": [{"name": "order_date", "type": "DATE"}],
                    "sorting": [{"name": "orderkey", "type": "INTEGER"}],
                    "clustering": [{"name": "customer_key", "type": "INTEGER"}],
                }
            },
        }

        name = generate_database_name("tpch", 0.01, "duckdb", complex_config)

        # Should contain all expected components
        assert "tpch" in name
        assert "sf001" in name
        assert "custom" in name  # Not standard config
        assert "pk" in name and "fk" in name and "uniq" in name
        assert "zorder" in name
        assert "part" in name and "sort" in name and "clust" in name

    def test_name_length_limit(self):
        """Test name length limitations."""
        # Create a configuration that would generate a very long name
        long_config = {
            "primary_keys": {"enabled": True},
            "foreign_keys": {"enabled": True},
            "unique_constraints": {"enabled": True},
            "check_constraints": {"enabled": True},
            "platform_optimizations": {
                "z_ordering_enabled": True,
                "auto_optimize_enabled": True,
                "materialized_views_enabled": True,
            },
            "table_tunings": {
                "very_long_table_name": {
                    "partitioning": [{"name": "very_long_column_name", "type": "DATE"}],
                    "sorting": [{"name": "another_very_long_column_name", "type": "INTEGER"}],
                    "clustering": [{"name": "yet_another_very_long_column_name", "type": "INTEGER"}],
                    "distribution": [{"name": "distributed_column_name", "type": "INTEGER"}],
                }
            },
        }

        name = generate_database_name("very_long_benchmark_name", 0.001, "duckdb", long_config)

        # Should be within reasonable limits
        assert len(name) <= 63

        # Should still contain essential components
        assert "verylongbenchmarkname" in name[:30] or "sf0001" in name


class TestDatabaseNameParsing:
    """Test database name parsing functionality."""

    def test_basic_name_parsing(self):
        """Test basic database name parsing."""
        name = "tpch_sf1_notuning_noconstraints"
        parsed = parse_database_name(name)

        assert parsed["benchmark"] == "tpch"
        assert parsed["scale_factor"] == 1.0
        assert parsed["tuning_mode"] == "notuning"
        assert parsed["has_constraints"] is False
        assert parsed["has_optimizations"] is False

    def test_complex_name_parsing(self):
        """Test parsing of complex database names."""
        name = "tpch_sf001_custom_pk_fk_part_sort.duckdb"
        parsed = parse_database_name(name)

        assert parsed["benchmark"] == "tpch"
        assert parsed["scale_factor"] == 0.01
        assert parsed["tuning_mode"] == "custom"
        assert parsed["has_constraints"] is True
        assert parsed["has_optimizations"] is True
        assert "pk" in parsed["characteristics"]
        assert "fk" in parsed["characteristics"]
        assert "part" in parsed["characteristics"]
        assert "sort" in parsed["characteristics"]
        assert "bloom" not in parsed["characteristics"]

    def test_filename_parsing(self):
        """Test parsing database filenames with extensions."""
        # DuckDB file
        parsed = parse_database_name("tpch_sf1_tuned_pk.duckdb")
        assert parsed["benchmark"] == "tpch"
        assert parsed["original_name"] == "tpch_sf1_tuned_pk.duckdb"

        # SQLite file
        parsed = parse_database_name("tpcds_sf01_notuning.sqlite")
        assert parsed["benchmark"] == "tpcds"

    def test_invalid_name_parsing(self):
        """Test parsing of invalid or malformed names."""
        # Empty name
        parsed = parse_database_name("")
        assert parsed["benchmark"] == ""
        assert parsed["scale_factor"] is None

        # Single component
        parsed = parse_database_name("tpch")
        assert parsed["benchmark"] == "tpch"
        assert parsed["scale_factor"] is None


class TestDatabaseNameValidation:
    """Test database name validation."""

    def test_valid_names(self):
        """Test validation of valid database names."""
        assert validate_database_name("tpch_sf1_notuning", "duckdb") is True
        assert validate_database_name("valid_database_name_123", "duckdb") is True
        assert validate_database_name("a", "duckdb") is True

    def test_invalid_names(self):
        """Test validation of invalid database names."""
        # Empty name
        assert validate_database_name("", "duckdb") is False

        # Too long
        long_name = "a" * 70
        assert validate_database_name(long_name, "duckdb") is False

        # Invalid characters
        assert validate_database_name("invalid-name", "duckdb") is False
        assert validate_database_name("invalid name", "duckdb") is False
        assert validate_database_name("123_starts_with_number", "duckdb") is False


class TestTuningConfigurationHelpers:
    """Test tuning configuration helper functions."""

    def test_tuning_mode_detection(self):
        """Test tuning mode detection helper."""
        assert _get_tuning_mode(None) == "notuning"
        assert _get_tuning_mode({}) == "notuning"

        # Standard no-tuning
        notuning = {
            "primary_keys": {"enabled": False},
            "foreign_keys": {"enabled": False},
            "table_tunings": {},
            "platform_optimizations": {},
        }
        assert _get_tuning_mode(notuning) == "notuning"

        # Explicit metadata type
        explicit_notuning = {"_metadata": {"configuration_type": "notuning"}}
        assert _get_tuning_mode(explicit_notuning) == "notuning"

        explicit_tuned = {"_metadata": {"configuration_type": "tuned"}}
        assert _get_tuning_mode(explicit_tuned) == "tuned"

    def test_constraints_suffix_helper(self):
        """Test constraints suffix generation helper."""
        assert _get_constraints_suffix(None) == "noconstraints"
        assert _get_constraints_suffix({}) == "noconstraints"

        # Primary keys only
        pk_config = {"primary_keys": {"enabled": True}}
        assert _get_constraints_suffix(pk_config) == "pk"

        # Multiple constraints
        multi_config = {
            "primary_keys": {"enabled": True},
            "foreign_keys": {"enabled": True},
            "unique_constraints": {"enabled": True},
        }
        suffix = _get_constraints_suffix(multi_config)
        assert "pk" in suffix
        assert "fk" in suffix
        assert "uniq" in suffix

    def test_optimizations_suffix_helper(self):
        """Test optimizations suffix generation helper."""
        assert _get_optimizations_suffix(None) == ""
        assert _get_optimizations_suffix({}) == ""

        # Platform optimizations
        platform_config = {
            "platform_optimizations": {
                "z_ordering_enabled": True,
            }
        }
        suffix = _get_optimizations_suffix(platform_config)
        assert "zorder" in suffix
        assert "bloom" not in suffix

        # Table optimizations
        table_config = {
            "table_tunings": {
                "test_table": {
                    "partitioning": [{"name": "date_col"}],
                    "sorting": [{"name": "id_col"}],
                }
            }
        }
        suffix = _get_optimizations_suffix(table_config)
        assert "part" in suffix
        assert "sort" in suffix

    def test_config_hash_helper(self):
        """Test configuration hash generation helper."""
        assert _get_config_hash(None) == "000000"

        config1 = {"primary_keys": {"enabled": True}}
        config2 = {"primary_keys": {"enabled": False}}
        config3 = {"primary_keys": {"enabled": True}}

        hash1 = _get_config_hash(config1)
        hash2 = _get_config_hash(config2)
        hash3 = _get_config_hash(config3)

        # Different configs should have different hashes
        assert hash1 != hash2

        # Same configs should have same hashes
        assert hash1 == hash3

        # Hash should be 6 characters
        assert len(hash1) == 6
        assert hash1.isalnum()


class TestDatabaseConfigurationListing:
    """Test database configuration listing functionality."""

    def test_list_configurations(self):
        """Test listing and parsing multiple database configurations."""
        names = [
            "tpch_sf1_notuning_noconstraints.duckdb",
            "tpch_sf001_tuned_pk_fk_part.duckdb",
            "tpcds_sf01_custom_pk.duckdb",
        ]

        configs = list_database_configurations(names)

        assert len(configs) == 3

        # Check first configuration
        assert configs[0]["benchmark"] == "tpch"
        assert configs[0]["scale_factor"] == 1.0
        assert configs[0]["tuning_mode"] == "notuning"

        # Check second configuration
        assert configs[1]["benchmark"] == "tpch"
        assert configs[1]["scale_factor"] == 0.01
        assert configs[1]["tuning_mode"] == "tuned"
        assert configs[1]["has_constraints"] is True
        assert configs[1]["has_optimizations"] is True

        # Check third configuration
        assert configs[2]["benchmark"] == "tpcds"
        assert configs[2]["scale_factor"] == 0.1
        assert configs[2]["tuning_mode"] == "custom"


class TestDatabaseNamingIntegration:
    """Integration tests for database naming functionality."""

    def test_real_world_tpch_configurations(self):
        """Test naming with real-world TPC-H configurations."""
        # Load a real no-tuning configuration structure
        notuning_config = {
            "primary_keys": {"enabled": False, "enforce_uniqueness": False},
            "foreign_keys": {"enabled": False, "enforce_referential_integrity": False},
            "unique_constraints": {"enabled": False},
            "check_constraints": {"enabled": False},
            "platform_optimizations": {
                "z_ordering_enabled": False,
                "auto_optimize_enabled": False,
                "bloom_filters_enabled": False,
                "materialized_views_enabled": False,
            },
            "table_tunings": {},
            "_metadata": {
                "version": "2.0",
                "format": "unified_tuning",
                "database": "duckdb",
                "benchmark": "tpch",
                "configuration_type": "notuning",
            },
        }

        name = generate_database_name("tpch", 0.01, "duckdb", notuning_config)
        assert "tpch" in name
        assert "sf001" in name
        assert "notuning" in name
        assert "noconstraints" in name

        # Parse it back
        parsed = parse_database_name(name)
        assert parsed["benchmark"] == "tpch"
        assert parsed["scale_factor"] == 0.01
        assert parsed["tuning_mode"] == "notuning"

    def test_tuned_configuration_naming(self):
        """Test naming with a tuned configuration."""
        tuned_config = {
            "primary_keys": {"enabled": False},
            "foreign_keys": {"enabled": False},
            "table_tunings": {
                "orders": {
                    "table_name": "orders",
                    "partitioning": [{"name": "order_date", "type": "DATE", "order": 1}],
                },
                "lineitem": {
                    "table_name": "lineitem",
                    "partitioning": [{"name": "shipdate", "type": "DATE", "order": 1}],
                    "sorting": [
                        {"name": "orderkey", "type": "INTEGER", "order": 1},
                        {"name": "linenumber", "type": "INTEGER", "order": 2},
                    ],
                },
            },
            "_metadata": {"version": "2.0", "format": "unified_tuning"},
        }

        name = generate_database_name("tpch", 1.0, "duckdb", tuned_config)
        assert "tpch" in name
        assert "sf1" in name
        assert "custom" in name  # Has table tunings but not standard tuned config
        assert "noconstraints" in name
        assert "part" in name  # Has partitioning
        assert "sort" in name  # Has sorting
