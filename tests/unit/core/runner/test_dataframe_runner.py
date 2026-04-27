"""Unit tests for DataFrame benchmark runner.

Tests for:
- DataFrame execution mode detection
- DataFramePhases and DataFrameRunOptions
- run_dataframe_benchmark function
- Mode coexistence (SQL vs DataFrame)

Copyright 2026 Joe Harris / BenchBox Project
"""

from __future__ import annotations

import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from benchbox.core.results.models import BenchmarkResults
from benchbox.core.results.platform_info import PlatformInfoInput
from benchbox.core.runner.dataframe_runner import (
    DataFramePhases,
    DataFrameRunOptions,
    _get_queries_for_benchmark,
    get_execution_mode,
    is_dataframe_execution,
    run_dataframe_benchmark,
)
from benchbox.core.schemas import BenchmarkConfig

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


class TestIsDataFrameExecution:
    """Tests for is_dataframe_execution function."""

    def test_polars_df_is_dataframe(self):
        """Test polars-df is detected as DataFrame mode."""
        assert is_dataframe_execution(types.SimpleNamespace(type="polars-df")) is True

    def test_pandas_df_is_dataframe(self):
        """Test pandas-df is detected as DataFrame mode."""
        assert is_dataframe_execution(types.SimpleNamespace(type="pandas-df")) is True

    def test_duckdb_is_sql(self):
        """Test duckdb is detected as SQL mode."""
        assert is_dataframe_execution(types.SimpleNamespace(type="duckdb")) is False

    def test_polars_without_df_is_sql(self):
        """Test polars (without -df) is SQL mode."""
        assert is_dataframe_execution(types.SimpleNamespace(type="polars")) is False

    def test_none_config(self):
        """Test None config returns False."""
        assert is_dataframe_execution(None) is False

    def test_case_insensitive(self):
        """Test case insensitive detection."""
        assert is_dataframe_execution(types.SimpleNamespace(type="Polars-DF")) is True


class TestGetExecutionMode:
    """Tests for get_execution_mode function."""

    def test_dataframe_mode(self):
        """Test DataFrame platform returns 'dataframe'."""
        assert get_execution_mode(types.SimpleNamespace(type="polars-df")) == "dataframe"

    def test_sql_mode(self):
        """Test SQL platform returns 'sql'."""
        assert get_execution_mode(types.SimpleNamespace(type="duckdb")) == "sql"

    def test_none_returns_sql(self):
        """Test None config returns 'sql'."""
        assert get_execution_mode(None) == "sql"


class TestDataFramePhases:
    """Tests for DataFramePhases dataclass."""

    def test_default_values(self):
        """Test default phase values."""
        phases = DataFramePhases()

        assert phases.load is True
        assert phases.execute is True

    def test_custom_values(self):
        """Test custom phase values."""
        phases = DataFramePhases(load=False, execute=True)

        assert phases.load is False
        assert phases.execute is True


class TestDataFrameRunOptions:
    """Tests for DataFrameRunOptions dataclass."""

    def test_default_values(self):
        """Test default option values."""
        options = DataFrameRunOptions()

        assert options.ignore_memory_warnings is False
        assert options.force_regenerate is False
        assert options.prefer_parquet is True
        assert options.cache_dir is None

    def test_custom_values(self):
        """Test custom option values."""
        options = DataFrameRunOptions(
            ignore_memory_warnings=True,
            force_regenerate=True,
            prefer_parquet=False,
            cache_dir=Path("/tmp/cache"),
        )

        assert options.ignore_memory_warnings is True
        assert options.force_regenerate is True
        assert options.prefer_parquet is False
        assert options.cache_dir == Path("/tmp/cache")


class TestRunDataframeBenchmark:
    """Tests for run_dataframe_benchmark function."""

    def test_returns_benchmark_results(self):
        """Test that function returns BenchmarkResults."""
        from benchbox.core.results.models import BenchmarkResults

        # Mock adapter
        adapter = MagicMock()
        adapter.platform_name = "Polars"
        adapter.create_context.return_value = MagicMock()
        adapter.get_platform_info.return_value = {"platform": "Polars"}
        # Configure StandardPlatformInfo protocol (MagicMock matches @runtime_checkable on Python 3.10)
        adapter.get_standard_platform_info.return_value = PlatformInfoInput(name="Polars", execution_mode="dataframe")

        config = BenchmarkConfig(name="tpch", display_name="TPC-H", scale_factor=0.01)

        # Execute with load=False, execute=False (minimal execution)
        phases = DataFramePhases(load=False, execute=False)

        result = run_dataframe_benchmark(
            benchmark_config=config,
            adapter=adapter,
            phases=phases,
        )

        assert isinstance(result, BenchmarkResults)
        assert result.benchmark_name == "TPC-H"
        assert "Polars" in result.platform
        # Verify DataFrame mode is indicated in platform_info
        assert result.platform_info.get("execution_mode") == "dataframe"

    def test_sets_execution_metadata(self):
        """Test that execution_metadata includes mode info."""
        adapter = MagicMock()
        adapter.platform_name = "Pandas"
        adapter.create_context.return_value = MagicMock()
        adapter.get_platform_info.return_value = {"platform": "Pandas"}
        # Configure StandardPlatformInfo protocol (MagicMock matches @runtime_checkable on Python 3.10)
        adapter.get_standard_platform_info.return_value = PlatformInfoInput(name="Pandas", execution_mode="dataframe")

        config = BenchmarkConfig(name="tpch", display_name="TPC-H", scale_factor=0.01)

        phases = DataFramePhases(load=False, execute=False)

        result = run_dataframe_benchmark(
            benchmark_config=config,
            adapter=adapter,
            phases=phases,
        )

        assert result.execution_metadata is not None
        assert result.execution_metadata["execution_mode"] == "dataframe"
        assert result.execution_metadata["dataframe_platform"] == "Pandas"

    def test_handles_load_failure(self):
        """Test graceful handling of load failure."""
        adapter = MagicMock()
        adapter.platform_name = "Polars"
        adapter.create_context.return_value = MagicMock()
        adapter.get_platform_info.return_value = {}

        config = BenchmarkConfig(name="tpch", display_name="TPC-H", scale_factor=0.01)

        # Load enabled but no data available
        phases = DataFramePhases(load=True, execute=False)

        result = run_dataframe_benchmark(
            benchmark_config=config,
            adapter=adapter,
            phases=phases,
            data_dir=None,  # No data directory
            benchmark_instance=None,  # No benchmark tables
        )

        # Should return failed result, not raise exception
        assert result.validation_status == "FAILED"
        assert result.validation_details is not None
        assert "error" in result.validation_details

    def test_skip_dataframe_data_loading_bypasses_generic_loader(self):
        """Benchmarks with self-managed DataFrame loading must bypass _load_dataframe_data."""
        adapter = MagicMock()
        adapter.platform_name = "Polars"
        adapter.create_context.return_value = MagicMock()
        adapter.get_platform_info.return_value = {"platform": "Polars"}
        adapter.get_standard_platform_info.return_value = PlatformInfoInput(name="Polars", execution_mode="dataframe")

        config = BenchmarkConfig(
            name="metadata_primitives",
            display_name="Metadata",
            scale_factor=1.0,
            options={"power_iterations": 1},
        )

        class BenchmarkWithManagedLoading:
            def skip_dataframe_data_loading(self) -> bool:
                return True

        benchmark_instance = BenchmarkWithManagedLoading()

        with (
            patch("benchbox.core.runner.dataframe_runner._load_dataframe_data") as load_fn,
            patch("benchbox.core.runner.dataframe_runner.check_sufficient_memory") as mem_check,
            patch("benchbox.core.runner.dataframe_runner.validate_scale_factor", return_value=(True, None)),
        ):
            mem_check.return_value = MagicMock(is_safe=True)
            result = run_dataframe_benchmark(
                benchmark_config=config,
                adapter=adapter,
                phases=DataFramePhases(load=True, execute=False),
                benchmark_instance=benchmark_instance,
            )

        load_fn.assert_not_called()
        assert result.validation_status == "PASSED"
        assert result.total_queries == 0

    def test_load_phase_uses_data_loader_preparation_pipeline(self, tmp_path):
        """Data load phase should use DataFrameDataLoader.prepare_benchmark_data."""
        adapter = MagicMock()
        adapter.platform_name = "Polars"
        adapter.create_context.return_value = MagicMock()
        adapter.get_platform_info.return_value = {"platform": "Polars"}
        adapter.get_standard_platform_info.return_value = PlatformInfoInput(name="Polars", execution_mode="dataframe")
        adapter.load_table.return_value = 2

        config = BenchmarkConfig(name="tpch", display_name="TPC-H", scale_factor=1.0)

        benchmark_instance = MagicMock()
        benchmark_instance.name = "tpch"
        benchmark_instance.tables = {
            "lineitem": [tmp_path / "lineitem.tbl.1.zst"],
        }

        prepared = {"lineitem": tmp_path / "lineitem.parquet"}

        with patch("benchbox.core.runner.dataframe_runner.DataFrameDataLoader") as loader_cls:
            loader = loader_cls.return_value
            loader.prepare_benchmark_data.return_value = prepared

            result = run_dataframe_benchmark(
                benchmark_config=config,
                adapter=adapter,
                phases=DataFramePhases(load=True, execute=False),
                benchmark_instance=benchmark_instance,
            )

        assert result.validation_status == "PASSED"
        loader.prepare_benchmark_data.assert_called_once_with(
            benchmark=benchmark_instance,
            scale_factor=1.0,
            data_dir=None,
            write_config=None,
        )
        adapter.load_table.assert_called_once()
        args, kwargs = adapter.load_table.call_args
        assert args[0] == adapter.create_context.return_value
        assert args[1] == "lineitem"
        assert args[2] == [tmp_path / "lineitem.parquet"]
        assert kwargs["column_names"] is not None


def test_get_queries_for_benchmark_ignores_magicmock_synthesized_provider():
    config = BenchmarkConfig(name="dummy", display_name="Dummy", scale_factor=1.0)
    benchmark_instance = MagicMock()
    benchmark_instance.name = "dummy"

    queries = _get_queries_for_benchmark(config, benchmark_instance, stream_id=0)

    assert queries == []


class TestModeCoexistence:
    """Tests for SQL and DataFrame mode coexistence."""

    def test_same_benchmark_different_modes(self):
        """Test same benchmark can be identified for different modes."""
        sql_mode = get_execution_mode(types.SimpleNamespace(type="duckdb"))
        df_mode = get_execution_mode(types.SimpleNamespace(type="polars-df"))

        assert sql_mode == "sql"
        assert df_mode == "dataframe"
        assert sql_mode != df_mode

    def test_platform_naming_convention(self):
        """Test platform naming convention for mode detection."""
        platforms = {
            "duckdb": "sql",
            "sqlite": "sql",
            "datafusion": "sql",
            "polars": "sql",  # Without -df suffix = SQL mode
            "polars-df": "dataframe",
            "pandas-df": "dataframe",
            "snowflake": "sql",
            "bigquery": "sql",
        }

        for platform, expected_mode in platforms.items():
            actual_mode = get_execution_mode(types.SimpleNamespace(type=platform))
            assert actual_mode == expected_mode, f"Platform {platform} expected {expected_mode}, got {actual_mode}"


class TestResultSchemaCompatibility:
    """Tests for result schema compatibility between modes."""

    def test_dataframe_result_has_required_fields(self):
        """Test DataFrame results have all required BenchmarkResults fields."""

        adapter = MagicMock()
        adapter.platform_name = "Polars"
        adapter.create_context.return_value = MagicMock()
        adapter.get_platform_info.return_value = {}

        config = BenchmarkConfig(name="tpch", display_name="TPC-H", scale_factor=0.01)

        phases = DataFramePhases(load=False, execute=False)

        result = run_dataframe_benchmark(
            benchmark_config=config,
            adapter=adapter,
            phases=phases,
        )

        # Check all required BenchmarkResults fields are present
        assert hasattr(result, "benchmark_name")
        assert hasattr(result, "platform")
        assert hasattr(result, "scale_factor")
        assert hasattr(result, "execution_id")
        assert hasattr(result, "timestamp")
        assert hasattr(result, "duration_seconds")
        assert hasattr(result, "total_queries")
        assert hasattr(result, "successful_queries")
        assert hasattr(result, "failed_queries")
        assert hasattr(result, "query_results")
        assert hasattr(result, "validation_status")

    def test_execution_id_format(self):
        """Test execution ID has expected format."""
        adapter = MagicMock()
        adapter.platform_name = "Polars"
        adapter.create_context.return_value = MagicMock()
        adapter.get_platform_info.return_value = {}

        config = BenchmarkConfig(name="tpch", display_name="TPC-H", scale_factor=0.01)

        phases = DataFramePhases(load=False, execute=False)

        result = run_dataframe_benchmark(
            benchmark_config=config,
            adapter=adapter,
            phases=phases,
        )

        # DataFrame execution IDs are 8-character UUID hex strings
        # (df_ prefix was removed to fix filename redundancy)
        assert len(result.execution_id) == 8
        assert all(c in "0123456789abcdef" for c in result.execution_id)


class TestMaintenancePhaseValidation:
    """Tests for maintenance phase validation in DataFrame mode."""

    def test_maintenance_phase_raises_not_implemented(self):
        """Test that maintenance phase raises NotImplementedError in DataFrame mode."""
        adapter = MagicMock()
        adapter.platform_name = "Polars"
        adapter.create_context.return_value = MagicMock()
        adapter.get_platform_info.return_value = {}

        config = BenchmarkConfig(
            name="tpch", display_name="TPC-H", scale_factor=0.01, test_execution_type="maintenance"
        )

        phases = DataFramePhases(load=False, execute=True)

        with pytest.raises(NotImplementedError) as exc_info:
            run_dataframe_benchmark(
                benchmark_config=config,
                adapter=adapter,
                phases=phases,
            )

        # Verify error message is helpful
        assert "Maintenance phase is not yet implemented for DataFrame mode" in str(exc_info.value)
        assert "maintenance" in str(exc_info.value)
        assert "Polars" in str(exc_info.value)

    def test_combined_phase_raises_not_implemented(self):
        """Test that combined phase (queries + maintenance) raises NotImplementedError."""
        adapter = MagicMock()
        adapter.platform_name = "Pandas"
        adapter.create_context.return_value = MagicMock()
        adapter.get_platform_info.return_value = {}

        config = BenchmarkConfig(name="tpcds", display_name="TPC-DS", scale_factor=0.01, test_execution_type="combined")

        phases = DataFramePhases(load=False, execute=True)

        with pytest.raises(NotImplementedError) as exc_info:
            run_dataframe_benchmark(
                benchmark_config=config,
                adapter=adapter,
                phases=phases,
            )

        assert "Maintenance phase is not yet implemented for DataFrame mode" in str(exc_info.value)
        assert "combined" in str(exc_info.value)

    def test_standard_phase_does_not_raise(self):
        """Test that standard execution type works normally."""
        adapter = MagicMock()
        adapter.platform_name = "Polars"
        adapter.create_context.return_value = MagicMock()
        adapter.get_platform_info.return_value = {}

        config = BenchmarkConfig(name="tpch", display_name="TPC-H", scale_factor=0.01)

        # Execute with no load/execute to avoid data requirements
        phases = DataFramePhases(load=False, execute=False)

        # Should not raise
        result = run_dataframe_benchmark(
            benchmark_config=config,
            adapter=adapter,
            phases=phases,
        )

        assert result is not None
        assert result.validation_status in ("PASSED", "FAILED")

    def test_power_phase_does_not_raise(self):
        """Test that power execution type works normally (queries only)."""
        adapter = MagicMock()
        adapter.platform_name = "Polars"
        adapter.create_context.return_value = MagicMock()
        adapter.get_platform_info.return_value = {}

        config = BenchmarkConfig(name="tpch", display_name="TPC-H", scale_factor=0.01, test_execution_type="power")

        phases = DataFramePhases(load=False, execute=False)

        # Should not raise - power test is just queries, no maintenance
        result = run_dataframe_benchmark(
            benchmark_config=config,
            adapter=adapter,
            phases=phases,
        )

        assert result is not None
        assert isinstance(result, BenchmarkResults)

    def test_no_test_execution_type_defaults_to_standard(self):
        """Test that missing test_execution_type defaults to standard (no error)."""
        adapter = MagicMock()
        adapter.platform_name = "Polars"
        adapter.create_context.return_value = MagicMock()
        adapter.get_platform_info.return_value = {}

        # Use SimpleNamespace without test_execution_type to test getattr fallback
        config = types.SimpleNamespace(name="tpch", display_name="TPC-H", scale_factor=0.01)

        phases = DataFramePhases(load=False, execute=False)

        # Should not raise - defaults to "standard"
        result = run_dataframe_benchmark(
            benchmark_config=config,
            adapter=adapter,
            phases=phases,
        )

        assert result is not None
        assert isinstance(result, BenchmarkResults)


class _StubTPCDSQueryManager:
    def get_query(self, query_id, seed=None, variant=None):  # noqa: ANN001
        _ = (query_id, seed, variant)
        return "SELECT 1"


def test_tpcds_dataframe_requires_variant_parity():
    """TPC-DS DataFrame mode must fail if SQL variants are not implemented."""
    config = BenchmarkConfig(name="tpcds", display_name="TPC-DS", options={"tpcds_dataframe_variant_fallback": False})

    benchmark_instance = MagicMock()
    benchmark_instance.query_manager = _StubTPCDSQueryManager()

    with pytest.raises(RuntimeError, match="missing variant DataFrame implementations"):
        _get_queries_for_benchmark(config, benchmark_instance, stream_id=0)
