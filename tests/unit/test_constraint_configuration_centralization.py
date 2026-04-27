"""Unit tests for constraint configuration centralization.

Tests that constraint configuration is properly centralized through tuning.yaml files.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from pathlib import Path
from unittest.mock import Mock

import pytest

from benchbox.cli.config import ConfigManager

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


class TestTuningConfigurationValidation:
    """Test tuning configuration validation for constraints."""

    def setup_method(self):
        """Set up test fixtures."""
        self.config_manager = ConfigManager()

    def test_constraint_validation_explicit_specification_required(self):
        """Test that constraint settings must be explicitly specified."""
        # Create a mock configuration with None values for constraints
        mock_config = Mock()
        mock_config.primary_keys.enabled = None  # Not explicitly specified
        mock_config.foreign_keys.enabled = True
        mock_config.validate_for_platform = Mock(return_value=[])

        # Test validation should fail
        with pytest.raises(ValueError):
            self.config_manager._validate_unified_tuning_config(mock_config, "test_platform")

    def test_constraint_validation_passes_with_explicit_values(self):
        """Test that validation passes when constraint settings are explicit."""
        mock_config = Mock()
        mock_config.primary_keys.enabled = True
        mock_config.foreign_keys.enabled = False  # Explicit values
        mock_config.validate_for_platform = Mock(return_value=[])

        # Test validation should pass
        try:
            self.config_manager._validate_unified_tuning_config(mock_config, "test_platform")
        except ValueError:
            pytest.fail("Validation should pass with explicit constraint settings")


class TestExampleScriptConstraintRemoval:
    """Test that example scripts no longer accept constraint parameters."""

    def test_constraint_parameters_removed_from_examples(self):
        """Test that constraint parameters are no longer in example argument parsers."""
        # Test that key example files don't contain constraint parameters
        example_files = [
            "/Users/joe/Developer/BenchBox/examples/duckdb_tpch.py",
            "/Users/joe/Developer/BenchBox/examples/duckdb_tpcds.py",
            "/Users/joe/Developer/BenchBox/examples/databricks_tpch.py",
        ]

        for example_file in example_files:
            if Path(example_file).exists():
                with open(example_file, encoding="utf-8") as f:
                    content = f.read()

                # Check that constraint parameters are not in argument parser
                assert "--no-primary-keys" not in content, f"Found --no-primary-keys in {example_file}"
                assert "--no-foreign-keys" not in content, f"Found --no-foreign-keys in {example_file}"
                assert "--disable-all-constraints" not in content, f"Found --disable-all-constraints in {example_file}"
                assert "--disable-constraints" not in content, f"Found --disable-constraints in {example_file}"

                # Check that constraint logic is simplified
                assert "enable_primary_keys=" not in content, f"Found enable_primary_keys parameter in {example_file}"
                assert "enable_foreign_keys=" not in content, f"Found enable_foreign_keys parameter in {example_file}"


class TestTuningFileConstraintConfiguration:
    """Test that tuning files have proper constraint configuration."""

    def test_tuning_files_have_explicit_constraints(self):
        """Test that all tuning files explicitly specify constraint settings."""
        tuning_files = [
            "/Users/joe/Developer/BenchBox/examples/duckdb_tpch_tuned.yaml",
            "/Users/joe/Developer/BenchBox/examples/duckdb_tpch_notuning.yaml",
            "/Users/joe/Developer/BenchBox/examples/duckdb_tpcds_tuned.yaml",
        ]

        for tuning_file in tuning_files:
            if Path(tuning_file).exists():
                with open(tuning_file, encoding="utf-8") as f:
                    content = f.read()

                # Check that constraint settings are explicitly configured
                assert "primary_keys:" in content, f"Missing primary_keys configuration in {tuning_file}"
                assert "foreign_keys:" in content, f"Missing foreign_keys configuration in {tuning_file}"
                assert "enabled:" in content, f"Missing enabled configuration in {tuning_file}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
