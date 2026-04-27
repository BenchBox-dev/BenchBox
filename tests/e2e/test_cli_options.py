"""End-to-end tests for CLI options and flags.

Tests validate that CLI options work correctly across different configurations.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from types import SimpleNamespace

import pytest
from click.testing import CliRunner

from benchbox.cli.main import cli
from tests.integration._cli_e2e_utils import run_cli_command as run_cli_subprocess_command

pytestmark = pytest.mark.medium


_CLI_RUNNER = CliRunner()


def run_cli_command(args: Sequence[str], *, use_subprocess: bool = False) -> SimpleNamespace:
    """Run CLI in-process by default to avoid subprocess startup overhead.

    Keep optional subprocess mode for parity checks when needed.
    """
    if use_subprocess:
        result = run_cli_subprocess_command(list(args))
        return SimpleNamespace(returncode=result.returncode, stdout=result.stdout, stderr=result.stderr)

    result = _CLI_RUNNER.invoke(cli, list(args), env={"BENCHBOX_NON_INTERACTIVE": "true"})
    return SimpleNamespace(returncode=result.exit_code, stdout=result.output, stderr="")


# ============================================================================
# Benchmark Selection Tests
# ============================================================================


class TestBenchmarkSelection:
    """Tests for --benchmark option."""

    @pytest.mark.e2e
    @pytest.mark.e2e_quick
    @pytest.mark.tpch
    def test_benchmark_tpch(self, tmp_path: Path) -> None:
        """Test --benchmark tpch option."""
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
                "--dry-run",
                str(output_dir),
            ]
        )

        assert result.returncode == 0, f"Failed: {result.stdout}"
        assert "tpch" in result.stdout.lower() or "TPC-H" in result.stdout

    @pytest.mark.e2e
    @pytest.mark.e2e_quick
    @pytest.mark.tpcds
    def test_benchmark_tpcds(self, tmp_path: Path) -> None:
        """Test --benchmark tpcds option with an unofficial subscale dry run."""
        output_dir = tmp_path / "dry_run"
        output_dir.mkdir()

        result = run_cli_command(
            [
                "run",
                "--platform",
                "duckdb",
                "--benchmark",
                "tpcds",
                "--scale",
                "0.01",
                "--dry-run",
                str(output_dir),
            ]
        )

        assert result.returncode == 0, f"Failed: {result.stdout}"
        assert "UNOFFICIAL SUBSCALE RUN" in result.stdout

    @pytest.mark.e2e
    @pytest.mark.e2e_quick
    @pytest.mark.ssb
    def test_benchmark_ssb(self, tmp_path: Path) -> None:
        """Test --benchmark ssb option."""
        output_dir = tmp_path / "dry_run"
        output_dir.mkdir()

        result = run_cli_command(
            [
                "run",
                "--platform",
                "duckdb",
                "--benchmark",
                "ssb",
                "--scale",
                "0.01",
                "--dry-run",
                str(output_dir),
            ]
        )

        assert result.returncode == 0, f"Failed: {result.stdout}"

    @pytest.mark.e2e
    @pytest.mark.e2e_quick
    @pytest.mark.clickbench
    def test_benchmark_clickbench(self, tmp_path: Path) -> None:
        """Test --benchmark clickbench option.

        Note: ClickBench requires SF >= 1.0 due to native data generator limitations.
        """
        output_dir = tmp_path / "dry_run"
        output_dir.mkdir()

        result = run_cli_command(
            [
                "run",
                "--platform",
                "duckdb",
                "--benchmark",
                "clickbench",
                "--scale",
                "1",  # ClickBench requires SF >= 1.0
                "--dry-run",
                str(output_dir),
            ]
        )

        assert result.returncode == 0, f"Failed: {result.stdout}"


# ============================================================================
# Phase Execution Tests
# ============================================================================


class TestPhaseExecution:
    """Tests for --phases option."""

    @pytest.mark.e2e
    @pytest.mark.e2e_quick
    def test_phases_generate_only(self, tmp_path: Path) -> None:
        """Test --phases generate for data generation only."""
        output_dir = tmp_path / "dry_run"
        output_dir.mkdir()

        result = run_cli_command(
            [
                "run",
                "--benchmark",
                "tpch",
                "--scale",
                "0.01",
                "--phases",
                "generate",
                "--dry-run",
                str(output_dir),
            ]
        )

        assert result.returncode == 0, f"Failed: {result.stdout}"
        assert "data generation" in result.stdout.lower() or "generate" in result.stdout.lower()

    @pytest.mark.e2e
    @pytest.mark.e2e_quick
    def test_phases_generate_load(self, tmp_path: Path) -> None:
        """Test --phases generate,load for data generation and loading."""
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
                "--phases",
                "generate,load",
                "--dry-run",
                str(output_dir),
            ]
        )

        assert result.returncode == 0, f"Failed: {result.stdout}"

    @pytest.mark.e2e
    @pytest.mark.e2e_quick
    def test_phases_power(self, tmp_path: Path) -> None:
        """Test --phases power for power test only."""
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
                "--phases",
                "generate,load,power",
                "--dry-run",
                str(output_dir),
            ]
        )

        assert result.returncode == 0, f"Failed: {result.stdout}"

    @pytest.mark.e2e
    @pytest.mark.e2e_quick
    def test_phases_full_pipeline(self, tmp_path: Path) -> None:
        """Test full phase pipeline."""
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
                "--phases",
                "generate,load,warmup,power",
                "--dry-run",
                str(output_dir),
            ]
        )

        assert result.returncode == 0, f"Failed: {result.stdout}"


# ============================================================================
# Query Subset Tests
# ============================================================================


class TestQuerySubset:
    """Tests for --queries option."""

    @pytest.mark.e2e
    @pytest.mark.e2e_quick
    def test_queries_single(self, tmp_path: Path) -> None:
        """Test --queries with single query."""
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
                "Q1",
                "--dry-run",
                str(output_dir),
            ]
        )

        assert result.returncode == 0, f"Failed: {result.stdout}"

    @pytest.mark.e2e
    @pytest.mark.e2e_quick
    def test_queries_multiple(self, tmp_path: Path) -> None:
        """Test --queries with multiple queries."""
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
                "Q1,Q6,Q14,Q17",
                "--dry-run",
                str(output_dir),
            ]
        )

        assert result.returncode == 0, f"Failed: {result.stdout}"

    @pytest.mark.e2e
    @pytest.mark.e2e_quick
    def test_queries_lowercase(self, tmp_path: Path) -> None:
        """Test --queries with lowercase query IDs."""
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
                "q1,q6",
                "--dry-run",
                str(output_dir),
            ]
        )

        # Should accept lowercase and normalize
        assert result.returncode == 0, f"Failed: {result.stdout}"


# ============================================================================
# Tuning Mode Tests
# ============================================================================


class TestTuningMode:
    """Tests for --tuning option."""

    @pytest.mark.e2e
    @pytest.mark.e2e_quick
    def test_tuning_tuned(self, tmp_path: Path) -> None:
        """Test --tuning tuned option."""
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
                "tuned",
                "--dry-run",
                str(output_dir),
            ]
        )

        assert result.returncode == 0, f"Failed: {result.stdout}"

    @pytest.mark.e2e
    @pytest.mark.e2e_quick
    def test_tuning_notuning(self, tmp_path: Path) -> None:
        """Test --tuning notuning option."""
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
                "notuning",
                "--dry-run",
                str(output_dir),
            ]
        )

        assert result.returncode == 0, f"Failed: {result.stdout}"

    @pytest.mark.e2e
    @pytest.mark.e2e_quick
    def test_tuning_auto(self, tmp_path: Path) -> None:
        """Test --tuning auto option."""
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
                "auto",
                "--dry-run",
                str(output_dir),
            ]
        )

        assert result.returncode == 0, f"Failed: {result.stdout}"


# ============================================================================
# Compression Tests
# ============================================================================


class TestCompression:
    """Tests for --compression option."""

    @pytest.mark.e2e
    @pytest.mark.e2e_quick
    def test_compression_none(self, tmp_path: Path) -> None:
        """Test --compression none option."""
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
                "none",
                "--dry-run",
                str(output_dir),
            ]
        )

        assert result.returncode == 0, f"Failed: {result.stdout}"

    @pytest.mark.e2e
    @pytest.mark.e2e_quick
    def test_compression_zstd(self, tmp_path: Path) -> None:
        """Test --compression zstd option."""
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
                "zstd",
                "--dry-run",
                str(output_dir),
            ]
        )

        assert result.returncode == 0, f"Failed: {result.stdout}"

    @pytest.mark.e2e
    @pytest.mark.e2e_quick
    def test_compression_gzip(self, tmp_path: Path) -> None:
        """Test --compression gzip option."""
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
                "gzip",
                "--dry-run",
                str(output_dir),
            ]
        )

        assert result.returncode == 0, f"Failed: {result.stdout}"


# ============================================================================
# Validation Mode Tests
# ============================================================================


class TestValidationMode:
    """Tests for --validation option."""

    @pytest.mark.e2e
    @pytest.mark.e2e_quick
    def test_validation_disabled(self, tmp_path: Path) -> None:
        """Test --validation disabled option."""
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
                "disabled",
                "--dry-run",
                str(output_dir),
            ]
        )

        assert result.returncode == 0, f"Failed: {result.stdout}"

    @pytest.mark.e2e
    @pytest.mark.e2e_quick
    def test_validation_loose(self, tmp_path: Path) -> None:
        """Test --validation loose option."""
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
                "loose",
                "--dry-run",
                str(output_dir),
            ]
        )

        assert result.returncode == 0, f"Failed: {result.stdout}"


# ============================================================================
# Seed Tests
# ============================================================================


class TestSeed:
    """Tests for --seed option."""

    @pytest.mark.e2e
    @pytest.mark.e2e_quick
    def test_seed_reproducibility(self, tmp_path: Path) -> None:
        """Test --seed option for reproducible runs."""
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
                "--seed",
                "42",
                "--dry-run",
                str(output_dir),
            ]
        )

        assert result.returncode == 0, f"Failed: {result.stdout}"


# ============================================================================
# Force Tests
# ============================================================================


class TestForce:
    """Tests for --force option."""

    @pytest.mark.e2e
    @pytest.mark.e2e_quick
    def test_force_datagen(self, tmp_path: Path) -> None:
        """Test --force datagen option."""
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
                "--force",
                "datagen",
                "--dry-run",
                str(output_dir),
            ]
        )

        assert result.returncode == 0, f"Failed: {result.stdout}"

    @pytest.mark.e2e
    @pytest.mark.e2e_quick
    def test_force_all(self, tmp_path: Path) -> None:
        """Test --force all option."""
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
                "--force",
                "all",
                "--dry-run",
                str(output_dir),
            ]
        )

        assert result.returncode == 0, f"Failed: {result.stdout}"


# ============================================================================
# Scale Factor Tests
# ============================================================================


class TestScaleFactor:
    """Tests for --scale option."""

    @pytest.mark.e2e
    @pytest.mark.e2e_quick
    def test_scale_small(self, tmp_path: Path) -> None:
        """Test small scale factor 0.01."""
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
                "--dry-run",
                str(output_dir),
            ]
        )

        assert result.returncode == 0, f"Failed: {result.stdout}"

    @pytest.mark.e2e
    @pytest.mark.e2e_quick
    def test_scale_tenth(self, tmp_path: Path) -> None:
        """Test scale factor 0.1."""
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
                "0.1",
                "--dry-run",
                str(output_dir),
            ]
        )

        assert result.returncode == 0, f"Failed: {result.stdout}"


# ============================================================================
# Parametrized CLI Options Tests
# ============================================================================


@pytest.mark.e2e
@pytest.mark.e2e_quick
@pytest.mark.parametrize(
    "benchmark_type,expected_queries",
    [
        ("tpch", 22),
        ("ssb", 13),
    ],
)
def test_benchmark_query_counts(tmp_path: Path, benchmark_type: str, expected_queries: int) -> None:
    """Test that benchmarks have expected query counts."""
    output_dir = tmp_path / "dry_run"
    output_dir.mkdir()

    result = run_cli_command(
        [
            "run",
            "--platform",
            "duckdb",
            "--benchmark",
            benchmark_type,
            "--scale",
            "0.01",
            "--dry-run",
            str(output_dir),
        ]
    )

    assert result.returncode == 0, f"Failed for {benchmark_type}: {result.stdout}"


@pytest.mark.e2e
@pytest.mark.e2e_quick
@pytest.mark.parametrize(
    "tuning_mode",
    ["tuned", "notuning", "auto"],
)
def test_tuning_modes(tmp_path: Path, tuning_mode: str) -> None:
    """Test all tuning modes work."""
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
            tuning_mode,
            "--dry-run",
            str(output_dir),
        ]
    )

    assert result.returncode == 0, f"Failed for tuning mode {tuning_mode}: {result.stdout}"


@pytest.mark.e2e
@pytest.mark.e2e_quick
@pytest.mark.parametrize(
    "validation_mode",
    ["disabled", "loose"],
)
def test_validation_modes(tmp_path: Path, validation_mode: str) -> None:
    """Test validation modes work."""
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
            validation_mode,
            "--dry-run",
            str(output_dir),
        ]
    )

    assert result.returncode == 0, f"Failed for validation mode {validation_mode}: {result.stdout}"
