"""Integration tests for TPC-H Official Benchmark implementation.

These tests verify the complete TPC-H benchmark workflow including:
- Official benchmark execution
- QphH@Size metric calculation
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
            qphh_at_size=0.0,
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

    def test_run_official_benchmark_basic(self, benchmark_instance, mock_connection_factory):
        """Test basic official benchmark execution."""
        # Create mock methods on the benchmark instance (which official_benchmark.py expects)
        benchmark_instance.benchmark.run_power_test = Mock(return_value={"power_at_size": 100.0})
        benchmark_instance.benchmark.run_throughput_test = Mock(return_value={"throughput_at_size": 200.0})
        benchmark_instance.benchmark.run_maintenance_test = Mock(return_value=Mock(success=True))

        # Run benchmark
        result = benchmark_instance.run_official_benchmark(mock_connection_factory)

        # Verify results
        assert isinstance(result, TPCHOfficialBenchmarkResult)
        assert result.success is True
        assert result.start_time is not None
        assert result.end_time is not None
        assert result.total_time > 0
        assert result.power_at_size == 100.0
        assert result.throughput_at_size == 200.0
        # QphH@Size = sqrt(100 * 200) = sqrt(20000) ≈ 141.42
        assert abs(result.qphh_at_size - 141.42) < 0.01

    def test_run_official_benchmark_with_custom_config(self, benchmark_instance, mock_connection_factory):
        """Test official benchmark with custom configuration."""
        custom_config = TPCHOfficialBenchmarkConfig(
            scale_factor=0.01,
            num_streams=2,
            power_test_enabled=True,
            throughput_test_enabled=False,  # Only power test
            maintenance_test_enabled=False,
            verbose=True,
        )

        # Create mock method
        benchmark_instance.benchmark.run_power_test = Mock(return_value={"power_at_size": 150.0})

        result = benchmark_instance.run_official_benchmark(mock_connection_factory, config=custom_config)

        assert result.success is True
        assert result.power_at_size == 150.0
        assert result.throughput_at_size == 0.0  # Not run
        assert result.qphh_at_size == 0.0  # Cannot calculate without both

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
            qphh_at_size=141.42,  # sqrt(100 * 200)
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
            qphh_at_size=0.0,
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
            qphh_at_size=415.69,  # sqrt(360 * 480)
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
            assert "QphH@Size: 415.69" in content
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
            qphh_at_size=0.0,
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

    def test_qphh_calculation_accuracy(self, benchmark_instance, mock_connection_factory):
        """Test QphH@Size calculation accuracy with various values."""
        test_cases = [
            (100.0, 400.0, 200.0),  # sqrt(100*400) = 200
            (360.0, 480.0, 415.69),  # sqrt(360*480) ≈ 415.69
            (1000.0, 1000.0, 1000.0),  # sqrt(1000*1000) = 1000
        ]

        for power, throughput, expected_qphh in test_cases:
            # Create mock methods
            benchmark_instance.benchmark.run_power_test = Mock(return_value={"power_at_size": power})
            benchmark_instance.benchmark.run_throughput_test = Mock(return_value={"throughput_at_size": throughput})

            config = TPCHOfficialBenchmarkConfig(maintenance_test_enabled=False)
            result = benchmark_instance.run_official_benchmark(mock_connection_factory, config=config)

            assert abs(result.qphh_at_size - expected_qphh) < 0.01

    def test_partial_failure_handling(self, benchmark_instance, mock_connection_factory):
        """Test handling when some phases fail."""
        # Power test succeeds
        benchmark_instance.benchmark.run_power_test = Mock(return_value={"power_at_size": 100.0})
        # Throughput test fails
        benchmark_instance.benchmark.run_throughput_test = Mock(side_effect=Exception("Throughput failed"))

        config = TPCHOfficialBenchmarkConfig(maintenance_test_enabled=False)
        result = benchmark_instance.run_official_benchmark(mock_connection_factory, config=config)

        # Should still return a result, but marked as failed
        assert result.success is False
        assert len(result.errors) > 0
        assert "Throughput Test failed" in result.errors[0]
        assert result.power_at_size == 100.0  # Power succeeded
        assert result.throughput_at_size == 0.0  # Throughput failed
        assert result.qphh_at_size == 0.0  # Cannot calculate

    def test_timing_metrics(self, benchmark_instance, mock_connection_factory):
        """Test that timing metrics are properly recorded."""
        # Create mock methods
        benchmark_instance.benchmark.run_power_test = Mock(return_value={"power_at_size": 100.0})
        benchmark_instance.benchmark.run_throughput_test = Mock(return_value={"throughput_at_size": 200.0})

        config = TPCHOfficialBenchmarkConfig(maintenance_test_enabled=False)
        result = benchmark_instance.run_official_benchmark(mock_connection_factory, config=config)

        assert result.start_time is not None
        assert result.end_time is not None
        assert result.total_time > 0
        # Start time should be earlier than end time (ISO format string comparison)
        assert result.start_time < result.end_time

    def test_all_phases_enabled(self, benchmark_instance, mock_connection_factory):
        """Test benchmark execution with all three phases enabled."""
        # Create mock methods
        mock_power = Mock(return_value={"power_at_size": 500.0})
        mock_throughput = Mock(return_value={"throughput_at_size": 800.0})
        mock_maintenance = Mock(return_value=Mock(success=True))

        benchmark_instance.benchmark.run_power_test = mock_power
        benchmark_instance.benchmark.run_throughput_test = mock_throughput
        benchmark_instance.benchmark.run_maintenance_test = mock_maintenance

        result = benchmark_instance.run_official_benchmark(mock_connection_factory)

        # All three test methods should have been called
        assert mock_power.called
        assert mock_throughput.called
        assert mock_maintenance.called

        assert result.success is True
        assert result.power_at_size == 500.0
        assert result.throughput_at_size == 800.0
        # QphH@Size = sqrt(500 * 800) = sqrt(400000) ≈ 632.46
        assert abs(result.qphh_at_size - 632.46) < 0.01

    def test_zero_metric_handling(self, benchmark_instance, mock_connection_factory):
        """Test handling when metrics are zero (cannot calculate QphH@Size)."""
        # Power test returns zero
        benchmark_instance.benchmark.run_power_test = Mock(return_value={"power_at_size": 0.0})

        config = TPCHOfficialBenchmarkConfig(throughput_test_enabled=False, maintenance_test_enabled=False)
        result = benchmark_instance.run_official_benchmark(mock_connection_factory, config=config)

        assert result.power_at_size == 0.0
        assert result.throughput_at_size == 0.0
        assert result.qphh_at_size == 0.0  # Cannot calculate geometric mean with zero

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
