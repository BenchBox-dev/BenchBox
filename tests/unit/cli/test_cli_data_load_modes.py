"""Tests for CLI data-only and load-only execution modes.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import sys
import sys as _sys
from contextlib import ExitStack, contextmanager
from unittest.mock import Mock, patch

import pytest
from click.testing import CliRunner

from benchbox.cli.benchmarks import BenchmarkConfig
from benchbox.cli.main import cli

# benchbox.cli.commands.__init__ re-exports `run` (a Click Command) under the
# same name as the run submodule.  On Python 3.10 mock's string-based patch()
# resolves the target via getattr(benchbox.cli.commands, "run"), which returns
# the Command object, not the submodule.  Seeding sys.modules here via
# __import__ and using patch.object() avoids the ambiguity on all Python
# versions.
__import__("benchbox.cli.commands.run")
_run_module = _sys.modules["benchbox.cli.commands.run"]

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
    pytest.mark.skipif(
        sys.version_info < (3, 11),
        reason="Click command mock.patch requires Python 3.11+ for attribute access",
    ),
]


@contextmanager
def _mock_run_command_components(*, include_db_manager: bool = False):
    """Provide shared run-command mocks with default successful execution behavior."""
    with ExitStack() as stack:
        mocks = {
            "bench_mgr": stack.enter_context(patch.object(_run_module, "BenchmarkManager")),
            "profiler": stack.enter_context(patch.object(_run_module, "SystemProfiler")),
            "orchestrator": stack.enter_context(patch.object(_run_module, "BenchmarkOrchestrator")),
            "exporter": stack.enter_context(patch.object(_run_module, "ResultExporter")),
            "db_mgr": None,
        }
        if include_db_manager:
            mocks["db_mgr"] = stack.enter_context(patch.object(_run_module, "DatabaseManager"))

        mocks["bench_mgr"].return_value.benchmarks = {
            "tpch": {"display_name": "TPC-H", "estimated_time_range": (2, 10)}
        }
        mocks["profiler"].return_value.get_system_profile.return_value = Mock()

        mock_result = Mock()
        mock_result.validation_status = "PASSED"
        mock_result.validation_details = {"stages": []}
        mocks["orchestrator"].return_value.execute_benchmark.return_value = mock_result
        mocks["exporter"].return_value.export_result.return_value = {"json": "/tmp/result.json"}

        yield mocks


class TestCLIDataLoadModes:
    """Test data-only and load-only execution modes."""

    def setup_method(self):
        """Setup test fixtures."""
        self.runner = CliRunner()

    def test_data_only_no_database_required(self):
        """Test that data-only mode doesn't require database parameter."""
        with _mock_run_command_components() as mocks:
            # Test data-only without database parameter
            result = self.runner.invoke(cli, ["run", "--benchmark", "tpch", "--scale", "0.01", "--phases", "generate"])
            assert result.exit_code == 0
            assert "Data generation completed" in result.output or "Benchmark completed" in result.output

            # Verify orchestrator was called with None database_config
            mocks["orchestrator"].return_value.execute_benchmark.assert_called_once()
            call_args = mocks["orchestrator"].return_value.execute_benchmark.call_args[0]
            assert call_args[2] is None  # database_config should be None

    def test_data_only_ignores_database_parameter(self):
        """Test that data-only mode ignores database parameter if provided."""
        with _mock_run_command_components():
            # Test data-only with database parameter (should be ignored)
            result = self.runner.invoke(
                cli,
                [
                    "run",
                    "--platform",
                    "duckdb",
                    "--benchmark",
                    "tpch",
                    "--scale",
                    "0.01",
                    "--phases",
                    "generate",
                ],
            )
            assert result.exit_code == 0
            assert "Data generation completed" in result.output or "Benchmark completed" in result.output

    def test_load_only_requires_database(self):
        """Test that load-only mode requires database parameter."""
        result = self.runner.invoke(cli, ["run", "--benchmark", "tpch", "--scale", "0.01", "--phases", "load"])
        assert result.exit_code != 0
        assert "Error: --platform parameter is required for --phases load" in result.output

    def test_load_only_with_database(self):
        """Test load-only mode with database parameter."""
        with _mock_run_command_components(include_db_manager=True) as mocks:
            # Setup mocks
            mock_db_config = Mock()
            mock_db_config.type = "duckdb"
            mock_db_config.options = {}
            assert mocks["db_mgr"] is not None
            mocks["db_mgr"].return_value.create_config.return_value = mock_db_config

            # Test load-only with database parameter
            result = self.runner.invoke(
                cli,
                [
                    "run",
                    "--platform",
                    "duckdb",
                    "--benchmark",
                    "tpch",
                    "--scale",
                    "0.01",
                    "--phases",
                    "load",
                ],
            )
            assert result.exit_code == 0
            assert "Data loading completed" in result.output or "Benchmark completed" in result.output

            # Verify database config was created
            mocks["db_mgr"].return_value.create_config.assert_called_once()

            # Verify orchestrator was called with proper database_config
            mocks["orchestrator"].return_value.execute_benchmark.assert_called_once()
            call_args = mocks["orchestrator"].return_value.execute_benchmark.call_args[0]
            assert call_args[2] is not None  # database_config should not be None

    def test_benchmark_config_test_execution_type(self):
        """Test that benchmark config gets correct test_execution_type."""
        with _mock_run_command_components() as mocks:
            # Test data-only mode
            result = self.runner.invoke(cli, ["run", "--benchmark", "tpch", "--scale", "0.01", "--phases", "generate"])
            assert result.exit_code == 0
            # Data generation mode always shows COMPLETED status (not validation_status)
            assert "Data generation completed: COMPLETED" in result.output

            mocks["orchestrator"].return_value.execute_benchmark.assert_called_once()
            phases = mocks["orchestrator"].return_value.execute_benchmark.call_args[0][3]
            assert phases == ["generate"]

    def test_force_flag(self):
        """Ensure CLI forwards force flags into benchmark config options."""
        with _mock_run_command_components(include_db_manager=True) as mocks:
            mock_db_cfg = Mock()
            mock_db_cfg.type = "duckdb"
            mock_db_cfg.options = {}
            assert mocks["db_mgr"] is not None
            mocks["db_mgr"].return_value.create_config.return_value = mock_db_cfg

            result = self.runner.invoke(
                cli,
                [
                    "run",
                    "--platform",
                    "duckdb",
                    "--benchmark",
                    "tpch",
                    "--scale",
                    "0.01",
                    "--force",
                    "datagen",
                ],
            )
            assert result.exit_code == 0

            mocks["orchestrator"].return_value.execute_benchmark.assert_called_once()
            config = mocks["orchestrator"].return_value.execute_benchmark.call_args[0][0]
            assert isinstance(config, BenchmarkConfig)
            assert config.options.get("force_regenerate") is True

    def test_table_mode_option_forwarded(self):
        """Ensure CLI forwards --table-mode into benchmark config options."""
        with _mock_run_command_components(include_db_manager=True) as mocks:
            mock_db_cfg = Mock()
            mock_db_cfg.type = "duckdb"
            mock_db_cfg.options = {}
            assert mocks["db_mgr"] is not None
            mocks["db_mgr"].return_value.create_config.return_value = mock_db_cfg

            result = self.runner.invoke(
                cli,
                [
                    "run",
                    "--platform",
                    "duckdb",
                    "--benchmark",
                    "tpch",
                    "--scale",
                    "0.01",
                    "--table-mode",
                    "external",
                ],
            )
            assert result.exit_code == 0

            mocks["orchestrator"].return_value.execute_benchmark.assert_called_once()
            config = mocks["orchestrator"].return_value.execute_benchmark.call_args[0][0]
            assert isinstance(config, BenchmarkConfig)
            assert config.options.get("table_mode") == "external"

    def test_table_mode_cli_value_saved_for_quick_restart(self):
        """Explicit CLI --table-mode should be persisted in quick restart config."""
        with (
            _mock_run_command_components(include_db_manager=True) as mocks,
            patch("benchbox.cli.preferences.save_last_run_config") as mock_save_last_run_config,
        ):
            mock_db_cfg = Mock()
            mock_db_cfg.type = "duckdb"
            mock_db_cfg.options = {}
            mock_db_cfg.driver_version_actual = "1.4.3"
            mock_db_cfg.driver_version_resolved = "1.4.3"
            assert mocks["db_mgr"] is not None
            mocks["db_mgr"].return_value.create_config.return_value = mock_db_cfg

            result = self.runner.invoke(
                cli,
                [
                    "run",
                    "--platform",
                    "duckdb",
                    "--benchmark",
                    "tpch",
                    "--scale",
                    "0.01",
                    "--table-mode",
                    "external",
                ],
            )
            assert result.exit_code == 0
            assert mock_save_last_run_config.called
            _, kwargs = mock_save_last_run_config.call_args
            assert kwargs.get("additional_options", {}).get("table_mode") == "external"

    def test_table_mode_cli_precedence_over_quick_restart_config(self):
        """Explicit CLI --table-mode should override saved quick-restart table mode."""
        mock_sys = Mock()
        mock_sys.stdin = Mock()
        mock_sys.stdin.isatty.return_value = True
        mock_sys.stdout = Mock()
        mock_sys.stdout.isatty.return_value = True

        with (
            _mock_run_command_components(include_db_manager=True) as mocks,
            patch.object(_run_module, "sys", mock_sys),
            patch("benchbox.cli.onboarding.check_and_run_first_time_setup", return_value=False),
            patch(
                "benchbox.cli.preferences.load_last_run_config",
                return_value={
                    "database": "duckdb",
                    "benchmark": "tpch",
                    "scale": 0.01,
                    "phases": ["load", "power"],
                    "tuning_mode": "notuning",
                    "table_mode": "native",
                },
            ),
            patch("benchbox.cli.preferences.format_last_run_summary", return_value="saved run"),
            patch.object(_run_module.Confirm, "ask") as mock_confirm_ask,
            patch("benchbox.cli.preferences.save_last_run_config"),
        ):

            def _confirm_side_effect(prompt, default=False):
                prompt_text = str(prompt)
                if "Reuse this configuration?" in prompt_text:
                    return True
                if "configure tuning options" in prompt_text:
                    return False
                if "Proceed with execution?" in prompt_text:
                    return True
                return default

            mock_confirm_ask.side_effect = _confirm_side_effect

            mock_profile = Mock()
            mock_profile.cpu_cores_logical = 8
            mock_profile.cpu_cores_physical = 4
            mock_profile.memory_total_gb = 16
            mock_profile.is_apple_silicon = False
            mock_profile.architecture = "x86_64"
            mock_profile.os_type = "darwin"
            mock_profile.numa_nodes = None
            mocks["profiler"].return_value.get_system_profile.return_value = mock_profile

            mock_db_cfg = Mock()
            mock_db_cfg.type = "duckdb"
            mock_db_cfg.options = {}
            mock_db_cfg.driver_version_actual = "1.4.3"
            mock_db_cfg.driver_version_resolved = "1.4.3"
            assert mocks["db_mgr"] is not None
            mocks["db_mgr"].return_value.create_config.return_value = mock_db_cfg

            result = self.runner.invoke(cli, ["run", "--table-mode", "external"])
            assert result.exit_code == 0, result.output

            mocks["orchestrator"].return_value.execute_benchmark.assert_called_once()
            config = mocks["orchestrator"].return_value.execute_benchmark.call_args[0][0]
            assert isinstance(config, BenchmarkConfig)
            assert config.options.get("table_mode") == "external"

    def test_table_mode_external_rejects_tuned_in_quick_restart(self):
        """Quick-restart should still reject external table mode with tuned mode."""
        mock_sys = Mock()
        mock_sys.stdin = Mock()
        mock_sys.stdin.isatty.return_value = True
        mock_sys.stdout = Mock()
        mock_sys.stdout.isatty.return_value = True

        with (
            _mock_run_command_components(include_db_manager=True) as mocks,
            patch.object(_run_module, "sys", mock_sys),
            patch("benchbox.cli.onboarding.check_and_run_first_time_setup", return_value=False),
            patch(
                "benchbox.cli.preferences.load_last_run_config",
                return_value={
                    "database": "duckdb",
                    "benchmark": "tpch",
                    "scale": 0.01,
                    "phases": ["load", "power"],
                    "tuning_mode": "tuned",
                    "table_mode": "native",
                },
            ),
            patch("benchbox.cli.preferences.format_last_run_summary", return_value="saved run"),
            patch.object(_run_module.Confirm, "ask", side_effect=[True]),
            patch("benchbox.cli.preferences.save_last_run_config"),
        ):
            mock_profile = Mock()
            mock_profile.cpu_cores_logical = 8
            mock_profile.cpu_cores_physical = 4
            mock_profile.memory_total_gb = 16
            mock_profile.is_apple_silicon = False
            mock_profile.architecture = "x86_64"
            mock_profile.os_type = "darwin"
            mock_profile.numa_nodes = None
            mocks["profiler"].return_value.get_system_profile.return_value = mock_profile

            result = self.runner.invoke(cli, ["run", "--table-mode", "external"])
            assert result.exit_code != 0
            assert "--table-mode external is incompatible with --tuning tuned" in result.output
            mocks["orchestrator"].return_value.execute_benchmark.assert_not_called()

    def test_table_mode_external_shows_tag_in_output(self):
        """CLI should print [external] in the run announcement when --table-mode external."""
        with _mock_run_command_components(include_db_manager=True) as mocks:
            mock_db_cfg = Mock()
            mock_db_cfg.type = "duckdb"
            mock_db_cfg.options = {}
            mock_db_cfg.driver_version_actual = "1.4.3"
            mock_db_cfg.driver_version_resolved = "1.4.3"
            assert mocks["db_mgr"] is not None
            mocks["db_mgr"].return_value.create_config.return_value = mock_db_cfg

            result = self.runner.invoke(
                cli,
                [
                    "run",
                    "--platform",
                    "duckdb",
                    "--benchmark",
                    "tpch",
                    "--scale",
                    "0.01",
                    "--table-mode",
                    "external",
                ],
            )
            assert result.exit_code == 0
            assert "[external]" in result.output, f"Expected '[external]' tag in CLI output, got:\n{result.output}"

    def test_table_mode_native_omits_tag_in_output(self):
        """CLI should NOT print [external] when using default native mode."""
        with _mock_run_command_components(include_db_manager=True) as mocks:
            mock_db_cfg = Mock()
            mock_db_cfg.type = "duckdb"
            mock_db_cfg.options = {}
            mock_db_cfg.driver_version_actual = "1.4.3"
            mock_db_cfg.driver_version_resolved = "1.4.3"
            assert mocks["db_mgr"] is not None
            mocks["db_mgr"].return_value.create_config.return_value = mock_db_cfg

            result = self.runner.invoke(
                cli,
                [
                    "run",
                    "--platform",
                    "duckdb",
                    "--benchmark",
                    "tpch",
                    "--scale",
                    "0.01",
                ],
            )
            assert result.exit_code == 0
            assert "[external]" not in result.output

    def test_table_mode_external_rejects_tuned(self):
        """external table mode should reject explicit tuned mode."""
        result = self.runner.invoke(
            cli,
            [
                "run",
                "--platform",
                "duckdb",
                "--benchmark",
                "tpch",
                "--table-mode",
                "external",
                "--tuning",
                "tuned",
            ],
        )
        assert result.exit_code != 0
        assert "--table-mode external is incompatible with --tuning tuned" in result.output

    def test_enable_postgen_manifest_flag_forwarded(self):
        """Ensure CLI forwards the manifest validation flag into benchmark options."""
        with _mock_run_command_components() as mocks:
            # Use new composite --validation flag (postgen enables just manifest validation)
            result = self.runner.invoke(
                cli,
                [
                    "run",
                    "--benchmark",
                    "tpch",
                    "--scale",
                    "0.01",
                    "--phases",
                    "generate",
                    "--validation",
                    "postgen",
                ],
            )

            assert result.exit_code == 0
            call_args = mocks["orchestrator"].return_value.execute_benchmark.call_args[0]
            benchmark_config = call_args[0]
            assert benchmark_config.options["enable_postgen_manifest_validation"] is True


class TestCLIDataLoadModesDryRun:
    """Test data-only and load-only modes with dry-run."""

    def setup_method(self):
        """Setup test fixtures."""
        self.runner = CliRunner()

    def test_dry_run_data_only_no_database_required(self):
        """Test dry-run with data-only doesn't require database."""
        with (
            patch("benchbox.cli.dryrun.DryRunExecutor") as mock_executor,
            patch("benchbox.cli.main.BenchmarkManager") as mock_bench_mgr,
            patch("benchbox.cli.main.SystemProfiler") as mock_profiler,
        ):
            # Setup mocks
            mock_bench_mgr.return_value.benchmarks = {
                "tpch": {"display_name": "TPC-H", "estimated_time_range": (2, 10)}
            }
            mock_profiler.return_value.get_system_profile.return_value = Mock()
            mock_executor.return_value.execute_dry_run.return_value = Mock()
            mock_executor.return_value.display_dry_run_results.return_value = None
            mock_executor.return_value.save_dry_run_results.return_value = {"json": "/tmp/result.json"}

            # Test data-only dry-run without database parameter
            result = self.runner.invoke(
                cli,
                [
                    "run",
                    "--benchmark",
                    "tpch",
                    "--scale",
                    "0.01",
                    "--phases",
                    "generate",
                    "--dry-run",
                    "/tmp",
                ],
            )
            assert result.exit_code == 0

            # Verify dry run executor was called with None database_config
            mock_executor.return_value.execute_dry_run.assert_called_once()
            call_args = mock_executor.return_value.execute_dry_run.call_args[0]
            assert call_args[2] is None  # database_config should be None

    def test_dry_run_data_only_ignores_database(self):
        """Test dry-run with data-only ignores database parameter."""
        with (
            patch("benchbox.cli.dryrun.DryRunExecutor") as mock_executor,
            patch("benchbox.cli.main.BenchmarkManager") as mock_bench_mgr,
            patch("benchbox.cli.main.SystemProfiler") as mock_profiler,
        ):
            # Setup mocks
            mock_bench_mgr.return_value.benchmarks = {
                "tpch": {"display_name": "TPC-H", "estimated_time_range": (2, 10)}
            }
            mock_profiler.return_value.get_system_profile.return_value = Mock()
            mock_executor.return_value.execute_dry_run.return_value = Mock()
            mock_executor.return_value.display_dry_run_results.return_value = None
            mock_executor.return_value.save_dry_run_results.return_value = {"json": "/tmp/result.json"}

            # Test data-only dry-run with database parameter (should be ignored)
            result = self.runner.invoke(
                cli,
                [
                    "run",
                    "--platform",
                    "duckdb",
                    "--benchmark",
                    "tpch",
                    "--scale",
                    "0.01",
                    "--phases",
                    "generate",
                    "--dry-run",
                    "/tmp",
                ],
            )
            assert result.exit_code == 0
            assert "Platform parameter ignored in data-only dry run" in result.output

    def test_dry_run_load_only_requires_database(self):
        """Test dry-run with load-only requires database."""
        result = self.runner.invoke(
            cli,
            [
                "run",
                "--benchmark",
                "tpch",
                "--scale",
                "0.01",
                "--phases",
                "load",
                "--dry-run",
                "/tmp",
            ],
        )
        assert result.exit_code != 0
        assert "Dry run mode requires --platform and --benchmark parameters" in result.output

    def test_dry_run_missing_benchmark_data_only(self):
        """Test dry-run data-only requires benchmark parameter."""
        result = self.runner.invoke(cli, ["run", "--phases", "generate", "--dry-run", "/tmp"])
        assert result.exit_code != 0
        assert "Dry run with --phases generate requires --benchmark parameter" in result.output


class TestOrchestratorDataLoadModes:
    """Test orchestrator support for data-only and load-only modes."""

    @patch("benchbox.cli.orchestrator.get_platform_adapter")
    @patch("benchbox.cli.orchestrator.console")
    def test_execute_benchmark_data_only_skips_platform_adapter(self, mock_console, mock_get_adapter):
        """Test that data-only mode skips platform adapter creation."""
        from benchbox.cli.orchestrator import BenchmarkOrchestrator
        from benchbox.cli.system import SystemProfile

        # Create test config with data_only execution type
        config = BenchmarkConfig(
            name="test",
            display_name="Test",
            scale_factor=0.01,
            test_execution_type="data_only",
        )
        system_profile = Mock(spec=SystemProfile)
        system_profile.cpu_cores_logical = 4
        system_profile.memory_total_gb = 8

        orchestrator = BenchmarkOrchestrator()

        # Mock benchmark instance
        mock_benchmark = Mock()
        mock_benchmark._name = "test"
        mock_benchmark.scale_factor = 0.01
        mock_benchmark.output_dir = "/tmp/test"
        mock_benchmark.tables = None  # Force data generation
        mock_benchmark.generate_data.return_value = {"table1": "file1.csv"}

        # Mock parallel attribute to avoid comparison issues
        mock_benchmark.parallel = 1

        # Mock data generator attributes to avoid comparison issues
        if hasattr(mock_benchmark, "data_generator"):
            mock_benchmark.data_generator.parallel = 1
            mock_benchmark.data_generator.validator = Mock()
            mock_benchmark.data_generator.validator.should_regenerate_data.return_value = (
                True,
                "No existing data",
            )

        # Mock the centralized result creation method to return BenchmarkResults
        def mock_create_enhanced_result(platform, query_results, **kwargs):
            from datetime import datetime

            from benchbox.core.results.models import BenchmarkResults

            return BenchmarkResults(
                benchmark_name="test",
                platform=platform,
                scale_factor=0.01,
                execution_id="test123",
                timestamp=datetime.now(),
                duration_seconds=kwargs.get("duration_seconds", 1.0),
                query_definitions={},
                execution_phases=kwargs.get("phases", {}),
                total_queries=0,
                successful_queries=0,
                failed_queries=0,
                total_execution_time=1.0,
                average_query_time=0.0,
                validation_status="PASSED",
                validation_details={},
            )

        mock_benchmark.create_enhanced_benchmark_result = mock_create_enhanced_result

        # Patch DirectoryManager.get_datagen_path to avoid file system operations
        with patch.object(orchestrator, "_get_benchmark_instance", return_value=mock_benchmark):
            result = orchestrator.execute_benchmark(config, system_profile, None, ["generate"])

        # Verify platform adapter was not called
        mock_get_adapter.assert_not_called()

        # Generate-only runs without validation records should not claim validation passed.
        assert result.validation_status == "NOT_RUN"


class TestDryRunDataLoadModes:
    """Test dry-run executor support for data-only and load-only modes."""

    def test_execute_dry_run_with_none_database_config(self):
        """Test execute_dry_run with None database_config."""
        from datetime import datetime

        from benchbox.cli.dryrun import DryRunExecutor
        from benchbox.core.schemas import SystemProfile

        executor = DryRunExecutor()
        config = BenchmarkConfig(name="test", display_name="Test", scale_factor=0.01)
        system_profile = SystemProfile(
            os_name="Linux",
            os_version="6.6",
            architecture="x86_64",
            cpu_model="Test CPU",
            cpu_cores_physical=4,
            cpu_cores_logical=8,
            memory_total_gb=16.0,
            memory_available_gb=12.0,
            python_version="3.11",
            disk_space_gb=256.0,
            timestamp=datetime.now(),
        )

        # Mock benchmark instance
        mock_benchmark = Mock()
        mock_benchmark._name = "test"
        mock_benchmark.get_query_list.return_value = ["Q1", "Q2"]
        mock_benchmark.get_query.return_value = "SELECT 1"

        with patch.object(executor, "_get_benchmark_instance", return_value=mock_benchmark):
            result = executor.execute_dry_run(config, system_profile, None)

        # Verify result structure
        assert result.database_config["type"] == "data_only"
        assert result.platform_config == {"data_only": True}

    def test_get_platform_config_with_none(self):
        """Test _get_platform_config with None database_config."""
        from benchbox.cli.dryrun import DryRunExecutor
        from benchbox.cli.system import SystemProfile

        executor = DryRunExecutor()
        system_profile = Mock(spec=SystemProfile)

        result = executor._get_platform_config(None, system_profile)

        assert result == {"data_only": True}
