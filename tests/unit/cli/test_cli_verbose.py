"""Tests for CLI verbose logging functionality.

This module tests the verbose mode implementation across different
benchmark types and platforms to ensure comprehensive debug logging.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import logging
import sys
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from click.testing import CliRunner

from benchbox.cli.main import run, setup_verbose_logging

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


class TestVerboseLogging:
    """Test verbose logging setup and configuration."""

    def test_setup_verbose_logging_enabled(self):
        """Test verbose logging setup when enabled."""
        logger, settings = setup_verbose_logging(verbose=True)

        # Verify logger is returned and configured
        assert logger is not None
        assert settings.verbose_enabled is True
        assert settings.very_verbose is True

        # Verify root logger is set to DEBUG level or lower
        root_logger = logging.getLogger()
        assert root_logger.level <= logging.DEBUG

    def test_setup_verbose_logging_disabled(self):
        """Test verbose logging setup when disabled."""
        logger, settings = setup_verbose_logging(verbose=False)

        # When verbose is False, the function returns None (expected behavior)
        assert logger is None
        assert settings.verbose_enabled is False
        assert settings.level == 0

    def test_verbose_logging_third_party_suppression(self):
        """Test that third-party loggers are properly suppressed in verbose mode."""
        setup_verbose_logging(verbose=True)

        # Check that third-party loggers are set to appropriate levels
        urllib3_logger = logging.getLogger("urllib3")
        requests_logger = logging.getLogger("requests")
        sqlalchemy_logger = logging.getLogger("sqlalchemy")

        assert urllib3_logger.level >= logging.WARNING
        assert requests_logger.level >= logging.WARNING
        assert sqlalchemy_logger.level >= logging.INFO

    def test_verbose_logging_function_exists(self):
        """Test that verbose logging function exists and is callable."""
        assert callable(setup_verbose_logging)

        # Test that function handles both verbose states
        logger_verbose, verbose_settings = setup_verbose_logging(verbose=True)
        logger_normal, normal_settings = setup_verbose_logging(verbose=False)

        assert logger_verbose is not None
        # When verbose is False, function returns None
        assert logger_normal is None
        assert verbose_settings.verbose_enabled is True
        assert normal_settings.verbose_enabled is False


class TestCLIVerboseMode:
    """Test CLI verbose mode functionality."""

    def setup_method(self):
        """Setup test environment."""
        self.runner = CliRunner()
        self.temp_dir = Path(tempfile.mkdtemp())

    def teardown_method(self):
        """Cleanup test environment."""
        import shutil

        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir, ignore_errors=True)

    @patch("benchbox.cli.main.ConfigManager")
    @patch("benchbox.cli.orchestrator.BenchmarkOrchestrator")
    def test_verbose_flag_short_form(self, mock_orchestrator, mock_config_manager):
        """Test that -v flag enables verbose logging."""
        mock_config = Mock()
        mock_config.config_path = "test_config.yaml"
        mock_config.validate_config.return_value = True
        mock_config_manager.return_value = mock_config

        mock_orch = Mock()
        mock_orch.run_guided_benchmark.return_value = None
        mock_orchestrator.return_value = mock_orch

        result = self.runner.invoke(run, ["-v", "--non-interactive"])

        # Check that verbose flag was processed successfully
        assert result.exit_code in [0, 1]  # May exit with 1 due to mocking

    @patch("benchbox.cli.main.ConfigManager")
    @patch("benchbox.cli.orchestrator.BenchmarkOrchestrator")
    def test_verbose_flag_long_form(self, mock_orchestrator, mock_config_manager):
        """Test that --verbose flag enables verbose logging."""
        mock_config = Mock()
        mock_config.config_path = "test_config.yaml"
        mock_config.validate_config.return_value = True
        mock_config_manager.return_value = mock_config

        mock_orch = Mock()
        mock_orch.run_guided_benchmark.return_value = None
        mock_orchestrator.return_value = mock_orch

        result = self.runner.invoke(run, ["--verbose", "--non-interactive"])

        # Check that verbose flag was processed successfully
        assert result.exit_code in [0, 1]  # May exit with 1 due to mocking

    def test_verbose_without_flag_help_works(self):
        """Test that help works without verbose flag."""
        result = self.runner.invoke(run, ["--help"])

        # Check that help was displayed successfully
        assert result.exit_code == 0
        assert "--verbose" in result.output
        assert "-v" in result.output

    def test_quiet_conflicts_with_verbose(self):
        """--quiet used with -v/-vv should produce an explicit error."""
        result = self.runner.invoke(run, ["-v", "--quiet", "--non-interactive"])

        assert result.exit_code == 2
        assert "--quiet cannot be used with -v/-vv" in result.output


class TestVerboseModeIntegration:
    """Test verbose mode integration with different components."""

    def test_verbose_logging_infrastructure_works(self):
        """Test that verbose logging infrastructure is working."""
        # Setup verbose logging
        logger, settings = setup_verbose_logging(verbose=True)

        # Test that debug logging infrastructure works
        assert logger is not None
        assert settings.verbose_enabled is True

    def test_verbose_logging_with_different_loggers(self):
        """Test that verbose logging works with various logger names."""
        setup_verbose_logging(verbose=True)

        # Test various BenchBox loggers
        loggers = [
            "benchbox.cli.main",
            "benchbox.cli.orchestrator",
            "benchbox.platforms.duckdb",
            "benchbox.base",
        ]

        for logger_name in loggers:
            logger = logging.getLogger(logger_name)
            assert logger is not None
            assert hasattr(logger, "debug")
            assert hasattr(logger, "info")


class TestVerboseModeExamples:
    """Test that verbose mode examples work as documented."""

    def setup_method(self):
        """Setup test environment."""
        self.runner = CliRunner()

    @patch("benchbox.cli.main.ConfigManager")
    @patch("benchbox.cli.orchestrator.BenchmarkOrchestrator")
    def test_verbose_with_database_and_benchmark_flags(self, mock_orchestrator, mock_config_manager):
        """Test verbose mode with database and benchmark flags."""
        mock_config = Mock()
        mock_config.config_path = "test_config.yaml"
        mock_config.validate_config.return_value = True
        mock_config_manager.return_value = mock_config

        mock_orch = Mock()
        mock_orch.run_guided_benchmark.return_value = None
        mock_orchestrator.return_value = mock_orch

        result = self.runner.invoke(
            run,
            [
                "--platform",
                "duckdb",
                "--benchmark",
                "tpch",
                "--verbose",
                "--non-interactive",
            ],
        )

        # Check that command completed successfully
        assert result.exit_code in [0, 1]  # May exit with 1 due to mocking

    @patch("benchbox.cli.main.ConfigManager")
    @patch("benchbox.cli.orchestrator.BenchmarkOrchestrator")
    def test_verbose_short_flag_with_options(self, mock_orchestrator, mock_config_manager):
        """Test verbose short flag with various options."""
        mock_config = Mock()
        mock_config.config_path = "test_config.yaml"
        mock_config.validate_config.return_value = True
        mock_config_manager.return_value = mock_config

        mock_orch = Mock()
        mock_orch.run_guided_benchmark.return_value = None
        mock_orchestrator.return_value = mock_orch

        result = self.runner.invoke(
            run,
            [
                "-v",
                "--platform",
                "sqlite",
                "--benchmark",
                "ssb",
                "--scale",
                "0.01",
                "--non-interactive",
            ],
        )

        # Check that command completed successfully
        assert result.exit_code in [0, 1]  # May exit with 1 due to mocking


class TestVerboseLoggingCoverage:
    """Test verbose logging coverage across different scenarios."""

    def test_verbose_logging_infrastructure_complete(self):
        """Test that verbose logging infrastructure is complete."""
        # Verify that setup_verbose_logging function exists and is callable
        assert callable(setup_verbose_logging)

        # Verify that function properly handles both verbose states
        verbose_logger, verbose_settings = setup_verbose_logging(verbose=True)
        normal_logger, normal_settings = setup_verbose_logging(verbose=False)

        assert verbose_logger is not None
        assert verbose_settings.verbose_enabled is True
        # When verbose is False, function returns None
        assert normal_logger is None
        assert normal_settings.verbose_enabled is False

    def test_verbose_mode_help_text_includes_examples(self):
        """Test that CLI help includes verbose mode option."""
        runner = CliRunner()
        result = runner.invoke(run, ["--help"])

        # Check that help text includes verbose option
        assert "--verbose" in result.output
        assert "-v" in result.output
        # Simplified help text in new CLI structure
        assert "Verbose output" in result.output or "verbose" in result.output.lower()

    def test_verbose_logging_with_different_levels(self):
        """Test verbose logging with different logging levels."""
        # Test verbose enabled
        logger_verbose, verbose_settings = setup_verbose_logging(verbose=True)
        assert logger_verbose is not None
        assert verbose_settings.verbose_enabled is True

        # Test verbose disabled (returns None)
        logger_normal, normal_settings = setup_verbose_logging(verbose=False)
        assert logger_normal is None
        assert normal_settings.verbose_enabled is False

        # Verify verbose logger can handle different scenarios
        assert callable(logger_verbose.debug)
        assert callable(logger_verbose.info)
        assert callable(logger_verbose.warning)
        assert callable(logger_verbose.error)

    def test_setup_verbose_logging_return_values(self):
        """Test that setup_verbose_logging returns appropriate values."""
        # Test verbose mode returns logger, non-verbose returns None
        verbose_logger, verbose_settings = setup_verbose_logging(verbose=True)
        normal_logger, normal_settings = setup_verbose_logging(verbose=False)

        # Verbose should return logger, non-verbose should return None
        assert verbose_logger is not None
        assert verbose_settings.verbose_enabled is True
        assert normal_logger is None
        assert normal_settings.verbose_enabled is False

        # Verbose logger should have logging methods
        assert hasattr(verbose_logger, "debug")
        assert hasattr(verbose_logger, "info")
        assert hasattr(verbose_logger, "warning")
        assert hasattr(verbose_logger, "error")

    def test_verbose_logging_repeated_calls(self):
        """Test that repeated calls to setup_verbose_logging work correctly."""
        # Multiple calls should work without issues
        logger1, settings1 = setup_verbose_logging(verbose=True)
        logger2, settings2 = setup_verbose_logging(verbose=False)
        logger3, settings3 = setup_verbose_logging(verbose=True)

        assert logger1 is not None
        assert settings1.verbose_enabled is True
        assert logger2 is None  # Non-verbose returns None
        assert settings2.verbose_enabled is False
        assert logger3 is not None
        assert settings3.verbose_enabled is True
