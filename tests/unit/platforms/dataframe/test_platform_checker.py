"""Unit tests for DataFrame Platform Checker.

Tests for:
- Platform availability detection
- Version checking
- Installation suggestions
- Error message generation

Copyright 2026 Joe Harris / BenchBox Project
"""

from __future__ import annotations

import pytest

from benchbox.platforms.dataframe.platform_checker import (
    DATAFRAME_PLATFORMS,
    DataFrameFamily,
    DataFramePlatformChecker,
    PlatformInfo,
    PlatformStatus,
    format_platform_status_table,
    get_installation_suggestion,
    get_platform_error_message,
    require_platform,
)

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


class TestDataFrameFamily:
    """Tests for DataFrameFamily enum."""

    def test_pandas_family_value(self):
        """Test Pandas family enum value."""
        assert DataFrameFamily.PANDAS.value == "pandas"

    def test_expression_family_value(self):
        """Test Expression family enum value."""
        assert DataFrameFamily.EXPRESSION.value == "expression"


class TestPlatformInfo:
    """Tests for PlatformInfo dataclass."""

    def test_platform_info_creation(self):
        """Test creating PlatformInfo."""
        info = PlatformInfo(
            name="TestPlatform",
            family=DataFrameFamily.PANDAS,
            import_name="test_module",
            version_attr="__version__",
            extra_name="test-extra",
            description="A test platform",
        )

        assert info.name == "TestPlatform"
        assert info.family == DataFrameFamily.PANDAS
        assert info.import_name == "test_module"
        assert info.extra_name == "test-extra"

    def test_platform_info_with_versions(self):
        """Test PlatformInfo with version constraints."""
        info = PlatformInfo(
            name="TestPlatform",
            family=DataFrameFamily.EXPRESSION,
            import_name="test",
            version_attr="__version__",
            extra_name="test",
            description="Test",
            min_version="1.0.0",
            max_version="2.0.0",
        )

        assert info.min_version == "1.0.0"
        assert info.max_version == "2.0.0"


class TestDataFramePlatforms:
    """Tests for DATAFRAME_PLATFORMS registry."""

    def test_pandas_registered(self):
        """Test that Pandas is in the registry."""
        assert "pandas" in DATAFRAME_PLATFORMS
        info = DATAFRAME_PLATFORMS["pandas"]
        assert info.family == DataFrameFamily.PANDAS

    def test_polars_registered(self):
        """Test that Polars is in the registry."""
        assert "polars" in DATAFRAME_PLATFORMS
        info = DATAFRAME_PLATFORMS["polars"]
        assert info.family == DataFrameFamily.EXPRESSION

    def test_dask_registered(self):
        """Test that Dask is in the registry."""
        assert "dask" in DATAFRAME_PLATFORMS
        info = DATAFRAME_PLATFORMS["dask"]
        assert info.family == DataFrameFamily.PANDAS

    def test_pyspark_registered(self):
        """Test that PySpark is in the registry."""
        assert "pyspark" in DATAFRAME_PLATFORMS
        info = DATAFRAME_PLATFORMS["pyspark"]
        assert info.family == DataFrameFamily.EXPRESSION

    def test_datafusion_registered(self):
        """Test that DataFusion is in the registry."""
        assert "datafusion" in DATAFRAME_PLATFORMS
        info = DATAFRAME_PLATFORMS["datafusion"]
        assert info.family == DataFrameFamily.EXPRESSION

    def test_all_platforms_have_required_fields(self):
        """Test all platforms have required fields."""
        for name, info in DATAFRAME_PLATFORMS.items():
            assert info.name, f"{name} missing name"
            assert info.family, f"{name} missing family"
            assert info.import_name, f"{name} missing import_name"
            assert info.version_attr, f"{name} missing version_attr"
            assert info.description, f"{name} missing description"


class TestDataFramePlatformChecker:
    """Tests for DataFramePlatformChecker class."""

    def test_polars_is_available(self):
        """Test that Polars (core dep) is available."""
        assert DataFramePlatformChecker.is_available("polars")

    def test_pandas_is_available(self):
        """Test that Pandas is available (installed in dev)."""
        # Pandas is installed in dev dependencies
        assert DataFramePlatformChecker.is_available("pandas")

    def test_unknown_platform_not_available(self):
        """Test that unknown platform returns False."""
        assert not DataFramePlatformChecker.is_available("nonexistent_platform")

    def test_get_version_polars(self):
        """Test getting Polars version."""
        version = DataFramePlatformChecker.get_version("polars")
        assert version is not None
        assert "." in version  # Version has dots

    def test_get_version_unknown_platform(self):
        """Test getting version of unknown platform."""
        version = DataFramePlatformChecker.get_version("nonexistent")
        assert version is None

    def test_check_platform_polars(self):
        """Test checking Polars status."""
        status = DataFramePlatformChecker.check_platform("polars")

        assert isinstance(status, PlatformStatus)
        assert status.available is True
        assert status.version is not None
        assert status.info.name == "Polars"
        assert status.error is None

    def test_check_platform_unknown(self):
        """Test checking unknown platform status."""
        status = DataFramePlatformChecker.check_platform("nonexistent")

        assert status.available is False
        assert "Unknown DataFrame platform" in status.error

    def test_get_available_platforms(self):
        """Test getting list of available platforms."""
        available = DataFramePlatformChecker.get_available_platforms()

        assert isinstance(available, list)
        assert "polars" in available  # Core dependency

    def test_get_available_by_family_expression(self):
        """Test getting available expression family platforms."""
        available = DataFramePlatformChecker.get_available_by_family(DataFrameFamily.EXPRESSION)

        assert isinstance(available, list)
        assert "polars" in available  # Core dependency

    def test_get_all_platforms(self):
        """Test getting all platform info."""
        platforms = DataFramePlatformChecker.get_all_platforms()

        assert isinstance(platforms, dict)
        assert "pandas" in platforms
        assert "polars" in platforms
        assert all(isinstance(v, PlatformInfo) for v in platforms.values())

    def test_check_all_platforms(self):
        """Test checking all platform statuses."""
        statuses = DataFramePlatformChecker.check_all_platforms()

        assert isinstance(statuses, dict)
        assert all(isinstance(v, PlatformStatus) for v in statuses.values())
        # Polars should be available (core dep)
        assert statuses["polars"].available is True


class TestInstallationSuggestion:
    """Tests for installation suggestion generation."""

    def test_suggestion_for_pandas(self):
        """Test installation suggestion for Pandas."""
        suggestion = get_installation_suggestion("pandas")

        assert "benchbox[pandas]" in suggestion or "--extra pandas" in suggestion
        assert "uv add" in suggestion

    def test_suggestion_for_polars_core(self):
        """Test suggestion for Polars (core dependency)."""
        suggestion = get_installation_suggestion("polars")

        assert "core dependency" in suggestion

    def test_suggestion_for_unknown_platform(self):
        """Test suggestion for unknown platform."""
        suggestion = get_installation_suggestion("nonexistent")

        assert "Unknown" in suggestion


class TestPlatformErrorMessage:
    """Tests for platform error message generation."""

    def test_error_for_available_platform(self):
        """Test error message for available platform."""
        message = get_platform_error_message("polars")

        assert "available" in message.lower()

    def test_error_for_unknown_platform(self):
        """Test error message for unknown platform."""
        message = get_platform_error_message("nonexistent")

        assert "Unknown" in message


class TestRequirePlatform:
    """Tests for require_platform function."""

    def test_require_polars_succeeds(self):
        """Test requiring Polars (core dep) succeeds."""
        module = require_platform("polars")

        assert module is not None
        assert hasattr(module, "__version__")

    def test_require_unknown_raises(self):
        """Test requiring unknown platform raises ImportError."""
        with pytest.raises(ImportError, match="Unknown"):
            require_platform("nonexistent_platform")


class TestFormatPlatformStatusTable:
    """Tests for status table formatting."""

    def test_table_format(self):
        """Test that status table is properly formatted."""
        table = format_platform_status_table()

        assert "DataFrame Platform Status" in table
        assert "Platform" in table
        assert "Family" in table
        assert "Available" in table
        assert "Version" in table

    def test_table_shows_polars(self):
        """Test that table shows Polars status."""
        table = format_platform_status_table()

        assert "Polars" in table
        assert "expression" in table

    def test_table_shows_count(self):
        """Test that table shows available count."""
        table = format_platform_status_table()

        assert "Available:" in table
        assert "platforms" in table


class TestMinimumVersionEnforcement:
    """Below-minimum installs must report unavailable, not warn-and-pass."""

    def test_below_minimum_reports_unavailable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Simulate DataFusion 53 against the 54 floor."""
        monkeypatch.setattr(
            DataFramePlatformChecker,
            "get_version",
            staticmethod(lambda platform: "53.0.0"),
        )
        status = DataFramePlatformChecker.check_platform("datafusion")

        assert status.available is False
        assert status.error is not None
        assert "54.0.0" in status.error

    def test_at_minimum_reports_available(self) -> None:
        """The locked DataFusion 54 install stays available."""
        status = DataFramePlatformChecker.check_platform("datafusion")

        assert status.available is True
        assert status.error is None
