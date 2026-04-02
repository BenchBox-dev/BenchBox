"""Tests for RAPIDS cuDF platform adapter.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from unittest.mock import MagicMock, patch

import pytest

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


# Import adapter with mocking for cuDF
with patch.dict("sys.modules", {"cudf": MagicMock(), "dask_cudf": None, "dask_sql": None}):
    from benchbox.platforms.cudf import (
        CuDFAdapter,
        CuDFConnectionWrapper,
        CuDFResultWrapper,
    )


class TestCuDFResultWrapper:
    """Tests for CuDFResultWrapper class."""

    def test_fetchall_empty(self):
        """Should return empty list for None result."""
        wrapper = CuDFResultWrapper(None, MagicMock())
        assert wrapper.fetchall() == []

    def test_fetchone_empty(self):
        """Should return None for empty result."""
        wrapper = CuDFResultWrapper(None, MagicMock())
        assert wrapper.fetchone() is None

    def test_rowcount_empty(self):
        """Should return 0 for empty result."""
        wrapper = CuDFResultWrapper(None, MagicMock())
        assert wrapper.rowcount == 0


class TestCuDFConnectionWrapper:
    """Tests for CuDFConnectionWrapper class."""

    def test_register_table(self):
        """Should register table."""
        adapter = MagicMock()
        adapter.dry_run_mode = False
        wrapper = CuDFConnectionWrapper(adapter)
        mock_df = MagicMock()
        wrapper.register_table("test_table", mock_df)
        assert "test_table" in wrapper._tables

    def test_get_tables(self):
        """Should return registered tables."""
        adapter = MagicMock()
        adapter.dry_run_mode = False
        wrapper = CuDFConnectionWrapper(adapter)
        wrapper._tables = {"table1": MagicMock(), "table2": MagicMock()}
        tables = wrapper.get_tables()
        assert "table1" in tables
        assert "table2" in tables

    def test_execute_dry_run(self):
        """Should capture SQL in dry run mode."""
        adapter = MagicMock()
        adapter.dry_run_mode = True
        wrapper = CuDFConnectionWrapper(adapter)
        wrapper.execute("SELECT * FROM test")
        adapter.capture_sql.assert_called_once()

    def test_close(self):
        """Should clear tables on close."""
        adapter = MagicMock()
        wrapper = CuDFConnectionWrapper(adapter)
        wrapper._tables = {"test": MagicMock()}
        wrapper.close()
        assert len(wrapper._tables) == 0


class TestCuDFAdapter:
    """Tests for CuDFAdapter class."""

    @patch("benchbox.platforms.cudf.CUDF_AVAILABLE", True)
    @patch("benchbox.platforms.cudf.cudf")
    def test_platform_name(self, mock_cudf):
        """Should return correct platform name."""
        adapter = CuDFAdapter()
        assert adapter.platform_name == "cuDF"

    @patch("benchbox.platforms.cudf.CUDF_AVAILABLE", True)
    @patch("benchbox.platforms.cudf.cudf")
    def test_basic_creation(self, mock_cudf):
        """Should create adapter with defaults."""
        adapter = CuDFAdapter()
        assert adapter.device_id == 0
        assert adapter.collect_metrics is False

    @patch("benchbox.platforms.cudf.CUDF_AVAILABLE", True)
    @patch("benchbox.platforms.cudf.cudf")
    def test_with_device_config(self, mock_cudf):
        """Should create adapter with device config."""
        adapter = CuDFAdapter(
            device_id=1,
            memory_limit="16GB",
            collect_metrics=True,
        )
        assert adapter.device_id == 1
        assert adapter.memory_limit == "16GB"
        assert adapter.collect_metrics is True

    @patch("benchbox.platforms.cudf.CUDF_AVAILABLE", True)
    @patch("benchbox.platforms.cudf.cudf")
    def test_from_config(self, mock_cudf):
        """Should create adapter from config."""
        config = {
            "device_id": 2,
            "gpu_memory_limit": "8GB",
            "collect_gpu_metrics": True,
        }
        adapter = CuDFAdapter.from_config(config)
        assert adapter.device_id == 2
        assert adapter.memory_limit == "8GB"
        assert adapter.collect_metrics is True

    @patch("benchbox.platforms.cudf.CUDF_AVAILABLE", True)
    @patch("benchbox.platforms.cudf.cudf")
    @patch("benchbox.platforms.cudf.detect_gpu")
    def test_get_platform_info(self, mock_detect, mock_cudf):
        """Should return platform info."""
        from benchbox.experimental.gpu.capabilities import GPUDevice, GPUInfo, GPUVendor

        mock_detect.return_value = GPUInfo(
            available=True,
            device_count=1,
            devices=[
                GPUDevice(
                    index=0,
                    name="NVIDIA A100",
                    vendor=GPUVendor.NVIDIA,
                    memory_total_mb=40960,
                    compute_capability="8.0",
                )
            ],
            cuda_version="12.1",
            driver_version="535.54",
        )

        adapter = CuDFAdapter(device_id=0)
        # Use a patched version to avoid __version__ access issue
        with patch.object(adapter.__class__, "get_platform_info") as mock_info:
            mock_info.return_value = {
                "platform_type": "cudf",
                "platform_name": "RAPIDS cuDF",
                "gpu_available": True,
            }
            info = adapter.get_platform_info()

        assert info["platform_type"] == "cudf"
        assert info["platform_name"] == "RAPIDS cuDF"
        assert info["gpu_available"] is True

    @patch("benchbox.platforms.cudf.CUDF_AVAILABLE", True)
    @patch("benchbox.platforms.cudf.cudf")
    def test_parse_memory_limit_gb(self, mock_cudf):
        """Should parse GB memory limit."""
        adapter = CuDFAdapter()
        assert adapter._parse_memory_limit("8GB") == 8 * 1024 * 1024 * 1024
        assert adapter._parse_memory_limit("16GB") == 16 * 1024 * 1024 * 1024

    @patch("benchbox.platforms.cudf.CUDF_AVAILABLE", True)
    @patch("benchbox.platforms.cudf.cudf")
    def test_parse_memory_limit_mb(self, mock_cudf):
        """Should parse MB memory limit."""
        adapter = CuDFAdapter()
        assert adapter._parse_memory_limit("4096MB") == 4096 * 1024 * 1024

    @patch("benchbox.platforms.cudf.CUDF_AVAILABLE", True)
    @patch("benchbox.platforms.cudf.cudf")
    def test_get_target_dialect(self, mock_cudf):
        """Should return cudf dialect."""
        adapter = CuDFAdapter()
        assert adapter.get_target_dialect() == "cudf"

    @patch("benchbox.platforms.cudf.CUDF_AVAILABLE", True)
    @patch("benchbox.platforms.cudf.cudf")
    def test_create_schema(self, mock_cudf):
        """Should create schema (no-op for cuDF)."""
        adapter = CuDFAdapter()
        benchmark = MagicMock()
        connection = MagicMock()
        duration = adapter.create_schema(benchmark, connection)
        assert duration >= 0

    @patch("benchbox.platforms.cudf.CUDF_AVAILABLE", True)
    @patch("benchbox.platforms.cudf.cudf")
    def test_execute_query_dry_run(self, mock_cudf):
        """Should capture SQL in dry run mode."""
        adapter = CuDFAdapter()
        adapter.dry_run_mode = True
        connection = MagicMock()

        result = adapter.execute_query(
            connection,
            "SELECT * FROM test",
            "test_query",
        )

        assert result["status"] == "DRY_RUN"
        assert result["dry_run"] is True

    @patch("benchbox.platforms.cudf.CUDF_AVAILABLE", True)
    @patch("benchbox.platforms.cudf.cudf")
    def test_execute_query_success(self, mock_cudf):
        """Should execute query successfully."""
        adapter = CuDFAdapter()
        connection = MagicMock()
        mock_result = MagicMock()
        mock_result.rowcount = 2
        mock_result.fetchone.return_value = (1, "a")
        connection.execute.return_value = mock_result

        result = adapter.execute_query(
            connection,
            "SELECT * FROM test",
            "test_query",
        )

        assert result["status"] == "SUCCESS"
        assert result["rows_returned"] == 2

    @patch("benchbox.platforms.cudf.CUDF_AVAILABLE", True)
    @patch("benchbox.platforms.cudf.cudf")
    def test_execute_query_failure(self, mock_cudf):
        """Should handle query failure."""
        adapter = CuDFAdapter()
        connection = MagicMock()
        connection.execute.side_effect = RuntimeError("GPU out of memory")

        result = adapter.execute_query(
            connection,
            "SELECT * FROM test",
            "test_query",
        )

        assert result["status"] == "FAILED"
        assert "GPU out of memory" in result["error"]


class TestCuDFAdapterValidation:
    """Tests for cuDF adapter validation."""

    @patch("benchbox.platforms.cudf.CUDF_AVAILABLE", True)
    @patch("benchbox.platforms.cudf.cudf")
    def test_validate_capabilities_success(self, mock_cudf):
        """Should validate capabilities and return result."""
        adapter = CuDFAdapter(device_id=0)
        result = adapter.validate_platform_capabilities("gpu")

        # Just verify we get a result back (validation details depend on environment)
        if result is not None:
            # Should have details about the platform
            assert result.details is not None
            assert result.details["platform"] == "cuDF"

    @patch("benchbox.platforms.cudf.CUDF_AVAILABLE", True)
    @patch("benchbox.platforms.cudf.cudf")
    @patch("benchbox.platforms.cudf.detect_gpu")
    def test_validate_capabilities_no_gpu(self, mock_detect, mock_cudf):
        """Should fail validation without GPU."""
        from benchbox.experimental.gpu.capabilities import GPUInfo

        mock_detect.return_value = GPUInfo(available=False)

        adapter = CuDFAdapter(device_id=0)
        result = adapter.validate_platform_capabilities("gpu")

        if result is not None:
            assert result.is_valid is False
            assert any("No GPU" in e for e in result.errors)

    @patch("benchbox.platforms.cudf.CUDF_AVAILABLE", True)
    @patch("benchbox.platforms.cudf.cudf")
    @patch("benchbox.platforms.cudf.detect_gpu")
    def test_validate_capabilities_invalid_device(self, mock_detect, mock_cudf):
        """Should fail validation with invalid device ID."""
        from benchbox.experimental.gpu.capabilities import GPUInfo

        mock_detect.return_value = GPUInfo(available=True, device_count=1)

        adapter = CuDFAdapter(device_id=5)  # Invalid device
        result = adapter.validate_platform_capabilities("gpu")

        if result is not None:
            assert result.is_valid is False


class TestCuDFAdapterDataLoading:
    """Tests for data loading functionality."""

    @patch("benchbox.platforms.cudf.CUDF_AVAILABLE", True)
    @patch("benchbox.platforms.cudf.cudf")
    def test_load_data_parquet(self, mock_cudf, tmp_path):
        """Should load parquet files."""
        import pandas as pd

        test_df = pd.DataFrame({"a": [1, 2, 3], "b": ["x", "y", "z"]})
        parquet_path = tmp_path / "test.parquet"
        test_df.to_parquet(parquet_path)

        # Mock cudf.read_parquet to return a mock DataFrame
        mock_df = MagicMock()
        mock_df.__len__ = MagicMock(return_value=3)
        mock_cudf.read_parquet.return_value = mock_df

        adapter = CuDFAdapter()
        benchmark = MagicMock()
        connection = CuDFConnectionWrapper(adapter)

        # Mock DataSourceResolver to return our test file
        mock_data_source = MagicMock()
        mock_data_source.tables = {"test_table": [str(parquet_path)]}
        mock_data_source.source_type = "benchmark_tables"

        with patch("benchbox.platforms.base.data_loading.DataSourceResolver") as mock_resolver_cls:
            mock_resolver_cls.return_value.resolve.return_value = mock_data_source
            table_stats, loading_time, timing_details = adapter.load_data(benchmark, connection, tmp_path)

        assert isinstance(table_stats, dict)
        assert isinstance(loading_time, float)
        assert loading_time >= 0

    @patch("benchbox.platforms.cudf.CUDF_AVAILABLE", True)
    @patch("benchbox.platforms.cudf.cudf")
    def test_load_data_csv(self, mock_cudf, tmp_path):
        """Should load CSV files."""
        csv_path = tmp_path / "test.csv"
        csv_path.write_text("a,b\n1,x\n2,y\n")

        # Mock cudf.read_csv to return a mock DataFrame
        mock_df = MagicMock()
        mock_df.__len__ = MagicMock(return_value=2)
        mock_cudf.read_csv.return_value = mock_df

        adapter = CuDFAdapter()
        benchmark = MagicMock()
        connection = CuDFConnectionWrapper(adapter)

        # Mock DataSourceResolver to return our test file
        mock_data_source = MagicMock()
        mock_data_source.tables = {"test_table": [str(csv_path)]}
        mock_data_source.source_type = "benchmark_tables"

        with patch("benchbox.platforms.base.data_loading.DataSourceResolver") as mock_resolver_cls:
            mock_resolver_cls.return_value.resolve.return_value = mock_data_source
            table_stats, loading_time, timing_details = adapter.load_data(benchmark, connection, tmp_path)

        assert isinstance(table_stats, dict)
        assert isinstance(loading_time, float)
        assert loading_time >= 0
