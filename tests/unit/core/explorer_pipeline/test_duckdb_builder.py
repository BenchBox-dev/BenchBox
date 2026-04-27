"""Unit tests for DuckDBSnapshotBuilder."""

from __future__ import annotations

import json
from pathlib import Path

import duckdb
import pytest

from benchbox.core.explorer_pipeline.duckdb_builder import DuckDBSnapshotBuilder
from benchbox.core.explorer_pipeline.models import ManifestEntry

pytestmark = [pytest.mark.unit, pytest.mark.fast]


def _make_entry(**overrides) -> ManifestEntry:
    defaults: dict = {
        "result_id": "tpch-duckdb-sf0.1-20260315-abcd1234",
        "benchmark": "tpch",
        "scale_factor": 0.1,
        "platform": "duckdb",
        "driver_version": "1.2.0",
        "run_date": "2026-03-15",
        "power_score": 1234.56,
        "total_duration_s": 45.0,
        "query_count": 2,
        "trust_label": "maintainer-run",
        "visibility": "public-curated",
    }
    defaults.update(overrides)
    return ManifestEntry(**defaults)


class TestDuckDBSnapshotBuilder:
    def test_creates_duckdb_file(self, tmp_path: Path) -> None:
        builder = DuckDBSnapshotBuilder()
        out = tmp_path / "results.duckdb"
        builder.build([_make_entry()], out)

        assert out.exists()
        assert out.stat().st_size > 0

    def test_results_table_has_correct_columns(self, tmp_path: Path) -> None:
        builder = DuckDBSnapshotBuilder()
        out = tmp_path / "results.duckdb"
        builder.build([_make_entry()], out)

        with duckdb.connect(str(out), read_only=True) as con:
            cols = {row[0] for row in con.execute("DESCRIBE results").fetchall()}

        expected = {
            "result_id",
            "benchmark",
            "scale_factor",
            "platform",
            "driver_version",
            "run_date",
            "power_score",
            "total_duration_s",
            "geomean_ms",
            "query_count",
            "trust_label",
            "visibility",
            "platform_version",
            "execution_mode",
            "tuning_mode",
            "tuning_hash",
            "test_type",
            "validation_status",
            "cost_usd",
        }
        assert expected.issubset(cols)

    def test_row_count_matches_entries(self, tmp_path: Path) -> None:
        entries = [_make_entry(result_id=f"id-{i}", platform=f"platform-{i}") for i in range(3)]
        builder = DuckDBSnapshotBuilder()
        out = tmp_path / "results.duckdb"
        builder.build(entries, out)

        with duckdb.connect(str(out), read_only=True) as con:
            count = con.execute("SELECT COUNT(*) FROM results").fetchone()[0]

        assert count == 3

    def test_empty_entries_creates_empty_table(self, tmp_path: Path) -> None:
        builder = DuckDBSnapshotBuilder()
        out = tmp_path / "results.duckdb"
        builder.build([], out)

        with duckdb.connect(str(out), read_only=True) as con:
            count = con.execute("SELECT COUNT(*) FROM results").fetchone()[0]

        assert count == 0

    def test_nullable_fields_stored(self, tmp_path: Path) -> None:
        entry = _make_entry(driver_version=None, power_score=None)
        builder = DuckDBSnapshotBuilder()
        out = tmp_path / "results.duckdb"
        builder.build([entry], out)

        with duckdb.connect(str(out), read_only=True) as con:
            row = con.execute("SELECT driver_version, power_score FROM results").fetchone()

        assert row[0] is None
        assert row[1] is None

    def test_extended_fields_round_trip(self, tmp_path: Path) -> None:
        """Extended columns store and retrieve correct values (not just schema-present)."""
        entry = _make_entry(
            geomean_ms=5656.85,
            platform_version="v3",
            execution_mode="sql",
            tuning_mode="tuned",
            tuning_hash="abcd1234",
            test_type="power",
            validation_status="passed",
            cost_usd=0.42,
        )
        builder = DuckDBSnapshotBuilder()
        out = tmp_path / "results.duckdb"
        builder.build([entry], out)

        with duckdb.connect(str(out), read_only=True) as con:
            row = con.execute(
                "SELECT geomean_ms, platform_version, execution_mode, tuning_mode,"
                " tuning_hash, test_type, validation_status, cost_usd FROM results"
            ).fetchone()

        assert row[0] == pytest.approx(5656.85)
        assert row[1] == "v3"
        assert row[2] == "sql"
        assert row[3] == "tuned"
        assert row[4] == "abcd1234"
        assert row[5] == "power"
        assert row[6] == "passed"
        assert row[7] == pytest.approx(0.42)

    def test_extended_fields_null_when_absent(self, tmp_path: Path) -> None:
        """All extended columns store NULL when the entry has no value."""
        entry = _make_entry()  # all extended fields default to None
        builder = DuckDBSnapshotBuilder()
        out = tmp_path / "results.duckdb"
        builder.build([entry], out)

        with duckdb.connect(str(out), read_only=True) as con:
            row = con.execute(
                "SELECT geomean_ms, platform_version, execution_mode, tuning_mode,"
                " tuning_hash, test_type, validation_status, cost_usd FROM results"
            ).fetchone()

        assert row is not None and all(v is None for v in row)

    def test_results_schema_json_emitted(self, tmp_path: Path) -> None:
        """results_schema.json is written next to results.duckdb."""
        builder = DuckDBSnapshotBuilder()
        out = tmp_path / "results.duckdb"
        builder.build([_make_entry()], out)

        schema_path = tmp_path / "results_schema.json"
        assert schema_path.exists(), "results_schema.json not emitted"
        schema = json.loads(schema_path.read_text())
        assert "columns" in schema
        col_names = [c["name"] for c in schema["columns"]]
        assert "result_id" in col_names
        assert "benchmark" in col_names
        assert "geomean_ms" in col_names
        # All _COLUMNS names appear
        expected_names = [name for name, _ in DuckDBSnapshotBuilder._COLUMNS]
        assert col_names == expected_names

    def test_results_schema_json_column_types(self, tmp_path: Path) -> None:
        """results_schema.json columns carry their DuckDB type strings."""
        builder = DuckDBSnapshotBuilder()
        out = tmp_path / "results.duckdb"
        builder.build([], out)

        schema = json.loads((tmp_path / "results_schema.json").read_text())
        by_name = {c["name"]: c["type"] for c in schema["columns"]}
        assert by_name["result_id"] == "VARCHAR"
        assert by_name["scale_factor"] == "DOUBLE"
        assert by_name["query_count"] == "INTEGER"

    def test_overwrites_existing_file(self, tmp_path: Path) -> None:
        builder = DuckDBSnapshotBuilder()
        out = tmp_path / "results.duckdb"

        builder.build([_make_entry(result_id="id-1")], out)

        builder.build(
            [_make_entry(result_id="id-2"), _make_entry(result_id="id-3", platform="p2")],
            out,
        )

        with duckdb.connect(str(out), read_only=True) as con:
            count = con.execute("SELECT COUNT(*) FROM results").fetchone()[0]

        assert count == 2
