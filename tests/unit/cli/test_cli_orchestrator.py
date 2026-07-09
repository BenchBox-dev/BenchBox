"""Tests for CLI benchmark orchestrator functionality.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from benchbox.cli.orchestrator import BenchmarkOrchestrator
from benchbox.core.results.models import BenchmarkResults
from benchbox.core.schemas import BenchmarkConfig, DatabaseConfig, SystemProfile

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


class TestBenchmarkOrchestrator:
    """Test the BenchmarkOrchestrator class."""

    def setup_method(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.orchestrator = BenchmarkOrchestrator(base_dir=self.temp_dir)

    def teardown_method(self):
        """Clean up test fixtures."""
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_orchestrator_initialization(self):
        """Test BenchmarkOrchestrator initialization."""
        # Test with base directory
        orchestrator = BenchmarkOrchestrator(base_dir="/tmp/test")
        assert orchestrator.directory_manager.base_dir == Path("/tmp/test")
        assert orchestrator.custom_output_dir is None

        # Test without base directory
        orchestrator_default = BenchmarkOrchestrator()
        assert orchestrator_default.directory_manager.base_dir is not None

    def test_set_custom_output_dir(self):
        """Test setting custom output directory."""
        test_dir = "/custom/output/path"
        self.orchestrator.set_custom_output_dir(test_dir)
        assert self.orchestrator.custom_output_dir == test_dir

    @patch("benchbox.cli.orchestrator.run_benchmark_lifecycle")
    @patch("benchbox.cli.orchestrator.get_platform_adapter")
    @patch("benchbox.cli.orchestrator.console")
    def test_execute_benchmark_standard_mode(self, mock_console, mock_get_adapter, mock_lifecycle):
        """Test standard benchmark execution."""
        # Create test config
        config = BenchmarkConfig(name="tpch", display_name="TPC-H", scale_factor=0.01)

        # Create test system profile
        system_profile = Mock(spec=SystemProfile)
        system_profile.cpu_cores_logical = 8
        system_profile.memory_total_gb = 16

        # Create test database config
        database_config = Mock()
        database_config.type = "duckdb"
        database_config.name = "test_db"
        database_config.options = {"tuning_enabled": True}
        database_config.connection_params = {}
        # Mock model_dump() properly
        database_config.model_dump.return_value = {
            "type": "duckdb",
            "name": "test_db",
            "options": {"tuning_enabled": True},
            "connection_params": {},
        }

        # Mock benchmark instance
        mock_benchmark = Mock()
        mock_benchmark._name = "tpch"
        mock_benchmark.scale_factor = 0.01
        mock_benchmark.generate_data.return_value = {"customer": "customer.csv"}

        # Mock the centralized result creation method to return BenchmarkResults
        def mock_create_enhanced_result(platform, query_results, **kwargs):
            from datetime import datetime

            from benchbox.core.results.models import BenchmarkResults

            return BenchmarkResults(
                benchmark_name="TPC-H",
                platform=platform,
                scale_factor=0.01,
                execution_id="test123",
                timestamp=datetime.now(),
                duration_seconds=kwargs.get("duration_seconds", 1.0),
                query_definitions={},
                execution_phases=kwargs.get("phases", {}),
                total_queries=1,
                successful_queries=1,
                failed_queries=0,
                total_execution_time=1.5,
                average_query_time=1.5,
                validation_status="PASSED",
                validation_details={},
            )

        mock_benchmark.create_enhanced_benchmark_result = mock_create_enhanced_result

        # Mock platform adapter
        mock_adapter = Mock()
        mock_adapter.platform_name = "duckdb"
        mock_adapter.create_connection.return_value = Mock()
        mock_adapter.create_schema.return_value = 0.1
        mock_adapter.load_data.return_value = ({"customer": 1000}, 0.5, None)
        mock_adapter.configure_for_benchmark.return_value = None
        mock_adapter.run_benchmark.return_value = mock_benchmark.create_enhanced_benchmark_result("duckdb", [])

        mock_get_adapter.return_value = mock_adapter

        # Return a ready BenchmarkResults from lifecycle to avoid deep core coupling
        mock_lifecycle.return_value = mock_benchmark.create_enhanced_benchmark_result("duckdb", [])

        with patch.object(self.orchestrator, "_get_benchmark_instance", return_value=mock_benchmark):
            with patch.object(self.orchestrator, "_get_platform_config", return_value={}):
                result = self.orchestrator.execute_benchmark(config, system_profile, database_config)

        # Verify result
        assert isinstance(result, BenchmarkResults)
        assert result.benchmark_name == "TPC-H"
        assert result.validation_status == "PASSED"

        # Verify platform adapter was called
        mock_get_adapter.assert_called_once()

    @patch("benchbox.cli.orchestrator.run_benchmark_lifecycle")
    @patch("benchbox.cli.orchestrator.get_platform_adapter")
    def test_execute_benchmark_enriches_driver_metadata_on_canonical_path(self, mock_get_adapter, mock_lifecycle):
        """Driver metadata is propagated on orchestrator/lifecycle path."""
        config = BenchmarkConfig(name="tpch", display_name="TPC-H", scale_factor=0.01)
        system_profile = Mock(spec=SystemProfile)
        system_profile.cpu_cores_logical = 8
        system_profile.memory_total_gb = 16

        database_config = DatabaseConfig(
            type="duckdb",
            name="DuckDB",
            driver_package="duckdb",
            driver_version="1.0.0",
            driver_auto_install=True,
        )

        mock_benchmark = Mock()
        mock_benchmark._name = "tpch"
        mock_benchmark.scale_factor = 0.01
        mock_benchmark.generate_data.return_value = {"customer": "customer.csv"}

        mock_result = BenchmarkResults(
            benchmark_name="TPC-H",
            platform="duckdb",
            scale_factor=0.01,
            execution_id="test123",
            timestamp=datetime.now(),
            duration_seconds=1.0,
            query_definitions={},
            total_queries=1,
            successful_queries=1,
            failed_queries=0,
            total_execution_time=1.0,
            average_query_time=1.0,
            validation_status="PASSED",
            validation_details={},
            execution_metadata={},
        )

        mock_adapter = Mock()
        mock_adapter.driver_package = "duckdb"
        mock_adapter.driver_version_requested = "1.1.0"
        mock_adapter.driver_version_resolved = "1.1.0"
        mock_adapter.driver_version_actual = "1.1.0"
        mock_adapter.driver_runtime_strategy = "isolated-site-packages"
        mock_adapter.driver_runtime_path = "/tmp/runtime"
        mock_adapter.driver_runtime_python_executable = "/tmp/runtime/bin/python"
        mock_adapter.driver_auto_install_used = True
        mock_get_adapter.return_value = mock_adapter
        mock_lifecycle.return_value = mock_result

        with patch.object(self.orchestrator, "_get_benchmark_instance", return_value=mock_benchmark):
            result = self.orchestrator.execute_benchmark(config, system_profile, database_config)

        assert result.driver_version_resolved == "1.1.0"
        assert result.driver_runtime_strategy == "isolated-site-packages"
        assert result.execution_metadata["driver_version_resolved"] == "1.1.0"
        assert result.execution_metadata["driver_auto_install_used"] is True

    def test_execute_benchmark_data_only_mode(self):
        """Test data-only benchmark execution."""
        # Create test config with data_only execution type
        config = BenchmarkConfig(
            name="tpch",
            display_name="TPC-H",
            scale_factor=0.01,
            test_execution_type="data_only",
        )

        system_profile = Mock(spec=SystemProfile)
        system_profile.cpu_cores_logical = 4
        system_profile.memory_total_gb = 8

        # Create minimal execution phases for data-only mode
        from benchbox.platforms.base import (
            DataGenerationPhase,
            ExecutionPhases,
            SetupPhase,
            TableGenerationStats,
        )

        setup_phase = SetupPhase(
            data_generation=DataGenerationPhase(
                duration_ms=1500,
                status="SUCCESS",
                tables_generated=8,
                total_rows_generated=100,
                total_data_size_bytes=1024 * 1024,
                per_table_stats={
                    "test_table": TableGenerationStats(
                        generation_time_ms=200,
                        status="SUCCESS",
                        rows_generated=100,
                        data_size_bytes=1024 * 1024,
                        file_path="test.csv",
                    )
                },
            )
        )

        execution_phases = ExecutionPhases(setup=setup_phase)

        # Create a mock enhanced result to return from the benchmark
        mock_enhanced_result = BenchmarkResults(
            benchmark_name="TPC-H",
            platform="data_only",
            scale_factor=0.01,
            execution_id="test-exec-123",
            timestamp=datetime.now(),
            duration_seconds=1.5,
            query_definitions={},
            execution_phases=execution_phases,
            total_queries=1,
            successful_queries=1,
            failed_queries=0,
            total_execution_time=1.5,
            average_query_time=1.5,
            test_execution_type="data_only",
        )

        # Mock benchmark instance
        mock_benchmark = Mock()
        mock_benchmark._name = "tpch"
        mock_benchmark.scale_factor = 0.01
        mock_benchmark.generate_data.return_value = ["file1.csv", "file2.csv"]
        mock_benchmark.create_enhanced_benchmark_result.return_value = mock_enhanced_result

        with patch.object(self.orchestrator, "_get_benchmark_instance", return_value=mock_benchmark):
            with patch("benchbox.cli.orchestrator.console"):
                result = self.orchestrator.execute_benchmark(config, system_profile, None)

        # Verify result structure
        assert isinstance(result, BenchmarkResults)
        assert result.benchmark_name == "TPC-H"

    def test_execute_benchmark_with_error(self):
        """Test benchmark execution with error handling."""
        config = BenchmarkConfig(name="invalid", display_name="Invalid")
        system_profile = Mock(spec=SystemProfile)
        database_config = Mock()

        # Mock benchmark instance to raise exception
        with patch.object(self.orchestrator, "_get_benchmark_instance") as mock_get_bench:
            mock_get_bench.side_effect = ValueError("Unknown benchmark: invalid")

            result = self.orchestrator.execute_benchmark(config, system_profile, database_config)

        # Verify error result
        assert result.validation_status == "FAILED"
        assert "Unknown benchmark: invalid" in result.validation_details["error"]

    def test_get_benchmark_instance_success(self):
        """Test successful benchmark instance creation."""
        config = BenchmarkConfig(name="tpch", display_name="TPC-H", scale_factor=0.01)
        system_profile = Mock()
        system_profile.cpu_cores_logical = 4

        # Mock the _get_benchmark_class method to return a mock class
        mock_benchmark_class = Mock()
        mock_instance = Mock()
        mock_benchmark_class.return_value = mock_instance

        with patch.object(self.orchestrator, "_get_benchmark_class", return_value=mock_benchmark_class):
            result = self.orchestrator._get_benchmark_instance(config, system_profile)
            assert result == mock_instance

    def test_get_benchmark_instance_with_compression(self):
        """Test benchmark instance creation with compression settings."""
        config = BenchmarkConfig(
            name="tpch",
            display_name="TPC-H",
            scale_factor=0.1,
            compress_data=True,
            compression_type="zstd",
            compression_level=9,
        )
        system_profile = Mock()
        system_profile.cpu_cores_logical = 8

        # Mock the _get_benchmark_class method to return a mock class
        mock_benchmark_class = Mock()
        mock_instance = Mock()
        mock_benchmark_class.return_value = mock_instance

        with patch.object(self.orchestrator, "_get_benchmark_class", return_value=mock_benchmark_class):
            result = self.orchestrator._get_benchmark_instance(config, system_profile)
            assert result == mock_instance

            # Verify the expected subset of parameters was passed
            called_kwargs = mock_benchmark_class.call_args.kwargs
            assert called_kwargs["parallel"] == 8
            assert called_kwargs["scale_factor"] == 0.1
            assert called_kwargs["compress_data"] is True
            assert called_kwargs["compression_type"] == "zstd"
            assert called_kwargs["compression_level"] == 9

    def test_get_benchmark_instance_fallback_no_parallel(self):
        """Test benchmark instance creation for benchmarks without parallel support."""
        config = BenchmarkConfig(name="read_primitives", display_name="Primitives", scale_factor=1.0)
        system_profile = Mock()
        system_profile.cpu_cores_logical = 4

        class NoParallelBenchmark:
            def __init__(
                self,
                *,
                scale_factor,
                compress_data,
                compression_type,
                compression_level,
                verbose,
                quiet,
            ):
                self.kwargs = {
                    "scale_factor": scale_factor,
                    "compress_data": compress_data,
                    "compression_type": compression_type,
                    "compression_level": compression_level,
                    "verbose": verbose,
                    "quiet": quiet,
                }

        with patch.object(self.orchestrator, "_get_benchmark_class", return_value=NoParallelBenchmark):
            result = self.orchestrator._get_benchmark_instance(config, system_profile)
            assert isinstance(result, NoParallelBenchmark)
            assert result.kwargs["scale_factor"] == 1.0
            assert "parallel" not in result.kwargs

    def test_get_benchmark_instance_unknown_benchmark(self):
        """Test unknown benchmark handling."""
        config = BenchmarkConfig(name="unknown", display_name="Unknown")
        system_profile = Mock()

        with pytest.raises(ValueError) as exc_info:
            self.orchestrator._get_benchmark_instance(config, system_profile)

        assert "Benchmark 'unknown' not supported yet" in str(exc_info.value)

    def test_get_platform_config(self):
        """Test platform configuration extraction."""
        database_config = Mock()
        database_config.type = "duckdb"
        database_config.name = "test_db"
        database_config.connection_params = {"host": "localhost", "port": 5432}
        database_config.options = {"tuning_enabled": True, "force_recreate": False}
        # Mock model_dump() to return the config dict
        database_config.model_dump.return_value = {
            "type": "duckdb",
            "name": "test_db",
            "connection_params": {"host": "localhost", "port": 5432},
            "options": {"tuning_enabled": True, "force_recreate": False},
        }

        system_profile = Mock()
        system_profile.memory_total_gb = 32.0
        system_profile.cpu_cores_logical = 16

        config = self.orchestrator._get_platform_config(database_config, system_profile)

        # Verify configuration includes all expected elements
        assert config["connection_params"]["host"] == "localhost"
        assert config["connection_params"]["port"] == 5432
        # options dict is included nested
        assert config["options"]["tuning_enabled"] is True
        assert config["options"]["force_recreate"] is False
        assert config["memory_limit"] == "16GB"  # 80% of 32GB, capped at 16GB
        assert config["thread_limit"] == 8  # min(16, 8)
        # database_path is NOT set by get_platform_config() - it's handled by adapter's from_config()
        assert "database_path" not in config

    @patch("benchbox.cli.orchestrator.get_adapter")
    def test_build_platform_adapter_forwards_dataframe_platform_options(self, mock_get_adapter):
        """#1054 review: --platform-option values (e.g. target_partitions=4)
        parsed onto database_config.options must reach the DataFrame adapter
        constructor via get_adapter(), not just DatabaseManager.create_config -
        the adapter construction is what actually controls execution."""
        database_config = Mock()
        database_config.type = "datafusion"
        database_config.options = {"target_partitions": 4}

        from benchbox.core.runner.runner import LifecyclePhases

        adapter = self.orchestrator._build_platform_adapter(
            database_config,
            execution_mode="dataframe",
            output_root="/tmp/out",
            opts={},
            platform_cfg=None,
            benchmark=None,
            phases=LifecyclePhases(generate=False, load=False, execute=True),
            config=Mock(),
        )

        assert adapter is mock_get_adapter.return_value
        call_kwargs = mock_get_adapter.call_args.kwargs
        assert call_kwargs["target_partitions"] == 4

    @patch("benchbox.cli.orchestrator.get_adapter")
    def test_build_platform_adapter_filters_runtime_overrides_from_dataframe_options(self, mock_get_adapter):
        """#1062 review: database_config.options also carries runtime-only
        overrides (verbose, very_verbose, tuning_enabled, force_recreate, ...)
        merged in by PlatformHookRegistry.build_database_config(), not just
        user --platform-option values. Forwarding the whole options dict
        collides with the explicit verbose=/very_verbose= kwargs below
        (TypeError: multiple values for keyword argument) and would pass
        unexpected kwargs to DataFrame adapters' narrow constructors. Only
        keys registered as this platform's --platform-option specs may
        reach get_adapter()."""
        database_config = Mock()
        database_config.type = "datafusion"
        database_config.options = {
            "target_partitions": 4,
            "verbose": True,
            "very_verbose": True,
            "verbose_enabled": True,
            "verbose_level": 2,
            "quiet": False,
            "tuning_enabled": True,
            "force_recreate": False,
            "force_upload": False,
        }

        from benchbox.core.runner.runner import LifecyclePhases

        adapter = self.orchestrator._build_platform_adapter(
            database_config,
            execution_mode="dataframe",
            output_root="/tmp/out",
            opts={},
            platform_cfg=None,
            benchmark=None,
            phases=LifecyclePhases(generate=False, load=False, execute=True),
            config=Mock(),
        )

        assert adapter is mock_get_adapter.return_value
        call_kwargs = mock_get_adapter.call_args.kwargs
        assert call_kwargs["target_partitions"] == 4
        for runtime_only_key in (
            "tuning_enabled",
            "force_recreate",
            "force_upload",
            "verbose_enabled",
            "verbose_level",
            "quiet",
        ):
            assert runtime_only_key not in call_kwargs

    def test_prepare_run_config(self):
        """Test run configuration preparation."""
        config = BenchmarkConfig(
            name="tpch",
            display_name="TPC-H",
            scale_factor=0.1,
            queries=["Q1", "Q2", "Q3"],
            concurrency=2,
            options={"unified_tuning_configuration": {"constraints": True}},
        )

        database_config = Mock()
        database_config.type = "duckdb"

        run_config = self.orchestrator._prepare_run_config(config, database_config)

        # Verify configuration (access dataclass fields directly)
        assert run_config.query_subset == ["Q1", "Q2", "Q3"]
        assert run_config.concurrent_streams == 2
        assert run_config.connection is not None
        assert "database_path" in run_config.connection

    @patch("benchbox.cli.orchestrator.run_benchmark_lifecycle")
    def test_execute_data_only_mode_success(self, mock_lifecycle):
        """Test data-only mode execution success using lifecycle path."""
        config = BenchmarkConfig(name="tpch", display_name="TPC-H", scale_factor=0.01, test_execution_type="data_only")
        system_profile = Mock(spec=SystemProfile)

        # Minimal BenchmarkResults for data-only success
        success = BenchmarkResults(
            benchmark_name="TPC-H",
            platform="data_only",
            scale_factor=0.01,
            execution_id="test",
            timestamp=datetime.now(),
            duration_seconds=1.0,
            query_definitions={},
            execution_phases={},
            total_queries=0,
            successful_queries=0,
            failed_queries=0,
            total_execution_time=0.0,
            average_query_time=0.0,
            test_execution_type="data_only",
        )
        mock_lifecycle.return_value = success

        with patch.object(self.orchestrator, "_get_benchmark_instance", return_value=Mock()):
            result = self.orchestrator.execute_benchmark(config, system_profile, None)
        assert isinstance(result, BenchmarkResults)
        assert result.test_execution_type == "data_only"

    @patch("benchbox.cli.orchestrator.run_benchmark_lifecycle")
    def test_execute_data_only_mode_error(self, mock_lifecycle):
        """Test data-only mode execution error using lifecycle path."""
        config = BenchmarkConfig(name="tpch", display_name="TPC-H", scale_factor=0.01, test_execution_type="data_only")
        system_profile = Mock(spec=SystemProfile)

        failure = BenchmarkResults(
            benchmark_name="TPC-H",
            platform="data_only",
            scale_factor=0.01,
            execution_id="test",
            timestamp=datetime.now(),
            duration_seconds=0.0,
            query_definitions={},
            execution_phases={},
            total_queries=0,
            successful_queries=0,
            failed_queries=0,
            total_execution_time=0.0,
            average_query_time=0.0,
            test_execution_type="data_only",
            validation_status="FAILED",
            validation_details={"error": "Data generation failed"},
        )
        mock_lifecycle.return_value = failure

        with patch.object(self.orchestrator, "_get_benchmark_instance", return_value=Mock()):
            result = self.orchestrator.execute_benchmark(config, system_profile, None)
        assert isinstance(result, BenchmarkResults)
        assert result.validation_status == "FAILED"


class TestBenchmarkOrchestratorIntegration:
    """Test benchmark orchestrator integration scenarios."""

    def setup_method(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.orchestrator = BenchmarkOrchestrator(base_dir=self.temp_dir)

    def teardown_method(self):
        """Clean up test fixtures."""
        shutil.rmtree(self.temp_dir, ignore_errors=True)


class TestBenchmarkOrchestratorErrorHandling:
    """Test orchestrator error handling and edge cases."""

    def setup_method(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.orchestrator = BenchmarkOrchestrator(base_dir=self.temp_dir)

    def teardown_method(self):
        """Clean up test fixtures."""
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_platform_config_without_system_profile(self):
        """Test platform config generation without system profile."""
        database_config = Mock()
        database_config.type = "duckdb"
        database_config.name = "test"
        database_config.connection_params = {"host": "localhost"}
        database_config.options = {"tuning_enabled": True}
        database_config.model_dump.return_value = {
            "type": "duckdb",
            "name": "test",
            "connection_params": {"host": "localhost"},
            "options": {"tuning_enabled": True},
        }

        config = self.orchestrator._get_platform_config(database_config, None)

        assert config["connection_params"]["host"] == "localhost"
        # options are nested
        assert config["options"]["tuning_enabled"] is True
        # database_path is NOT set by get_platform_config() - it's handled by adapter's from_config()
        assert "database_path" not in config
        # Should not have memory_limit or thread_limit without system profile
        assert "memory_limit" not in config
        assert "thread_limit" not in config

    def test_platform_config_without_options(self):
        """Test platform config generation without database options."""
        database_config = Mock()
        database_config.type = "sqlite"
        database_config.name = "test"
        database_config.connection_params = {}
        database_config.options = None  # No options
        database_config.model_dump.return_value = {
            "type": "sqlite",
            "name": "test",
            "connection_params": {},
            "options": None,
        }

        system_profile = Mock()
        system_profile.memory_total_gb = 8.0
        system_profile.cpu_cores_logical = 4

        config = self.orchestrator._get_platform_config(database_config, system_profile)

        # Should still include system-based config
        assert config["memory_limit"] == "6GB"  # 80% of 8GB
        assert config["thread_limit"] == 4  # min(4, 8)
        # SQLite doesn't get database_path by default
        assert "database_path" not in config

    def test_system_profile_attribute_mapping(self):
        """Test that system profile attributes are correctly mapped to platform config.

        This test ensures we use the correct SystemProfile attribute names
        (memory_total_gb, cpu_cores_logical) rather than incorrect names that
        would cause fallback to default values.
        """
        database_config = Mock()
        database_config.connection_params = {}
        database_config.options = {}
        database_config.type = "duckdb"
        database_config.name = "test"

        database_config.model_dump.return_value = {
            "type": "duckdb",
            "name": "test",
            "connection_params": {},
            "options": {},
        }

        # Create a system profile with realistic values
        system_profile = Mock()
        system_profile.memory_total_gb = 16.0  # 16GB system memory
        system_profile.cpu_cores_logical = 10  # 10 logical CPU cores

        config = self.orchestrator._get_platform_config(database_config, system_profile)

        # Verify that actual system resources are used, not fallback defaults
        # Memory: min(int(16 * 0.8), 16) = 12GB (not the 3GB fallback from 4GB default)
        assert config["memory_limit"] == "12GB"

        # Threads: min(10, 8) = 8 (not the 2 thread fallback from 2 CPU default)
        assert config["thread_limit"] == 8

        # Test edge cases with high memory system (should cap at 16GB)
        system_profile.memory_total_gb = 32.0  # 32GB system
        config_high_mem = self.orchestrator._get_platform_config(database_config, system_profile)
        assert config_high_mem["memory_limit"] == "16GB"  # Capped at 16GB max

        # Test system with many CPU cores (should cap at 8 threads)
        system_profile.cpu_cores_logical = 32
        config_high_cpu = self.orchestrator._get_platform_config(database_config, system_profile)
        assert config_high_cpu["thread_limit"] == 8  # Capped at 8 max

    def test_system_profile_fallback_values(self):
        """Test that fallback values are reasonable when system profile attributes are missing.

        This test ensures that if SystemProfile attributes are missing or incorrect,
        we get reasonable fallback values (4GB memory, 2 threads).
        """
        database_config = Mock()
        database_config.type = "duckdb"
        database_config.name = "test"
        database_config.connection_params = {}
        database_config.options = {}
        database_config.model_dump.return_value = {
            "type": "duckdb",
            "name": "test",
            "connection_params": {},
            "options": {},
        }

        # System profile without the expected attributes (simulating old bug)
        # Create a simple object without the expected attributes
        class EmptyProfile:
            pass

        system_profile = EmptyProfile()

        config = self.orchestrator._get_platform_config(database_config, system_profile)

        # Should fall back to defaults: memory_limit from 4GB default, thread_limit from 2 cores default
        assert config["memory_limit"] == "3GB"  # int(4 * 0.8) = 3GB
        assert config["thread_limit"] == 2  # min(2, 8) = 2

    def test_prepare_run_config_minimal(self):
        """Test run configuration preparation with minimal config."""
        config = BenchmarkConfig(name="tpch", display_name="TPC-H", scale_factor=1.0)
        database_config = Mock()
        database_config.type = "duckdb"

        run_config = self.orchestrator._prepare_run_config(config, database_config)

        # Should have connection but no query_subset or concurrent_streams
        assert run_config.connection is not None
        # For dataclass fields that might be None, we check if they're None or have default values
        assert run_config.query_subset is None or run_config.query_subset == []


if __name__ == "__main__":
    pytest.main([__file__])
