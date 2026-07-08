"""Unit tests for DataFrame platform factory functions.

Tests for:
- get_dataframe_adapter() factory
- list_available_dataframe_platforms()
- get_dataframe_requirements()
- is_dataframe_platform()
- Platform hook registration

Copyright 2026 Joe Harris / BenchBox Project
"""

from __future__ import annotations

import pytest

from benchbox.platforms import (
    PANDAS_AVAILABLE,
    POLARS_AVAILABLE,
    PandasDataFrameAdapter,
    PolarsDataFrameAdapter,
    get_dataframe_adapter,
    get_dataframe_requirements,
    is_dataframe_platform,
    list_available_dataframe_platforms,
)

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


class TestGetDataFrameAdapter:
    """Tests for get_dataframe_adapter factory function."""

    def test_create_polars_adapter(self):
        """Test creating a Polars DataFrame adapter."""
        adapter = get_dataframe_adapter("polars-df")

        assert adapter is not None
        assert isinstance(adapter, PolarsDataFrameAdapter)
        assert adapter.platform_name == "Polars"

    def test_create_pandas_adapter(self):
        """Test creating a Pandas DataFrame adapter."""
        adapter = get_dataframe_adapter("pandas-df")

        assert adapter is not None
        assert isinstance(adapter, PandasDataFrameAdapter)
        assert adapter.platform_name == "Pandas"

    def test_case_insensitive_platform_names(self):
        """Test that platform names are case-insensitive."""
        adapter1 = get_dataframe_adapter("POLARS-DF")
        adapter2 = get_dataframe_adapter("Polars-Df")
        adapter3 = get_dataframe_adapter("polars-df")

        assert adapter1.platform_name == adapter2.platform_name == adapter3.platform_name

    def test_unknown_platform_raises_value_error(self):
        """Test that unknown platform raises ValueError."""
        with pytest.raises(ValueError, match="Unknown DataFrame platform"):
            get_dataframe_adapter("unknown-df")

    def test_config_passed_to_adapter(self):
        """Test that configuration is passed to the adapter."""
        adapter = get_dataframe_adapter("polars-df", streaming=True, rechunk=False)

        assert adapter.streaming is True
        assert adapter.rechunk is False


class TestListAvailableDataFramePlatforms:
    """Tests for list_available_dataframe_platforms function."""

    def test_returns_dictionary(self):
        """Test that function returns a dictionary."""
        platforms = list_available_dataframe_platforms()

        assert isinstance(platforms, dict)

    def test_includes_polars_df(self):
        """Test that polars-df is in the platform list."""
        platforms = list_available_dataframe_platforms()

        assert "polars-df" in platforms
        assert platforms["polars-df"] == POLARS_AVAILABLE

    def test_includes_pandas_df(self):
        """Test that pandas-df is in the platform list."""
        platforms = list_available_dataframe_platforms()

        assert "pandas-df" in platforms
        assert platforms["pandas-df"] == PANDAS_AVAILABLE

    def test_both_platforms_available_in_dev(self):
        """Test that both platforms are available in dev environment."""
        platforms = list_available_dataframe_platforms()

        # Both should be available in the dev environment
        assert platforms["polars-df"] is True
        assert platforms["pandas-df"] is True


class TestGetDataFrameRequirements:
    """Tests for get_dataframe_requirements function."""

    def test_polars_df_requirements(self):
        """Test requirements for polars-df."""
        req = get_dataframe_requirements("polars-df")

        assert "polars" in req.lower()
        assert "core dependency" in req.lower()

    def test_pandas_df_requirements(self):
        """Test requirements for pandas-df."""
        req = get_dataframe_requirements("pandas-df")

        assert "--extra pandas" in req.lower()

    def test_unknown_platform_requirements(self):
        """Test requirements for unknown platform."""
        req = get_dataframe_requirements("unknown-df")

        assert "Unknown" in req


class TestIsDataFramePlatform:
    """Tests for is_dataframe_platform function."""

    def test_polars_df_is_dataframe_platform(self):
        """Test that polars-df is recognized as DataFrame platform."""
        assert is_dataframe_platform("polars-df") is True

    def test_pandas_df_is_dataframe_platform(self):
        """Test that pandas-df is recognized as DataFrame platform."""
        assert is_dataframe_platform("pandas-df") is True

    def test_case_insensitive(self):
        """Test case insensitivity."""
        assert is_dataframe_platform("POLARS-DF") is True
        assert is_dataframe_platform("Pandas-Df") is True

    def test_sql_platforms_not_dataframe(self):
        """Test that SQL platforms are not DataFrame platforms."""
        assert is_dataframe_platform("duckdb") is False
        assert is_dataframe_platform("polars") is False  # SQL Polars, not DataFrame
        assert is_dataframe_platform("clickhouse") is False
        assert is_dataframe_platform("databricks") is False


class TestPlatformHookRegistration:
    """Tests for DataFrame platform hook registration."""

    def test_polars_df_options_registered(self):
        """Test that polars-df platform options are registered."""
        from benchbox.cli.platform_hooks import PlatformHookRegistry

        # Options are keyed by the base platform name (`polars`), not the `-df`
        # CLI alias, so they are reachable via the normalized run platform key.
        specs = PlatformHookRegistry.list_option_specs("polars")

        assert "streaming" in specs
        assert "rechunk" in specs
        assert "n_rows" in specs

    def test_pandas_df_options_registered(self):
        """Test that pandas-df platform options are registered."""
        from benchbox.cli.platform_hooks import PlatformHookRegistry

        specs = PlatformHookRegistry.list_option_specs("pandas")

        assert "dtype_backend" in specs

    def test_polars_df_option_defaults(self):
        """Test polars-df option defaults."""
        from benchbox.cli.platform_hooks import PlatformHookRegistry

        defaults = PlatformHookRegistry.get_default_options("polars")

        assert defaults["streaming"] == "false"
        assert defaults["rechunk"] == "true"
        assert defaults["n_rows"] is None

    def test_pandas_df_option_defaults(self):
        """Test pandas-df option defaults."""
        from benchbox.cli.platform_hooks import PlatformHookRegistry

        defaults = PlatformHookRegistry.get_default_options("pandas")

        assert defaults["dtype_backend"] == "numpy_nullable"

    def test_polars_df_option_parsing(self):
        """Test parsing polars-df options."""
        from benchbox.cli.platform_hooks import PlatformHookRegistry

        parsed = PlatformHookRegistry.parse_options(
            "polars",
            [("streaming", "true"), ("rechunk", "false"), ("n_rows", "1000")],
        )

        assert parsed["streaming"] is True
        assert parsed["rechunk"] is False
        assert parsed["n_rows"] == 1000

    def test_pandas_df_option_parsing(self):
        """Test parsing pandas-df options."""
        from benchbox.cli.platform_hooks import PlatformHookRegistry

        parsed = PlatformHookRegistry.parse_options(
            "pandas",
            [("dtype_backend", "pyarrow")],
        )

        assert parsed["dtype_backend"] == "pyarrow"

    def test_pandas_df_invalid_choice_raises(self):
        """Test that invalid dtype_backend choice raises error."""
        from benchbox.cli.platform_hooks import PlatformHookRegistry, PlatformOptionError

        with pytest.raises(PlatformOptionError, match="Invalid value"):
            PlatformHookRegistry.parse_options(
                "pandas",
                [("dtype_backend", "invalid_backend")],
            )


class TestDataFrameAdapterContext:
    """Tests for DataFrame adapter context creation."""

    def test_polars_adapter_creates_context(self):
        """Test that Polars adapter can create a context."""
        adapter = get_dataframe_adapter("polars-df")
        ctx = adapter.create_context()

        assert ctx is not None
        assert ctx.platform == "Polars"
        assert ctx.family == "expression"

    def test_pandas_adapter_creates_context(self):
        """Test that Pandas adapter can create a context."""
        adapter = get_dataframe_adapter("pandas-df")
        ctx = adapter.create_context()

        assert ctx is not None
        assert ctx.platform == "Pandas"
        assert ctx.family == "pandas"
