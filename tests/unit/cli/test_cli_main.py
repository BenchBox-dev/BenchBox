"""Unit tests for CLI main entry point.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import json
import sys
from unittest.mock import Mock, patch

import pytest
from click.testing import CliRunner

import benchbox
from benchbox.cli.main import cli, run

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


@pytest.mark.unit
class TestConfigManagerFactory:
    """Test config manager factory function."""

    def test_get_config_manager_returns_instance(self):
        """Test that get_config_manager returns ConfigManager instance."""
        from benchbox.cli.config import ConfigManager
        from benchbox.cli.main import get_config_manager

        manager = get_config_manager()

        assert isinstance(manager, ConfigManager)
        assert hasattr(manager, "get")
        assert hasattr(manager, "set")
        assert hasattr(manager, "config")

    def test_main_block_execution(self):
        """Test CLI entry point responds to --help."""
        runner = CliRunner()
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "Usage:" in result.output or "BenchBox" in result.output


@pytest.mark.unit
class TestCLIMain:
    """Test CLI main entry point and commands."""

    def test_cli_group_help(self):
        """Test CLI group help message."""
        runner = CliRunner()
        result = runner.invoke(cli, ["--help"])

        assert result.exit_code == 0
        expected_banner = f"BenchBox {benchbox.__version__} - Interactive database benchmark runner."
        assert expected_banner in result.output
        assert "run" in result.output

    def test_cli_version(self):
        """Test CLI version command."""
        runner = CliRunner()
        result = runner.invoke(cli, ["--version"])

        assert result.exit_code == 0
        assert f"BenchBox Version: {benchbox.__version__}" in result.output
        assert f"Release Tag: v{benchbox.__version__}" in result.output

    @patch("benchbox.utils.version.get_version_info")
    def test_cli_version_json(self, mock_version_info):
        """CLI JSON version output should preserve the version utility payload."""
        mock_version_info.return_value = {
            "benchbox_version": benchbox.__version__,
            "pyproject_version": benchbox.__version__,
            "version_consistent": False,
            "version_message": "synthetic mismatch for passthrough verification",
        }
        runner = CliRunner()
        result = runner.invoke(cli, ["--version-json"])

        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert payload["benchbox_version"] == benchbox.__version__
        assert payload["version_consistent"] is False
        assert payload["version_message"] == "synthetic mismatch for passthrough verification"

    def test_cli_version_json_real_payload(self):
        """Test CLI version JSON command against the real version metadata path."""
        runner = CliRunner()
        result = runner.invoke(cli, ["--version-json"])

        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert payload["benchbox_version"] == benchbox.__version__
        assert payload["pyproject_version"] == benchbox.__version__
        assert payload["expected_version"] == benchbox.__version__
        assert payload["version_consistent"] is True
        assert payload["version_message"] == f"All version markers aligned at {benchbox.__version__}"

    @pytest.mark.skipif(
        sys.version_info < (3, 11),
        reason="Click command mock.patch requires Python 3.11+ for attribute access",
    )
    @patch("benchbox.cli.main.ConfigManager")
    def test_cli_context_initialization(self, mock_config_manager):
        """Test CLI context is properly initialized."""
        mock_config = Mock()
        mock_config_manager.return_value = mock_config

        runner = CliRunner()
        result = runner.invoke(cli, ["run", "--help"])

        assert result.exit_code == 0
        mock_config_manager.assert_called_once()


@pytest.mark.unit
@pytest.mark.skipif(
    sys.version_info < (3, 11),
    reason="Click command mock.patch requires Python 3.11+ for attribute access",
)
class TestRunCommand:
    """Test run command functionality."""

    def test_run_command_help(self):
        """Test run command help message."""
        runner = CliRunner()
        result = runner.invoke(run, ["--help"])

        assert result.exit_code == 0
        assert "Run benchmarks" in result.output
        assert "--platform" in result.output
        assert "--benchmark" in result.output
        assert "--scale" in result.output
        assert "--output" in result.output
        # New help system uses --help all instead of --help-all
        assert "--help" in result.output
        assert "all" in result.output.lower()

    @patch("benchbox.cli.main.get_config_manager")
    @patch("benchbox.cli.commands.run.SystemProfiler")
    @patch("benchbox.cli.commands.run.DatabaseManager")
    @patch("benchbox.cli.commands.run.BenchmarkManager")
    @patch("benchbox.cli.commands.run.BenchmarkOrchestrator")
    @patch("benchbox.cli.commands.run.console")
    def test_run_command_interactive_mode(
        self,
        mock_console,
        mock_orchestrator_class,
        mock_benchmark_manager_class,
        mock_database_manager_class,
        mock_profiler_class,
        mock_get_cfg,
    ):
        """Test run command in interactive mode."""
        # Setup mocks

        mock_profiler = Mock()
        mock_system_profile = Mock()
        mock_system_profile.cpu_cores_logical = 8
        mock_system_profile.memory_total_gb = 16
        mock_profiler.get_system_profile.return_value = mock_system_profile
        mock_profiler_class.return_value = mock_profiler

        mock_database_manager = Mock()
        mock_database_config = Mock()
        mock_database_config.type = "duckdb"
        mock_database_manager.select_database.return_value = mock_database_config
        mock_database_manager_class.return_value = mock_database_manager

        mock_benchmark_manager = Mock()
        mock_benchmark_config = Mock()
        mock_benchmark_config.name = "tpch"
        mock_benchmark_config.scale_factor = 0.01
        mock_benchmark_config.options = {}
        mock_benchmark_manager.select_benchmark.return_value = mock_benchmark_config
        mock_benchmark_manager_class.return_value = mock_benchmark_manager

        mock_orchestrator = Mock()
        mock_result = Mock()
        mock_result.validation_status = "PASSED"
        mock_result.execution_id = "test_id"
        mock_orchestrator.execute_benchmark.return_value = mock_result
        mock_orchestrator_class.return_value = mock_orchestrator

        runner = CliRunner()

        # Interactive mode requires TTY - test that it properly rejects non-TTY
        result = runner.invoke(cli, ["run"])

        # Should exit with code 2 (TTY required error)
        assert result.exit_code == 2

    @patch("benchbox.cli.main.get_config_manager")
    @patch("benchbox.cli.commands.run.SystemProfiler")
    @patch("benchbox.cli.commands.run.DatabaseManager")
    @patch("benchbox.cli.commands.run.BenchmarkManager")
    @patch("benchbox.cli.commands.run.BenchmarkOrchestrator")
    @patch("benchbox.cli.commands.run.console")
    def test_run_command_quick_mode_partial_args(
        self,
        mock_console,
        mock_orchestrator_class,
        mock_benchmark_manager_class,
        mock_database_manager_class,
        mock_profiler_class,
        mock_get_cfg,
    ):
        """Test run command quick mode with partial arguments."""
        cfg = Mock()

        def _cfg_get2(key, default=None):
            mapping = {
                "output.compression.enabled": False,
                "output.compression.type": "zstd",
                "output.compression.level": None,
                "output.formats": ["json"],
            }
            return mapping.get(key, default)

        cfg.get.side_effect = _cfg_get2
        cfg.config_path = "test.toml"
        cfg.validate_config.return_value = True
        mock_get_cfg.return_value = cfg

        # Setup all mocks for interactive fallback
        mock_profiler = Mock()
        mock_system_profile = Mock()
        mock_system_profile.cpu_cores_logical = 8
        mock_system_profile.memory_total_gb = 16
        mock_profiler.get_system_profile.return_value = mock_system_profile
        mock_profiler_class.return_value = mock_profiler

        mock_database_manager = Mock()
        mock_database_config = Mock()
        mock_database_config.type = "duckdb"
        mock_database_manager.select_database.return_value = mock_database_config
        mock_database_manager_class.return_value = mock_database_manager

        mock_benchmark_manager = Mock()
        mock_benchmark_config = Mock()
        mock_benchmark_config.name = "tpch"
        mock_benchmark_config.scale_factor = 0.01
        mock_benchmark_config.options = {}
        mock_benchmark_manager.select_benchmark.return_value = mock_benchmark_config
        mock_benchmark_manager_class.return_value = mock_benchmark_manager

        mock_orchestrator = Mock()
        mock_result = Mock()
        mock_result.validation_status = "PASSED"
        mock_result.execution_id = "test_id"
        mock_orchestrator.execute_benchmark.return_value = mock_result
        mock_orchestrator_class.return_value = mock_orchestrator

        runner = CliRunner()

        # Test quick mode without all required arguments - should fall back to interactive
        # which requires TTY
        result = runner.invoke(cli, ["run", "--quick"])

        # Should exit with code 2 (TTY required for interactive fallback)
        assert result.exit_code == 2

    @patch("benchbox.cli.main.get_config_manager")
    @patch("benchbox.cli.commands.run.DatabaseManager")
    @patch("benchbox.cli.commands.run.BenchmarkManager")
    @patch("benchbox.cli.commands.run.SystemProfiler")
    @patch("benchbox.cli.commands.run.console")
    def test_run_command_quick_mode_complete_args(
        self,
        mock_console,
        mock_profiler_class,
        mock_benchmark_manager_class,
        mock_database_manager_class,
        mock_get_cfg,
    ):
        """Test run command quick mode with complete arguments."""
        cfg = Mock()

        def _cfg_get3(key, default=None):
            mapping = {
                "output.compression.enabled": False,
                "output.compression.type": "zstd",
                "output.compression.level": None,
                "output.formats": ["json"],
            }
            return mapping.get(key, default)

        cfg.get.side_effect = _cfg_get3
        cfg.config_path = "test.toml"
        cfg.validate_config.return_value = True
        mock_get_cfg.return_value = cfg

        # Mock database manager
        mock_database_manager = Mock()
        mock_database_config = Mock()
        mock_database_config.options = {}
        mock_database_manager.create_config.return_value = mock_database_config
        mock_database_manager_class.return_value = mock_database_manager

        # Mock benchmark manager
        mock_benchmark_manager = Mock()
        mock_benchmark_manager.benchmarks = {"tpch": {"display_name": "TPC-H", "estimated_time_range": (2, 10)}}
        mock_benchmark_manager_class.return_value = mock_benchmark_manager

        # Mock system profiler
        mock_profiler = Mock()
        mock_system_profile = Mock()
        mock_system_profile.cpu_cores_logical = 8
        mock_system_profile.memory_total_gb = 16
        mock_profiler.get_system_profile.return_value = mock_system_profile
        mock_profiler_class.return_value = mock_profiler

        # Mock orchestrator - will be patched inline

        runner = CliRunner()

        with patch("benchbox.cli.commands.run.console.print"):
            with patch("benchbox.cli.commands.run.ResultExporter") as mock_exporter_class:
                with patch("benchbox.cli.commands.run.BenchmarkOrchestrator") as mock_orchestrator_class:
                    # Setup orchestrator mock
                    mock_orchestrator = Mock()
                    mock_result = Mock()
                    mock_result.validation_status = "PASSED"
                    mock_result.execution_id = "test_id"
                    mock_orchestrator.execute_benchmark.return_value = mock_result
                    from pathlib import Path as _Path

                    mock_orchestrator.directory_manager = Mock()
                    mock_orchestrator.directory_manager.get_result_path.return_value = _Path("/tmp/test.json")
                    mock_orchestrator.directory_manager.results_dir = "/tmp"
                    mock_orchestrator_class.return_value = mock_orchestrator

                    mock_exporter = Mock()
                    mock_exporter.export_result.return_value = {"json": "/tmp/test.json"}
                    mock_exporter_class.return_value = mock_exporter

                    result = runner.invoke(
                        cli,
                        [
                            "run",
                            "--platform",
                            "duckdb",
                            "--benchmark",
                            "tpch",
                            "--scale",
                            "0.01",
                            "--output",
                            "/tmp/test",
                        ],
                    )

        assert result.exit_code == 0
        # Verify orchestrator was invoked and results exported
        mock_orchestrator.execute_benchmark.assert_called_once()
        mock_exporter.export_result.assert_called_once()

    def test_run_command_parameter_validation(self):
        """Test run command parameter validation."""
        runner = CliRunner()

        # Test invalid scale factor
        result = runner.invoke(cli, ["run", "--scale", "invalid"])
        assert result.exit_code != 0
        assert "Invalid value" in result.output

    @patch("benchbox.cli.main.get_config_manager")
    @patch("benchbox.cli.commands.run.SystemProfiler")
    @patch("benchbox.cli.commands.run.DatabaseManager")
    @patch("benchbox.cli.commands.run.BenchmarkManager")
    @patch("benchbox.cli.commands.run.BenchmarkOrchestrator")
    @patch("benchbox.cli.commands.run.console")
    def test_run_command_with_output_directory(
        self,
        mock_console,
        mock_orchestrator_class,
        mock_benchmark_manager_class,
        mock_database_manager_class,
        mock_profiler_class,
        mock_get_cfg,
    ):
        """Test run command with output directory specified."""
        cfg = Mock()

        def _cfg_get5(key, default=None):
            mapping = {
                "output.compression.enabled": False,
                "output.compression.type": "zstd",
                "output.compression.level": None,
                "output.formats": ["json"],
            }
            return mapping.get(key, default)

        cfg.get.side_effect = _cfg_get5
        cfg.config_path = "test.toml"
        cfg.validate_config.return_value = True
        mock_get_cfg.return_value = cfg

        # Setup all mocks for interactive mode
        mock_profiler = Mock()
        mock_system_profile = Mock()
        mock_system_profile.cpu_cores_logical = 8
        mock_system_profile.memory_total_gb = 16
        mock_profiler.get_system_profile.return_value = mock_system_profile
        mock_profiler_class.return_value = mock_profiler

        mock_database_manager = Mock()
        mock_database_config = Mock()
        mock_database_config.type = "duckdb"
        mock_database_manager.select_database.return_value = mock_database_config
        mock_database_manager_class.return_value = mock_database_manager

        mock_benchmark_manager = Mock()
        mock_benchmark_config = Mock()
        mock_benchmark_config.name = "tpch"
        mock_benchmark_config.scale_factor = 0.01
        mock_benchmark_config.options = {}
        mock_benchmark_manager.select_benchmark.return_value = mock_benchmark_config
        mock_benchmark_manager_class.return_value = mock_benchmark_manager

        mock_orchestrator = Mock()
        mock_result = Mock()
        mock_result.validation_status = "PASSED"
        mock_result.execution_id = "test_id"
        mock_orchestrator.execute_benchmark.return_value = mock_result
        mock_orchestrator_class.return_value = mock_orchestrator

        runner = CliRunner()

        # Test with only output directory - should fall back to interactive (requires TTY)
        with runner.isolated_filesystem():
            result = runner.invoke(cli, ["run", "--output", "./test_output"])

        # Should exit with code 2 (TTY required)
        assert result.exit_code == 2

    def test_run_command_default_scale_factor(self):
        """Test that run command uses default scale factor."""
        runner = CliRunner()
        result = runner.invoke(run, ["--help"])

        # Check that default scale factor is documented
        assert "0.01" in result.output


@pytest.mark.unit
@pytest.mark.skipif(
    sys.version_info < (3, 11),
    reason="Click command mock.patch requires Python 3.11+ for attribute access",
)
class TestCLIIntegration:
    """Test CLI integration scenarios."""

    @patch("benchbox.cli.commands.run.SystemProfiler")
    @patch("benchbox.cli.commands.run.DatabaseManager")
    @patch("benchbox.cli.commands.run.BenchmarkManager")
    @patch("benchbox.cli.commands.run.BenchmarkOrchestrator")
    @patch("benchbox.cli.commands.run.ResultExporter")
    @patch("benchbox.cli.commands.run.console")
    def test_full_cli_workflow_mocked(
        self,
        mock_console,
        mock_result_exporter,
        mock_orchestrator,
        mock_benchmark_manager,
        mock_database_manager,
        mock_profiler,
    ):
        """Test full CLI workflow with all components mocked."""
        # Setup system profiler
        mock_profiler_instance = Mock()
        mock_system_profile = Mock()
        mock_system_profile.cpu_cores_logical = 8
        mock_system_profile.memory_total_gb = 16
        mock_profiler_instance.get_system_profile.return_value = mock_system_profile
        mock_profiler.return_value = mock_profiler_instance

        # Setup database manager
        mock_database_manager_instance = Mock()
        mock_database_config = Mock()
        mock_database_config.type = "duckdb"
        mock_database_manager_instance.select_database.return_value = mock_database_config
        mock_database_manager.return_value = mock_database_manager_instance

        # Setup benchmark manager
        mock_benchmark_manager_instance = Mock()
        mock_benchmark_config = Mock()
        mock_benchmark_config.name = "tpch"
        mock_benchmark_config.scale_factor = 0.01
        mock_benchmark_config.options = {}
        mock_benchmark_manager_instance.select_benchmark.return_value = mock_benchmark_config
        mock_benchmark_manager.return_value = mock_benchmark_manager_instance

        # Setup orchestrator
        mock_orchestrator_instance = Mock()
        mock_result = Mock()
        mock_result.validation_status = "PASSED"
        mock_result.execution_id = "test_id"
        mock_orchestrator_instance.execute_benchmark.return_value = mock_result
        mock_orchestrator.return_value = mock_orchestrator_instance

        # Setup result exporter
        mock_exporter_instance = Mock()
        mock_exporter_instance.export_result.return_value = {"json": "/tmp/test.json"}
        mock_result_exporter.return_value = mock_exporter_instance

        runner = CliRunner()

        # Test interactive mode without TTY - should reject
        result = runner.invoke(cli, ["run"])

        # Should exit with code 2 (TTY required)
        assert result.exit_code == 2

    def test_cli_error_handling_invalid_command(self):
        """Test CLI error handling for invalid commands."""
        runner = CliRunner()
        result = runner.invoke(cli, ["invalid_command"])

        assert result.exit_code != 0
        assert "No such command" in result.output

    def test_cli_error_handling_invalid_option(self):
        """Test CLI error handling for invalid options."""
        runner = CliRunner()
        result = runner.invoke(cli, ["run", "--invalid-option"])

        assert result.exit_code != 0
        assert "No such option" in result.output

    @patch("benchbox.cli.commands.run.SystemProfiler")
    @patch("benchbox.cli.commands.run.DatabaseManager")
    @patch("benchbox.cli.commands.run.BenchmarkManager")
    @patch("benchbox.cli.commands.run.BenchmarkOrchestrator")
    @patch("benchbox.cli.commands.run.console")
    def test_cli_context_preservation(
        self,
        mock_console,
        mock_orchestrator_class,
        mock_benchmark_manager_class,
        mock_database_manager_class,
        mock_profiler_class,
    ):
        """Test that CLI context is preserved across commands."""
        # Setup all mocks for interactive mode
        mock_profiler = Mock()
        mock_system_profile = Mock()
        mock_system_profile.cpu_cores_logical = 8
        mock_system_profile.memory_total_gb = 16
        mock_profiler.get_system_profile.return_value = mock_system_profile
        mock_profiler_class.return_value = mock_profiler

        mock_database_manager = Mock()
        mock_database_config = Mock()
        mock_database_config.type = "duckdb"
        mock_database_manager.select_database.return_value = mock_database_config
        mock_database_manager_class.return_value = mock_database_manager

        mock_benchmark_manager = Mock()
        mock_benchmark_config = Mock()
        mock_benchmark_config.name = "tpch"
        mock_benchmark_config.scale_factor = 0.01
        mock_benchmark_config.options = {}
        mock_benchmark_manager.select_benchmark.return_value = mock_benchmark_config
        mock_benchmark_manager_class.return_value = mock_benchmark_manager

        mock_orchestrator = Mock()
        mock_result = Mock()
        mock_result.validation_status = "PASSED"
        mock_result.execution_id = "test_id"
        mock_orchestrator.execute_benchmark.return_value = mock_result
        mock_orchestrator_class.return_value = mock_orchestrator

        runner = CliRunner()

        # Test that context object is created - interactive mode requires TTY
        result = runner.invoke(cli, ["run"])

        # Should exit with code 2 (TTY required)
        assert result.exit_code == 2


@pytest.mark.unit
@pytest.mark.skipif(
    sys.version_info < (3, 11),
    reason="Click command mock.patch requires Python 3.11+ for attribute access",
)
class TestCLIExceptionHandling:
    """Test CLI exception handling scenarios."""

    @patch("benchbox.cli.main.ConfigManager")
    @patch("benchbox.cli.main.SystemProfiler")
    def test_system_profiler_exception_handling(self, mock_profiler_class, mock_config_manager):
        """Test handling of SystemProfiler exceptions."""
        mock_config_manager.return_value = Mock()

        # Make SystemProfiler raise an exception
        mock_profiler_class.side_effect = Exception("System profiling failed")

        runner = CliRunner()
        result = runner.invoke(cli, ["run"])

        # CLI should handle the exception gracefully
        assert result.exit_code != 0

    @patch("benchbox.cli.main.ConfigManager")
    def test_config_manager_exception_handling(self, mock_config_manager):
        """Test handling of ConfigManager exceptions."""
        # Make ConfigManager raise an exception
        mock_config_manager.side_effect = Exception("Config initialization failed")

        runner = CliRunner()
        result = runner.invoke(cli, ["run"])

        # CLI should handle the exception gracefully
        assert result.exit_code != 0


@pytest.mark.unit
class TestCLICompressionOptions:
    """Test CLI compression options."""

    def test_run_command_compression_help(self):
        """Test that compression options appear in --help-topic all."""
        runner = CliRunner()
        result = runner.invoke(run, ["--help-topic", "all"])

        assert result.exit_code == 0
        assert "--compression" in result.output
        assert "zstd" in result.output

    def test_compression_option_validation(self):
        """Test compression option validation."""
        runner = CliRunner()

        # Test invalid compression type (new composite format)
        result = runner.invoke(cli, ["run", "--compression", "invalid"])
        assert result.exit_code != 0
        assert "Invalid compression type" in result.output

    def test_compression_level_validation(self):
        """Test compression level validation."""
        runner = CliRunner()

        # Test invalid compression level (should be a number in format type:level)
        result = runner.invoke(cli, ["run", "--compression", "zstd:invalid"])
        assert result.exit_code != 0
        assert "Invalid compression level" in result.output
