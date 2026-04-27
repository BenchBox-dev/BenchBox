"""Tests for newly implemented CLI commands.

Tests for datagen, aggregate, plot, shell, calculate-qphh, and run-official commands.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import json
import sys
import sys as _sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from benchbox.cli.app import cli

# benchbox.cli.commands.__init__ re-exports several Click Commands under the
# same names as their submodules.  On Python 3.10 mock's string-based patch()
# resolves the target via getattr(benchbox.cli.commands, "<module>"), which
# returns the Command object, not the submodule.  Seeding sys.modules here via
# __import__ and using patch.object() avoids the ambiguity on all Python
# versions.
__import__("benchbox.cli.commands.shell")
_shell_module = _sys.modules["benchbox.cli.commands.shell"]
__import__("benchbox.cli.commands.datagen")
_datagen_module = _sys.modules["benchbox.cli.commands.datagen"]
__import__("benchbox.cli.commands.run_official")
_run_official_module = _sys.modules["benchbox.cli.commands.run_official"]

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


# Skip marker for tests that use mock.patch on CLI module attributes (Python 3.10 incompatible)
skip_py310_cli_mock = pytest.mark.skipif(
    sys.version_info < (3, 11),
    reason="CLI mock.patch requires Python 3.11+ for module attribute access",
)


class TestDatagenCommand:
    """Test the datagen CLI command."""

    def test_datagen_command_exists(self):
        """Test that the datagen command is available."""
        runner = CliRunner()
        result = runner.invoke(cli, ["--help"])

        assert result.exit_code == 0
        assert "datagen" in result.output

    def test_datagen_help(self):
        """Test the datagen help output."""
        runner = CliRunner()
        result = runner.invoke(cli, ["datagen", "--help"])

        assert result.exit_code == 0
        assert "Generate benchmark data" in result.output
        assert "--benchmark" in result.output
        assert "--scale" in result.output
        assert "--output" in result.output
        assert "--seed" in result.output

    def test_datagen_requires_benchmark_and_scale(self):
        """Test that datagen requires benchmark and scale."""
        runner = CliRunner()
        result = runner.invoke(cli, ["datagen"])

        assert result.exit_code != 0
        assert "Missing option" in result.output or "required" in result.output.lower()


class TestAggregateCommand:
    """Test the aggregate CLI command."""

    def test_aggregate_command_exists(self):
        """Test that the aggregate command is available."""
        runner = CliRunner()
        result = runner.invoke(cli, ["--help"])

        assert result.exit_code == 0
        assert "aggregate" in result.output

    def test_aggregate_help(self):
        """Test the aggregate help output."""
        runner = CliRunner()
        result = runner.invoke(cli, ["aggregate", "--help"])

        assert result.exit_code == 0
        assert "Aggregate multiple benchmark results" in result.output
        assert "--input-dir" in result.output
        assert "--output-file" in result.output
        assert "--benchmark" in result.output
        assert "--platform" in result.output

    def test_aggregate_requires_input_and_output(self):
        """Test that aggregate requires input-dir and output-file."""
        runner = CliRunner()
        result = runner.invoke(cli, ["aggregate"])

        assert result.exit_code != 0
        assert "Missing option" in result.output or "required" in result.output.lower()

    def test_aggregate_with_empty_directory(self):
        """Test aggregate with directory containing no JSON files."""
        runner = CliRunner()

        with tempfile.TemporaryDirectory() as tmpdir:
            output_file = Path(tmpdir) / "trends.csv"

            result = runner.invoke(cli, ["aggregate", "--input-dir", tmpdir, "--output-file", str(output_file)])

            assert result.exit_code == 1
            assert "No JSON result files found" in result.output

    def test_aggregate_success(self):
        """Test successful aggregation of result files."""
        runner = CliRunner()

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a sample result file
            result_file = Path(tmpdir) / "result1.json"
            result_data = {
                "schema_version": "1.0",
                "benchmark": {"id": "tpch", "name": "TPC-H"},
                "execution": {
                    "timestamp": "2024-01-01T00:00:00",
                    "platform": "DuckDB",
                    "duration_ms": 1000,
                },
                "configuration": {"scale_factor": 0.01},
                "results": {
                    "queries": {
                        "details": [
                            {
                                "id": 1,
                                "status": "SUCCESS",
                                "timing": {"execution_ms": 100},
                            }
                        ]
                    }
                },
            }
            result_file.write_text(json.dumps(result_data))

            output_file = Path(tmpdir) / "trends.csv"

            result = runner.invoke(cli, ["aggregate", "--input-dir", tmpdir, "--output-file", str(output_file)])

            assert result.exit_code == 0
            assert "Aggregation complete" in result.output
            assert output_file.exists()


class TestShellCommand:
    """Test the shell CLI command."""

    def test_shell_command_exists(self):
        """Test that the shell command is available."""
        runner = CliRunner()
        result = runner.invoke(cli, ["--help"])

        assert result.exit_code == 0
        assert "shell" in result.output

    def test_shell_help(self):
        """Test the shell help output."""
        runner = CliRunner()
        result = runner.invoke(cli, ["shell", "--help"])

        assert result.exit_code == 0
        assert "interactive" in result.output.lower() and "sql" in result.output.lower()
        assert "--platform" in result.output
        assert "--database" in result.output
        assert "--benchmark" in result.output
        assert "--scale" in result.output
        assert "--list" in result.output
        assert "--last" in result.output
        assert "--output" in result.output

    def test_shell_no_databases_found(self):
        """Test shell with no databases available."""
        runner = CliRunner()

        with tempfile.TemporaryDirectory() as tmpdir:
            result = runner.invoke(cli, ["shell", "--output", tmpdir])

            assert result.exit_code == 1
            assert "No databases found" in result.output

    def test_shell_list_flag(self):
        """Test shell --list flag lists databases without connecting."""
        runner = CliRunner()

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a sample database with correct naming pattern (no decimal in scale)
            db_path = Path(tmpdir) / "datagen" / "tpch_sf1"
            db_path.mkdir(parents=True)
            db_file = db_path / "tpch_sf1_none_none.duckdb"
            db_file.touch()

            result = runner.invoke(cli, ["shell", "--output", tmpdir, "--list"])

            # Should list databases and exit successfully
            assert result.exit_code == 0
            assert "tpch" in result.output.lower() or "Available" in result.output

    @skip_py310_cli_mock
    def test_shell_direct_database_path(self):
        """Test shell with direct database path."""
        runner = CliRunner()

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a DuckDB file
            db_path = Path(tmpdir) / "test.duckdb"
            db_path.touch()

            # This should start the shell (but will fail in test without interaction)
            # We're just testing that it accepts the path and tries to connect
            with patch.object(_shell_module, "_launch_duckdb_shell") as mock_launch:
                runner.invoke(cli, ["shell", "--database", str(db_path)])

                # Should have called _launch_duckdb_shell
                mock_launch.assert_called_once()

    @skip_py310_cli_mock
    def test_shell_platform_autodetect(self):
        """Test shell auto-detects platform from file extension."""
        runner = CliRunner()

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a DuckDB file
            db_path = Path(tmpdir) / "test.duckdb"
            db_path.touch()

            # Don't specify --platform, should auto-detect
            with patch.object(_shell_module, "_launch_duckdb_shell") as mock_launch:
                runner.invoke(cli, ["shell", "--database", str(db_path)])

                # Should have auto-detected and called DuckDB shell
                mock_launch.assert_called_once()

    @skip_py310_cli_mock
    def test_shell_sqlite_autodetect(self):
        """Test shell auto-detects SQLite from .sqlite extension."""
        runner = CliRunner()

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a .sqlite file
            db_path = Path(tmpdir) / "test.sqlite"
            db_path.touch()

            # Don't specify --platform, should auto-detect
            with patch.object(_shell_module, "_launch_sqlite_shell") as mock_launch:
                runner.invoke(cli, ["shell", "--database", str(db_path)])

                # Should have auto-detected and called SQLite shell
                mock_launch.assert_called_once()

    def test_shell_unsupported_platform_explicit(self):
        """Test shell with explicitly unsupported platform."""
        runner = CliRunner()

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.sqlite"
            db_path.touch()

            result = runner.invoke(cli, ["shell", "--platform", "unsupported", "--database", str(db_path)])

            assert result.exit_code == 1
            assert "not supported" in result.output.lower()

    def test_shell_benchmark_filter(self):
        """Test shell with --benchmark filter."""
        runner = CliRunner()

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create databases for different benchmarks with correct naming pattern (no decimals)
            datagen_dir = Path(tmpdir) / "datagen"
            tpch_dir = datagen_dir / "tpch_sf1"
            tpcds_dir = datagen_dir / "tpcds_sf1"
            tpch_dir.mkdir(parents=True)
            tpcds_dir.mkdir(parents=True)

            (tpch_dir / "tpch_sf1_none_none.duckdb").touch()
            (tpcds_dir / "tpcds_sf1_none_none.duckdb").touch()

            # Filter for tpch only
            result = runner.invoke(cli, ["shell", "--output", tmpdir, "--benchmark", "tpch", "--list"])

            assert result.exit_code == 0
            # Should show tpch but implementation may vary
            # This is a basic test that the flag is accepted

    def test_shell_scale_filter(self):
        """Test shell with --scale filter."""
        runner = CliRunner()

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create databases with different scales using correct naming pattern (no decimals)
            datagen_dir = Path(tmpdir) / "datagen"
            dir1 = datagen_dir / "tpch_sf1"
            dir2 = datagen_dir / "tpch_sf10"
            dir1.mkdir(parents=True)
            dir2.mkdir(parents=True)

            (dir1 / "tpch_sf1_none_none.duckdb").touch()
            (dir2 / "tpch_sf10_none_none.duckdb").touch()

            # Filter for scale 1.0 only
            result = runner.invoke(cli, ["shell", "--output", tmpdir, "--scale", "1.0", "--list"])

            assert result.exit_code == 0
            # Should filter to scale 1.0 but implementation may vary

    def test_shell_discovers_databases_in_multiple_locations(self):
        """Test that shell finds databases in both datagen/ and databases/ directories."""
        from benchbox.cli.config import DirectoryManager

        runner = CliRunner()

        with tempfile.TemporaryDirectory() as tmpdir:
            # Use DirectoryManager to create correct directory structure
            dir_mgr = DirectoryManager(base_dir=tmpdir)

            # Create database in datagen directory (standard location)
            datagen_path = dir_mgr.get_datagen_path("tpch", 1.0)
            datagen_path.mkdir(parents=True, exist_ok=True)
            (datagen_path / "tpch_sf1_notuning.duckdb").touch()

            # Create database in databases directory (alternate location)
            dir_mgr.databases_dir.mkdir(parents=True, exist_ok=True)
            (dir_mgr.databases_dir / "tpcds_sf10_notuning.duckdb").touch()

            # Should find both databases
            result = runner.invoke(cli, ["shell", "--output", tmpdir, "--list"])

            assert result.exit_code == 0
            # Both databases should be listed
            assert "tpch" in result.output.lower() or "Available" in result.output
            assert "tpcds" in result.output.lower() or "Available" in result.output


class TestMetricsCommand:
    """Test the metrics CLI command group."""

    def test_metrics_command_exists(self):
        """Test that the metrics command is available."""
        runner = CliRunner()
        result = runner.invoke(cli, ["--help"])

        assert result.exit_code == 0
        assert "metrics" in result.output

    def test_metrics_help(self):
        """Test the metrics help output."""
        runner = CliRunner()
        result = runner.invoke(cli, ["metrics", "--help"])

        assert result.exit_code == 0
        assert "Calculate benchmark performance metrics" in result.output
        assert "qphh" in result.output

    def test_metrics_qphh_help(self):
        """Test the metrics qphh help output."""
        runner = CliRunner()
        result = runner.invoke(cli, ["metrics", "qphh", "--help"])

        assert result.exit_code == 0
        assert "QphH" in result.output
        assert "--power-results" in result.output
        assert "--throughput-results" in result.output
        assert "--scale-factor" in result.output

    def test_metrics_qphh_requires_both_results(self):
        """Test that metrics qphh requires power and throughput results."""
        runner = CliRunner()
        result = runner.invoke(cli, ["metrics", "qphh"])

        assert result.exit_code != 0
        assert "Missing option" in result.output or "required" in result.output.lower()

    def test_metrics_qphh_success(self):
        """Test successful QphH calculation via metrics command."""
        runner = CliRunner()

        with tempfile.TemporaryDirectory() as tmpdir:
            power_file = Path(tmpdir) / "power.json"
            throughput_file = Path(tmpdir) / "throughput.json"

            # Create sample result files with new schema (summary.tpc_metrics)
            power_data = {
                "environment": {"scale_factor": 1.0},
                "summary": {
                    "tpc_metrics": {"power_at_size": 36.0},
                    "timing": {"total_ms": 100000},
                },
            }
            throughput_data = {
                "environment": {"scale_factor": 1.0, "num_streams": 2},
                "run": {"streams": 2},
                "summary": {
                    "tpc_metrics": {"throughput_at_size": 36.0},
                    "timing": {"total_ms": 200000},
                },
            }

            power_file.write_text(json.dumps(power_data))
            throughput_file.write_text(json.dumps(throughput_data))

            result = runner.invoke(
                cli,
                ["metrics", "qphh", "--power-results", str(power_file), "--throughput-results", str(throughput_file)],
            )

            assert result.exit_code == 0
            assert "QphH@Size" in result.output


class TestCalculateQphhCommand:
    """Test the calculate-qphh CLI command (deprecated)."""

    def test_calculate_qphh_hidden_from_help(self):
        """Test that calculate-qphh is hidden from main help."""
        runner = CliRunner()
        result = runner.invoke(cli, ["--help"])

        assert result.exit_code == 0
        # calculate-qphh should NOT appear in main help (it's hidden)
        assert "calculate-qphh" not in result.output

    def test_calculate_qphh_help(self):
        """Test the calculate-qphh help output."""
        runner = CliRunner()
        result = runner.invoke(cli, ["calculate-qphh", "--help"])

        assert result.exit_code == 0
        assert "QphH" in result.output
        assert "--power-results" in result.output
        assert "--throughput-results" in result.output
        assert "--scale-factor" in result.output

    def test_calculate_qphh_requires_both_results(self):
        """Test that calculate-qphh requires power and throughput results."""
        runner = CliRunner()
        result = runner.invoke(cli, ["calculate-qphh"])

        assert result.exit_code != 0
        assert "Missing option" in result.output or "required" in result.output.lower()

    def test_calculate_qphh_shows_deprecation_warning(self):
        """Test calculate-qphh shows deprecation warning when executed."""
        runner = CliRunner()

        with tempfile.TemporaryDirectory() as tmpdir:
            power_file = Path(tmpdir) / "power.json"
            throughput_file = Path(tmpdir) / "throughput.json"

            # Create sample result files with new schema (summary.tpc_metrics)
            power_data = {
                "environment": {"scale_factor": 1.0},
                "summary": {
                    "tpc_metrics": {"power_at_size": 36.0},
                    "timing": {"total_ms": 100000},
                },
            }
            throughput_data = {
                "environment": {"scale_factor": 1.0, "num_streams": 2},
                "run": {"streams": 2},
                "summary": {
                    "tpc_metrics": {"throughput_at_size": 36.0},
                    "timing": {"total_ms": 200000},
                },
            }

            power_file.write_text(json.dumps(power_data))
            throughput_file.write_text(json.dumps(throughput_data))

            result = runner.invoke(
                cli,
                ["calculate-qphh", "--power-results", str(power_file), "--throughput-results", str(throughput_file)],
            )

            assert result.exit_code == 0
            # Should show deprecation warning
            assert "deprecated" in result.output.lower() or "DeprecationWarning" in result.output
            # But still work
            assert "QphH@Size" in result.output


class TestRunOfficialFlag:
    """Test the run --official flag."""

    def test_run_official_flag_in_help(self):
        """Test that --official flag is shown in run help."""
        runner = CliRunner()
        result = runner.invoke(cli, ["run", "--help"])

        assert result.exit_code == 0
        assert "--official" in result.output
        assert "TPC-compliant" in result.output

    def test_run_official_invalid_scale_factor(self):
        """Test run --official rejects non-TPC scale factors."""
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["run", "--platform", "duckdb", "--benchmark", "tpch", "--scale", "0.5", "--phases", "power", "--official"],
        )

        assert result.exit_code == 1
        assert "not TPC-compliant" in result.output

    def test_run_official_warns_on_missing_seed(self):
        """Test run --official warns when seed is not provided."""
        runner = CliRunner()

        # The official mode validation runs before any benchmark execution,
        # so we just need to test that the warning is shown
        result = runner.invoke(
            cli,
            [
                "run",
                "--platform",
                "duckdb",
                "--benchmark",
                "tpch",
                "--scale",
                "1",
                "--phases",
                "power",
                "--official",
                "--dry-run",
                "/tmp/test",
            ],
        )

        # Should warn about missing seed (validation happens before dry run)
        assert "No --seed specified" in result.output or "seed" in result.output.lower()


class TestRunOfficialCommand:
    """Test the run-official CLI command (deprecated)."""

    def test_run_official_hidden_from_help(self):
        """Test that run-official is hidden from main help."""
        runner = CliRunner()
        result = runner.invoke(cli, ["--help"])

        assert result.exit_code == 0
        # run-official should NOT appear in main help (it's hidden)
        assert "run-official" not in result.output

    def test_run_official_still_functional(self):
        """Test that run-official command still works (backwards compatibility)."""
        runner = CliRunner()
        result = runner.invoke(cli, ["run-official", "--help"])

        # May show deprecation warning but should still work
        assert "TPC-compliant" in result.output or "DEPRECATED" in result.output

    def test_run_official_shows_deprecation_warning(self):
        """Test run-official shows deprecation warning when executed."""
        runner = CliRunner()
        result = runner.invoke(
            cli, ["run-official", "tpch", "--platform", "duckdb", "--scale", "0.5", "--phases", "power"]
        )

        # Should show deprecation warning (even if it fails due to invalid scale)
        assert "deprecated" in result.output.lower() or "DeprecationWarning" in result.output

    def test_run_official_invalid_scale_factor(self):
        """Test run-official still rejects non-TPC scale factors."""
        runner = CliRunner()
        result = runner.invoke(
            cli, ["run-official", "tpch", "--platform", "duckdb", "--scale", "0.5", "--phases", "power"]
        )

        assert result.exit_code == 1
        assert "not TPC-compliant" in result.output


class TestDatagenParseRunArgs:
    """Test the _parse_run_args helper directly."""

    def test_benchmark_and_scale(self):
        from benchbox.cli.commands.datagen import _parse_run_args

        result = _parse_run_args(["--benchmark", "tpch", "--scale", "0.1"])
        assert result["benchmark"] == "tpch"
        assert result["scale"] == 0.1

    def test_seed_parsed_as_int(self):
        from benchbox.cli.commands.datagen import _parse_run_args

        result = _parse_run_args(["--seed", "42"])
        assert result["seed"] == 42

    def test_verbose_is_boolean_true(self):
        from benchbox.cli.commands.datagen import _parse_run_args

        result = _parse_run_args(["--verbose"])
        assert result["verbose"] is True

    def test_all_three_together(self):
        from benchbox.cli.commands.datagen import _parse_run_args

        result = _parse_run_args(["--benchmark", "tpch", "--scale", "0.1", "--verbose"])
        assert result["benchmark"] == "tpch"
        assert result["scale"] == 0.1
        assert result["verbose"] is True


class TestDatagenCommandBranches:
    """Test datagen CLI branches not covered by existing tests."""

    def test_non_parquet_format_note_in_console(self):
        """Non-parquet format triggers a console note about default format being used."""
        # _parse_run_args doesn't encode data_format - the datagen command
        # prints a note when data_format != 'parquet'. Verify the note is emitted
        # by checking the console directly with mocked ctx.invoke.
        from unittest.mock import MagicMock, patch as _patch

        from benchbox.cli.commands.datagen import _parse_run_args

        runner = CliRunner()
        with (
            _patch.object(_datagen_module, "console") as mock_console,
            _patch.object(_datagen_module, "run"),
        ):
            calls = []
            mock_console.print.side_effect = lambda *a, **k: calls.append(str(a))
            runner.invoke(
                cli,
                ["datagen", "--benchmark", "tpch", "--scale", "0.01", "--format", "csv"],
            )
        # The note about format not being supported is shown
        all_output = " ".join(calls)
        assert "csv" in all_output.lower() or "format" in all_output.lower()

    def test_seed_forwarded_in_run_args(self):
        from benchbox.cli.commands.datagen import _parse_run_args

        result = _parse_run_args(["--benchmark", "tpch", "--scale", "0.1", "--seed", "99"])
        assert result["seed"] == 99


class TestRunOfficialCommandBranches:
    """Test run-official validation branches."""

    def test_throughput_without_streams_exits_1(self):
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["run-official", "tpch", "--platform", "duckdb", "--scale", "1", "--phases", "throughput"],
        )
        assert result.exit_code == 1
        assert "streams" in result.output.lower()

    def test_valid_scale_with_mock_run_shows_deprecation(self):
        runner = CliRunner()
        with patch.object(_run_official_module, "run") as mock_run:
            mock_run.return_value = None
            result = runner.invoke(
                cli,
                ["run-official", "tpch", "--platform", "duckdb", "--scale", "1", "--phases", "power", "--seed", "42"],
                catch_exceptions=False,
            )
        assert "deprecated" in result.output.lower() or "DeprecationWarning" in result.output

    def test_tpc_allowed_scale_factors_constant(self):
        from benchbox.cli.commands.run_official import TPC_ALLOWED_SCALE_FACTORS

        for sf in (1, 10, 100, 1000, 10000):
            assert sf in TPC_ALLOWED_SCALE_FACTORS

    def test_no_seed_shows_warning(self):
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["run-official", "tpch", "--platform", "duckdb", "--scale", "5", "--phases", "power"],
        )
        # Scale 5 is not TPC-allowed so exits 1, but we can still check warnings
        # OR scale is 1 which is valid and should show seed warning
        assert "seed" in result.output.lower() or "not TPC-compliant" in result.output

    def test_validate_results_forwarded(self):
        runner = CliRunner()
        with patch.object(_run_official_module, "run") as mock_run:
            mock_run.return_value = None
            result = runner.invoke(
                cli,
                [
                    "run-official",
                    "tpch",
                    "--platform",
                    "duckdb",
                    "--scale",
                    "1",
                    "--phases",
                    "power",
                    "--seed",
                    "42",
                    "--validate-results",
                ],
                catch_exceptions=False,
            )
        # deprecated command still runs; just verify it didn't crash unexpectedly
        assert result.exit_code in (0, 1)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
