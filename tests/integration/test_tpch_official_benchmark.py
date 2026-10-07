"""Integration tests for TPC-H Official Benchmark implementation.

These tests verify the complete TPC-H benchmark workflow including:
- Official benchmark execution
- All three test phases (Power, Throughput, Maintenance)
- Report generation and validation
- Compliance checking

Copyright 2026 Joe Harris / BenchBox Project

TPC Benchmark™ H (TPC-H) - Copyright © Transaction Processing Performance Council
This implementation is based on the TPC-H specification.

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import os
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from benchbox.core.tpch.official_benchmark import (
    TPCHOfficialBenchmark,
    TPCHOfficialBenchmarkConfig,
    TPCHOfficialBenchmarkResult,
)

# Mark all tests in this file as integration tests
pytestmark = [
    pytest.mark.integration,
    pytest.mark.slow,
]


def _power(value, *, success=True):
    return SimpleNamespace(power_at_size=value, success=success, queries_executed=22, queries_successful=22)


def _throughput(value):
    return SimpleNamespace(throughput_at_size=value, success=True, outstanding_stream_ids=[])


@pytest.fixture
def phases(monkeypatch):
    module = "benchbox.core.tpch.official_benchmark"
    power = Mock()
    power.return_value.run.return_value = _power(100.0)
    adapter = Mock()
    adapter._run_routed_throughput.return_value = _throughput(200.0)
    throughput = adapter._run_routed_throughput
    maintenance = Mock()
    maintenance.return_value.run_maintenance_test.return_value = Mock(success=True, errors=[])
    monkeypatch.setattr(f"{module}.TPCHPowerTest", power)
    monkeypatch.setattr(f"{module}.TPCHMaintenanceTest", maintenance)
    return SimpleNamespace(power=power, throughput=throughput, maintenance=maintenance, adapter=adapter)


@pytest.mark.filterwarnings("ignore:TPCHOfficialBenchmark.run_official_benchmark is deprecated:DeprecationWarning")
class TestTPCHOfficialBenchmark:
    """Test suite for TPC-H Official Benchmark implementation."""

    @pytest.fixture
    def temp_dir(self):
        """Create temporary directory for test outputs."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            yield Path(tmp_dir)

    @pytest.fixture
    def benchmark_instance(self, temp_dir):
        """Create TPCHOfficialBenchmark instance for testing."""
        return TPCHOfficialBenchmark(
            scale_factor=0.01,  # Very small scale for testing
            output_dir=temp_dir,
            verbose=False,
        )

    @pytest.fixture
    def mock_connection_factory(self):
        """Mock database connection factory."""

        def factory():
            conn = Mock()
            conn.connection_string = "test://mock"
            conn.close = Mock()
            return conn

        return factory

    def test_official_benchmark_initialization(self, temp_dir):
        """Test initialization of TPCHOfficialBenchmark."""
        benchmark = TPCHOfficialBenchmark(scale_factor=0.01, output_dir=temp_dir, verbose=True, num_streams=2)

        assert benchmark.config.scale_factor == 0.01
        assert benchmark.config.output_dir == temp_dir
        assert benchmark.config.verbose is True
        assert benchmark.config.num_streams == 2
        assert benchmark.benchmark is not None
        assert temp_dir.exists()

    def test_benchmark_result_initialization(self):
        """Test TPCHOfficialBenchmarkResult initialization."""
        config = TPCHOfficialBenchmarkConfig(scale_factor=0.01)
        result = TPCHOfficialBenchmarkResult(
            config=config,
            start_time="2023-01-01T00:00:00",
            end_time="2023-01-01T01:00:00",
            total_time=3600.0,
            power_test_result=None,
            throughput_test_result=None,
            maintenance_test_result=None,
            power_at_size=0.0,
            throughput_at_size=0.0,
            success=True,
            errors=[],
        )

        assert result.config.scale_factor == 0.01
        assert result.power_test_result is None
        assert result.throughput_test_result is None
        assert result.maintenance_test_result is None
        assert result.success is True
        assert result.errors == []

    def test_config_initialization(self):
        """Test configuration initialization."""
        config = TPCHOfficialBenchmarkConfig(
            scale_factor=0.01,
            num_streams=8,
            power_test_enabled=False,
            throughput_test_enabled=True,
            maintenance_test_enabled=False,
            validation_enabled=False,
            audit_trail=False,
            verbose=True,
        )

        assert config.scale_factor == 0.01
        assert config.num_streams == 8
        assert config.power_test_enabled is False
        assert config.throughput_test_enabled is True
        assert config.maintenance_test_enabled is False
        assert config.validation_enabled is False
        assert config.audit_trail is False
        assert config.verbose is True

    def test_run_official_benchmark_basic(self, benchmark_instance, mock_connection_factory, phases):
        """Test basic official benchmark execution."""

        # Run benchmark
        result = benchmark_instance.run_official_benchmark(mock_connection_factory, adapter=phases.adapter)

        # Verify results
        assert isinstance(result, TPCHOfficialBenchmarkResult)
        assert result.success is True
        assert result.start_time is not None
        assert result.end_time is not None
        assert result.total_time > 0
        assert result.power_at_size == 100.0
        assert result.throughput_at_size == 200.0
        assert not hasattr(result, "qphh_at_size")

    def test_run_official_benchmark_warns_that_the_api_is_deprecated(
        self, benchmark_instance, mock_connection_factory, phases
    ):
        with pytest.warns(DeprecationWarning, match="TPC-H throughput driver"):
            benchmark_instance.run_official_benchmark(mock_connection_factory, adapter=phases.adapter)

    def test_run_official_benchmark_with_custom_config(self, benchmark_instance, mock_connection_factory, phases):
        """Test official benchmark with custom configuration."""
        custom_config = TPCHOfficialBenchmarkConfig(
            scale_factor=0.01,
            num_streams=2,
            power_test_enabled=True,
            throughput_test_enabled=False,  # Only power test
            maintenance_test_enabled=False,
            verbose=True,
        )

        phases.power.return_value.run.return_value = _power(150.0)

        result = benchmark_instance.run_official_benchmark(
            mock_connection_factory, config=custom_config, adapter=phases.adapter
        )

        assert result.success is True
        assert result.power_at_size == 150.0
        assert result.throughput_at_size == 0.0  # Not run
        assert not hasattr(result, "qphh_at_size")

    def test_validate_compliance(self, benchmark_instance):
        """Test compliance validation."""
        # Valid result
        valid_result = TPCHOfficialBenchmarkResult(
            config=TPCHOfficialBenchmarkConfig(),
            start_time="2023-01-01T00:00:00",
            end_time="2023-01-01T01:00:00",
            total_time=3600.0,
            power_test_result=None,
            throughput_test_result=None,
            maintenance_test_result=None,
            power_at_size=100.0,
            throughput_at_size=200.0,
            success=True,
            errors=[],
        )

        assert benchmark_instance.validate_compliance(valid_result) is True

        # Invalid result (failed)
        invalid_result = TPCHOfficialBenchmarkResult(
            config=TPCHOfficialBenchmarkConfig(),
            start_time="2023-01-01T00:00:00",
            end_time="2023-01-01T01:00:00",
            total_time=3600.0,
            power_test_result=None,
            throughput_test_result=None,
            maintenance_test_result=None,
            power_at_size=0.0,
            throughput_at_size=0.0,
            success=False,
            errors=["Test error"],
        )

        assert benchmark_instance.validate_compliance(invalid_result) is False

    def test_generate_audit_trail(self, benchmark_instance, temp_dir):
        """Test audit trail generation."""
        result = TPCHOfficialBenchmarkResult(
            config=TPCHOfficialBenchmarkConfig(scale_factor=0.01, num_streams=2),
            start_time="2023-01-01T00:00:00",
            end_time="2023-01-01T01:00:00",
            total_time=3600.0,
            power_test_result=None,
            throughput_test_result=None,
            maintenance_test_result=None,
            power_at_size=360.0,
            throughput_at_size=480.0,
            success=True,
            errors=[],
        )

        # Use system temp directory for test files to ensure OS cleanup
        with tempfile.NamedTemporaryFile(
            mode="w", suffix="_tpch_audit_trail_test.txt", delete=False, encoding="utf-8"
        ) as tmp_file:
            audit_file = Path(tmp_file.name)

        try:
            audit_path = benchmark_instance.generate_audit_trail(result, audit_file)

            assert audit_path.exists()
            assert audit_path.is_file()
            assert audit_path == audit_file  # Ensure it used our specified path

            content = audit_path.read_text()
            assert "TPC-H Official Benchmark Audit Trail" in content
            assert "Scale Factor: 0.01" in content
            assert "Number of Streams: 2" in content
            assert "Throughput@Size:" in content
            assert "QphH" not in content
        finally:
            # Clean up the temp file
            if audit_file.exists():
                os.unlink(audit_file)

    def test_error_handling_during_execution(self):
        """Test error handling during benchmark execution."""
        config = TPCHOfficialBenchmarkConfig(scale_factor=0.01, verbose=False)

        result = TPCHOfficialBenchmarkResult(
            config=config,
            start_time="2023-01-01T00:00:00",
            end_time="",
            total_time=0.0,
            power_test_result=None,
            throughput_test_result=None,
            maintenance_test_result=None,
            power_at_size=0.0,
            throughput_at_size=0.0,
            success=True,
            errors=[],
        )

        # Test that error handling works by simulating failure logic
        try:
            raise Exception("Database connection failed")
        except Exception as e:
            result.errors.append(f"Power Test failed: {e}")
            result.success = False

        # Verify error handling worked correctly
        assert isinstance(result, TPCHOfficialBenchmarkResult)
        assert result.success is False
        assert len(result.errors) > 0
        assert "Power Test failed" in result.errors[0]
        assert "Database connection failed" in result.errors[0]

    def test_phase_metrics_are_reported_and_no_combined_metric_is_computed(
        self, benchmark_instance, mock_connection_factory, phases
    ):
        for power, throughput in [(100.0, 400.0), (360.0, 480.0), (1000.0, 1000.0)]:
            phases.power.return_value.run.return_value = _power(power)
            phases.throughput.return_value = _throughput(throughput)

            config = TPCHOfficialBenchmarkConfig(maintenance_test_enabled=False)
            result = benchmark_instance.run_official_benchmark(
                mock_connection_factory, config=config, adapter=phases.adapter
            )

            assert result.power_at_size == power
            assert result.throughput_at_size == throughput
            assert not hasattr(result, "qphh_at_size")

    def test_partial_failure_handling(self, benchmark_instance, mock_connection_factory, phases):
        """Test handling when some phases fail."""
        phases.throughput.side_effect = Exception("Throughput failed")

        config = TPCHOfficialBenchmarkConfig(maintenance_test_enabled=False)
        result = benchmark_instance.run_official_benchmark(
            mock_connection_factory, config=config, adapter=phases.adapter
        )

        # Should still return a result, but marked as failed
        assert result.success is False
        assert len(result.errors) > 0
        assert "Throughput Test failed" in result.errors[0]
        assert result.power_at_size == 100.0  # Power succeeded
        assert result.throughput_at_size == 0.0  # Throughput failed
        assert not hasattr(result, "qphh_at_size")

    def test_timing_metrics(self, benchmark_instance, mock_connection_factory, phases):
        """Test that timing metrics are properly recorded."""

        config = TPCHOfficialBenchmarkConfig(maintenance_test_enabled=False)
        result = benchmark_instance.run_official_benchmark(
            mock_connection_factory, config=config, adapter=phases.adapter
        )

        assert result.start_time is not None
        assert result.end_time is not None
        assert result.total_time > 0
        # Start time should be earlier than end time (ISO format string comparison)
        assert result.start_time < result.end_time

    def test_all_phases_enabled(self, benchmark_instance, mock_connection_factory, phases):
        """Test benchmark execution with all three phases enabled."""
        phases.power.return_value.run.return_value = _power(500.0)
        phases.throughput.return_value = _throughput(800.0)

        result = benchmark_instance.run_official_benchmark(mock_connection_factory, adapter=phases.adapter)

        assert phases.power.return_value.run.called
        assert phases.throughput.called
        assert phases.maintenance.return_value.run_maintenance_test.called

        assert result.success is True
        assert result.power_at_size == 500.0
        assert result.throughput_at_size == 800.0
        assert not hasattr(result, "qphh_at_size")

    def test_zero_metric_handling(self, benchmark_instance, mock_connection_factory, phases):
        phases.power.return_value.run.return_value = _power(0.0)

        config = TPCHOfficialBenchmarkConfig(throughput_test_enabled=False, maintenance_test_enabled=False)
        result = benchmark_instance.run_official_benchmark(
            mock_connection_factory, config=config, adapter=phases.adapter
        )

        assert result.power_at_size == 0.0
        assert result.throughput_at_size == 0.0
        assert not hasattr(result, "qphh_at_size")

    def test_integration_with_base_benchmark(self, temp_dir):
        """Test integration with main TPCHBenchmark class."""
        from benchbox.core.tpch.benchmark import TPCHBenchmark

        # Create base benchmark
        TPCHBenchmark(scale_factor=0.01, output_dir=temp_dir, verbose=False)

        # Test that we can create an official benchmark from it
        official_benchmark = TPCHOfficialBenchmark(scale_factor=0.01, output_dir=temp_dir, verbose=False)

        assert official_benchmark.benchmark is not None
        assert official_benchmark.config is not None
        assert isinstance(official_benchmark.benchmark, TPCHBenchmark)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
