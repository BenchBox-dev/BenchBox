"""Tests for CLI execution pipeline functionality.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import time
from datetime import datetime
from unittest.mock import MagicMock

import pytest

from benchbox.cli.execution_pipeline import (
    BenchmarkExecutionStage,
    ExecutionContext,
    ExecutionPipeline,
)
from benchbox.core.schemas import (
    BenchmarkConfig,
    DatabaseConfig,
    RunConfig,
    SystemProfile,
)
from tests.fixtures.result_dict_fixtures import make_benchmark_results

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


class TestExecutionContext:
    """Test ExecutionContext dataclass."""

    def test_execution_context_creation(self):
        """Test creating ExecutionContext with required fields."""
        benchmark_config = BenchmarkConfig(name="tpch", display_name="TPC-H")
        database_config = DatabaseConfig(type="duckdb", name="test.db")

        context = ExecutionContext(benchmark_config=benchmark_config, database_config=database_config)

        assert context.benchmark_config == benchmark_config
        assert context.database_config == database_config
        assert context.system_profile is None
        assert context.run_config is None
        assert context.result is None
        assert context.stage == "initializing"
        assert context.errors == []
        assert context.warnings == []

    def test_execution_context_with_optional_fields(self):
        """Test ExecutionContext with optional fields."""
        benchmark_config = BenchmarkConfig(name="ssb", display_name="SSB")
        system_profile = SystemProfile(
            os_name="Linux",
            os_version="5.4.0",
            architecture="x86_64",
            cpu_model="Intel",
            cpu_cores_physical=4,
            cpu_cores_logical=8,
            memory_total_gb=16.0,
            memory_available_gb=12.0,
            python_version="3.11.0",
            disk_space_gb=500.0,
            timestamp=datetime.now(),
            hostname="test",
        )
        run_config = RunConfig(scale_factor=1.0, test_execution_type="power")

        context = ExecutionContext(
            benchmark_config=benchmark_config,
            system_profile=system_profile,
            run_config=run_config,
        )

        assert context.benchmark_config == benchmark_config
        assert context.system_profile == system_profile
        assert context.run_config == run_config


class TestBenchmarkExecutionStage:
    """Test BenchmarkExecutionStage functionality."""

    def test_benchmark_execution_stage_creation(self):
        """Test creating BenchmarkExecutionStage."""
        stage = BenchmarkExecutionStage()

        assert stage.name == "benchmark_execution"
        assert hasattr(stage, "logger")

    def test_benchmark_execution_stage_data_only_test(self):
        """Test executing data-only benchmark test."""
        # Setup context
        benchmark_config = BenchmarkConfig(
            name="test",
            display_name="Test Benchmark",
            scale_factor=0.01,
            test_execution_type="data_only",
        )
        run_config = RunConfig(scale_factor=0.01, test_execution_type="data_only")

        context = ExecutionContext(benchmark_config=benchmark_config, run_config=run_config)

        # Mock the benchmark instance
        mock_benchmark = MagicMock()
        mock_benchmark.generate_data.return_value = [
            "/path/file1.csv",
            "/path/file2.csv",
        ]
        context.benchmark_instance = mock_benchmark

        # Execute stage
        stage = BenchmarkExecutionStage()
        result_context = stage.execute(context)

        # Verify data generation was called
        mock_benchmark.generate_data.assert_called_once()

        # Verify result was created
        assert result_context.result is not None
        assert result_context.result.test_execution_type == "data_only"
        assert result_context.result.benchmark_id == "test"

    def test_benchmark_execution_stage_data_only_emits_duration_and_phase_status(self):
        """Data-only pipeline path should emit non-zero duration and phase timing metadata."""
        benchmark_config = BenchmarkConfig(
            name="test",
            display_name="Test Benchmark",
            scale_factor=0.01,
            test_execution_type="data_only",
        )
        run_config = RunConfig(scale_factor=0.01, test_execution_type="data_only")
        context = ExecutionContext(benchmark_config=benchmark_config, run_config=run_config)

        mock_benchmark = MagicMock()

        def _generate_data():
            time.sleep(0.02)
            return ["/path/file1.csv"]

        mock_benchmark.generate_data.side_effect = _generate_data
        mock_benchmark.create_enhanced_benchmark_result.side_effect = lambda **kwargs: make_benchmark_results(
            benchmark_id="test",
            benchmark_name="Test Benchmark",
            duration_seconds=kwargs.get("duration_seconds", 0.0),
            execution_metadata=kwargs.get("execution_metadata", {}),
            test_execution_type="data_only",
        )
        context.benchmark_instance = mock_benchmark

        stage = BenchmarkExecutionStage()
        result_context = stage.execute(context)

        assert result_context.result is not None
        assert result_context.result.duration_seconds > 0
        phase_status = result_context.result.execution_metadata["phase_status"]["data_generation"]
        assert phase_status["duration_ms"] > 0
        assert phase_status["artifacts_generated"] == 1


class TestExecutionPipeline:
    """Test ExecutionPipeline functionality."""

    def test_pipeline_creation(self):
        """Test creating ExecutionPipeline."""
        pipeline = ExecutionPipeline()

        assert pipeline.console is not None
        assert len(pipeline.stages) == 4  # All execution stages
        assert isinstance(pipeline.stages[3], BenchmarkExecutionStage)

    def test_pipeline_execute_with_mock_stages(self):
        """Test executing pipeline with mock stages."""
        pipeline = ExecutionPipeline()

        # Create mock context
        context = ExecutionContext(
            benchmark_config=BenchmarkConfig(name="test", display_name="Test"),
            database_config=DatabaseConfig(type="duckdb", name="test.db"),
        )

        # Replace stages with mocks that succeed
        mock_stage1 = MagicMock()
        mock_stage1.can_execute.return_value = True
        mock_stage1.execute.return_value = context
        mock_stage1.name = "mock1"

        mock_stage2 = MagicMock()
        mock_stage2.can_execute.return_value = True
        mock_stage2.execute.return_value = context
        mock_stage2.name = "mock2"

        pipeline.stages = [mock_stage1, mock_stage2]

        result = pipeline.execute(context)

        # Verify all stages were executed with context
        mock_stage1.execute.assert_called_once_with(context)
        mock_stage2.execute.assert_called_once_with(context)
        assert result == context

    def test_pipeline_execute_with_stage_error(self):
        """Test pipeline handling stage execution failure."""
        pipeline = ExecutionPipeline()

        # Create mock context
        context = ExecutionContext(benchmark_config=BenchmarkConfig(name="test", display_name="Test"))

        # Create stage that raises exception
        mock_stage = MagicMock()
        mock_stage.can_execute.return_value = True
        mock_stage.execute.side_effect = RuntimeError("Stage failed")
        mock_stage.name = "failing_stage"
        mock_stage.on_error.return_value = context

        pipeline.stages = [mock_stage]

        # Pipeline should handle the exception and call on_error
        result = pipeline.execute(context)

        mock_stage.on_error.assert_called_once()
        assert result == context

    def test_pipeline_skip_stages_when_conditions_not_met(self):
        """Test pipeline skips stages when can_execute returns False."""
        pipeline = ExecutionPipeline()

        context = ExecutionContext(benchmark_config=BenchmarkConfig(name="test", display_name="Test"))

        # Create stage that cannot execute
        mock_stage = MagicMock()
        mock_stage.can_execute.return_value = False  # Cannot execute
        mock_stage.name = "skipped_stage"

        pipeline.stages = [mock_stage]

        result = pipeline.execute(context)

        # Stage should not be executed
        mock_stage.execute.assert_not_called()
        assert result == context


class TestExecutionPipelineIntegration:
    """Test integration scenarios for execution pipeline."""

    def test_pipeline_context_mutation(self):
        """Test that stages can mutate the execution context."""
        # Create actual context (not mock) to test mutation
        benchmark_config = BenchmarkConfig(name="test", display_name="Test")
        database_config = DatabaseConfig(type="duckdb", name="test.db")

        context = ExecutionContext(benchmark_config=benchmark_config, database_config=database_config)

        # Create stage that modifies context
        def modify_context_stage(ctx):
            ctx.result = make_benchmark_results(
                benchmark_id="modified",
                benchmark_name="Modified by stage",
            )
            return ctx

        mock_stage = MagicMock()
        mock_stage.can_execute.return_value = True
        mock_stage.execute.side_effect = modify_context_stage
        mock_stage.name = "modifier"

        pipeline = ExecutionPipeline()
        pipeline.stages = [mock_stage]  # Replace default stages

        # Execute pipeline
        result = pipeline.execute(context)

        # Verify context was modified
        assert context.result is not None
        assert context.result.benchmark_id == "modified"
        assert context.result.benchmark_name == "Modified by stage"
        assert result == context

    def test_pipeline_with_progress_callback(self):
        """Test pipeline progress callback functionality."""
        pipeline = ExecutionPipeline()

        # Track progress calls
        progress_calls = []

        def progress_callback(stage_name, context):
            progress_calls.append(stage_name)

        pipeline.set_progress_callback(progress_callback)

        context = ExecutionContext(benchmark_config=BenchmarkConfig(name="test", display_name="Test"))

        # Create mock stage
        mock_stage = MagicMock()
        mock_stage.can_execute.return_value = True
        mock_stage.execute.return_value = context
        mock_stage.name = "test_stage"

        pipeline.stages = [mock_stage]

        pipeline.execute(context)

        # Verify progress callback was called
        assert "test_stage" in progress_calls
