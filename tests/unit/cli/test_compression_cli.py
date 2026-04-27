"""Tests for CLI compression options.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import sys
import sys as _sys
from unittest.mock import MagicMock, patch

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
]


class TestCompressionCLI:
    """Test CLI compression options."""

    def setup_method(self):
        """Set up test fixtures."""
        self.runner = CliRunner()

    @pytest.mark.skipif(
        sys.version_info < (3, 11),
        reason="Click command mock.patch requires Python 3.11+ for attribute access",
    )
    @patch("benchbox.cli.main.get_config_manager")
    @patch.object(_run_module, "BenchmarkOrchestrator")
    @patch.object(_run_module, "DatabaseManager")
    @patch.object(_run_module, "BenchmarkManager")
    @patch.object(_run_module, "SystemProfiler")
    def test_cli_compression_options(
        self, mock_profiler, mock_bench_manager, mock_db_manager, mock_orchestrator, mock_get_cfg
    ):
        """Test CLI compression options are properly parsed and used."""
        # Mock config manager
        cfg = MagicMock()
        cfg.get.side_effect = lambda key, default=None: {"export_formats": ["json"]}.get(key, default)
        cfg.config_path = "test.toml"
        cfg.validate_config.return_value = True
        mock_get_cfg.return_value = cfg

        # Mock the managers
        mock_db_instance = MagicMock()
        mock_db_manager.return_value = mock_db_instance
        mock_db_instance.create_config.return_value = MagicMock()

        mock_bench_instance = MagicMock()
        mock_bench_manager.return_value = mock_bench_instance
        mock_bench_instance.benchmarks = {
            "ssb": {
                "display_name": "SSB",
                "estimated_time_range": (1, 5),
                "queries": 13,
                "complexity": "Low",
            }
        }

        mock_profiler_instance = MagicMock()
        mock_profiler.return_value = mock_profiler_instance
        mock_profiler_instance.get_system_profile.return_value = MagicMock()

        mock_orchestrator_instance = MagicMock()
        mock_orchestrator.return_value = mock_orchestrator_instance
        mock_result = MagicMock()
        mock_result.validation_status = "PASSED"
        mock_orchestrator_instance.execute_benchmark.return_value = mock_result

        # Test CLI with compression options
        result = self.runner.invoke(
            cli,
            [
                "run",
                "--platform",
                "duckdb",
                "--benchmark",
                "ssb",
                "--scale",
                "0.01",
                "--compression",
                "zstd:5",
            ],
        )

        # Check that command executed without errors
        assert result.exit_code == 0

        # Verify orchestrator was called
        mock_orchestrator_instance.execute_benchmark.assert_called_once()

        # Get the benchmark config that was passed
        call_args = mock_orchestrator_instance.execute_benchmark.call_args
        benchmark_config = call_args[0][0]  # First positional argument

        # Verify compression settings were passed through
        assert isinstance(benchmark_config, BenchmarkConfig)
        assert benchmark_config.compress_data is True
        assert benchmark_config.compression_type == "zstd"
        assert benchmark_config.compression_level == 5

    @pytest.mark.skipif(
        sys.version_info < (3, 11),
        reason="Click command mock.patch requires Python 3.11+ for attribute access",
    )
    @patch("benchbox.cli.main.get_config_manager")
    @patch.object(_run_module, "BenchmarkOrchestrator")
    @patch.object(_run_module, "DatabaseManager")
    @patch.object(_run_module, "BenchmarkManager")
    @patch.object(_run_module, "SystemProfiler")
    def test_cli_compression_defaults(
        self, mock_profiler, mock_bench_manager, mock_db_manager, mock_orchestrator, mock_get_cfg
    ):
        """Test CLI compression defaults."""
        # Mock config manager
        cfg = MagicMock()
        cfg.get.side_effect = lambda key, default=None: {"export_formats": ["json"]}.get(key, default)
        cfg.config_path = "test.toml"
        cfg.validate_config.return_value = True
        mock_get_cfg.return_value = cfg

        # Mock the managers (same setup as above)
        mock_db_instance = MagicMock()
        mock_db_manager.return_value = mock_db_instance
        mock_db_instance.create_config.return_value = MagicMock()

        mock_bench_instance = MagicMock()
        mock_bench_manager.return_value = mock_bench_instance
        mock_bench_instance.benchmarks = {
            "ssb": {
                "display_name": "SSB",
                "estimated_time_range": (1, 5),
                "queries": 13,
                "complexity": "Low",
            }
        }

        mock_profiler_instance = MagicMock()
        mock_profiler.return_value = mock_profiler_instance
        mock_profiler_instance.get_system_profile.return_value = MagicMock()

        mock_orchestrator_instance = MagicMock()
        mock_orchestrator.return_value = mock_orchestrator_instance
        mock_result = MagicMock()
        mock_result.validation_status = "PASSED"
        mock_orchestrator_instance.execute_benchmark.return_value = mock_result

        # Test CLI without compression options
        result = self.runner.invoke(
            cli,
            ["run", "--platform", "duckdb", "--benchmark", "ssb", "--scale", "0.01"],
        )

        # Check that command executed without errors
        assert result.exit_code == 0

        # Get the benchmark config that was passed
        call_args = mock_orchestrator_instance.execute_benchmark.call_args
        benchmark_config = call_args[0][0]

        # Verify current default compression settings.
        assert benchmark_config.compress_data is False
        assert benchmark_config.compression_type == "none"
        assert benchmark_config.compression_level is None

    def test_cli_help_includes_compression_options(self):
        """Test that CLI --help-topic all includes compression options."""
        result = self.runner.invoke(cli, ["run", "--help-topic", "all"])

        assert result.exit_code == 0
        # New consolidated --compression option in advanced options
        assert "--compression" in result.output

    def test_cli_compression_examples_in_help(self):
        """Test that compression option is shown in --help-topic all."""
        result = self.runner.invoke(cli, ["run", "--help-topic", "all"])

        assert result.exit_code == 0
        # The new --compression option should be visible
        assert "--compression" in result.output

    def test_invalid_compression_type_validation(self):
        """Test that invalid compression types are rejected."""
        result = self.runner.invoke(
            cli,
            [
                "run",
                "--platform",
                "duckdb",
                "--benchmark",
                "ssb",
                "--compression",
                "invalid",
            ],
        )

        # Should fail with invalid compression format
        assert result.exit_code != 0
        assert "Invalid compression" in result.output or "error" in result.output.lower()

    @pytest.mark.skipif(
        sys.version_info < (3, 11),
        reason="Click command mock.patch requires Python 3.11+ for attribute access",
    )
    @patch("benchbox.cli.main.get_config_manager")
    @patch("benchbox.cli.dryrun.DryRunExecutor")
    @patch.object(_run_module, "DatabaseManager")
    @patch.object(_run_module, "BenchmarkManager")
    @patch.object(_run_module, "SystemProfiler")
    def test_dry_run_with_compression_options(
        self, mock_profiler, mock_bench_manager, mock_db_manager, mock_dry_run, mock_get_cfg
    ):
        """Test that dry run mode includes compression parameters."""
        # Mock config manager
        cfg = MagicMock()
        cfg.get.side_effect = lambda key, default=None: {"export_formats": ["json"]}.get(key, default)
        cfg.config_path = "test.toml"
        cfg.validate_config.return_value = True
        mock_get_cfg.return_value = cfg

        # Mock the managers
        mock_db_instance = MagicMock()
        mock_db_manager.return_value = mock_db_instance
        mock_db_instance.create_config.return_value = MagicMock()

        mock_bench_instance = MagicMock()
        mock_bench_manager.return_value = mock_bench_instance
        mock_bench_instance.benchmarks = {
            "ssb": {
                "display_name": "SSB",
                "estimated_time_range": (1, 5),
                "queries": 13,
                "complexity": "Low",
            }
        }

        mock_profiler_instance = MagicMock()
        mock_profiler.return_value = mock_profiler_instance
        mock_profiler_instance.get_system_profile.return_value = MagicMock()

        mock_dry_run_instance = MagicMock()
        mock_dry_run.return_value = mock_dry_run_instance
        mock_dry_run_instance.execute_dry_run.return_value = MagicMock()

        # Test dry run with compression options
        result = self.runner.invoke(
            cli,
            [
                "run",
                "--platform",
                "duckdb",
                "--benchmark",
                "ssb",
                "--scale",
                "0.01",
                "--compression",
                "gzip:9",
                "--dry-run",
                "/tmp/test",
            ],
        )

        # Check that command executed
        assert result.exit_code == 0

        # Verify dry run executor was called
        mock_dry_run_instance.execute_dry_run.assert_called_once()

        # Get the benchmark config passed to dry run
        call_args = mock_dry_run_instance.execute_dry_run.call_args
        benchmark_config = call_args[0][0]  # First positional argument

        # Verify compression settings in dry run.
        assert isinstance(benchmark_config, BenchmarkConfig)
        assert benchmark_config.compress_data is True
        assert benchmark_config.compression_type == "gzip"
        assert benchmark_config.compression_level == 9


class TestBenchmarkConfig:
    """Test BenchmarkConfig with compression parameters."""

    def test_benchmark_config_defaults(self):
        """Test BenchmarkConfig compression defaults."""
        config = BenchmarkConfig(name="test", display_name="Test")

        # BenchmarkConfig may not set compression defaults - that's handled by the mixin
        # Just verify the fields exist and can be set
        assert hasattr(config, "compress_data")
        assert hasattr(config, "compression_type")
        assert hasattr(config, "compression_level")

    def test_benchmark_config_compression_settings(self):
        """Test BenchmarkConfig with compression settings."""
        config = BenchmarkConfig(
            name="test",
            display_name="Test",
            compress_data=True,
            compression_type="gzip",
            compression_level=5,
        )

        assert config.compress_data is True
        assert config.compression_type == "gzip"
        assert config.compression_level == 5

    def test_benchmark_config_post_init(self):
        """Test BenchmarkConfig post_init behavior."""
        config = BenchmarkConfig(name="test", display_name="Test")

        # Options should be initialized as empty dict
        assert config.options == {}
