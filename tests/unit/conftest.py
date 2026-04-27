"""Unit-test-specific fixtures for BenchBox.

These fixtures are only needed by tests under tests/unit/ and are kept
separate from the root conftest to reduce its size.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import sys as _sys
from pathlib import Path
from unittest.mock import patch

import pytest

# benchbox.cli.commands.__init__ re-exports `run` (a Click Command) under the
# same name as the run submodule.  On Python 3.10 mock's string-based patch()
# resolves the target via getattr(benchbox.cli.commands, "run"), which returns
# the Command object, not the submodule.  Seeding sys.modules here via
# __import__ and using patch.object() avoids the ambiguity on all Python
# versions.
__import__("benchbox.cli.commands.run")
_run_module = _sys.modules["benchbox.cli.commands.run"]


@pytest.fixture
def cli_benchmark_mocks():
    """Pre-configured mocks for CLI benchmark testing.

    This fixture provides a standard set of mocks for testing CLI benchmark
    commands without spawning subprocesses or invoking real platform adapters.
    Use this to reduce CLI test execution time from ~19s to <5s.

    Returns:
        Dictionary with mock objects for BenchmarkManager, DatabaseManager,
        SystemProfiler, ConfigManager, and BenchmarkOrchestrator.

    Example:
        def test_cli_run_command(cli_benchmark_mocks, cli_runner):
            result = cli_runner.invoke(cli, ["run", "--platform", "duckdb", ...])
            assert result.exit_code == 0
    """
    with (
        patch("benchbox.cli.main.BenchmarkManager") as mock_main_manager,
        patch("benchbox.cli.main.DatabaseManager") as mock_main_db_manager,
        patch("benchbox.cli.main.SystemProfiler") as mock_main_profiler,
        patch("benchbox.cli.main.ConfigManager") as mock_config,
        patch("benchbox.cli.main.get_config_manager") as mock_get_config_manager,
        patch("benchbox.cli.orchestrator.BenchmarkOrchestrator") as mock_orchestrator,
        patch.object(_run_module, "BenchmarkManager") as mock_run_manager,
        patch.object(_run_module, "DatabaseManager") as mock_run_db_manager,
        patch.object(_run_module, "SystemProfiler") as mock_run_profiler,
        patch.object(_run_module, "BenchmarkOrchestrator") as mock_run_orchestrator,
        patch.object(_run_module, "_execute_orchestrated_run") as mock_execute_orchestrated_run,
        patch.object(_run_module, "_export_orchestrated_result") as mock_export_orchestrated_result,
        patch.object(_run_module, "_render_post_run_charts"),
        patch("benchbox.cli.preferences.save_last_run_config"),
    ):
        # Configure BenchmarkManager
        mock_manager_instance = type("MockBenchmarkManager", (), {})()
        mock_manager_instance.benchmarks = {
            "tpch": {"display_name": "TPC-H", "estimated_time_range": (2, 10)},
            "tpcds": {"display_name": "TPC-DS", "estimated_time_range": (5, 30)},
        }
        mock_manager_instance.set_verbosity = lambda *_args, **_kwargs: None
        mock_manager_instance.validate_scale_factor = lambda *_args, **_kwargs: None
        mock_main_manager.return_value = mock_manager_instance
        mock_run_manager.return_value = mock_manager_instance

        # Configure DatabaseManager
        mock_db_manager_instance = type("MockDatabaseManager", (), {})()
        mock_db_manager_instance.set_verbosity = lambda *_args, **_kwargs: None
        mock_db_config = type(
            "MockDbConfig",
            (),
            {
                "type": "duckdb",
                "options": {},
                "driver_version_actual": None,
                "driver_version_resolved": None,
            },
        )()
        mock_db_manager_instance.create_config = lambda *_args, **_kwargs: mock_db_config
        mock_main_db_manager.return_value = mock_db_manager_instance
        mock_run_db_manager.return_value = mock_db_manager_instance

        # Configure SystemProfiler
        mock_system_profile = type(
            "MockSystemProfile",
            (),
            {"cpu_cores_logical": 4, "memory_total_gb": 8},
        )()
        mock_profiler_instance = type("MockProfiler", (), {})()
        mock_profiler_instance.get_system_profile = lambda: mock_system_profile
        mock_main_profiler.return_value = mock_profiler_instance
        mock_run_profiler.return_value = mock_profiler_instance

        # Configure ConfigManager
        mock_config_instance = type("MockConfigManager", (), {})()
        mock_config_instance.config_path = Path("benchbox.yaml")
        mock_config_instance.validate_config = lambda: True
        mock_config_instance.load_unified_tuning_config = lambda *_args, **_kwargs: None
        mock_config_instance.get = lambda _key, default=None: default
        mock_config.return_value = mock_config_instance
        mock_get_config_manager.return_value = mock_config_instance

        # Configure BenchmarkOrchestrator
        mock_orchestrator_instance = type("MockOrchestrator", (), {})()
        mock_orchestrator_instance.set_verbosity = lambda *_args, **_kwargs: None
        mock_orchestrator_instance.set_custom_output_dir = lambda *_args, **_kwargs: None
        mock_orchestrator.return_value = mock_orchestrator_instance
        mock_run_orchestrator.return_value = mock_orchestrator_instance

        # Configure result execution helpers
        mock_result = type(
            "MockResult",
            (),
            {"validation_status": "PASSED", "execution_id": "mock-exec-id", "query_results": []},
        )()
        mock_execute_orchestrated_run.return_value = mock_result
        mock_export_orchestrated_result.return_value = {"json": "benchmark_runs/results/mock-exec-id.json"}

        yield {
            "manager": mock_run_manager,
            "db_manager": mock_run_db_manager,
            "profiler": mock_run_profiler,
            "config": mock_config,
            "orchestrator": mock_run_orchestrator,
        }


@pytest.fixture
def cli_runner():
    """Provide a Click CLI test runner.

    This fixture creates a CliRunner instance for testing Click CLI commands.
    Use in conjunction with cli_benchmark_mocks for fast CLI testing.

    Returns:
        click.testing.CliRunner instance
    """
    from click.testing import CliRunner

    return CliRunner()
