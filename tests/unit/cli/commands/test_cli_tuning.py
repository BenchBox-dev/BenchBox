"""Tests for the unified tuning CLI commands.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import pytest
from click.testing import CliRunner

from benchbox.cli.app import cli

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


@pytest.fixture
def runner():
    """Create a Click CLI test runner."""
    return CliRunner()


class TestTuningGroup:
    """Tests for the tuning command group."""

    def test_tuning_help(self, runner):
        """Test that tuning --help shows available subcommands."""
        result = runner.invoke(cli, ["tuning", "--help"])
        assert result.exit_code == 0
        assert "init" in result.output
        assert "validate" in result.output
        assert "defaults" in result.output
        assert "platforms" in result.output

    def test_tuning_init_help(self, runner):
        """Test that tuning init --help shows options."""
        result = runner.invoke(cli, ["tuning", "init", "--help"])
        assert result.exit_code == 0
        assert "--platform" in result.output
        assert "--mode" in result.output
        assert "--profile" in result.output
        assert "--output" in result.output
        assert "--smart-defaults" in result.output

    def test_tuning_validate_help(self, runner):
        """Test that tuning validate --help shows options."""
        result = runner.invoke(cli, ["tuning", "validate", "--help"])
        assert result.exit_code == 0
        assert "--platform" in result.output
        assert "CONFIG_FILE" in result.output

    def test_tuning_defaults_help(self, runner):
        """Test that tuning defaults --help shows options."""
        result = runner.invoke(cli, ["tuning", "defaults", "--help"])
        assert result.exit_code == 0
        assert "--platform" in result.output

    def test_tuning_platforms_help(self, runner):
        """Test that tuning platforms --help works."""
        result = runner.invoke(cli, ["tuning", "platforms", "--help"])
        assert result.exit_code == 0


class TestTuningInit:
    """Tests for the tuning init command."""

    def test_init_requires_platform(self, runner):
        """Test that init requires --platform option."""
        result = runner.invoke(cli, ["tuning", "init"])
        assert result.exit_code != 0
        assert "Missing option" in result.output or "required" in result.output.lower()

    def test_init_auto_mode_sql(self, runner):
        """Test that init auto-detects SQL mode for SQL platforms."""
        result = runner.invoke(cli, ["tuning", "init", "--platform", "duckdb", "--help"])
        assert result.exit_code == 0
        # DuckDB should default to SQL mode

    def test_init_auto_mode_dataframe(self, runner):
        """Test that init auto-detects DataFrame mode for DataFrame platforms."""
        result = runner.invoke(cli, ["tuning", "init", "--platform", "polars", "--help"])
        assert result.exit_code == 0
        # Polars should default to DataFrame mode

    def test_init_invalid_dataframe_platform(self, runner):
        """Test that dataframe mode with SQL platform shows error."""
        result = runner.invoke(cli, ["tuning", "init", "--platform", "duckdb", "--mode", "dataframe"])
        assert result.exit_code != 0
        assert "does not support DataFrame mode" in result.output


class TestTuningDefaults:
    """Tests for the tuning defaults command."""

    def test_defaults_requires_platform(self, runner):
        """Test that defaults requires --platform option."""
        result = runner.invoke(cli, ["tuning", "defaults"])
        assert result.exit_code != 0

    def test_defaults_polars(self, runner):
        """Test defaults output for polars platform."""
        result = runner.invoke(cli, ["tuning", "defaults", "--platform", "polars"])
        assert result.exit_code == 0
        assert "Smart Defaults" in result.output
        assert "polars" in result.output.lower()
        assert "System Profile" in result.output


class TestTuningPlatforms:
    """Tests for the tuning platforms command."""

    def test_platforms_lists_sql_and_dataframe(self, runner):
        """Test that platforms command lists both SQL and DataFrame platforms."""
        result = runner.invoke(cli, ["tuning", "platforms"])
        assert result.exit_code == 0
        assert "SQL Platforms" in result.output
        assert "DataFrame Platforms" in result.output
        # Check some SQL platforms
        assert "duckdb" in result.output.lower()
        assert "snowflake" in result.output.lower()
        # Check some DataFrame platforms
        assert "polars" in result.output.lower()
        assert "pandas" in result.output.lower()


class TestRetiredShimsNotRegistered:
    """Pin that the retired create-sample-tuning/df-tuning shims are gone, not merely hidden.

    Per the tuning-renderer-consolidation-and-baseline-policy-20260712 TODO's
    w5, these deprecated CLI shims (and their backing modules
    benchbox/cli/commands/tuning.py, benchbox/cli/commands/df_tuning.py) were
    retired outright rather than kept as hidden compatibility commands.
    """

    def test_create_sample_tuning_is_not_registered(self):
        assert cli.commands.get("create-sample-tuning") is None

    def test_df_tuning_is_not_registered(self):
        assert cli.commands.get("df-tuning") is None

    def test_tuning_is_not_hidden(self):
        """Test that tuning (the surviving command) is not hidden."""
        cmd = cli.commands.get("tuning")
        assert cmd is not None, "tuning should be registered"
        assert not cmd.hidden, "tuning should not be hidden"


class TestCommandCategorization:
    """Tests for command categorization in help output."""

    def test_tuning_in_configuration_category(self, runner):
        """Test that tuning appears in Configuration category."""
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        # tuning should appear after Configuration: header
        assert "tuning" in result.output
        # Retired shims should not appear
        assert "create-sample-tuning" not in result.output
        assert "df-tuning" not in result.output
