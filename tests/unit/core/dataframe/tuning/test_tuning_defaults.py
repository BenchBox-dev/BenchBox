"""Unit tests for DataFrame tuning defaults.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import pytest

from benchbox.core.dataframe.tuning import (
    DataFrameTuningConfiguration,
    SystemProfile,
    detect_system_profile,
    get_profile_summary,
    get_smart_defaults,
)

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


class TestSystemProfile:
    """Tests for SystemProfile dataclass."""

    def test_default_values(self):
        """Test default values."""
        profile = SystemProfile(cpu_cores=4, available_memory_gb=8.0)
        assert profile.cpu_cores == 4
        assert profile.available_memory_gb == 8.0
        assert profile.has_gpu is False
        assert profile.gpu_memory_gb == 0.0
        assert profile.gpu_device_count == 0

    def test_with_gpu(self):
        """Test profile with GPU."""
        profile = SystemProfile(
            cpu_cores=8,
            available_memory_gb=32.0,
            has_gpu=True,
            gpu_memory_gb=16.0,
            gpu_device_count=2,
        )
        assert profile.has_gpu is True
        assert profile.gpu_memory_gb == 16.0
        assert profile.gpu_device_count == 2


class TestDetectSystemProfile:
    """Tests for detect_system_profile() function."""

    def test_returns_system_profile(self):
        """Test that detect_system_profile returns valid profile."""
        profile = detect_system_profile()
        assert isinstance(profile, SystemProfile)
        assert profile.cpu_cores >= 1
        assert profile.available_memory_gb > 0


class TestGetProfileSummary:
    """Tests for get_profile_summary() function."""

    def test_low_memory_category(self):
        """Test low memory category."""
        profile = SystemProfile(cpu_cores=4, available_memory_gb=2.0)
        summary = get_profile_summary(profile)
        assert summary["memory_category"] == "very_low"

    def test_medium_memory_category(self):
        """Test medium memory category."""
        profile = SystemProfile(cpu_cores=8, available_memory_gb=16.0)
        summary = get_profile_summary(profile)
        assert summary["memory_category"] == "medium"

    def test_high_memory_category(self):
        """Test high memory category."""
        profile = SystemProfile(cpu_cores=16, available_memory_gb=64.0)
        summary = get_profile_summary(profile)
        assert summary["memory_category"] == "high"

    def test_gpu_info_in_summary(self):
        """Test GPU info in summary."""
        profile = SystemProfile(
            cpu_cores=8,
            available_memory_gb=16.0,
            has_gpu=True,
            gpu_memory_gb=8.0,
            gpu_device_count=1,
        )
        summary = get_profile_summary(profile)
        assert summary["has_gpu"] is True
        assert summary["gpu_memory_gb"] == 8.0


class TestGetSmartDefaults:
    """Tests for get_smart_defaults() function."""

    def test_returns_configuration(self):
        """Test that get_smart_defaults returns valid config."""
        config = get_smart_defaults("polars")
        assert isinstance(config, DataFrameTuningConfiguration)

    def test_datafusion_defaults_use_only_supported_controls(self):
        profile = SystemProfile(cpu_cores=6, available_memory_gb=2.0)
        config = get_smart_defaults("datafusion", profile)

        assert config.parallelism.thread_count == 6
        assert config.memory.chunk_size == 50_000
        assert config.execution.streaming_mode is False

    def test_polars_defaults(self):
        """Test Polars-specific defaults."""
        profile = SystemProfile(cpu_cores=8, available_memory_gb=16.0)
        config = get_smart_defaults("polars", profile)

        # Should have lazy evaluation enabled
        assert config.execution.lazy_evaluation is True

    def test_polars_low_memory_defaults(self):
        """Test Polars defaults with low memory."""
        profile = SystemProfile(cpu_cores=4, available_memory_gb=2.0)
        config = get_smart_defaults("polars", profile)

        # Should enable streaming mode
        assert config.execution.streaming_mode is True
        assert config.memory.chunk_size is not None

    def test_polars_high_memory_defaults(self):
        """Test Polars defaults with high memory."""
        profile = SystemProfile(cpu_cores=32, available_memory_gb=128.0)
        config = get_smart_defaults("polars", profile)

        # Should prefer in-memory processing
        assert config.execution.engine_affinity == "in-memory"
        assert config.execution.streaming_mode is False

    def test_pandas_defaults(self):
        """Test Pandas-specific defaults."""
        profile = SystemProfile(cpu_cores=4, available_memory_gb=16.0)
        config = get_smart_defaults("pandas", profile)

        # Should use pyarrow backend with enough memory
        assert config.data_types.dtype_backend == "pyarrow"

    def test_pandas_low_memory_defaults(self):
        """Test Pandas defaults with low memory."""
        profile = SystemProfile(cpu_cores=4, available_memory_gb=4.0)
        config = get_smart_defaults("pandas", profile)

        # Should use numpy_nullable backend
        assert config.data_types.dtype_backend == "numpy_nullable"
        # Should enable memory map
        assert config.io.memory_map is True

    def test_dask_defaults(self):
        """Test Dask-specific defaults."""
        profile = SystemProfile(cpu_cores=8, available_memory_gb=32.0)
        config = get_smart_defaults("dask", profile)

        # Should have worker configuration
        assert config.parallelism.worker_count is not None
        assert config.parallelism.threads_per_worker is not None
        assert config.memory.memory_limit is not None

    def test_modin_defaults(self):
        """Test Modin-specific defaults."""
        profile = SystemProfile(cpu_cores=8, available_memory_gb=16.0)
        config = get_smart_defaults("modin", profile)

        # Should default to ray engine
        assert config.execution.engine_affinity == "ray"

    def test_cudf_defaults(self):
        """Test cuDF-specific defaults."""
        profile = SystemProfile(
            cpu_cores=8,
            available_memory_gb=32.0,
            has_gpu=True,
            gpu_memory_gb=16.0,
            gpu_device_count=1,
        )
        config = get_smart_defaults("cudf", profile)

        # Should enable GPU
        assert config.gpu.enabled is True
        assert config.gpu.device_id == 0

    def test_cudf_small_gpu_defaults(self):
        """Test cuDF defaults with small GPU memory."""
        profile = SystemProfile(
            cpu_cores=8,
            available_memory_gb=32.0,
            has_gpu=True,
            gpu_memory_gb=4.0,
            gpu_device_count=1,
        )
        config = get_smart_defaults("cudf", profile)

        # Should enable spill to host with small GPU
        assert config.gpu.spill_to_host is True
        assert config.gpu.pool_type == "managed"

    def test_platform_normalization(self):
        """Test that platform names are normalized."""
        config1 = get_smart_defaults("POLARS")
        config2 = get_smart_defaults("polars-df")

        # Both should work
        assert isinstance(config1, DataFrameTuningConfiguration)
        assert isinstance(config2, DataFrameTuningConfiguration)

    def test_auto_detect_profile(self):
        """Test that profile is auto-detected when not provided."""
        config = get_smart_defaults("polars")
        assert config.metadata is not None
        assert config.metadata.platform == "polars"

    def test_metadata_included(self):
        """Test that metadata is included in returned config."""
        config = get_smart_defaults("dask")
        assert config.metadata is not None
        assert config.metadata.generated_by == "benchbox-smart-defaults"
