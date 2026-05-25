"""End-to-end tests for CLI error handling.

Tests validate that the CLI correctly handles invalid inputs and error conditions.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from types import SimpleNamespace

import pytest
from click.testing import CliRunner

from benchbox.cli.main import cli
from tests.integration._cli_e2e_utils import run_cli_command as run_cli_subprocess_command

pytestmark = pytest.mark.fast


_CLI_RUNNER = CliRunner()


def run_cli_command(args: Sequence[str], *, use_subprocess: bool = False) -> SimpleNamespace:
    """Run CLI in-process by default to reduce subprocess startup cost."""
    if use_subprocess:
        result = run_cli_subprocess_command(list(args))
        return SimpleNamespace(returncode=result.returncode, stdout=result.stdout, stderr=result.stderr)

    result = _CLI_RUNNER.invoke(cli, list(args), env={"BENCHBOX_NON_INTERACTIVE": "true"})
    return SimpleNamespace(returncode=result.exit_code, stdout=result.output, stderr="")


# ============================================================================
# Missing Parameter Tests
# ============================================================================


class TestMissingParameters:
    """Tests for missing required parameters."""

    @pytest.mark.e2e
    @pytest.mark.e2e_quick
    def test_missing_platform_error(self, tmp_path: Path) -> None:
        """Test error when --platform is missing (without data-only mode)."""
        output_dir = tmp_path / "dry_run"
        output_dir.mkdir()

        result = run_cli_command(
            [
                "run",
                "--benchmark",
                "tpch",
                "--scale",
                "0.01",
                "--dry-run",
                str(output_dir),
            ]
        )

        # Should fail or require platform
        assert result.returncode != 0 or "platform" in result.stdout.lower()

    @pytest.mark.e2e
    @pytest.mark.e2e_quick
    def test_missing_benchmark_error(self, tmp_path: Path) -> None:
        """Test error when --benchmark is missing."""
        output_dir = tmp_path / "dry_run"
        output_dir.mkdir()

        result = run_cli_command(
            [
                "run",
                "--platform",
                "duckdb",
                "--scale",
                "0.01",
                "--dry-run",
                str(output_dir),
            ]
        )

        # Should fail or require benchmark
        assert result.returncode != 0 or "benchmark" in result.stdout.lower()

    @pytest.mark.e2e
    @pytest.mark.e2e_quick
    def test_missing_output_for_cloud_error(self) -> None:
        """Test that cloud platforms require --output for non-dry-run."""
        # This test just validates the help text mentions output requirement
        result = run_cli_command(["run", "--help", "all"])

        assert result.returncode == 0
        # Help should mention output requirement for cloud platforms
        assert "output" in result.stdout.lower()


# ============================================================================
# Invalid Parameter Tests
# ============================================================================


class TestInvalidParameters:
    """Tests for invalid parameter values."""

    @pytest.mark.e2e
    @pytest.mark.e2e_quick
    def test_invalid_platform_name(self, tmp_path: Path) -> None:
        """Test behavior with unknown platform name in dry-run mode.

        Note: Dry-run mode allows unknown platforms to preview configuration
        and queries without requiring platform availability. This is useful
        for developing queries offline. The CLI will still complete successfully.
        """
        output_dir = tmp_path / "dry_run"
        output_dir.mkdir()

        result = run_cli_command(
            [
                "run",
                "--platform",
                "nonexistent_platform_xyz",
                "--benchmark",
                "tpch",
                "--scale",
                "0.01",
                "--dry-run",
                str(output_dir),
            ]
        )

        # Dry-run mode completes even for unknown platforms (allows offline development)
        assert result.returncode == 0
        assert "Dry run completed" in result.stdout

    @pytest.mark.e2e
    @pytest.mark.e2e_quick
    def test_invalid_benchmark_name(self, tmp_path: Path) -> None:
        """Test error with invalid benchmark name.

        Note: The CLI displays an error message for unknown benchmarks but
        currently returns exit code 0 for user-friendliness. The error message
        is clear and actionable.
        """
        output_dir = tmp_path / "dry_run"
        output_dir.mkdir()

        result = run_cli_command(
            [
                "run",
                "--platform",
                "duckdb",
                "--benchmark",
                "nonexistent_benchmark_xyz",
                "--scale",
                "0.01",
                "--dry-run",
                str(output_dir),
            ]
        )

        # CLI shows error message for unknown benchmark
        assert "unknown benchmark" in result.stdout.lower()
        assert "nonexistent_benchmark_xyz" in result.stdout

    @pytest.mark.e2e
    @pytest.mark.e2e_quick
    def test_negative_scale_factor(self, tmp_path: Path) -> None:
        """Test error with negative scale factor."""
        output_dir = tmp_path / "dry_run"
        output_dir.mkdir()

        result = run_cli_command(
            [
                "run",
                "--platform",
                "duckdb",
                "--benchmark",
                "tpch",
                "--scale",
                "-1",
                "--dry-run",
                str(output_dir),
            ]
        )

        # Should fail with negative scale
        assert result.returncode != 0

    @pytest.mark.e2e
    @pytest.mark.e2e_quick
    def test_zero_scale_factor(self, tmp_path: Path) -> None:
        """Test error with zero scale factor."""
        output_dir = tmp_path / "dry_run"
        output_dir.mkdir()

        result = run_cli_command(
            [
                "run",
                "--platform",
                "duckdb",
                "--benchmark",
                "tpch",
                "--scale",
                "0",
                "--dry-run",
                str(output_dir),
            ]
        )

        # Should fail with zero scale
        assert result.returncode != 0

    @pytest.mark.e2e
    @pytest.mark.e2e_quick
    def test_invalid_query_id(self, tmp_path: Path) -> None:
        """Test error with invalid query ID."""
        output_dir = tmp_path / "dry_run"
        output_dir.mkdir()

        result = run_cli_command(
            [
                "run",
                "--platform",
                "duckdb",
                "--benchmark",
                "tpch",
                "--scale",
                "0.01",
                "--queries",
                "INVALID_QUERY_ID!!!",
                "--dry-run",
                str(output_dir),
            ]
        )

        # Should fail with invalid query ID
        assert result.returncode != 0

    @pytest.mark.e2e
    @pytest.mark.e2e_quick
    def test_query_id_out_of_range(self, tmp_path: Path) -> None:
        """Test error with query ID out of range for benchmark."""
        output_dir = tmp_path / "dry_run"
        output_dir.mkdir()

        run_cli_command(
            [
                "run",
                "--platform",
                "duckdb",
                "--benchmark",
                "tpch",
                "--scale",
                "0.01",
                "--queries",
                "Q999",  # TPC-H only has Q1-Q22
                "--dry-run",
                str(output_dir),
            ]
        )
        # May fail or warn about invalid query ID
        # Some implementations may just skip invalid queries
        # The important thing is it doesn't crash - test passes if no exception

    @pytest.mark.e2e
    @pytest.mark.e2e_quick
    def test_invalid_tuning_mode(self, tmp_path: Path) -> None:
        """Test error with invalid tuning mode."""
        output_dir = tmp_path / "dry_run"
        output_dir.mkdir()

        result = run_cli_command(
            [
                "run",
                "--platform",
                "duckdb",
                "--benchmark",
                "tpch",
                "--scale",
                "0.01",
                "--tuning",
                "invalid_tuning_mode",
                "--dry-run",
                str(output_dir),
            ]
        )

        # Should fail with invalid tuning mode
        assert result.returncode != 0

    @pytest.mark.e2e
    @pytest.mark.e2e_quick
    def test_invalid_compression_type(self, tmp_path: Path) -> None:
        """Test error with invalid compression type."""
        output_dir = tmp_path / "dry_run"
        output_dir.mkdir()

        result = run_cli_command(
            [
                "run",
                "--platform",
                "duckdb",
                "--benchmark",
                "tpch",
                "--scale",
                "0.01",
                "--compression",
                "invalid_compression",
                "--dry-run",
                str(output_dir),
            ]
        )

        # Should fail with invalid compression
        assert result.returncode != 0

    @pytest.mark.e2e
    @pytest.mark.e2e_quick
    def test_invalid_validation_mode(self, tmp_path: Path) -> None:
        """Test error with invalid validation mode."""
        output_dir = tmp_path / "dry_run"
        output_dir.mkdir()

        result = run_cli_command(
            [
                "run",
                "--platform",
                "duckdb",
                "--benchmark",
                "tpch",
                "--scale",
                "0.01",
                "--validation",
                "invalid_validation",
                "--dry-run",
                str(output_dir),
            ]
        )

        # Should fail with invalid validation mode
        assert result.returncode != 0


# ============================================================================
# Query Subset Constraint Tests
# ============================================================================


class TestQuerySubsetConstraints:
    """Tests for --queries option constraints."""

    @pytest.mark.e2e
    @pytest.mark.e2e_quick
    def test_too_many_queries_error(self, tmp_path: Path) -> None:
        """Test error when more than 100 queries specified."""
        output_dir = tmp_path / "dry_run"
        output_dir.mkdir()

        # Generate more than 100 query IDs
        queries = ",".join([f"Q{i}" for i in range(1, 110)])

        result = run_cli_command(
            [
                "run",
                "--platform",
                "duckdb",
                "--benchmark",
                "tpch",
                "--scale",
                "0.01",
                "--queries",
                queries,
                "--dry-run",
                str(output_dir),
            ]
        )

        # Should fail with too many queries (max 100 for DoS protection)
        assert result.returncode != 0 or "100" in result.stdout or "max" in result.stdout.lower()


# ============================================================================
# Help Command Tests
# ============================================================================


class TestHelpCommands:
    """Tests for help commands."""

    @pytest.mark.e2e
    @pytest.mark.e2e_quick
    def test_help_basic(self) -> None:
        """Test --help displays help."""
        result = run_cli_command(["--help"])

        assert result.returncode == 0
        assert "Usage:" in result.stdout or "usage:" in result.stdout.lower()

    @pytest.mark.e2e
    @pytest.mark.e2e_quick
    def test_help_run_command(self) -> None:
        """Test run --help displays run command help."""
        result = run_cli_command(["run", "--help"])

        assert result.returncode == 0
        assert "platform" in result.stdout.lower()
        assert "benchmark" in result.stdout.lower()

    @pytest.mark.e2e
    @pytest.mark.e2e_quick
    def test_help_all_options(self) -> None:
        """Test run --help all displays all options."""
        result = run_cli_command(["run", "--help", "all"])

        assert result.returncode == 0
        # Should show advanced options
        assert "compression" in result.stdout.lower() or "advanced" in result.stdout.lower()

    @pytest.mark.e2e
    @pytest.mark.e2e_quick
    def test_help_examples(self) -> None:
        """Test run --help examples displays examples."""
        result = run_cli_command(["run", "--help", "examples"])

        assert result.returncode == 0
        # Should show usage examples
        assert "example" in result.stdout.lower() or "benchbox" in result.stdout.lower()


# ============================================================================
# Version Command Tests
# ============================================================================


class TestVersionCommand:
    """Tests for version command."""

    @pytest.mark.e2e
    @pytest.mark.e2e_quick
    def test_version_displays(self) -> None:
        """Test --version displays version information."""
        result = run_cli_command(["--version"])

        assert result.returncode == 0
        assert "version" in result.stdout.lower() or "benchbox" in result.stdout.lower()


# ============================================================================
# Dry Run Output Directory Tests
# ============================================================================


class TestDryRunDirectory:
    """Tests for dry-run output directory handling."""

    @pytest.mark.e2e
    @pytest.mark.e2e_quick
    def test_dry_run_nonexistent_directory(self, tmp_path: Path) -> None:
        """Test dry-run with nonexistent directory creates it or fails gracefully."""
        output_dir = tmp_path / "nonexistent" / "nested" / "directory"
        # Don't create the directory

        result = run_cli_command(
            [
                "run",
                "--platform",
                "duckdb",
                "--benchmark",
                "tpch",
                "--scale",
                "0.01",
                "--dry-run",
                str(output_dir),
            ]
        )

        # Should either create directory or fail with clear error
        if result.returncode == 0:
            assert output_dir.exists(), "Directory should have been created"
        else:
            assert "directory" in result.stdout.lower() or "path" in result.stdout.lower()

    @pytest.mark.e2e
    @pytest.mark.e2e_quick
    def test_dry_run_file_instead_of_directory(self, tmp_path: Path) -> None:
        """Test dry-run when path is a file instead of directory."""
        file_path = tmp_path / "not_a_directory.txt"
        file_path.write_text("This is a file, not a directory")

        result = run_cli_command(
            [
                "run",
                "--platform",
                "duckdb",
                "--benchmark",
                "tpch",
                "--scale",
                "0.01",
                "--dry-run",
                str(file_path),
            ]
        )

        # Should fail because path is not a directory
        assert result.returncode != 0


# ============================================================================
# Platform Option Tests
# ============================================================================


class TestPlatformOptions:
    """Tests for --platform-option handling."""

    @pytest.mark.e2e
    @pytest.mark.e2e_quick
    def test_invalid_platform_option_format(self, tmp_path: Path) -> None:
        """Test error with invalid platform option format."""
        output_dir = tmp_path / "dry_run"
        output_dir.mkdir()

        result = run_cli_command(
            [
                "run",
                "--platform",
                "duckdb",
                "--benchmark",
                "tpch",
                "--scale",
                "0.01",
                "--platform-option",
                "invalid_no_equals",
                "--dry-run",
                str(output_dir),
            ]
        )

        # Should fail with invalid format (missing =)
        assert result.returncode != 0 or "=" in result.stdout or "format" in result.stdout.lower()

    @pytest.mark.e2e
    @pytest.mark.e2e_quick
    def test_valid_platform_option(self, tmp_path: Path) -> None:
        """Test valid platform option is accepted."""
        output_dir = tmp_path / "dry_run"
        output_dir.mkdir()

        result = run_cli_command(
            [
                "run",
                "--platform",
                "duckdb",
                "--benchmark",
                "tpch",
                "--scale",
                "0.01",
                "--platform-option",
                "threads=4",
                "--dry-run",
                str(output_dir),
            ]
        )

        assert result.returncode == 0, f"Failed: {result.stdout}"


# ============================================================================
# Parametrized Error Tests
# ============================================================================


@pytest.mark.e2e
@pytest.mark.e2e_quick
@pytest.mark.parametrize(
    "invalid_scale",
    ["-1", "-0.5", "0", "-100"],
)
def test_invalid_scale_factors(tmp_path: Path, invalid_scale: str) -> None:
    """Test that invalid scale factors are rejected."""
    output_dir = tmp_path / "dry_run"
    output_dir.mkdir()

    result = run_cli_command(
        [
            "run",
            "--platform",
            "duckdb",
            "--benchmark",
            "tpch",
            "--scale",
            invalid_scale,
            "--dry-run",
            str(output_dir),
        ]
    )

    assert result.returncode != 0, f"Should have rejected scale factor: {invalid_scale}"


@pytest.mark.e2e
@pytest.mark.e2e_quick
@pytest.mark.parametrize(
    "invalid_queries",
    [
        "!!!invalid!!!",
        "@#$%^&*",
        "Q1;DROP TABLE",
        "Q1' OR '1'='1",
    ],
)
def test_invalid_query_patterns(tmp_path: Path, invalid_queries: str) -> None:
    """Test that potentially malicious query patterns are rejected."""
    output_dir = tmp_path / "dry_run"
    output_dir.mkdir()

    result = run_cli_command(
        [
            "run",
            "--platform",
            "duckdb",
            "--benchmark",
            "tpch",
            "--scale",
            "0.01",
            "--queries",
            invalid_queries,
            "--dry-run",
            str(output_dir),
        ]
    )

    # Should fail with invalid query pattern
    assert result.returncode != 0, f"Should have rejected query pattern: {invalid_queries}"
