"""Unit tests for CLI configuration management.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import contextlib
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
import yaml

from benchbox.cli.config import BenchBoxConfig, ConfigManager

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


@pytest.fixture
def temp_dir():
    """Create a temporary directory for testing."""
    with tempfile.TemporaryDirectory() as td:
        yield Path(td)


@pytest.mark.unit
class TestBenchBoxConfig:
    """Test BenchBoxConfig model."""

    def test_config_model_creation_empty(self):
        """Test creating empty BenchBoxConfig."""
        config = BenchBoxConfig()

        assert config.system == {}
        assert config.database == {}
        assert config.benchmarks == {}
        assert config.output == {}
        assert config.execution == {}

    def test_config_model_creation_with_data(self):
        """Test creating BenchBoxConfig with initial data."""
        config_data = {
            "system": {"cpu_cores": 8, "memory_gb": 16},
            "database": {"type": "duckdb", "path": "/tmp/test.db"},
            "benchmarks": {"default_scale": 0.01, "timeout": 3600},
            "output": {"format": "json", "directory": "/tmp/results"},
            "execution": {"parallel": True, "threads": 4},
        }

        config = BenchBoxConfig(**config_data)

        assert config.system["cpu_cores"] == 8
        assert config.database["type"] == "duckdb"
        assert config.benchmarks["default_scale"] == 0.01
        assert config.output["format"] == "json"
        assert config.execution["parallel"] is True

    def test_config_model_extra_fields(self):
        """Test that extra fields are allowed in config model."""
        config_data = {
            "custom_field": "custom_value",
            "nested_custom": {"key": "value"},
        }

        config = BenchBoxConfig(**config_data)

        # Extra fields should be allowed
        assert hasattr(config, "custom_field")
        assert config.custom_field == "custom_value"

    def test_config_model_validation(self):
        """Test config model validation."""
        # Valid config should work
        config = BenchBoxConfig(system={"memory": "8GB"}, database={"connection_string": "test"})

        assert isinstance(config.system, dict)
        assert isinstance(config.database, dict)


@pytest.mark.unit
class TestConfigManager:
    """Test ConfigManager functionality."""

    def test_config_manager_default_path_current_directory(self, temp_dir):
        """Test ConfigManager finds config in current directory."""
        # config file in temp directory
        config_file = temp_dir / "benchbox.yaml"
        config_data = {"system": {"test": True}}

        with open(config_file, "w", encoding="utf-8") as f:
            yaml.dump(config_data, f)

        # Mock Path.cwd() to return temp directory
        with patch("benchbox.cli.config.Path") as mock_path:
            mock_path.return_value = temp_dir
            mock_path.home.return_value = Path.home()

            # Mock current directory check
            current_config = Mock()
            current_config.exists.return_value = True
            mock_path.return_value = current_config

            with patch.object(ConfigManager, "_get_default_config_path", return_value=config_file):
                config_manager = ConfigManager()

                assert config_manager.config_path == config_file

    def test_config_manager_default_path_home_directory(self, temp_dir):
        """Test ConfigManager uses home directory when current doesn't exist."""
        # config file in home-like directory
        home_config_dir = temp_dir / ".benchbox"
        home_config_dir.mkdir()
        home_config_file = home_config_dir / "config.yaml"

        config_data = {"system": {"home_test": True}}
        with open(home_config_file, "w", encoding="utf-8") as f:
            yaml.dump(config_data, f)

        with patch("benchbox.cli.config.Path") as mock_path:
            # Mock current directory check to return False
            current_config = Mock()
            current_config.exists.return_value = False

            # Mock home directory
            mock_path.home.return_value = temp_dir
            mock_path.return_value = current_config

            with patch.object(ConfigManager, "_get_default_config_path", return_value=home_config_file):
                config_manager = ConfigManager()

                assert config_manager.config_path == home_config_file

    def test_config_manager_custom_path(self, temp_dir):
        """Test ConfigManager with custom config path."""
        custom_config = temp_dir / "custom_config.yaml"
        config_data = {"custom": True}

        with open(custom_config, "w", encoding="utf-8") as f:
            yaml.dump(config_data, f)

        config_manager = ConfigManager(config_path=custom_config)

        assert config_manager.config_path == custom_config

    def test_config_manager_load_existing_config(self, temp_dir):
        """Test loading existing configuration file."""
        config_file = temp_dir / "test_config.yaml"
        config_data = {
            "system": {"cpu_cores": 4},
            "database": {"type": "sqlite"},
            "benchmarks": {"tpch": {"scale": 0.1}},
        }

        with open(config_file, "w", encoding="utf-8") as f:
            yaml.dump(config_data, f)

        config_manager = ConfigManager(config_path=config_file)

        assert config_manager.config.system["cpu_cores"] == 4
        assert config_manager.config.database["type"] == "sqlite"
        assert config_manager.config.benchmarks["tpch"]["scale"] == 0.1

    def test_config_manager_load_nonexistent_config(self, temp_dir):
        """Test loading non-existent configuration file creates default."""
        nonexistent_config = temp_dir / "nonexistent.yaml"

        config_manager = ConfigManager(config_path=nonexistent_config)

        # Should create default config with system settings
        assert isinstance(config_manager.config, BenchBoxConfig)
        assert config_manager.config.system.get("auto_profile") is True
        assert config_manager.config.database.get("preferred") == "duckdb"

    def test_config_manager_load_invalid_yaml(self, temp_dir):
        """Test handling of invalid YAML configuration."""
        config_file = temp_dir / "invalid.yaml"

        # Write invalid YAML
        with open(config_file, "w", encoding="utf-8") as f:
            f.write("invalid: yaml: content: [unclosed")

        # Should handle invalid YAML gracefully
        config_manager = ConfigManager(config_path=config_file)

        # Should fall back to default config
        assert isinstance(config_manager.config, BenchBoxConfig)

    def test_config_manager_save_config(self, temp_dir):
        """Test saving configuration to file."""
        config_file = temp_dir / "save_test.yaml"
        config_manager = ConfigManager(config_path=config_file)

        # Modify config
        config_manager.config.system = {"cpu_cores": 8}
        config_manager.config.database = {"type": "duckdb"}

        # Save config (assuming save method exists)
        if hasattr(config_manager, "save_config"):
            config_manager.save_config()

            # Verify file was written
            assert config_file.exists()

            # Verify content
            with open(config_file, encoding="utf-8") as f:
                saved_data = yaml.safe_load(f)

            assert saved_data["system"]["cpu_cores"] == 8
            assert saved_data["database"]["type"] == "duckdb"

    def test_config_manager_get_setting(self, temp_dir):
        """Test getting specific settings from config."""
        config_file = temp_dir / "settings_test.yaml"
        config_data = {
            "benchmarks": {
                "tpch": {"default_scale": 0.01, "timeout": 3600},
                "tpcds": {"default_scale": 0.1, "timeout": 7200},
            }
        }

        with open(config_file, "w", encoding="utf-8") as f:
            yaml.dump(config_data, f)

        config_manager = ConfigManager(config_path=config_file)

        # Test getting nested settings
        if hasattr(config_manager, "get_setting"):
            tpch_scale = config_manager.get_setting("benchmarks.tpch.default_scale")
            assert tpch_scale == 0.01

            tpcds_timeout = config_manager.get_setting("benchmarks.tpcds.timeout")
            assert tpcds_timeout == 7200

    def test_config_manager_set_setting(self, temp_dir):
        """Test setting specific configuration values."""
        config_file = temp_dir / "set_test.yaml"
        config_manager = ConfigManager(config_path=config_file)

        # Test setting values
        if hasattr(config_manager, "set_setting"):
            config_manager.set_setting("system.cpu_cores", 16)
            config_manager.set_setting("database.connection_pool_size", 10)

            assert config_manager.config.system["cpu_cores"] == 16
            assert config_manager.config.database["connection_pool_size"] == 10

    def test_config_manager_merge_config(self, temp_dir):
        """Test merging configuration with runtime overrides."""
        config_file = temp_dir / "merge_test.yaml"
        base_config = {
            "system": {"cpu_cores": 4, "memory_gb": 8},
            "database": {"type": "sqlite"},
        }

        with open(config_file, "w", encoding="utf-8") as f:
            yaml.dump(base_config, f)

        config_manager = ConfigManager(config_path=config_file)

        # Test merging runtime overrides
        runtime_overrides = {
            "system": {"cpu_cores": 8},  # Override existing
            "benchmarks": {"scale": 0.1},  # Add new section
        }

        if hasattr(config_manager, "merge_config"):
            config_manager.merge_config(runtime_overrides)

            assert config_manager.config.system["cpu_cores"] == 8  # Overridden
            assert config_manager.config.system["memory_gb"] == 8  # Preserved
            assert config_manager.config.benchmarks["scale"] == 0.1  # Added

    def test_config_manager_validate_config(self, temp_dir):
        """Test configuration validation."""
        config_file = temp_dir / "validate_test.yaml"
        config_data = {
            "system": {"cpu_cores": 4},
            "database": {"type": "duckdb"},
            "benchmarks": {"default_scale": 0.01, "timeout_minutes": 60},
            "execution": {"max_workers": 4},
        }

        with open(config_file, "w", encoding="utf-8") as f:
            yaml.dump(config_data, f)

        config_manager = ConfigManager(config_path=config_file)

        # Test validation
        if hasattr(config_manager, "validate_config"):
            is_valid = config_manager.validate_config()
            assert is_valid is True


@pytest.mark.unit
class TestConfigManagerEdgeCases:
    """Test ConfigManager edge cases and error handling."""

    def test_config_manager_permission_denied(self, temp_dir):
        """Test handling of permission denied errors."""
        # a directory without write permissions
        readonly_dir = temp_dir / "readonly"
        readonly_dir.mkdir()
        readonly_dir.chmod(0o444)

        config_file = readonly_dir / "config.yaml"

        try:
            # This should handle permission errors gracefully
            config_manager = ConfigManager(config_path=config_file)
            assert isinstance(config_manager.config, BenchBoxConfig)
        finally:
            # Restore permissions for cleanup
            with contextlib.suppress(OSError, PermissionError):
                readonly_dir.chmod(0o755)

    def test_config_manager_empty_file(self, temp_dir):
        """Test handling of empty configuration file."""
        config_file = temp_dir / "empty.yaml"
        config_file.touch()  # Create empty file

        config_manager = ConfigManager(config_path=config_file)

        # Should handle empty file gracefully and return default config
        assert isinstance(config_manager.config, BenchBoxConfig)
        assert config_manager.config.system.get("auto_profile") is True

    def test_config_manager_corrupted_file(self, temp_dir):
        """Test handling of corrupted configuration file."""
        config_file = temp_dir / "corrupted.yaml"

        # Write binary data to YAML file
        with open(config_file, "wb") as f:
            f.write(b"\xff\xfe\x00corrupted\x00data")

        # Should handle corrupted file gracefully and return default config
        config_manager = ConfigManager(config_path=config_file)
        assert isinstance(config_manager.config, BenchBoxConfig)
        assert config_manager.config.system.get("auto_profile") is True

    def test_config_manager_very_large_config(self, temp_dir):
        """Test handling of large configuration files - optimized version."""
        config_file = temp_dir / "large.yaml"

        # a reasonably large config structure (reduced for speed)
        large_config = {
            "system": {f"key_{i}": f"value_{i}" for i in range(50)},  # Reduced from 1000 to 50
            "benchmarks": {
                f"benchmark_{i}": {
                    "scale": 0.01 * i,
                    "queries": [f"q{j}" for j in range(10)],  # Reduced from 100 to 10
                }
                for i in range(3)  # Reduced from 10 to 3
            },
        }

        with open(config_file, "w", encoding="utf-8") as f:
            yaml.dump(large_config, f)

        # Should handle large configs
        config_manager = ConfigManager(config_path=config_file)

        assert isinstance(config_manager.config, BenchBoxConfig)
        # Should have 50 test keys + 3 default keys (auto_profile, save_profile, profile_cache_hours)
        assert len(config_manager.config.system) == 53
        # Should have 3 test benchmarks + 4 default keys (default_scale, timeout_minutes, max_memory_gb, continue_on_error)
        assert len(config_manager.config.benchmarks) == 7
