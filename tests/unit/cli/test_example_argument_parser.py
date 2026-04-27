"""
Tests for CLI ExampleArgumentParser functionality.

Tests consolidated argument parsing functionality used across examples.
"""

import argparse
import sys
from unittest.mock import patch

import pytest

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


# Import the ExampleArgumentParser - handle import errors gracefully
try:
    from benchbox.cli.config import ExampleArgumentParser

    IMPORTS_AVAILABLE = True
    skip_reason = None
except ImportError as e:
    # If CLI modules aren't available due to missing dependencies, skip these tests
    IMPORTS_AVAILABLE = False
    skip_reason = f"CLI modules not available: {e}"


@pytest.mark.skipif(not IMPORTS_AVAILABLE, reason=skip_reason or "CLI modules not available")
class TestExampleArgumentParser:
    """Test ExampleArgumentParser functionality when imports are available."""

    def test_create_benchmark_parser_basic(self):
        """Test creating basic benchmark parser."""
        parser = ExampleArgumentParser.create_benchmark_parser("Test Description")

        assert isinstance(parser, argparse.ArgumentParser)
        assert parser.description == "Test Description"

        # Test parsing basic arguments
        args = parser.parse_args(["--scale", "2.0", "--verbose"])
        assert args.scale == 2.0
        assert args.verbose is True
        assert args.quiet is False

    def test_create_benchmark_parser_custom_scale(self):
        """Test creating parser with custom default scale."""
        parser = ExampleArgumentParser.create_benchmark_parser("Test", default_scale=0.1)

        # Test default scale
        args = parser.parse_args([])
        assert args.scale == 0.1

        # Test overriding scale
        args = parser.parse_args(["--scale", "5.0"])
        assert args.scale == 5.0

    def test_add_tuning_arguments(self):
        """Test adding tuning arguments to parser."""
        parser = ExampleArgumentParser.create_benchmark_parser("Test")
        ExampleArgumentParser.add_tuning_arguments(parser)

        # Test tuning arguments
        args = parser.parse_args(
            [
                "--tuning-config",
                "config.yaml",
                "--platform-name",
                "custom_db",
                "--force",
            ]
        )

        assert args.tuning_config == "config.yaml"
        assert args.database_name == "custom_db"
        assert args.force is True

    def test_add_execution_arguments(self):
        """Test adding execution arguments to parser."""
        parser = ExampleArgumentParser.create_benchmark_parser("Test")
        ExampleArgumentParser.add_execution_arguments(parser)

        # Test execution arguments
        args = parser.parse_args(
            [
                "--iterations",
                "5",
                "--warm-up",
                "2",
                "--profile",
                "standard",
                "--concurrent",
                "--streams",
                "4",
                "--phase",
                "power",
            ]
        )

        assert args.iterations == 5
        assert args.warm_up == 2
        assert args.profile == "standard"
        assert args.concurrent is True
        assert args.streams == 4
        assert args.phase == "power"

    def test_add_output_arguments(self):
        """Test adding output arguments to parser."""
        parser = ExampleArgumentParser.create_benchmark_parser("Test")
        ExampleArgumentParser.add_output_arguments(parser)

        # Test output arguments
        args = parser.parse_args(
            [
                "--save-results",
                "results.json",
                "--export-format",
                "json",
                "--export-format",
                "csv",
                "--dry-run",
                "/tmp/plan",
            ]
        )

        assert args.save_results == "results.json"
        assert args.export_format == ["json", "csv"]
        assert args.dry_run == "/tmp/plan"

    def test_add_platform_arguments_databricks(self):
        """Test adding Databricks-specific arguments."""
        parser = ExampleArgumentParser.create_benchmark_parser("Test")
        ExampleArgumentParser.add_platform_arguments(parser, "databricks")

        # Test Databricks arguments
        args = parser.parse_args(
            [
                "--server-hostname",
                "test.databricks.com",
                "--http-path",
                "/sql/1.0/endpoints/abc123",
                "--catalog",
                "test_catalog",
                "--schema",
                "test_schema",
                "--create-catalog",
                "--enable-delta-optimization",
                "--auto-optimize",
                "--cluster-size",
                "Medium",
            ]
        )

        assert args.server_hostname == "test.databricks.com"
        assert args.http_path == "/sql/1.0/endpoints/abc123"
        assert args.catalog == "test_catalog"
        assert args.schema == "test_schema"
        assert args.create_catalog is True
        assert args.enable_delta_optimization is True
        assert args.auto_optimize is True
        assert args.cluster_size == "Medium"

    def test_add_platform_arguments_duckdb(self):
        """Test adding DuckDB-specific arguments."""
        parser = ExampleArgumentParser.create_benchmark_parser("Test")
        ExampleArgumentParser.add_platform_arguments(parser, "duckdb")

        # Test DuckDB arguments
        args = parser.parse_args(
            [
                "--memory-limit",
                "4GB",
                "--threads",
                "8",
                "--temp-directory",
                "/tmp/duckdb",
            ]
        )

        assert args.memory_limit == "4GB"
        assert args.threads == 8
        assert args.temp_directory == "/tmp/duckdb"

    def test_add_platform_arguments_clickhouse(self):
        """Test adding ClickHouse-specific arguments."""
        parser = ExampleArgumentParser.create_benchmark_parser("Test")
        ExampleArgumentParser.add_platform_arguments(parser, "clickhouse")

        # Test ClickHouse arguments
        args = parser.parse_args(
            [
                "--deployment-mode",
                "local",
                "--host",
                "clickhouse.example.com",
                "--port",
                "9440",
                "--user",
                "test_user",
                "--password",
                "secret123",
                "--secure",
            ]
        )

        assert args.host == "clickhouse.example.com"
        assert args.port == 9440
        assert args.user == "test_user"
        assert args.password == "secret123"
        assert args.secure is True
        assert args.deployment_mode == "local"

    def test_add_platform_arguments_clickhouse_accepts_legacy_mode_alias(self):
        """Legacy `--mode` should populate deployment_mode for compatibility."""
        parser = ExampleArgumentParser.create_benchmark_parser("Test")
        ExampleArgumentParser.add_platform_arguments(parser, "clickhouse")

        args = parser.parse_args(["--mode", "embedded"])

        assert args.deployment_mode == "embedded"

    def test_add_platform_arguments_unknown(self):
        """Test adding arguments for unknown platform (should not crash)."""
        parser = ExampleArgumentParser.create_benchmark_parser("Test")

        # Should not raise an exception
        ExampleArgumentParser.add_platform_arguments(parser, "unknown_platform")

        # Parser should still work normally
        args = parser.parse_args(["--scale", "1.5"])
        assert args.scale == 1.5

    def test_parse_and_validate_args_success(self):
        """Test successful argument parsing and validation."""
        parser = ExampleArgumentParser.create_benchmark_parser("Test")
        ExampleArgumentParser.add_execution_arguments(parser)

        # Mock sys.argv to provide test arguments
        test_args = ["--scale", "1.0", "--iterations", "3"]
        with patch.object(sys, "argv", ["script.py"] + test_args):
            args = ExampleArgumentParser.parse_and_validate_args(parser)

        assert args.scale == 1.0
        assert args.iterations == 3

    def test_parse_and_validate_args_mutual_exclusion_phase(self):
        """Test mutual exclusion validation for phase control options."""
        parser = ExampleArgumentParser.create_benchmark_parser("Test")
        ExampleArgumentParser.add_execution_arguments(parser)

        # Test invalid phase options
        test_args = ["--phase", "invalid_phase"]
        with patch.object(sys, "argv", ["script.py"] + test_args):
            # This should work at parser level, validation happens in main
            args = ExampleArgumentParser.parse_and_validate_args(parser)
            assert args.phase == "invalid_phase"

    def test_parse_and_validate_args_mutual_exclusion_verbosity(self):
        """Test mutual exclusion validation for verbosity options."""
        parser = ExampleArgumentParser.create_benchmark_parser("Test")

        # Test conflicting verbosity options
        test_args = ["--verbose", "--quiet"]
        with patch.object(sys, "argv", ["script.py"] + test_args), pytest.raises(SystemExit):
            ExampleArgumentParser.parse_and_validate_args(parser)

    def test_complete_example_parser(self):
        """Test creating a complete example parser with all argument groups."""
        parser = ExampleArgumentParser.create_benchmark_parser("Complete Test", default_scale=0.01)
        ExampleArgumentParser.add_tuning_arguments(parser)
        ExampleArgumentParser.add_execution_arguments(parser)
        ExampleArgumentParser.add_output_arguments(parser)
        ExampleArgumentParser.add_platform_arguments(parser, "duckdb")

        # Test complex argument combination
        test_args = [
            "--scale",
            "2.0",
            "--platform",
            "test.db",
            "--verbose",
            "--tuning-config",
            "tuning.yaml",
            "--iterations",
            "3",
            "--warm-up",
            "1",
            "--concurrent",
            "--streams",
            "2",
            "--save-results",
            "results.json",
            "--export-format",
            "json",
            "--memory-limit",
            "2GB",
            "--threads",
            "4",
        ]

        with patch.object(sys, "argv", ["script.py"] + test_args):
            args = ExampleArgumentParser.parse_and_validate_args(parser)

        # Verify all arguments were parsed correctly
        assert args.scale == 2.0
        assert args.platform == "test.db"
        assert args.verbose is True
        assert args.tuning_config == "tuning.yaml"
        assert args.iterations == 3
        assert args.warm_up == 1
        assert args.concurrent is True
        assert args.streams == 2
        assert args.save_results == "results.json"
        assert args.export_format == ["json"]
        assert args.memory_limit == "2GB"
        assert args.threads == 4


class TestExampleArgumentParserMocked:
    """Test behavior when ExampleArgumentParser is not available."""

    def test_import_failure_handling(self):
        """Test that import failure is handled gracefully."""
        if IMPORTS_AVAILABLE:
            assert ExampleArgumentParser is not None
            return
        assert "not available" in skip_reason


class TestArgumentParserIntegration:
    """Test integration aspects that should work regardless of import availability."""

    def test_argparse_available(self):
        """Test that basic argparse is available."""
        # argparse is part of standard library, should always be available
        parser = argparse.ArgumentParser(description="Test")
        parser.add_argument("--test", type=str, help="Test argument")

        args = parser.parse_args(["--test", "value"])
        assert args.test == "value"

    def test_argument_patterns(self):
        """Test common argument patterns used in examples."""
        parser = argparse.ArgumentParser()

        # Common patterns from examples
        parser.add_argument("--scale", type=float, default=1.0)
        parser.add_argument("--platform", type=str)
        parser.add_argument("--verbose", action="store_true")
        parser.add_argument("--quiet", action="store_true")

        # Test basic parsing
        args = parser.parse_args(["--scale", "0.1", "--verbose"])
        assert args.scale == 0.1
        assert args.verbose is True
        assert args.quiet is False
        assert args.platform is None
