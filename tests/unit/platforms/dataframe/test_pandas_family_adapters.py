"""Unit tests for Pandas Family DataFrame adapters.

Tests for Modin, cuDF, and Dask DataFrame adapters that extend PandasFamilyAdapter.
These tests focus on platform registration and factory functions since the actual
adapters require their respective libraries to be installed.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import pytest

from benchbox.platforms import (
    CUDF_AVAILABLE,
    DASK_AVAILABLE,
    MODIN_AVAILABLE,
    get_dataframe_requirements,
    is_dataframe_platform,
    list_available_dataframe_platforms,
)

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


# =============================================================================
# Platform Registration Tests
# =============================================================================


class TestPandasFamilyPlatformRegistration:
    """Tests for Pandas family platform registration."""

    def test_modin_df_is_dataframe_platform(self):
        """Test that modin-df is recognized as a DataFrame platform."""
        assert is_dataframe_platform("modin-df") is True

    def test_cudf_df_is_dataframe_platform(self):
        """Test that cudf-df is recognized as a DataFrame platform."""
        assert is_dataframe_platform("cudf-df") is True

    def test_dask_df_is_dataframe_platform(self):
        """Test that dask-df is recognized as a DataFrame platform."""
        assert is_dataframe_platform("dask-df") is True

    def test_case_insensitive_platform_check(self):
        """Test that platform checks are case-insensitive."""
        assert is_dataframe_platform("MODIN-DF") is True
        assert is_dataframe_platform("Modin-Df") is True
        assert is_dataframe_platform("CUDF-DF") is True
        assert is_dataframe_platform("CuDF-Df") is True
        assert is_dataframe_platform("DASK-DF") is True
        assert is_dataframe_platform("Dask-Df") is True


class TestPandasFamilyPlatformListing:
    """Tests for listing Pandas family platforms."""

    def test_list_includes_modin_df(self):
        """Test that modin-df is included in platform list."""
        platforms = list_available_dataframe_platforms()

        assert "modin-df" in platforms
        assert platforms["modin-df"] == MODIN_AVAILABLE

    def test_list_includes_cudf_df(self):
        """Test that cudf-df is included in platform list."""
        platforms = list_available_dataframe_platforms()

        assert "cudf-df" in platforms
        assert platforms["cudf-df"] == CUDF_AVAILABLE

    def test_list_includes_dask_df(self):
        """Test that dask-df is included in platform list."""
        platforms = list_available_dataframe_platforms()

        assert "dask-df" in platforms
        assert platforms["dask-df"] == DASK_AVAILABLE

    def test_list_has_all_expected_platforms(self):
        """Test that all expected DataFrame platforms are listed."""
        platforms = list_available_dataframe_platforms()

        # All DataFrame platforms (both pandas and expression family)
        expected = {
            "polars-df",
            "pandas-df",
            "modin-df",
            "cudf-df",
            "dask-df",
            "datafusion-df",
            "pyspark-df",
            "lakesail-df",
        }
        assert set(platforms.keys()) == expected


class TestPandasFamilyRequirements:
    """Tests for Pandas family platform requirements."""

    def test_modin_df_requirements_contain_modin(self):
        """Test that modin-df requirements mention modin."""
        req = get_dataframe_requirements("modin-df")

        assert "modin" in req.lower()

    def test_modin_df_requirements_mention_engine(self):
        """Test that modin-df requirements mention ray or dask."""
        req = get_dataframe_requirements("modin-df")

        assert "ray" in req.lower() or "dask" in req.lower()

    def test_cudf_df_requirements_contain_cudf(self):
        """Test that cudf-df requirements mention cudf."""
        req = get_dataframe_requirements("cudf-df")

        assert "cudf" in req.lower()

    def test_cudf_df_requirements_mention_gpu(self):
        """Test that cudf-df requirements mention GPU/CUDA."""
        req = get_dataframe_requirements("cudf-df")

        assert "gpu" in req.lower() or "cuda" in req.lower()

    def test_dask_df_requirements_contain_dask(self):
        """Test that dask-df requirements mention dask."""
        req = get_dataframe_requirements("dask-df")

        assert "dask" in req.lower()

    def test_dask_df_requirements_mention_distributed(self):
        """Test that dask-df requirements mention distributed."""
        req = get_dataframe_requirements("dask-df")

        assert "distributed" in req.lower()


# =============================================================================
# Platform Hook Registration Tests
# =============================================================================


class TestPandasFamilyPlatformHooks:
    """Tests for platform hook registration of new adapters."""

    def test_modin_df_engine_option_registered(self):
        """Test that modin-df engine option is registered."""
        from benchbox.cli.platform_hooks import PlatformHookRegistry

        if MODIN_AVAILABLE:
            specs = PlatformHookRegistry.list_option_specs("modin-df")
            assert "engine" in specs
        else:
            # If modin not available, verify platform exists but may have no options
            pass

    def test_modin_df_engine_choices(self):
        """Test that modin-df engine has correct choices."""
        from benchbox.cli.platform_hooks import PlatformHookRegistry

        if MODIN_AVAILABLE:
            specs = PlatformHookRegistry.list_option_specs("modin-df")
            engine_spec = specs.get("engine")
            if engine_spec and hasattr(engine_spec, "choices"):
                assert "ray" in engine_spec.choices
                assert "dask" in engine_spec.choices

    def test_cudf_df_device_id_option_registered(self):
        """Test that cudf-df device_id option is registered."""
        from benchbox.cli.platform_hooks import PlatformHookRegistry

        if CUDF_AVAILABLE:
            specs = PlatformHookRegistry.list_option_specs("cudf-df")
            assert "device_id" in specs

    def test_cudf_df_spill_to_host_option_registered(self):
        """Test that cudf-df spill_to_host option is registered."""
        from benchbox.cli.platform_hooks import PlatformHookRegistry

        if CUDF_AVAILABLE:
            specs = PlatformHookRegistry.list_option_specs("cudf-df")
            assert "spill_to_host" in specs

    def test_dask_df_n_workers_option_registered(self):
        """Test that dask-df n_workers option is registered."""
        from benchbox.cli.platform_hooks import PlatformHookRegistry

        if DASK_AVAILABLE:
            specs = PlatformHookRegistry.list_option_specs("dask-df")
            assert "n_workers" in specs

    def test_dask_df_threads_per_worker_option_registered(self):
        """Test that dask-df threads_per_worker option is registered."""
        from benchbox.cli.platform_hooks import PlatformHookRegistry

        if DASK_AVAILABLE:
            specs = PlatformHookRegistry.list_option_specs("dask-df")
            assert "threads_per_worker" in specs

    def test_dask_df_use_distributed_option_registered(self):
        """Test that dask-df use_distributed option is registered."""
        from benchbox.cli.platform_hooks import PlatformHookRegistry

        if DASK_AVAILABLE:
            specs = PlatformHookRegistry.list_option_specs("dask-df")
            assert "use_distributed" in specs

    def test_dask_df_scheduler_address_option_registered(self):
        """Test that dask-df scheduler_address option is registered."""
        from benchbox.cli.platform_hooks import PlatformHookRegistry

        if DASK_AVAILABLE:
            specs = PlatformHookRegistry.list_option_specs("dask-df")
            assert "scheduler_address" in specs


# =============================================================================
# Factory Integration Tests
# =============================================================================


class TestPandasFamilyFactory:
    """Tests for DataFrame adapter factory with Pandas family adapters."""

    def test_unknown_platform_raises_value_error(self):
        """Test that unknown platform raises ValueError."""
        from benchbox.platforms import get_dataframe_adapter

        with pytest.raises(ValueError, match="Unknown DataFrame platform"):
            get_dataframe_adapter("unknown-df")

    def test_modin_df_in_factory_mapping(self):
        """Test that modin-df is in the factory mapping."""
        from benchbox.platforms import get_dataframe_adapter

        # If modin is not available, this should raise ImportError
        if not MODIN_AVAILABLE:
            with pytest.raises(ImportError, match="[Mm]odin"):
                get_dataframe_adapter("modin-df")
        else:
            # If available, should create adapter successfully
            adapter = get_dataframe_adapter("modin-df")
            assert adapter is not None

    def test_cudf_df_in_factory_mapping(self):
        """Test that cudf-df is in the factory mapping."""
        from benchbox.platforms import get_dataframe_adapter

        if not CUDF_AVAILABLE:
            with pytest.raises(ImportError, match="[Cc]u[Dd][Ff]"):
                get_dataframe_adapter("cudf-df")
        else:
            adapter = get_dataframe_adapter("cudf-df")
            assert adapter is not None

    def test_dask_df_in_factory_mapping(self):
        """Test that dask-df is in the factory mapping."""
        from benchbox.platforms import get_dataframe_adapter

        if not DASK_AVAILABLE:
            with pytest.raises(ImportError, match="[Dd]ask"):
                get_dataframe_adapter("dask-df")
        else:
            adapter = get_dataframe_adapter("dask-df")
            assert adapter is not None


# =============================================================================
# Adapter Module Import Tests
# =============================================================================


class TestAdapterModuleAvailability:
    """Tests for adapter module availability flags."""

    def test_modin_available_flag_is_boolean(self):
        """Test that MODIN_AVAILABLE is a boolean."""
        from benchbox.platforms.dataframe import MODIN_AVAILABLE as available

        assert isinstance(available, bool)

    def test_cudf_available_flag_is_boolean(self):
        """Test that CUDF_AVAILABLE is a boolean."""
        from benchbox.platforms.dataframe import CUDF_AVAILABLE as available

        assert isinstance(available, bool)

    def test_dask_available_flag_is_boolean(self):
        """Test that DASK_AVAILABLE is a boolean."""
        from benchbox.platforms.dataframe import DASK_AVAILABLE as available

        assert isinstance(available, bool)

    def test_modin_adapter_class_import(self):
        """Test that ModinDataFrameAdapter can be imported."""
        from benchbox.platforms.dataframe import ModinDataFrameAdapter

        # The class is always importable; instantiation requires the library
        if MODIN_AVAILABLE:
            assert ModinDataFrameAdapter is not None
            # Should be able to instantiate
            adapter = ModinDataFrameAdapter()
            assert adapter.platform_name == "Modin"
        else:
            # Class exists but instantiation fails
            assert ModinDataFrameAdapter is not None
            with pytest.raises(ImportError):
                ModinDataFrameAdapter()

    def test_cudf_adapter_class_import(self):
        """Test that CuDFDataFrameAdapter can be imported."""
        from benchbox.platforms.dataframe import CuDFDataFrameAdapter

        if CUDF_AVAILABLE:
            assert CuDFDataFrameAdapter is not None
            adapter = CuDFDataFrameAdapter()
            assert adapter.platform_name == "cuDF"
        else:
            # Class exists but instantiation fails
            assert CuDFDataFrameAdapter is not None
            with pytest.raises(ImportError):
                CuDFDataFrameAdapter()

    def test_dask_adapter_class_import(self):
        """Test that DaskDataFrameAdapter can be imported."""
        from benchbox.platforms.dataframe import DaskDataFrameAdapter

        if DASK_AVAILABLE:
            assert DaskDataFrameAdapter is not None
            adapter = DaskDataFrameAdapter(use_distributed=False)
            assert adapter.platform_name == "Dask"
        else:
            # Class exists but instantiation fails
            assert DaskDataFrameAdapter is not None
            with pytest.raises(ImportError):
                DaskDataFrameAdapter()


# =============================================================================
# Module Export Tests
# =============================================================================


class TestModuleExports:
    """Tests for module __all__ exports."""

    def test_platforms_init_exports_modin_adapter(self):
        """Test that platforms __init__ exports ModinDataFrameAdapter."""
        from benchbox import platforms

        assert hasattr(platforms, "ModinDataFrameAdapter")
        assert hasattr(platforms, "MODIN_AVAILABLE")

    def test_platforms_init_exports_cudf_adapter(self):
        """Test that platforms __init__ exports CuDFDataFrameAdapter."""
        from benchbox import platforms

        assert hasattr(platforms, "CuDFDataFrameAdapter")
        assert hasattr(platforms, "CUDF_AVAILABLE")

    def test_platforms_init_exports_dask_adapter(self):
        """Test that platforms __init__ exports DaskDataFrameAdapter."""
        from benchbox import platforms

        assert hasattr(platforms, "DaskDataFrameAdapter")
        assert hasattr(platforms, "DASK_AVAILABLE")

    def test_dataframe_init_exports_modin_adapter(self):
        """Test that dataframe __init__ exports ModinDataFrameAdapter."""
        from benchbox.platforms import dataframe

        assert hasattr(dataframe, "ModinDataFrameAdapter")
        assert hasattr(dataframe, "MODIN_AVAILABLE")

    def test_dataframe_init_exports_cudf_adapter(self):
        """Test that dataframe __init__ exports CuDFDataFrameAdapter."""
        from benchbox.platforms import dataframe

        assert hasattr(dataframe, "CuDFDataFrameAdapter")
        assert hasattr(dataframe, "CUDF_AVAILABLE")

    def test_dataframe_init_exports_dask_adapter(self):
        """Test that dataframe __init__ exports DaskDataFrameAdapter."""
        from benchbox.platforms import dataframe

        assert hasattr(dataframe, "DaskDataFrameAdapter")
        assert hasattr(dataframe, "DASK_AVAILABLE")
