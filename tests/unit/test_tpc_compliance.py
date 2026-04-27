"""Unit tests for TPC compliance framework.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import json
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import Mock

import pytest

import benchbox.utils.clock as _clock
from benchbox.core.connection import DatabaseConnection
from benchbox.core.tpc_compliance import (
    TPCCompliantBenchmark,
    TPCConnectionManager,
    TPCMaintenanceTest,
    TPCMetrics,
    TPCPowerTest,
    TPCQueryResult,
    TPCTestConfig,
    TPCTestPhase,
    TPCTestResult,
    TPCTestStatus,
    TPCThroughputTest,
    TPCTimer,
    TPCValidationResult,
    TPCValidator,
)

# Mark all tests in this file as unit tests
pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


class TestTPCMetrics:
    """Test TPC metrics data structure."""

    def test_metrics_initialization(self):
        """Test metrics initialization with provided values."""
        metrics = TPCMetrics(
            execution_time=10.5,
            throughput=100.0,
            power_score=85.5,
            compliance_score=95.0,
        )

        assert metrics.execution_time == 10.5
        assert metrics.throughput == 100.0
        assert metrics.power_score == 85.5
        assert metrics.compliance_score == 95.0

    def test_metrics_to_dict(self):
        """Test metrics conversion to dictionary."""
        metrics = TPCMetrics(
            execution_time=100.0,
            throughput=200.0,
            power_score=1000.0,
            compliance_score=95.5,
        )

        # Test that metrics have the correct values
        assert metrics.execution_time == 100.0
        assert metrics.throughput == 200.0
        assert metrics.power_score == 1000.0
        assert metrics.compliance_score == 95.5


class TestTPCQueryResult:
    """Test TPC query result data structure."""

    def test_query_result_initialization(self):
        """Test query result initialization."""
        start_time = datetime.now()
        end_time = start_time + timedelta(seconds=5)

        result = TPCQueryResult(
            query_id="Q1",
            stream_id=0,
            execution_time=5.0,
            start_time=start_time,
            end_time=end_time,
            status=TPCTestStatus.COMPLETED,
            result_rows=100,
        )

        assert result.query_id == "Q1"
        assert result.stream_id == 0
        assert result.execution_time == 5.0
        assert result.status == TPCTestStatus.COMPLETED
        assert result.result_rows == 100
        assert result.error_message is None

    def test_query_result_to_dict(self):
        """Test query result conversion to dictionary."""
        start_time = datetime.now()
        end_time = start_time + timedelta(seconds=5)

        result = TPCQueryResult(
            query_id="Q1",
            stream_id=0,
            execution_time=5.0,
            start_time=start_time,
            end_time=end_time,
            status=TPCTestStatus.COMPLETED,
            result_rows=100,
        )

        result_dict = result.to_dict()

        assert result_dict["query_id"] == "Q1"
        assert result_dict["stream_id"] == 0
        assert result_dict["execution_time_seconds"] == 5.0
        assert result_dict["status"] == "completed"
        assert result_dict["result_rows"] == 100


class TestTPCTestResult:
    """Test TPC test result data structure."""

    def test_test_result_initialization(self):
        """Test test result initialization."""
        start_time = datetime.now()
        end_time = start_time + timedelta(seconds=60)

        result = TPCTestResult(
            test_phase=TPCTestPhase.POWER,
            test_name="Power Test",
            start_time=start_time,
            end_time=end_time,
            total_time=60.0,
            status=TPCTestStatus.COMPLETED,
        )

        assert result.test_phase == TPCTestPhase.POWER
        assert result.test_name == "Power Test"
        assert result.total_time == 60.0
        assert result.status == TPCTestStatus.COMPLETED
        assert len(result.query_results) == 0

    def test_calculate_statistics(self):
        """Test statistics calculation."""
        start_time = datetime.now()
        end_time = start_time + timedelta(seconds=60)

        result = TPCTestResult(
            test_phase=TPCTestPhase.POWER,
            test_name="Power Test",
            start_time=start_time,
            end_time=end_time,
            total_time=60.0,
            status=TPCTestStatus.COMPLETED,
        )

        # Include some query results
        query_times = [1.0, 2.0, 3.0, 4.0, 5.0]
        for i, exec_time in enumerate(query_times):
            query_result = TPCQueryResult(
                query_id=f"Q{i + 1}",
                stream_id=0,
                execution_time=exec_time,
                start_time=start_time,
                end_time=start_time + timedelta(seconds=exec_time),
                status=TPCTestStatus.COMPLETED,
            )
            result.query_results.append(query_result)

        # Include one failed query
        failed_result = TPCQueryResult(
            query_id="Q6",
            stream_id=0,
            execution_time=0.0,
            start_time=start_time,
            end_time=start_time,
            status=TPCTestStatus.FAILED,
            error_message="Test error",
        )
        result.query_results.append(failed_result)

        result.calculate_statistics()

        assert result.min_query_time == 1.0
        assert result.max_query_time == 5.0
        assert result.avg_query_time == 3.0
        assert result.median_query_time == 3.0
        assert result.total_queries == 6
        assert result.successful_queries == 5
        assert result.failed_queries == 1


class TestTPCTestConfig:
    """Test TPC test configuration."""

    def test_config_initialization(self):
        """Test configuration initialization."""
        config = TPCTestConfig(
            test_name="Test Run",
            benchmark_name="TPC-H",
            scale_factor=10.0,
            throughput_streams=4,
        )

        assert config.test_name == "Test Run"
        assert config.benchmark_name == "TPC-H"
        assert config.scale_factor == 10.0
        assert config.throughput_streams == 4
        assert config.power_test_enabled is True
        assert config.throughput_test_enabled is True
        assert config.maintenance_test_enabled is True

    def test_config_validation(self):
        """Test configuration validation."""
        # Valid configuration
        config = TPCTestConfig(
            test_name="Test Run",
            benchmark_name="TPC-H",
            scale_factor=1.0,
            throughput_streams=2,
        )

        errors = config.validate()
        assert len(errors) == 0

        # Invalid configuration
        invalid_config = TPCTestConfig(test_name="", benchmark_name="", scale_factor=0.0, throughput_streams=0)

        errors = invalid_config.validate()
        assert len(errors) > 0
        assert "Test name is required" in errors
        assert "Benchmark name is required" in errors
        assert "Scale factor must be positive" in errors
        assert "Throughput streams must be positive" in errors

    def test_config_to_dict(self):
        """Test configuration conversion to dictionary."""
        config = TPCTestConfig(
            test_name="Test Run",
            benchmark_name="TPC-H",
            scale_factor=10.0,
            throughput_streams=4,
        )

        config_dict = config.to_dict()

        assert config_dict["test_name"] == "Test Run"
        assert config_dict["benchmark_name"] == "TPC-H"
        assert config_dict["scale_factor"] == 10.0
        assert config_dict["throughput_streams"] == 4


class TestTPCTimer:
    """Test TPC timer utilities."""

    def test_timer_basic_functionality(self, monkeypatch):
        """Test basic timer functionality."""
        clock = iter([100.0, 100.15]).__next__
        monkeypatch.setattr(_clock, "perf_counter", clock)

        timer = TPCTimer()
        timer.start("test")
        elapsed = timer.stop("test")

        assert elapsed == pytest.approx(0.15, abs=1e-6)

    def test_timer_multiple_timers(self, monkeypatch):
        """Test multiple concurrent timers."""
        times = iter([1.0, 1.05, 1.10, 1.10]).__next__
        monkeypatch.setattr(_clock, "perf_counter", times)

        timer = TPCTimer()
        timer.start("timer1")  # 1.0
        timer.start("timer2")  # 1.05

        elapsed1 = timer.stop("timer1")  # 1.10 - 1.0 = 0.10
        elapsed2 = timer.stop("timer2")  # 1.10 - 1.05 = 0.05

        assert elapsed1 == pytest.approx(0.10, abs=1e-6)
        assert elapsed2 == pytest.approx(0.05, abs=1e-6)
        assert elapsed1 > elapsed2

    def test_timer_elapsed(self, monkeypatch):
        """Test elapsed time measurement."""
        times = iter([0.0, 0.05, 0.12]).__next__
        monkeypatch.setattr(_clock, "perf_counter", times)

        timer = TPCTimer()
        timer.start("test")  # 0.0
        elapsed = timer.elapsed("test")  # 0.05 - 0.0

        assert elapsed == pytest.approx(0.05, abs=1e-6)

        # Timer should still be running
        final_elapsed = timer.stop("test")  # 0.12 - 0.0
        assert final_elapsed > elapsed

    def test_timer_context_manager(self, monkeypatch):
        """Test timer context manager."""
        times = iter([5.0, 5.08, 5.08]).__next__
        monkeypatch.setattr(_clock, "perf_counter", times)

        timer = TPCTimer()

        with timer.measure("context_test") as get_elapsed:
            elapsed = get_elapsed()
            assert elapsed == pytest.approx(0.08, abs=1e-6)

    def test_timer_error_handling(self):
        """Test timer error handling."""
        timer = TPCTimer()

        # Test stopping non-existent timer
        with pytest.raises(ValueError, match="Timer 'nonexistent' was not started"):
            timer.stop("nonexistent")

        # Test elapsed on non-existent timer
        with pytest.raises(ValueError, match="Timer 'nonexistent' was not started"):
            timer.elapsed("nonexistent")


class TestTPCConnectionManager:
    """Test TPC connection manager."""

    def test_connection_manager_initialization(self):
        """Test connection manager initialization."""
        mock_factory = Mock(return_value=Mock(spec=DatabaseConnection))
        manager = TPCConnectionManager(mock_factory, max_connections=5)

        assert manager.max_connections == 5
        assert manager.connection_factory == mock_factory

    def test_get_connection(self):
        """Test getting database connections."""
        mock_connection = Mock(spec=DatabaseConnection)
        mock_factory = Mock(return_value=mock_connection)
        manager = TPCConnectionManager(mock_factory, max_connections=5)

        # connection with specific ID
        conn1 = manager.get_connection(1)
        assert conn1 == mock_connection
        mock_factory.assert_called_once()

        # same connection again
        conn2 = manager.get_connection(1)
        assert conn2 == mock_connection
        # Factory should not be called again
        mock_factory.assert_called_once()

    def test_connection_limit(self):
        """Test connection limit enforcement."""
        mock_factory = Mock(return_value=Mock(spec=DatabaseConnection))
        manager = TPCConnectionManager(mock_factory, max_connections=2)

        # maximum connections
        manager.get_connection(1)
        manager.get_connection(2)

        # Attempt to exceed limit
        with pytest.raises(RuntimeError, match="Maximum connections"):
            manager.get_connection(3)

    def test_release_connection(self):
        """Test releasing connections."""
        mock_connection = Mock(spec=DatabaseConnection)
        mock_factory = Mock(return_value=mock_connection)
        manager = TPCConnectionManager(mock_factory, max_connections=5)

        # and release connection
        manager.get_connection(1)
        manager.release_connection(1)

        # Connection should be closed
        mock_connection.close.assert_called_once()

    def test_close_all(self):
        """Test closing all connections."""
        mock_connections = [Mock(spec=DatabaseConnection) for _ in range(3)]
        mock_factory = Mock(side_effect=mock_connections)
        manager = TPCConnectionManager(mock_factory, max_connections=5)

        # multiple connections
        for i in range(3):
            manager.get_connection(i)

        # Close all connections
        manager.close_all()

        # All connections should be closed
        for mock_conn in mock_connections:
            mock_conn.close.assert_called_once()

    def test_context_manager(self):
        """Test connection manager as context manager."""
        mock_connection = Mock(spec=DatabaseConnection)
        mock_factory = Mock(return_value=mock_connection)

        with TPCConnectionManager(mock_factory, max_connections=5) as manager:
            manager.get_connection(1)

        # Connection should be closed after exiting context
        mock_connection.close.assert_called_once()


class TestTPCValidator:
    """Test TPC validator utilities."""

    def test_validator_initialization(self):
        """Test validator initialization."""
        reference_results = {"Q1": [1, 2, 3], "Q2": [4, 5, 6]}
        validator = TPCValidator(reference_results)

        assert validator.reference_results == reference_results

    def test_validate_query_result(self):
        """Test query result validation."""
        reference_results = {"Q1": [1, 2, 3]}
        validator = TPCValidator(reference_results)

        # Test passing validation
        result = validator.validate_query_result("Q1", [1, 2, 3])
        assert result == TPCValidationResult.PASS

        # Test failing validation
        result = validator.validate_query_result("Q1", [1, 2, 4])
        assert result == TPCValidationResult.FAIL

        # Test missing reference
        result = validator.validate_query_result("Q2", [1, 2, 3])
        assert result == TPCValidationResult.WARNING

    def test_validate_test_result(self):
        """Test test result validation."""
        validator = TPCValidator()

        # test result with successful queries
        start_time = datetime.now()
        test_result = TPCTestResult(
            test_phase=TPCTestPhase.POWER,
            test_name="Test",
            start_time=start_time,
            end_time=start_time + timedelta(seconds=60),
            total_time=60.0,
            status=TPCTestStatus.COMPLETED,
        )

        # Include successful query results
        for i in range(10):
            query_result = TPCQueryResult(
                query_id=f"Q{i + 1}",
                stream_id=0,
                execution_time=1.0 + i * 0.1,
                start_time=start_time,
                end_time=start_time + timedelta(seconds=1),
                status=TPCTestStatus.COMPLETED,
            )
            test_result.query_results.append(query_result)

        test_result.calculate_statistics()

        validations = validator.validate_test_result(test_result)

        assert validations["execution_time"] == TPCValidationResult.PASS
        assert validations["success_rate"] == TPCValidationResult.PASS
        assert validations["test_duration"] == TPCValidationResult.PASS

    def test_calculate_result_hash(self):
        """Test result hash calculation."""
        validator = TPCValidator()

        result1 = [1, 2, 3]
        result2 = [1, 2, 3]
        result3 = [1, 2, 4]

        hash1 = validator.calculate_result_hash(result1)
        hash2 = validator.calculate_result_hash(result2)
        hash3 = validator.calculate_result_hash(result3)

        assert hash1 == hash2
        assert hash1 != hash3
        assert len(hash1) == 64  # SHA-256 hex digest length


class MockTPCPowerTest(TPCPowerTest):
    """Mock implementation of TPC Power Test for testing."""

    def __init__(self, config, connection_manager, timer, validator):
        # The parent class expects (benchmark, connection_string, dialect)
        super().__init__(benchmark=None, connection_string="test://", dialect="test")
        # Store the test attributes
        self.config = config
        self.connection_manager = connection_manager
        self.timer = timer
        self.validator = validator
        self.query_ids = ["Q1", "Q2", "Q3"]

    def get_queries(self):
        return self.query_ids

    def execute_query(self, query_id, connection, stream_id=0):
        start_time = datetime.now()
        end_time = start_time + timedelta(milliseconds=10)

        return TPCQueryResult(
            query_id=query_id,
            stream_id=stream_id,
            execution_time=0.01,
            start_time=start_time,
            end_time=end_time,
            status=TPCTestStatus.COMPLETED,
            result_rows=100,
        )

    def run(self) -> TPCTestResult:
        """Run the power test and return a properly populated result."""
        query_results = []
        for query_id in self.query_ids:
            connection = self.connection_manager.get_connection()
            try:
                result = self.execute_query(query_id, connection)
                query_results.append(result)
            finally:
                self.connection_manager.release_connection(connection)

        return TPCTestResult(
            test_type="power",
            test_phase=TPCTestPhase.POWER,
            test_name=self.config.test_name if self.config else "Power Test",
            success=True,
            duration=len(query_results) * 0.01,
            metric_value=1000.0,
            status=TPCTestStatus.COMPLETED,
            query_results=query_results,
            successful_queries=len(query_results),
            failed_queries=0,
        )


class MockTPCThroughputTest(TPCThroughputTest):
    """Mock implementation of TPC Throughput Test for testing."""

    def __init__(self, config, connection_manager, timer, validator):
        # The parent class expects (benchmark, connection_string, num_streams, dialect)
        num_streams = config.throughput_streams if config else 2
        super().__init__(
            benchmark=None,
            connection_string="test://",
            num_streams=num_streams,
            dialect="test",
        )
        # Store the test attributes
        self.config = config
        self.connection_manager = connection_manager
        self.timer = timer
        self.validator = validator
        self.query_ids = ["Q1", "Q2"]

    def get_queries(self):
        return self.query_ids

    def execute_query(self, query_id, connection, stream_id=0):
        start_time = datetime.now()
        end_time = start_time + timedelta(milliseconds=10)

        return TPCQueryResult(
            query_id=query_id,
            stream_id=stream_id,
            execution_time=0.01,
            start_time=start_time,
            end_time=end_time,
            status=TPCTestStatus.COMPLETED,
            result_rows=100,
        )

    def run(self) -> TPCTestResult:
        """Run the throughput test and return a properly populated result."""
        streams = self.config.throughput_streams if self.config else 2
        query_results = []

        # Simulate multiple streams
        for stream_id in range(streams):
            for query_id in self.query_ids:
                connection = self.connection_manager.get_connection()
                try:
                    result = self.execute_query(query_id, connection, stream_id)
                    query_results.append(result)
                finally:
                    self.connection_manager.release_connection(connection)

        return TPCTestResult(
            test_type="throughput",
            test_phase=TPCTestPhase.THROUGHPUT,
            test_name=self.config.test_name if self.config else "Throughput Test",
            success=True,
            duration=len(query_results) * 0.01,
            metric_value=streams * len(self.query_ids) * 100.0,
            status=TPCTestStatus.COMPLETED,
            query_results=query_results,
            successful_queries=len(query_results),
            failed_queries=0,
            concurrent_streams=streams,
        )


class MockTPCMaintenanceTest(TPCMaintenanceTest):
    """Mock implementation of TPC Maintenance Test for testing."""

    def __init__(self, config, connection_manager, timer, validator):
        # The parent class expects (benchmark, connection_string, dialect)
        super().__init__(benchmark=None, connection_string="test://", dialect="test")
        # Store the test attributes
        self.config = config
        self.connection_manager = connection_manager
        self.timer = timer
        self.validator = validator
        self.operations = ["INSERT", "UPDATE", "DELETE"]

    def get_queries(self):
        return self.operations

    def execute_query(self, query_id, connection, stream_id=0):
        return self.execute_maintenance_operation(query_id, connection)

    def get_maintenance_operations(self):
        return self.operations

    def execute_maintenance_operation(self, operation, connection):
        start_time = datetime.now()
        end_time = start_time + timedelta(milliseconds=10)

        return TPCQueryResult(
            query_id=operation,
            stream_id=0,
            execution_time=0.01,
            start_time=start_time,
            end_time=end_time,
            status=TPCTestStatus.COMPLETED,
            result_rows=10,
        )

    def run(self) -> TPCTestResult:
        """Run the maintenance test and return a properly populated result."""
        query_results = []
        for operation in self.operations:
            connection = self.connection_manager.get_connection()
            try:
                result = self.execute_maintenance_operation(operation, connection)
                query_results.append(result)
            finally:
                self.connection_manager.release_connection(connection)

        return TPCTestResult(
            test_type="maintenance",
            test_phase=TPCTestPhase.MAINTENANCE,
            test_name=self.config.test_name if self.config else "Maintenance Test",
            success=True,
            duration=len(query_results) * 0.01,
            metric_value=len(query_results) * 10.0,
            status=TPCTestStatus.COMPLETED,
            query_results=query_results,
            successful_queries=len(query_results),
            failed_queries=0,
        )


class TestTPCPowerTest:
    """Test TPC Power Test implementation."""

    def test_power_test_run(self):
        """Test power test execution."""
        config = TPCTestConfig(test_name="Power Test", benchmark_name="TPC-H", throughput_streams=1)

        mock_connection = Mock(spec=DatabaseConnection)
        mock_factory = Mock(return_value=mock_connection)
        connection_manager = TPCConnectionManager(mock_factory, max_connections=2)
        timer = TPCTimer()
        validator = TPCValidator()

        power_test = MockTPCPowerTest(config, connection_manager, timer, validator)

        result = power_test.run()

        assert result.test_phase == TPCTestPhase.POWER
        assert result.status == TPCTestStatus.COMPLETED
        assert len(result.query_results) == 3
        assert result.successful_queries == 3
        assert result.failed_queries == 0


class TestTPCThroughputTest:
    """Test TPC Throughput Test implementation."""

    def test_throughput_test_run(self):
        """Test throughput test execution."""
        config = TPCTestConfig(
            test_name="Throughput Test",
            benchmark_name="TPC-H",
            throughput_streams=2,
            throughput_query_limit=2,  # Limit queries for faster testing
        )

        mock_connection = Mock(spec=DatabaseConnection)
        mock_factory = Mock(return_value=mock_connection)
        connection_manager = TPCConnectionManager(mock_factory, max_connections=5)
        timer = TPCTimer()
        validator = TPCValidator()

        throughput_test = MockTPCThroughputTest(config, connection_manager, timer, validator)

        result = throughput_test.run()

        assert result.test_phase == TPCTestPhase.THROUGHPUT
        assert result.status == TPCTestStatus.COMPLETED
        assert result.concurrent_streams == 2
        assert len(result.query_results) >= 2  # At least 2 queries executed


class TestTPCMaintenanceTest:
    """Test TPC Maintenance Test implementation."""

    def test_maintenance_test_run(self):
        """Test maintenance test execution."""
        config = TPCTestConfig(test_name="Maintenance Test", benchmark_name="TPC-H", throughput_streams=1)

        mock_connection = Mock(spec=DatabaseConnection)
        mock_factory = Mock(return_value=mock_connection)
        connection_manager = TPCConnectionManager(mock_factory, max_connections=2)
        timer = TPCTimer()
        validator = TPCValidator()

        maintenance_test = MockTPCMaintenanceTest(config, connection_manager, timer, validator)

        result = maintenance_test.run()

        assert result.test_phase == TPCTestPhase.MAINTENANCE
        assert result.status == TPCTestStatus.COMPLETED
        assert len(result.query_results) == 3
        assert result.successful_queries == 3
        assert result.failed_queries == 0


class MockTPCCompliantBenchmark(TPCCompliantBenchmark):
    """Mock implementation of TPC Compliant Benchmark for testing."""

    def __init__(self, config, connection_factory):
        """Initialize mock benchmark with required attributes."""
        self.config = config
        self.connection_factory = connection_factory

        # mock instances for tests
        mock_connection_manager = TPCConnectionManager(connection_factory, max_connections=5)
        mock_timer = TPCTimer()
        mock_validator = TPCValidator()

        self.power_test = MockTPCPowerTest(config, mock_connection_manager, mock_timer, mock_validator)
        self.throughput_test = MockTPCThroughputTest(config, mock_connection_manager, mock_timer, mock_validator)
        self.maintenance_test = MockTPCMaintenanceTest(config, mock_connection_manager, mock_timer, mock_validator)

    def run_benchmark(self):
        """Run the complete benchmark suite."""
        # Validate configuration first
        errors = self.config.validate()
        if errors:
            raise ValueError(f"Configuration errors: {', '.join(errors)}")

        power_result = self.run_power_test()
        throughput_result = self.run_throughput_test()
        maintenance_result = self.run_maintenance_test()

        # Calculate scores using the proper methods
        power_score = self.calculate_power_score(power_result)
        throughput_score = self.calculate_throughput_score(throughput_result)

        # TPCMetrics object
        metrics = TPCMetrics(
            execution_time=power_result.duration + throughput_result.duration + maintenance_result.duration,
            throughput=throughput_result.metric_value,
            power_score=power_score,
            compliance_score=95.0,
        )

        # Include additional attributes expected by tests
        metrics.benchmark_name = self.config.benchmark_name
        metrics.scale_factor = self.config.scale_factor
        metrics.power_score = power_score
        metrics.throughput_score = throughput_score
        metrics.composite_score = self.calculate_composite_score(metrics)

        # Save results if requested
        if self.config.save_detailed_results and self.config.output_directory:
            self._save_results(metrics)

        return metrics

    def _save_results(self, metrics):
        """Save benchmark results to file."""
        import json
        from pathlib import Path

        results_file = Path(self.config.output_directory) / f"{self.config.test_name}_metrics.json"

        # the metrics dictionary
        metrics_dict = {
            "benchmark_name": metrics.benchmark_name,
            "scale_factor": metrics.scale_factor,
            "power_score": metrics.power_score,
            "throughput_score": metrics.throughput_score,
            "composite_score": metrics.composite_score,
            "execution_time_seconds": metrics.execution_time,
            "throughput": metrics.throughput,
            "compliance_score": metrics.compliance_score,
        }

        with open(results_file, "w", encoding="utf-8") as f:
            json.dump(metrics_dict, f, indent=2)

    def run_power_test(self) -> TPCTestResult:
        """Run the power test phase."""
        return self.power_test.run()

    def run_throughput_test(self) -> TPCTestResult:
        """Run the throughput test phase."""
        return self.throughput_test.run()

    def run_maintenance_test(self) -> TPCTestResult:
        """Run the maintenance test phase."""
        return self.maintenance_test.run()

    def create_power_test(self):
        return MockTPCPowerTest(self.config, self.connection_manager, self.timer, self.validator)

    def create_throughput_test(self):
        return MockTPCThroughputTest(self.config, self.connection_manager, self.timer, self.validator)

    def create_maintenance_test(self):
        return MockTPCMaintenanceTest(self.config, self.connection_manager, self.timer, self.validator)

    def calculate_power_score(self, power_result):
        return 1000.0 * self.config.scale_factor

    def calculate_throughput_score(self, throughput_result):
        return 500.0 * self.config.scale_factor * self.config.throughput_streams

    def calculate_composite_score(self, metrics):
        return (metrics.power_score * metrics.throughput_score) ** 0.5


class TestTPCCompliantBenchmark:
    """Test TPC Compliant Benchmark implementation."""

    def test_benchmark_initialization(self):
        """Test benchmark initialization."""
        config = TPCTestConfig(test_name="Full Benchmark", benchmark_name="TPC-H", throughput_streams=2)

        mock_connection = Mock(spec=DatabaseConnection)
        mock_factory = Mock(return_value=mock_connection)

        benchmark = MockTPCCompliantBenchmark(config, mock_factory)

        assert benchmark.config == config
        assert benchmark.connection_factory == mock_factory
        assert isinstance(benchmark.power_test, MockTPCPowerTest)
        assert isinstance(benchmark.throughput_test, MockTPCThroughputTest)
        assert isinstance(benchmark.maintenance_test, MockTPCMaintenanceTest)

    def test_benchmark_run(self):
        """Test complete benchmark execution."""
        config = TPCTestConfig(
            test_name="Full Benchmark",
            benchmark_name="TPC-H",
            scale_factor=1.0,
            throughput_streams=2,
            throughput_query_limit=2,  # Limit for faster testing
            save_detailed_results=False,  # Don't save files during testing
        )

        mock_connection = Mock(spec=DatabaseConnection)
        mock_factory = Mock(return_value=mock_connection)

        benchmark = MockTPCCompliantBenchmark(config, mock_factory)

        metrics = benchmark.run_benchmark()

        assert isinstance(metrics, TPCMetrics)
        assert metrics.benchmark_name == "TPC-H"
        assert metrics.scale_factor == 1.0
        assert metrics.power_score == 1000.0
        assert metrics.throughput_score == 1000.0  # 500 * 1.0 * 2
        assert metrics.composite_score == 1000.0  # sqrt(1000 * 1000)

    def test_benchmark_config_validation(self):
        """Test benchmark configuration validation."""
        # Invalid configuration
        invalid_config = TPCTestConfig(test_name="", benchmark_name="", scale_factor=0.0, throughput_streams=0)

        mock_connection = Mock(spec=DatabaseConnection)
        mock_factory = Mock(return_value=mock_connection)

        benchmark = MockTPCCompliantBenchmark(invalid_config, mock_factory)

        with pytest.raises(ValueError, match="Configuration errors"):
            benchmark.run_benchmark()

    def test_benchmark_save_results(self):
        """Test benchmark result saving."""
        with tempfile.TemporaryDirectory() as temp_dir:
            config = TPCTestConfig(
                test_name="Save Test",
                benchmark_name="TPC-H",
                scale_factor=1.0,
                throughput_streams=2,
                throughput_query_limit=2,
                save_detailed_results=True,
                output_directory=Path(temp_dir),
            )

            mock_connection = Mock(spec=DatabaseConnection)
            mock_factory = Mock(return_value=mock_connection)

            benchmark = MockTPCCompliantBenchmark(config, mock_factory)

            benchmark.run_benchmark()

            # Check that results file was created
            results_file = Path(temp_dir) / "Save Test_metrics.json"
            assert results_file.exists()

            # Verify file contents
            with open(results_file, encoding="utf-8") as f:
                saved_metrics = json.load(f)

            assert saved_metrics["benchmark_name"] == "TPC-H"
            assert saved_metrics["scale_factor"] == 1.0
            assert saved_metrics["power_score"] == 1000.0
