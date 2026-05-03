"""Tests for Flight Data benchmark implementation.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import csv
import json
import tempfile
from datetime import date
from pathlib import Path

import pytest

from benchbox.core.flightdata.benchmark import FlightDataBenchmark
from benchbox.core.flightdata.downloader import MONTHS_PER_SCALE_FACTOR, FlightDataDownloader
from benchbox.core.flightdata.schema import FLIGHT_SCHEMA

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


class TestBenchmarkInitialization:
    """Tests for benchmark initialization."""

    def test_default_init(self):
        """Should initialize with default values."""
        bm = FlightDataBenchmark()
        assert bm.scale_factor == 1.0
        assert bm.end_year == 2024

    def test_custom_scale_factor(self):
        """Should accept custom scale factor."""
        bm = FlightDataBenchmark(scale_factor=0.01)
        assert bm.scale_factor == 0.01

    def test_invalid_scale_factor(self):
        """Should raise for non-positive scale factor."""
        with pytest.raises(ValueError, match="must be positive"):
            FlightDataBenchmark(scale_factor=0)

        with pytest.raises(ValueError, match="must be positive"):
            FlightDataBenchmark(scale_factor=-1.0)

    def test_custom_output_dir(self):
        """Should accept custom output directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            bm = FlightDataBenchmark(output_dir=tmpdir)
            assert Path(bm.output_dir) == Path(tmpdir)

    def test_benchmark_metadata(self):
        """Should have correct metadata."""
        bm = FlightDataBenchmark(scale_factor=0.01)
        assert bm._name == "Flight Data OLAP"
        assert bm._version == "1.0"
        assert "BTS" in bm._description or "aviation" in bm._description.lower()

    def test_query_date_range_set(self):
        """Should set query date range based on scale factor."""
        bm = FlightDataBenchmark(scale_factor=0.01)
        assert bm._query_start_date is not None
        assert bm._query_end_date is not None
        assert bm._query_start_date < bm._query_end_date

    def test_query_end_date_is_exclusive_upper_bound(self):
        """The stored query end date should match the exclusive < end_date filters."""
        bm = FlightDataBenchmark(scale_factor=0.01)
        newest_year, newest_month = bm.downloader.months[0]

        if newest_month == 12:
            expected_end = date(newest_year + 1, 1, 1)
        else:
            expected_end = date(newest_year, newest_month + 1, 1)

        assert date.fromisoformat(bm._query_end_date) == expected_end


class TestQueries:
    """Tests for query retrieval."""

    def setup_method(self):
        self.bm = FlightDataBenchmark(scale_factor=0.01)

    def test_get_all_queries(self):
        """Should return all 20 queries."""
        queries = self.bm.get_queries()
        assert len(queries) == 20

    def test_query_keys_are_strings(self):
        """All query keys should be strings."""
        queries = self.bm.get_queries()
        for key in queries:
            assert isinstance(key, str)

    def test_query_sql_non_empty(self):
        """All query SQL strings should be non-empty."""
        queries = self.bm.get_queries()
        for key, sql in queries.items():
            assert sql.strip(), f"Query {key!r} has empty SQL"

    def test_get_query_by_key(self):
        """Should retrieve a specific query by key."""
        sql = self.bm.get_query("ontime-by-carrier")
        assert "reporting_airline" in sql.lower()
        assert "SELECT" in sql.upper()

    def test_get_query_by_numeric_id(self):
        """Should retrieve a query by its numeric ID."""
        sql = self.bm.get_query("1")  # ontime-by-carrier
        assert "reporting_airline" in sql.lower()

    def test_get_query_invalid(self):
        """Should raise ValueError for unknown query ID."""
        with pytest.raises(ValueError, match="Unknown query"):
            self.bm.get_query("nonexistent-query")

    def test_queries_contain_date_params(self):
        """Queries should have start/end date placeholders filled in."""
        queries = self.bm.get_queries()
        for key, sql in queries.items():
            assert "{start_date}" not in sql, f"Query {key!r} has unfilled {{start_date}}"
            assert "{end_date}" not in sql, f"Query {key!r} has unfilled {{end_date}}"

    def test_query_categories(self):
        """Should have all expected categories."""
        categories = self.bm.query_manager.get_categories()
        assert "ontime" in categories
        assert "delay" in categories
        assert "routes" in categories
        assert "temporal" in categories
        assert "carriers" in categories

    def test_queries_by_category(self):
        """Should return queries for each category."""
        assert len(self.bm.get_queries_by_category("ontime")) == 5
        assert len(self.bm.get_queries_by_category("delay")) == 4
        assert len(self.bm.get_queries_by_category("routes")) == 4
        assert len(self.bm.get_queries_by_category("temporal")) == 4
        assert len(self.bm.get_queries_by_category("carriers")) == 3

    def test_query_info(self):
        """Should return metadata for a query."""
        info = self.bm.get_query_info("ontime-by-carrier")
        assert info["id"] == "1"
        assert "name" in info
        assert "description" in info
        assert info["category"] == "ontime"


class TestSchema:
    """Tests for schema definitions."""

    def setup_method(self):
        self.bm = FlightDataBenchmark(scale_factor=0.01)

    def test_schema_has_all_tables(self):
        """Schema should define all three tables."""
        schema = self.bm.get_schema()
        assert "flights" in schema
        assert "airlines" in schema
        assert "airports" in schema

    def test_flights_table_columns(self):
        """Flights table should have all required columns."""
        schema = FLIGHT_SCHEMA["flights"]
        cols = schema["columns"]
        required = [
            "flight_id",
            "flight_date",
            "year",
            "month",
            "reporting_airline",
            "origin",
            "dest",
            "dep_delay",
            "arr_delay",
            "cancelled",
            "distance",
        ]
        for col in required:
            assert col in cols, f"Missing column: {col}"

    def test_get_create_tables_sql(self):
        """Should generate valid CREATE TABLE statements."""
        sql = self.bm.get_create_tables_sql()
        assert "CREATE TABLE" in sql
        assert "flights" in sql
        assert "airlines" in sql
        assert "airports" in sql

    def test_create_tables_sql_duckdb_dialect(self):
        """Should generate DuckDB-compatible SQL."""
        sql = self.bm.get_create_tables_sql(dialect="duckdb")
        assert "DOUBLE" in sql
        assert "VARCHAR" in sql


class TestBenchmarkInfo:
    """Tests for benchmark metadata."""

    def test_benchmark_info_structure(self):
        """Should return complete benchmark info dict."""
        bm = FlightDataBenchmark(scale_factor=0.01)
        info = bm.get_benchmark_info()
        assert info["name"] == "Flight Data OLAP"
        assert info["num_queries"] == 20
        assert "flights" in info["tables"]
        assert "airlines" in info["tables"]
        assert "airports" in info["tables"]
        assert info["scale_factor"] == 0.01


class TestDataGeneration:
    """Tests for data generation (synthetic only - no network)."""

    def test_generate_creates_files(self):
        """Should create CSV files for all three tables."""
        with tempfile.TemporaryDirectory() as tmpdir:
            bm = FlightDataBenchmark(scale_factor=0.01, output_dir=tmpdir, seed=42)
            paths = bm.generate_data()

            assert len(paths) == 3
            for p in paths:
                assert Path(p).exists(), f"File not created: {p}"
                assert Path(p).stat().st_size > 0

    def test_generate_flights_has_rows(self):
        """Generated flights.csv should have data rows."""
        with tempfile.TemporaryDirectory() as tmpdir:
            bm = FlightDataBenchmark(scale_factor=0.01, output_dir=tmpdir, seed=42)
            bm.generate_data()

            flights_path = Path(tmpdir) / "flights.csv"
            lines = flights_path.read_text().strip().splitlines()
            assert len(lines) > 1, "flights.csv should have rows beyond the header"

    def test_generate_idempotent(self):
        """Should return same files on second call."""
        with tempfile.TemporaryDirectory() as tmpdir:
            bm = FlightDataBenchmark(scale_factor=0.01, output_dir=tmpdir, seed=42)
            paths1 = bm.generate_data()
            paths2 = bm.generate_data()
            assert set(str(p) for p in paths1) == set(str(p) for p in paths2)

    def test_reference_data_airlines(self):
        """airlines.csv should be copied with correct headers."""
        with tempfile.TemporaryDirectory() as tmpdir:
            bm = FlightDataBenchmark(scale_factor=0.01, output_dir=tmpdir, seed=42)
            bm.generate_data()

            airlines_path = Path(tmpdir) / "airlines.csv"
            header = airlines_path.read_text().splitlines()[0]
            assert "code" in header
            assert "name" in header

    def test_reference_data_airports(self):
        """airports.csv should be copied with correct headers."""
        with tempfile.TemporaryDirectory() as tmpdir:
            bm = FlightDataBenchmark(scale_factor=0.01, output_dir=tmpdir, seed=42)
            bm.generate_data()

            airports_path = Path(tmpdir) / "airports.csv"
            header = airports_path.read_text().splitlines()[0]
            assert "code" in header
            assert "latitude" in header

    def test_download_stats(self):
        """Should return stats after generation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            bm = FlightDataBenchmark(scale_factor=0.01, output_dir=tmpdir, seed=42)
            bm.generate_data()
            stats = bm.get_download_stats()
            assert stats["total_flights"] > 0
            assert stats["scale_factor"] == 0.01

    def test_large_scale_generation_uses_manifest_tracked_flight_shards(self, tmp_path, monkeypatch):
        """SF1 FlightData should avoid one large flights.csv stream."""

        def fake_process_month(self, writer, year, month, start_id):
            writer.writerow(_flight_row(start_id, year, month))
            return 1

        monkeypatch.setattr(FlightDataDownloader, "_process_month", fake_process_month)
        downloader = FlightDataDownloader(scale_factor=1.0, output_dir=tmp_path, seed=42, verbose=1)
        downloader._num_months = MONTHS_PER_SCALE_FACTOR
        downloader._months = [(2024, 12), (2024, 11)]

        tables = downloader.download()

        flights = tables["flights"]
        assert isinstance(flights, list)
        assert len(flights) == 2
        assert not (tmp_path / "flights.csv").exists()
        assert all(path.parent == tmp_path / "flights" for path in flights)

        manifest = json.loads((tmp_path / "_datagen_manifest.json").read_text(encoding="utf-8"))
        flight_entries = manifest["tables"]["flights"]["formats"]["csv"]
        assert len(flight_entries) == 2
        assert [entry["row_count"] for entry in flight_entries] == [1, 1]
        assert manifest["format_preference"] == ["csv"]
        assert flight_entries[0]["metadata"] == {
            "csv_delimiter": ",",
            "csv_has_header": True,
            "csv_null_marker": None,
        }

        reused_downloader = FlightDataDownloader(scale_factor=1.0, output_dir=tmp_path, seed=42, verbose=1)
        reused_downloader._num_months = MONTHS_PER_SCALE_FACTOR
        reused_downloader._months = [(2024, 12), (2024, 11)]
        reused_downloader.download()

        reused_manifest = json.loads((tmp_path / "_datagen_manifest.json").read_text(encoding="utf-8"))
        reused_entries = reused_manifest["tables"]["flights"]["formats"]["csv"]
        assert [entry["row_count"] for entry in reused_entries] == [1, 1]

    def test_legacy_large_single_flight_file_is_split_and_removed(self, tmp_path, monkeypatch):
        """A valid legacy single-file cache should be repaired without redownloading."""
        monkeypatch.setattr("benchbox.core.flightdata.downloader.FLIGHTS_SHARD_ROW_TARGET", 2)
        downloader = FlightDataDownloader(scale_factor=1.0, output_dir=tmp_path, seed=42, verbose=1)
        downloader._num_months = MONTHS_PER_SCALE_FACTOR

        legacy_path = tmp_path / "flights.csv"
        _write_csv(legacy_path, FlightDataDownloader._flight_header(), [_flight_row(i) for i in range(1, 6)])
        _write_csv(tmp_path / "airlines.csv", ["code", "name"], [["AA", "American"]])
        _write_csv(
            tmp_path / "airports.csv",
            ["code", "name", "city", "state", "latitude", "longitude"],
            [["ATL", "Atlanta", "Atlanta", "GA", "33.64", "-84.43"]],
        )

        repaired = downloader.repair_reusable_layout()

        assert repaired is not None
        assert not legacy_path.exists()
        flights = repaired["flights"]
        assert isinstance(flights, list)
        assert len(flights) == 3
        assert [path.name for path in flights] == ["flights_0001.csv", "flights_0002.csv", "flights_0003.csv"]
        for path in flights:
            assert path.read_text(encoding="utf-8").splitlines()[0].startswith("flight_id,flight_date")

        manifest = json.loads((tmp_path / "_datagen_manifest.json").read_text(encoding="utf-8"))
        entries = manifest["tables"]["flights"]["formats"]["csv"]
        assert [entry["row_count"] for entry in entries] == [2, 2, 1]

    def test_legacy_large_single_flight_file_with_bad_width_is_rejected(self, tmp_path, monkeypatch):
        """Legacy repair should fail before publishing malformed FlightData shards."""
        monkeypatch.setattr("benchbox.core.flightdata.downloader.FLIGHTS_SHARD_ROW_TARGET", 2)
        downloader = FlightDataDownloader(scale_factor=1.0, output_dir=tmp_path, seed=42, verbose=1)
        downloader._num_months = MONTHS_PER_SCALE_FACTOR

        legacy_path = tmp_path / "flights.csv"
        _write_csv(legacy_path, FlightDataDownloader._flight_header(), [_flight_row(1)[:-1]])

        with pytest.raises(ValueError, match="row 2 has 27 columns; expected 28"):
            downloader.repair_reusable_layout()

        assert legacy_path.exists()
        assert not (tmp_path / "flights").exists()
        assert not (tmp_path / ".flights-shards.tmp").exists()

    def test_empty_legacy_large_single_flight_file_is_rejected(self, tmp_path):
        """Empty legacy sources should not leave staged shard directories behind."""
        downloader = FlightDataDownloader(scale_factor=1.0, output_dir=tmp_path, seed=42, verbose=1)
        downloader._num_months = MONTHS_PER_SCALE_FACTOR
        legacy_path = tmp_path / "flights.csv"
        legacy_path.write_text("", encoding="utf-8")

        with pytest.raises(ValueError, match="is empty"):
            downloader.repair_reusable_layout()

        assert legacy_path.exists()
        assert not (tmp_path / "flights").exists()
        assert not (tmp_path / ".flights-shards.tmp").exists()

    def test_existing_flight_shard_with_bad_width_is_rejected(self, tmp_path):
        """Shard reuse should validate FlightData rows before writing a fresh manifest."""
        shard_dir = tmp_path / "flights"
        shard_dir.mkdir()
        _write_csv(shard_dir / "flights_0001.csv", FlightDataDownloader._flight_header(), [_flight_row(1)[:-1]])
        _write_csv(tmp_path / "airlines.csv", ["code", "name"], [["AA", "American"]])
        _write_csv(
            tmp_path / "airports.csv",
            ["code", "name", "city", "state", "latitude", "longitude"],
            [["ATL", "Atlanta", "Atlanta", "GA", "33.64", "-84.43"]],
        )
        downloader = FlightDataDownloader(scale_factor=1.0, output_dir=tmp_path, seed=42, verbose=1)
        downloader._num_months = MONTHS_PER_SCALE_FACTOR

        with pytest.raises(ValueError, match="row 2 has 27 columns; expected 28"):
            downloader.download()

        assert not (tmp_path / "_datagen_manifest.json").exists()

    def test_csv_loading_config_declares_headered_comma_csv(self):
        """Native loaders should receive FlightData's real CSV dialect."""
        bm = FlightDataBenchmark(scale_factor=0.01)

        assert bm.get_csv_loading_config("flights") == [
            "delim=','",
            "header=true",
            "auto_detect=true",
            "ignore_errors=true",
        ]


class TestPublicWrapper:
    """Tests for the public FlightData wrapper class."""

    def test_public_import(self):
        """Should be importable from benchbox."""
        from benchbox import FlightData

        assert FlightData is not None

    def test_public_wrapper_init(self):
        """Public wrapper should initialize correctly."""
        from benchbox import FlightData

        bm = FlightData(scale_factor=0.01)
        assert bm.scale_factor == 0.01

    def test_public_wrapper_get_queries(self):
        """Public wrapper should expose queries."""
        from benchbox import FlightData

        bm = FlightData(scale_factor=0.01)
        queries = bm.get_queries()
        assert len(queries) == 20

    def test_registry_has_flightdata(self):
        """Benchmark registry should include flightdata."""
        from benchbox.core.benchmark_registry import BENCHMARK_CLASS_NAMES, BENCHMARK_METADATA

        assert "flightdata" in BENCHMARK_METADATA
        assert "flightdata" in BENCHMARK_CLASS_NAMES
        assert BENCHMARK_CLASS_NAMES["flightdata"] == "FlightData"


def _flight_row(flight_id: int, year: int = 2024, month: int = 12) -> list[str | int | float]:
    return [
        flight_id,
        f"{year}-{month:02d}-01",
        year,
        month,
        1,
        1,
        "AA",
        100,
        "ATL",
        "LAX",
        800,
        805.0,
        5.0,
        1000,
        1010.0,
        10.0,
        0,
        "",
        0,
        120.0,
        125.0,
        100.0,
        1946.0,
        "",
        "",
        "",
        "",
        "",
    ]


def _write_csv(path: Path, header: list[str], rows: list[list[object]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(rows)
