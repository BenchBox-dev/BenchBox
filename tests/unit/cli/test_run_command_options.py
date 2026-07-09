"""Tests for run command option parsing, validation, and error handling.

Covers CLI-level behavior for the `benchbox run` command including:
- Option conflict detection (--quiet + --verbose)
- Phase validation
- Official mode constraints
- Table mode / tuning incompatibility
- Dry-run mode edge cases
- Help topic rendering
- Scale factor validation

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from benchbox.cli.app import cli
from benchbox.cli.commands.run import run
from benchbox.cli.config import ConfigManager

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


def _run_obj():
    """Return the obj dict needed for invoking the run command directly."""
    return {"config": ConfigManager()}


class TestQuietVerboseConflict:
    """Test --quiet and --verbose mutual exclusion."""

    def test_quiet_and_verbose_together_exits_with_code_2(self):
        """Using both --quiet and --verbose should exit with code 2."""
        runner = CliRunner()
        result = runner.invoke(
            run,
            ["--quiet", "--verbose", "--platform", "duckdb", "--benchmark", "tpch"],
            obj={},
        )

        assert result.exit_code == 2
        assert "cannot be used with" in result.output

    def test_quiet_and_double_verbose_together_exits_with_code_2(self):
        """Using both --quiet and -vv should exit with code 2."""
        runner = CliRunner()
        result = runner.invoke(
            run,
            ["--quiet", "-vv", "--platform", "duckdb", "--benchmark", "tpch"],
            obj={},
        )

        assert result.exit_code == 2
        assert "cannot be used with" in result.output


class TestInvalidPhaseValidation:
    """Test that invalid phase names are rejected."""

    def test_invalid_phase_name_rejected(self):
        """A phase name not in the valid set should produce an error."""
        runner = CliRunner()
        result = runner.invoke(
            run,
            ["--platform", "duckdb", "--benchmark", "tpch", "--phases", "bogus_phase"],
            obj={},
        )

        assert result.exit_code == 1
        assert "Invalid phases" in result.output
        assert "bogus_phase" in result.output

    def test_mixed_valid_and_invalid_phases_rejected(self):
        """A mix of valid and invalid phases should still fail."""
        runner = CliRunner()
        result = runner.invoke(
            run,
            ["--platform", "duckdb", "--benchmark", "tpch", "--phases", "power,foobar"],
            obj={},
        )

        assert result.exit_code == 1
        assert "Invalid phases" in result.output
        assert "foobar" in result.output

    def test_valid_phases_shows_valid_list_on_error(self):
        """Error output should list all valid phase names."""
        runner = CliRunner()
        result = runner.invoke(
            run,
            ["--platform", "duckdb", "--benchmark", "tpch", "--phases", "invalid"],
            obj={},
        )

        assert result.exit_code == 1
        assert "Valid phases" in result.output
        for phase in ("generate", "load", "warmup", "power", "throughput", "maintenance"):
            assert phase in result.output


class TestOfficialModeValidation:
    """Test TPC official mode constraints."""

    def test_official_mode_rejects_non_compliant_scale_factor(self):
        """Official mode should reject scale factors not in the allowed set."""
        runner = CliRunner()
        result = runner.invoke(
            run,
            ["--official", "--platform", "duckdb", "--benchmark", "tpch", "--scale", "0.01"],
            obj={},
        )

        assert result.exit_code == 1
        assert "not TPC-compliant" in result.output
        assert "0.01" in result.output

    def test_official_mode_warns_without_seed(self):
        """Official mode without --seed should produce a warning but not fail at this stage."""
        runner = CliRunner()
        result = runner.invoke(
            run,
            [
                "--official",
                "--platform",
                "duckdb",
                "--benchmark",
                "tpch",
                "--scale",
                "1",
                "--phases",
                "generate",
            ],
            obj={},
        )

        # Command may fail later (platform check, etc.), but should get past official validation
        assert "Warning" in result.output or "seed" in result.output.lower()

    def test_official_mode_shows_compliance_banner(self):
        """Official mode with compliant scale shows the compliance banner."""
        runner = CliRunner()
        result = runner.invoke(
            run,
            [
                "--official",
                "--platform",
                "duckdb",
                "--benchmark",
                "tpch",
                "--scale",
                "1",
                "--seed",
                "42",
                "--phases",
                "generate",
            ],
            obj={},
        )

        # Should reach the compliance banner before any downstream failure
        assert "TPC-Compliant" in result.output or "TPC-allowed" in result.output
        assert "Seed: 42" in result.output


class TestTableModeAndTuningIncompatibility:
    """Test --table-mode external + --tuning tuned rejection."""

    def test_external_table_mode_with_tuned_rejected(self):
        """Combining --table-mode external with --tuning tuned should fail."""
        runner = CliRunner()
        result = runner.invoke(
            run,
            [
                "--platform",
                "duckdb",
                "--benchmark",
                "tpch",
                "--table-mode",
                "external",
                "--tuning",
                "tuned",
            ],
            obj={},
        )

        assert result.exit_code == 1
        assert "incompatible" in result.output.lower()

    def test_external_table_mode_with_notuning_allowed(self):
        """--table-mode external with --tuning notuning should pass this validation."""
        runner = CliRunner()
        result = runner.invoke(
            run,
            [
                "--platform",
                "duckdb",
                "--benchmark",
                "tpch",
                "--table-mode",
                "external",
                "--tuning",
                "notuning",
                "--phases",
                "generate",
            ],
            obj={},
        )

        # Should not fail on incompatibility check (may fail later for other reasons)
        assert "incompatible" not in result.output.lower()


class TestDryRunValidation:
    """Test dry-run mode input validation."""

    def test_dry_run_requires_platform_and_benchmark(self):
        """Dry run without --platform and --benchmark should fail."""
        runner = CliRunner()
        result = runner.invoke(
            run,
            ["--dry-run", "/tmp/drytest"],
            obj=_run_obj(),
        )

        assert result.exit_code == 1
        assert "requires --platform and --benchmark" in result.output

    def test_dry_run_data_only_requires_benchmark(self):
        """Dry run with --phases generate requires --benchmark."""
        runner = CliRunner()
        result = runner.invoke(
            run,
            ["--dry-run", "/tmp/drytest", "--phases", "generate"],
            obj=_run_obj(),
        )

        assert result.exit_code == 1
        assert "requires --benchmark" in result.output

    def test_dry_run_rejects_fractional_scale_above_one(self):
        """Dry run should reject non-integer scale factors >= 1 (e.g., 1.5)."""
        runner = CliRunner()
        result = runner.invoke(
            run,
            [
                "--dry-run",
                "/tmp/drytest",
                "--platform",
                "duckdb",
                "--benchmark",
                "tpch",
                "--scale",
                "1.5",
            ],
            obj=_run_obj(),
        )

        assert result.exit_code == 1
        assert "must be whole integers" in result.output
        assert "1.5" in result.output

    def test_dry_run_accepts_integer_scale_factor(self):
        """Dry run should accept integer scale factors >= 1 (e.g., 1, 10)."""
        runner = CliRunner()
        result = runner.invoke(
            run,
            [
                "--dry-run",
                "/tmp/drytest",
                "--platform",
                "duckdb",
                "--benchmark",
                "tpch",
                "--scale",
                "1",
                "--phases",
                "power",
            ],
            obj=_run_obj(),
        )

        # Should get past scale validation (may fail downstream for missing platform)
        assert "must be whole integers" not in result.output

    def test_dry_run_accepts_fractional_scale_below_one(self):
        """Dry run should accept fractional scale factors < 1 (e.g., 0.01)."""
        runner = CliRunner()
        result = runner.invoke(
            run,
            [
                "--dry-run",
                "/tmp/drytest",
                "--platform",
                "duckdb",
                "--benchmark",
                "tpch",
                "--scale",
                "0.01",
                "--phases",
                "power",
            ],
            obj=_run_obj(),
        )

        # Should get past scale validation
        assert "must be whole integers" not in result.output

    def test_dry_run_joinorder_omitted_scale_uses_benchmark_default(self, tmp_path):
        """Omitted --scale should use JoinOrder's canonical SF=1 registry default."""
        runner = CliRunner()

        with patch("benchbox.cli.dryrun.DryRunExecutor") as dry_run_executor:
            dry_run_executor.return_value.execute_dry_run.return_value = MagicMock()
            dry_run_executor.return_value.save_dry_run_results.return_value = {}

            result = runner.invoke(
                run,
                [
                    "--dry-run",
                    str(tmp_path / "drytest"),
                    "--platform",
                    "duckdb",
                    "--benchmark",
                    "joinorder",
                    "--phases",
                    "generate",
                    "--non-interactive",
                ],
                obj=_run_obj(),
            )

        assert result.exit_code == 0, result.output
        benchmark_config = dry_run_executor.return_value.execute_dry_run.call_args.args[0]
        assert benchmark_config.name == "joinorder"
        assert benchmark_config.scale_factor == 1.0

    def test_dry_run_joinorder_explicit_unsupported_scale_still_rejected(self, tmp_path):
        """Explicit --scale 0.01 must still be rejected for canonical JoinOrder."""
        runner = CliRunner()
        result = runner.invoke(
            run,
            [
                "--dry-run",
                str(tmp_path / "drytest"),
                "--platform",
                "duckdb",
                "--benchmark",
                "joinorder",
                "--phases",
                "generate",
                "--scale",
                "0.01",
                "--non-interactive",
            ],
            obj=_run_obj(),
        )

        assert result.exit_code == 1
        assert "joinorder accepts scale_factor in [1.0]; got 0.01" in result.output

    def test_dry_run_unknown_benchmark_rejected(self):
        """Dry run with an unknown benchmark name should fail gracefully."""
        runner = CliRunner()
        result = runner.invoke(
            run,
            [
                "--dry-run",
                "/tmp/drytest",
                "--platform",
                "duckdb",
                "--benchmark",
                "nonexistent_bench",
                "--scale",
                "0.01",
            ],
            obj=_run_obj(),
        )

        assert result.exit_code == 1
        assert "Unknown benchmark" in result.output or "nonexistent_bench" in result.output


class TestHelpTopicRendering:
    """Test --help and --help-topic output."""

    def test_run_help_shows_core_options(self):
        """The basic --help should show core options."""
        runner = CliRunner()
        result = runner.invoke(cli, ["run", "--help"])

        assert result.exit_code == 0
        assert "--platform" in result.output
        assert "--benchmark" in result.output
        assert "--scale" in result.output
        assert "--phases" in result.output
        assert "--dry-run" in result.output
        assert "--queries" in result.output
        assert "--tuning" in result.output

    def test_run_help_topic_all_shows_advanced_options(self):
        """--help-topic all should reveal advanced options."""
        runner = CliRunner()
        result = runner.invoke(cli, ["run", "--help-topic", "all"])

        assert result.exit_code == 0
        assert "--capture-plans" in result.output
        assert "--mode" in result.output
        assert "--seed" in result.output
        assert "--validation" in result.output
        assert "--strict-translation" in result.output
        assert "--presort" in result.output

    def test_run_help_topic_examples_shows_usage_examples(self):
        """--help-topic examples should show usage examples."""
        runner = CliRunner()
        result = runner.invoke(cli, ["run", "--help-topic", "examples"])

        assert result.exit_code == 0
        assert "benchbox run" in result.output
        # Examples should contain platform and benchmark references
        assert "duckdb" in result.output.lower() or "tpch" in result.output.lower()


class TestDryRunDataOnlyMode:
    """Test dry-run with --phases generate (data-only mode)."""

    def test_dry_run_data_only_skips_platform(self):
        """Dry run with --phases generate should note that platform is ignored."""
        runner = CliRunner()
        result = runner.invoke(
            run,
            [
                "--dry-run",
                "/tmp/drytest",
                "--platform",
                "duckdb",
                "--benchmark",
                "tpch",
                "--phases",
                "generate",
                "--scale",
                "0.01",
            ],
            obj=_run_obj(),
        )

        # Should warn that platform is ignored in data-only mode
        assert "Note:" in result.output or "ignored" in result.output.lower()


class TestDuplicatePhaseDedup:
    """Test that duplicate phases are de-duplicated."""

    def test_duplicate_phases_do_not_cause_error(self):
        """Specifying the same phase twice should not fail."""
        runner = CliRunner()
        result = runner.invoke(
            run,
            [
                "--platform",
                "duckdb",
                "--benchmark",
                "tpch",
                "--phases",
                "power,power",
            ],
            obj={},
        )

        # Should not fail on duplicate phases (may fail downstream for platform availability)
        assert "Invalid phases" not in result.output


class TestPlatformOptionsWithoutPlatform:
    """Test --platform-option without --platform."""

    def test_platform_option_without_platform_fails(self):
        """Using --platform-option without --platform should error."""
        runner = CliRunner()
        result = runner.invoke(
            run,
            [
                "--benchmark",
                "tpch",
                "--platform-option",
                "threads=4",
            ],
            obj={},
        )

        assert result.exit_code == 1
        assert "Platform options require a --platform selection" in result.output


class TestNonInteractiveModeValidation:
    """Test non-interactive mode argument requirements."""

    def test_non_interactive_missing_benchmark_fails(self):
        """Non-interactive mode without --benchmark should fail."""
        runner = CliRunner()
        result = runner.invoke(
            run,
            ["--non-interactive", "--platform", "duckdb", "--phases", "power"],
            obj={},
        )

        assert result.exit_code == 2
        assert "Non-interactive mode requires all parameters" in result.output
        assert "--benchmark" in result.output

    def test_non_interactive_missing_platform_for_query_phases(self):
        """Non-interactive mode without --platform for query phases should fail."""
        runner = CliRunner()
        result = runner.invoke(
            run,
            ["--non-interactive", "--benchmark", "tpch", "--phases", "power"],
            obj={},
        )

        assert result.exit_code == 2
        assert "Non-interactive mode requires all parameters" in result.output
        assert "--platform" in result.output

    def test_non_interactive_data_only_does_not_require_platform(self):
        """Non-interactive mode with --phases generate should not require --platform."""
        runner = CliRunner()
        result = runner.invoke(
            run,
            ["--non-interactive", "--benchmark", "tpch", "--phases", "generate"],
            obj={},
        )

        # Should not fail on missing --platform in data-only mode
        assert "Missing: --platform" not in result.output
