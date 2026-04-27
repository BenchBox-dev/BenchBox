"""Tests for the monitoring optional-import gate.

Verifies that runner.py, dataframe_runner.py, and progress.py degrade
gracefully when benchbox.monitoring is not importable - i.e. when
_MONITORING_AVAILABLE is False.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


class TestRunnerMonitoringGate:
    """runner.py falls back to monitor=None when monitoring is unavailable."""

    def test_no_monitor_created_when_monitoring_unavailable(self):
        """With _MONITORING_AVAILABLE=False, run_benchmark_lifecycle leaves monitor=None."""
        import benchbox.core.runner.runner as runner_mod

        mock_results = MagicMock()
        mock_results.execution_context = None

        with (
            patch.object(runner_mod, "_MONITORING_AVAILABLE", False),
            patch.object(runner_mod, "get_benchmark_instance", return_value=MagicMock()),
            patch.object(runner_mod, "get_platform_adapter", return_value=MagicMock()),
            patch.object(runner_mod, "_resolve_output_dir_handler", return_value=None),
            patch.object(runner_mod, "_finalize_validation_metadata", return_value=mock_results),
            patch.object(runner_mod, "_enrich_driver_runtime_metadata", return_value=mock_results),
            patch.object(runner_mod, "attach_snapshot_to_result") as mock_attach,
        ):
            from benchbox.core.runner.runner import LifecyclePhases, run_benchmark_lifecycle
            from benchbox.core.schemas import BenchmarkConfig, DatabaseConfig, SystemProfile

            benchmark_config = MagicMock(spec=BenchmarkConfig)
            benchmark_config.name = "tpch"
            benchmark_config.scale_factor = 0.01
            benchmark_config.test_execution_type = "data_only"
            benchmark_config.options = {}

            database_config = MagicMock(spec=DatabaseConfig)
            database_config.type = "duckdb"

            system_profile = MagicMock(spec=SystemProfile)

            phases = LifecyclePhases(generate=False, load=False, execute=False)

            run_benchmark_lifecycle(
                benchmark_config=benchmark_config,
                database_config=database_config,
                system_profile=system_profile,
                platform_config={},
                phases=phases,
            )

        # attach_snapshot_to_result must not be called - monitor is None
        mock_attach.assert_not_called()

    def test_monitor_none_skips_resource_monitoring(self):
        """ResourceMonitor is not started when monitor is None."""
        import benchbox.core.runner.runner as runner_mod

        mock_results = MagicMock()
        mock_results.execution_context = None

        with (
            patch.object(runner_mod, "_MONITORING_AVAILABLE", False),
            patch.object(runner_mod, "get_benchmark_instance", return_value=MagicMock()),
            patch.object(runner_mod, "get_platform_adapter", return_value=MagicMock()),
            patch.object(runner_mod, "_resolve_output_dir_handler", return_value=None),
            patch.object(runner_mod, "_finalize_validation_metadata", return_value=mock_results),
            patch.object(runner_mod, "_enrich_driver_runtime_metadata", return_value=mock_results),
            patch.object(runner_mod, "ResourceMonitor") as mock_resource_monitor,
        ):
            from benchbox.core.runner.runner import LifecyclePhases, run_benchmark_lifecycle
            from benchbox.core.schemas import BenchmarkConfig, DatabaseConfig, SystemProfile

            benchmark_config = MagicMock(spec=BenchmarkConfig)
            benchmark_config.name = "tpch"
            benchmark_config.scale_factor = 0.01
            benchmark_config.test_execution_type = "data_only"
            benchmark_config.options = {}

            database_config = MagicMock(spec=DatabaseConfig)
            database_config.type = "duckdb"

            system_profile = MagicMock(spec=SystemProfile)
            phases = LifecyclePhases(generate=False, load=False, execute=False)

            run_benchmark_lifecycle(
                benchmark_config=benchmark_config,
                database_config=database_config,
                system_profile=system_profile,
                platform_config={},
                phases=phases,
            )

        mock_resource_monitor.assert_not_called()


class TestProgressMonitoringGate:
    """BenchmarkProgress.monitor is None when monitoring is unavailable."""

    def test_monitor_is_none_when_monitoring_unavailable(self):
        """With _MONITORING_AVAILABLE=False, BenchmarkProgress.monitor stays None."""
        from rich.console import Console

        import benchbox.cli.progress as progress_mod
        from benchbox.cli.progress import BenchmarkProgress

        console = Console()
        with patch.object(progress_mod, "_MONITORING_AVAILABLE", False):
            progress = BenchmarkProgress(console, enable_monitoring=True)

        assert progress.monitor is None

    def test_monitor_created_when_monitoring_available(self):
        """With _MONITORING_AVAILABLE=True, BenchmarkProgress.monitor is set."""
        from rich.console import Console

        import benchbox.cli.progress as progress_mod
        from benchbox.cli.progress import BenchmarkProgress

        console = Console()
        with patch.object(progress_mod, "_MONITORING_AVAILABLE", True):
            progress = BenchmarkProgress(console, enable_monitoring=True)

        assert progress.monitor is not None

    def test_monitor_is_none_when_explicitly_disabled(self):
        """enable_monitoring=False always yields monitor=None regardless of availability."""
        from rich.console import Console

        import benchbox.cli.progress as progress_mod
        from benchbox.cli.progress import BenchmarkProgress

        console = Console()
        with patch.object(progress_mod, "_MONITORING_AVAILABLE", True):
            progress = BenchmarkProgress(console, enable_monitoring=False)

        assert progress.monitor is None


class TestDataFrameRunnerMonitoringGate:
    """dataframe_runner.py degrades gracefully when monitor is None."""

    def test_time_operation_skipped_when_monitor_is_none(self):
        """_execute_dataframe_queries returns without error when monitor=None."""
        from benchbox.core.runner.dataframe_runner import _execute_dataframe_queries

        mock_adapter = MagicMock()
        mock_adapter.run_query.return_value = {"duration_ms": 10.0, "rows": 0}

        mock_ctx = MagicMock()
        mock_ctx.warmup_iterations = 0
        mock_ctx.measurement_iterations = 0
        mock_ctx.queries = []

        mock_benchmark_config = MagicMock()
        mock_benchmark_config.options = {}
        mock_benchmark_config.name = "tpch"

        # Should not raise - monitor=None is safe even with no queries
        result = _execute_dataframe_queries(
            adapter=mock_adapter,
            ctx=mock_ctx,
            benchmark_config=mock_benchmark_config,
            benchmark_instance=None,
            monitor=None,
        )

        assert isinstance(result, list)
