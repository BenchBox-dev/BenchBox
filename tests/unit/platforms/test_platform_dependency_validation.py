"""
Tests for platform dependency validation functionality.

Tests consolidated dependency validation methods added to PlatformAdapter base class.
"""

from unittest.mock import patch

import pytest

from benchbox.platforms.base import PlatformAdapter

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


class TestDependencyValidation:
    """Test dependency validation methods in PlatformAdapter."""

    def test_check_import_success(self):
        """Test successful module import check."""
        # Test with a module that should always be available
        result = PlatformAdapter._check_import("os")
        assert result is True

    def test_check_import_failure(self):
        """Test failed module import check."""
        # Test with a module that should not exist
        result = PlatformAdapter._check_import("definitely_nonexistent_module_xyz")
        assert result is False

    @patch("benchbox.platforms.base.connection_lifecycle.ConnectionLifecycleMixin._check_import")
    def test_validate_platform_dependencies(self, mock_check_import):
        """Test validation of all platform dependencies."""
        # Mock all dependencies as available
        mock_check_import.return_value = True

        with patch.object(PlatformAdapter, "_check_databricks_dependencies", return_value=True):
            result = PlatformAdapter.validate_platform_dependencies()

        expected_deps = [
            "duckdb",
            "databricks",
            "clickhouse",
            "cloudpathlib",
            "snowflake",
            "psutil",
        ]

        # Check that all expected dependencies are included
        for dep in expected_deps:
            assert dep in result
            assert result[dep] is True

        # Verify that _check_import was called for non-Databricks dependencies
        assert mock_check_import.call_count >= 5  # Should be called for most dependencies

    @patch("benchbox.platforms.base.connection_lifecycle.ConnectionLifecycleMixin._check_import")
    def test_validate_platform_dependencies_mixed(self, mock_check_import):
        """Test validation with mixed available/unavailable dependencies."""

        # Mock different availability for different modules
        def mock_import_side_effect(module_name):
            available_modules = ["duckdb", "psutil"]
            return module_name in available_modules

        mock_check_import.side_effect = mock_import_side_effect

        with patch.object(PlatformAdapter, "_check_databricks_dependencies", return_value=False):
            result = PlatformAdapter.validate_platform_dependencies()

        # Check expected results
        assert result["duckdb"] is True
        assert result["psutil"] is True
        assert result["databricks"] is False
        assert result["clickhouse"] is False
        assert result["cloudpathlib"] is False
        assert result["snowflake"] is False

    @patch("benchbox.platforms.base.connection_lifecycle.ConnectionLifecycleMixin._check_import")
    def test_check_databricks_dependencies(self, mock_check_import):
        """Test Databricks-specific dependency checking."""
        # Test when all Databricks modules are available
        mock_check_import.return_value = True
        result = PlatformAdapter._check_databricks_dependencies()
        assert result is True

        # Verify that both required modules were checked
        from unittest.mock import call

        expected_calls = [call("databricks.sql"), call("databricks.sdk")]
        mock_check_import.assert_has_calls(expected_calls, any_order=True)

    @patch("benchbox.platforms.base.connection_lifecycle.ConnectionLifecycleMixin._check_import")
    def test_check_databricks_dependencies_partial(self, mock_check_import):
        """Test Databricks dependency checking with partial availability."""

        # Mock only one module as available
        def mock_side_effect(module_name):
            return module_name == "databricks.sql"

        mock_check_import.side_effect = mock_side_effect
        result = PlatformAdapter._check_databricks_dependencies()
        assert result is False  # Should require ALL modules to be available

    def test_get_install_command(self):
        """Test installation command retrieval."""
        assert PlatformAdapter._get_install_command("duckdb") == "uv add duckdb"
        assert PlatformAdapter._get_install_command("databricks") == "uv add databricks-sql-connector databricks-sdk"
        assert PlatformAdapter._get_install_command("clickhouse") == "uv add clickhouse-driver"
        assert PlatformAdapter._get_install_command("cloudpathlib") == "uv add cloudpathlib"
        assert PlatformAdapter._get_install_command("snowflake") == "uv add snowflake-connector-python"
        assert PlatformAdapter._get_install_command("psutil") == "uv add psutil"
        assert PlatformAdapter._get_install_command("unknown_dependency") is None

    @patch("benchbox.platforms.base.connection_lifecycle.quiet_console")
    @patch("benchbox.platforms.base.connection_lifecycle.ConnectionLifecycleMixin.validate_platform_dependencies")
    @patch("sys.exit")
    def test_require_dependencies_all_available(self, mock_exit, mock_validate, mock_console):
        """Test require_dependencies when all dependencies are available."""
        # Mock all required dependencies as available
        mock_validate.return_value = {"duckdb": True, "cloudpathlib": True}

        result = PlatformAdapter.require_dependencies(["duckdb", "cloudpathlib"])

        # Should not exit and should return the validation results
        mock_exit.assert_not_called()
        assert result == {"duckdb": True, "cloudpathlib": True}

        # Should print success message
        assert any(
            "✅ All required dependencies are available" in str(call) for call in mock_console.print.call_args_list
        )

    @patch("benchbox.platforms.base.connection_lifecycle.quiet_console")
    @patch("benchbox.platforms.base.connection_lifecycle.ConnectionLifecycleMixin.validate_platform_dependencies")
    @patch("benchbox.platforms.base.connection_lifecycle.ConnectionLifecycleMixin._get_install_command")
    @patch("sys.exit")
    def test_require_dependencies_missing_with_exit(self, mock_exit, mock_get_install, mock_validate, mock_console):
        """Test require_dependencies with missing dependencies and exit enabled."""
        # Mock some dependencies as missing
        mock_validate.return_value = {"duckdb": False, "cloudpathlib": True}
        mock_get_install.return_value = "uv add duckdb"

        PlatformAdapter.require_dependencies(["duckdb", "cloudpathlib"], exit_on_missing=True)

        # Should call sys.exit(1)
        mock_exit.assert_called_once_with(1)

        # Should print error message
        console_calls = [str(call) for call in mock_console.print.call_args_list]
        assert any("❌ Missing required dependencies:" in call for call in console_calls)
        assert any("duckdb" in call for call in console_calls)

    @patch("benchbox.platforms.base.connection_lifecycle.quiet_console")
    @patch("benchbox.platforms.base.connection_lifecycle.ConnectionLifecycleMixin.validate_platform_dependencies")
    @patch("sys.exit")
    def test_require_dependencies_missing_no_exit(self, mock_exit, mock_validate, mock_console):
        """Test require_dependencies with missing dependencies and exit disabled."""
        # Mock some dependencies as missing
        mock_validate.return_value = {"duckdb": False, "cloudpathlib": True}

        result = PlatformAdapter.require_dependencies(["duckdb", "cloudpathlib"], exit_on_missing=False)

        # Should not exit but should return the validation results
        mock_exit.assert_not_called()
        assert result == {"duckdb": False, "cloudpathlib": True}

        # Should still print error message
        console_calls = [str(call) for call in mock_console.print.call_args_list]
        assert any("❌ Missing required dependencies:" in call for call in console_calls)

    def test_require_dependencies_empty_list(self):
        """Test require_dependencies with empty requirements list."""
        with patch(
            "benchbox.platforms.base.connection_lifecycle.ConnectionLifecycleMixin.validate_platform_dependencies"
        ) as mock_validate:
            mock_validate.return_value = {}

            with patch("benchbox.platforms.base.connection_lifecycle.quiet_console") as mock_console:
                result = PlatformAdapter.require_dependencies([])

            # Should succeed and print success message
            assert any(
                "✅ All required dependencies are available" in str(call) for call in mock_console.print.call_args_list
            )
            assert result == {}


class TestDependencyIntegration:
    """Test integration of dependency validation with real modules."""

    def test_real_os_module_check(self):
        """Test dependency check with real os module (should always be available)."""
        result = PlatformAdapter._check_import("os")
        assert result is True

    def test_real_nonexistent_module_check(self):
        """Test dependency check with nonexistent module."""
        result = PlatformAdapter._check_import("this_module_definitely_does_not_exist_12345")
        assert result is False

    def test_validate_dependencies_returns_dict(self):
        """Test that validate_platform_dependencies returns proper structure."""
        result = PlatformAdapter.validate_platform_dependencies()

        assert isinstance(result, dict)
        assert len(result) > 0

        # All values should be boolean
        for dep_name, available in result.items():
            assert isinstance(dep_name, str)
            assert isinstance(available, bool)
