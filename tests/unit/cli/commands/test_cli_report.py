"""Unit tests for report CLI command."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest
from click.testing import CliRunner

from benchbox.cli.app import cli
from benchbox.core.results.database import ResultDatabase
from tests.fixtures.result_dict_fixtures import make_benchmark_results, make_v2_result_dict

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


def create_test_result(
    execution_id: str = "test-exec-001",
    platform: str = "DuckDB",
    benchmark: str = "TPC-H",
    scale_factor: float = 1.0,
    timestamp: datetime | None = None,
    geometric_mean_ms: float = 100.0,
):
    """Report-test defaults delegating to shared factory."""
    return make_benchmark_results(
        benchmark_name=benchmark,
        platform=platform,
        scale_factor=scale_factor,
        execution_id=execution_id,
        timestamp=timestamp,
        duration_seconds=10.0,
        total_queries=22,
        successful_queries=22,
        validation_status="PASSED",
        geometric_mean_execution_time=geometric_mean_ms / 1000.0,
        platform_info={"platform_version": "1.0.0"},
    )


class TestReportStats:
    """Tests for benchbox report stats command."""

    def test_stats_empty_database(self, tmp_path):
        """Test stats command with empty database."""
        runner = CliRunner()
        db_path = tmp_path / "test.db"

        result = runner.invoke(cli, ["report", "stats", "--db-path", str(db_path)])

        assert result.exit_code == 0
        assert "Total Results" in result.output
        assert "0" in result.output

    def test_stats_with_data(self, tmp_path):
        """Test stats command with data."""
        db_path = tmp_path / "test.db"
        db = ResultDatabase(db_path)
        db.store_result(create_test_result(execution_id="stat-1"))
        db.store_result(create_test_result(execution_id="stat-2", platform="Snowflake"))

        runner = CliRunner()
        result = runner.invoke(cli, ["report", "stats", "--db-path", str(db_path)])

        assert result.exit_code == 0
        assert "2" in result.output  # Total Results


class TestReportList:
    """Tests for benchbox report list command."""

    def test_list_empty_database(self, tmp_path):
        """Test list command with empty database."""
        runner = CliRunner()
        db_path = tmp_path / "test.db"

        result = runner.invoke(cli, ["report", "list", "--db-path", str(db_path)])

        assert result.exit_code == 0
        assert "No results found" in result.output

    def test_list_with_results(self, tmp_path):
        """Test list command with results."""
        db_path = tmp_path / "test.db"
        db = ResultDatabase(db_path)
        db.store_result(create_test_result(execution_id="list-1", platform="DuckDB"))

        runner = CliRunner()
        result = runner.invoke(cli, ["report", "list", "--db-path", str(db_path)])

        assert result.exit_code == 0
        assert "DuckDB" in result.output
        assert "TPC-H" in result.output

    def test_list_with_platform_filter(self, tmp_path):
        """Test list command with platform filter."""
        db_path = tmp_path / "test.db"
        db = ResultDatabase(db_path)
        db.store_result(create_test_result(execution_id="f1", platform="DuckDB"))
        db.store_result(create_test_result(execution_id="f2", platform="Snowflake"))

        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["report", "list", "--platform", "DuckDB", "--db-path", str(db_path)],
        )

        assert result.exit_code == 0
        assert "DuckDB" in result.output
        # Snowflake should not appear in filtered results
        # (can't easily check for absence without parsing table)


class TestReportRankings:
    """Tests for benchbox report rankings command."""

    def test_rankings_no_data(self, tmp_path):
        """Test rankings command with no matching data."""
        runner = CliRunner()
        db_path = tmp_path / "test.db"

        result = runner.invoke(
            cli,
            [
                "report",
                "rankings",
                "--benchmark",
                "TPC-H",
                "--scale-factor",
                "1",
                "--db-path",
                str(db_path),
            ],
        )

        assert result.exit_code == 0
        assert "No results found" in result.output

    def test_rankings_with_data(self, tmp_path):
        """Test rankings command with data."""
        db_path = tmp_path / "test.db"
        db = ResultDatabase(db_path)
        now = datetime.now(timezone.utc)

        db.store_result(
            create_test_result(
                execution_id="r1",
                platform="DuckDB",
                benchmark="TPC-H",
                scale_factor=1.0,
                geometric_mean_ms=100.0,
                timestamp=now,
            )
        )
        db.store_result(
            create_test_result(
                execution_id="r2",
                platform="Snowflake",
                benchmark="TPC-H",
                scale_factor=1.0,
                geometric_mean_ms=200.0,
                timestamp=now,
            )
        )

        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "report",
                "rankings",
                "--benchmark",
                "TPC-H",
                "--scale-factor",
                "1",
                "--db-path",
                str(db_path),
            ],
        )

        assert result.exit_code == 0
        assert "Platform Rankings" in result.output
        assert "DuckDB" in result.output
        assert "Snowflake" in result.output


class TestReportTrends:
    """Tests for benchbox report trends command."""

    def test_trends_no_data(self, tmp_path):
        """Test trends command with no matching data."""
        runner = CliRunner()
        db_path = tmp_path / "test.db"

        result = runner.invoke(
            cli,
            [
                "report",
                "trends",
                "--platform",
                "DuckDB",
                "--benchmark",
                "TPC-H",
                "--scale-factor",
                "1",
                "--db-path",
                str(db_path),
            ],
        )

        assert result.exit_code == 0
        assert "No trend data found" in result.output


class TestReportRegressions:
    """Tests for benchbox report regressions command."""

    def test_regressions_no_data(self, tmp_path):
        """Test regressions command with no data."""
        runner = CliRunner()
        db_path = tmp_path / "test.db"

        result = runner.invoke(
            cli,
            ["report", "regressions", "--db-path", str(db_path)],
        )

        assert result.exit_code == 0
        assert "No performance regressions detected" in result.output


class TestReportImport:
    """Tests for benchbox report import command."""

    def test_import_directory(self, tmp_path):
        """Test importing results from a directory."""
        db_path = tmp_path / "test.db"
        results_dir = tmp_path / "results"
        results_dir.mkdir()

        # Create test result file using v2.0 schema format
        result_data = make_v2_result_dict(
            version="2.0",
            benchmark_id="tpc_h",
            benchmark_name="TPC-H",
            platform="DuckDB",
            platform_version="1.0.0",
            execution_id="import-test",
            timestamp="2025-01-01T10:00:00",
            scale_factor=1.0,
        )

        with open(results_dir / "result.json", "w", encoding="utf-8") as f:
            json.dump(result_data, f)

        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["report", "import", str(results_dir), "--db-path", str(db_path)],
        )

        assert result.exit_code == 0
        assert "Imported: 1" in result.output

    def test_import_nonexistent_directory(self, tmp_path):
        """Test importing from nonexistent directory."""
        runner = CliRunner()
        db_path = tmp_path / "test.db"

        result = runner.invoke(
            cli,
            ["report", "import", "/nonexistent/path", "--db-path", str(db_path)],
        )

        assert result.exit_code != 0  # Should fail


class TestReportHelp:
    """Tests for report command help."""

    def test_report_help(self):
        """Test report command help message."""
        runner = CliRunner()
        result = runner.invoke(cli, ["report", "--help"])

        assert result.exit_code == 0
        assert "Historical result analysis" in result.output
        assert "rankings" in result.output
        assert "trends" in result.output
        assert "regressions" in result.output
        assert "import" in result.output
        assert "stats" in result.output

    def test_rankings_help(self):
        """Test rankings subcommand help."""
        runner = CliRunner()
        result = runner.invoke(cli, ["report", "rankings", "--help"])

        assert result.exit_code == 0
        assert "--benchmark" in result.output
        assert "--scale-factor" in result.output
        assert "--metric" in result.output
