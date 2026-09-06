"""Unit tests for DataFrame tuning types.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import pytest

from benchbox.core.dataframe.tuning.types import (
    DataFrameTuningType,
    get_all_platforms,
)

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


class TestDataFrameTuningType:
    """Tests for DataFrameTuningType enum."""

    def test_enum_values_exist(self):
        """Test that expected enum values exist."""
        assert DataFrameTuningType.THREAD_COUNT.value == "thread_count"
        assert DataFrameTuningType.WORKER_COUNT.value == "worker_count"
        assert DataFrameTuningType.STREAMING_MODE.value == "streaming_mode"
        assert DataFrameTuningType.MEMORY_LIMIT.value == "memory_limit"
        assert DataFrameTuningType.GPU_DEVICE.value == "gpu_device"

    def test_is_compatible_with_platform_polars(self):
        """Test Polars platform compatibility."""
        # Compatible with Polars
        assert DataFrameTuningType.THREAD_COUNT.is_compatible_with_platform("polars") is True
        assert DataFrameTuningType.STREAMING_MODE.is_compatible_with_platform("polars") is True
        assert DataFrameTuningType.CHUNK_SIZE.is_compatible_with_platform("polars") is True

        # Not compatible with Polars
        assert DataFrameTuningType.WORKER_COUNT.is_compatible_with_platform("polars") is False
        assert DataFrameTuningType.GPU_DEVICE.is_compatible_with_platform("polars") is False

    def test_is_compatible_with_platform_pandas(self):
        """Test Pandas platform compatibility."""
        # Compatible with Pandas
        assert DataFrameTuningType.DTYPE_BACKEND.is_compatible_with_platform("pandas") is True
        assert DataFrameTuningType.CHUNK_SIZE.is_compatible_with_platform("pandas") is True

        # Not compatible with Pandas
        assert DataFrameTuningType.THREAD_COUNT.is_compatible_with_platform("pandas") is False
        assert DataFrameTuningType.GPU_DEVICE.is_compatible_with_platform("pandas") is False

    def test_is_compatible_with_platform_datafusion(self):
        """DataFusion exposes the SessionConfig settings its adapter applies."""
        assert DataFrameTuningType.THREAD_COUNT.is_compatible_with_platform("datafusion") is True
        assert DataFrameTuningType.CHUNK_SIZE.is_compatible_with_platform("datafusion") is True
        assert DataFrameTuningType.STREAMING_MODE.is_compatible_with_platform("datafusion") is False

    def test_is_compatible_with_platform_dask(self):
        """Test Dask platform compatibility."""
        # Compatible with Dask
        assert DataFrameTuningType.WORKER_COUNT.is_compatible_with_platform("dask") is True
        assert DataFrameTuningType.THREADS_PER_WORKER.is_compatible_with_platform("dask") is True
        assert DataFrameTuningType.MEMORY_LIMIT.is_compatible_with_platform("dask") is True
        assert DataFrameTuningType.SPILL_TO_DISK.is_compatible_with_platform("dask") is True

    def test_is_compatible_with_platform_cudf(self):
        """Test cuDF platform compatibility."""
        # Compatible with cuDF
        assert DataFrameTuningType.GPU_DEVICE.is_compatible_with_platform("cudf") is True
        assert DataFrameTuningType.GPU_POOL_TYPE.is_compatible_with_platform("cudf") is True
        assert DataFrameTuningType.GPU_SPILL_TO_HOST.is_compatible_with_platform("cudf") is True

    def test_is_compatible_with_platform_modin(self):
        """Test Modin platform compatibility."""
        # Compatible with Modin
        assert DataFrameTuningType.WORKER_COUNT.is_compatible_with_platform("modin") is True
        assert DataFrameTuningType.ENGINE_AFFINITY.is_compatible_with_platform("modin") is True

    def test_is_compatible_with_platform_case_insensitive(self):
        """Test that platform name matching is case-insensitive."""
        assert DataFrameTuningType.THREAD_COUNT.is_compatible_with_platform("POLARS") is True
        assert DataFrameTuningType.THREAD_COUNT.is_compatible_with_platform("Polars") is True

    def test_is_compatible_with_platform_strips_df_suffix(self):
        """Test that -df suffix is stripped from platform names."""
        assert DataFrameTuningType.THREAD_COUNT.is_compatible_with_platform("polars-df") is True
        assert DataFrameTuningType.WORKER_COUNT.is_compatible_with_platform("dask-df") is True

    def test_compatible_with_multiple_platforms(self):
        """Test that settings are compatible with multiple platforms."""
        # THREAD_COUNT should be compatible with Polars and Modin
        assert DataFrameTuningType.THREAD_COUNT.is_compatible_with_platform("polars") is True
        assert DataFrameTuningType.THREAD_COUNT.is_compatible_with_platform("modin") is True

        # GPU_DEVICE should only be compatible with cuDF
        assert DataFrameTuningType.GPU_DEVICE.is_compatible_with_platform("cudf") is True
        assert DataFrameTuningType.GPU_DEVICE.is_compatible_with_platform("polars") is False


class TestGetAllPlatforms:
    """Tests for get_all_platforms() function."""

    def test_returns_all_platforms(self):
        """Test that all expected platforms are returned."""
        platforms = get_all_platforms()
        assert "polars" in platforms
        assert "datafusion" in platforms
        assert "pandas" in platforms
        assert "dask" in platforms
        assert "modin" in platforms
        assert "cudf" in platforms

    def test_returns_list(self):
        """Test that return type is a list."""
        platforms = get_all_platforms()
        assert isinstance(platforms, list)
