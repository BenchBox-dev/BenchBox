"""Tests for NYC Taxi data downloader.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import csv
import tempfile
from pathlib import Path

import pytest

from benchbox.core.nyctaxi.downloader import (
    TAXI_ZONES_DATA,
    NYCTaxiDataDownloader,
)

pytestmark = [
    pytest.mark.unit,
    pytest.mark.medium,
]


class TestDownloaderConfiguration:
    """Tests for downloader initialization and configuration."""

    def test_default_configuration(self):
        """Should use default values when not specified."""
        with tempfile.TemporaryDirectory() as tmpdir:
            downloader = NYCTaxiDataDownloader(output_dir=tmpdir)
            assert downloader.scale_factor == 1.0
            assert downloader.year == 2019
            assert downloader.months == list(range(1, 13))

    def test_scale_factor_affects_sample_rate(self):
        """Scale factor should affect sample rate."""
        with tempfile.TemporaryDirectory() as tmpdir:
            dl1 = NYCTaxiDataDownloader(scale_factor=1.0, output_dir=tmpdir)
            dl2 = NYCTaxiDataDownloader(scale_factor=10.0, output_dir=tmpdir)
            assert dl2.sample_rate > dl1.sample_rate

    def test_max_sample_rate(self):
        """Sample rate should be capped at 1.0."""
        with tempfile.TemporaryDirectory() as tmpdir:
            downloader = NYCTaxiDataDownloader(scale_factor=1000.0, output_dir=tmpdir)
            assert downloader.sample_rate <= 1.0

    def test_custom_year(self):
        """Should accept custom year."""
        with tempfile.TemporaryDirectory() as tmpdir:
            downloader = NYCTaxiDataDownloader(year=2020, output_dir=tmpdir)
            assert downloader.year == 2020

    def test_custom_months(self):
        """Should accept custom months."""
        with tempfile.TemporaryDirectory() as tmpdir:
            downloader = NYCTaxiDataDownloader(months=[1, 2, 3], output_dir=tmpdir)
            assert downloader.months == [1, 2, 3]

    def test_seed_for_reproducibility(self, seed):
        """Should accept seed for reproducibility."""
        with tempfile.TemporaryDirectory() as tmpdir:
            downloader = NYCTaxiDataDownloader(seed=seed, output_dir=tmpdir)
            assert downloader.seed == seed


class TestTaxiZonesData:
    """Tests for embedded taxi zones data."""

    def test_has_zones(self):
        """Should have taxi zone data."""
        assert len(TAXI_ZONES_DATA) > 0

    def test_zone_structure(self):
        """Each zone should have (id, borough, zone, service_zone)."""
        for zone in TAXI_ZONES_DATA:
            assert len(zone) == 4
            assert isinstance(zone[0], int)
            assert isinstance(zone[1], str)
            assert isinstance(zone[2], str)
            assert isinstance(zone[3], str)

    def test_popular_zones_exist(self):
        """Popular zones should exist in data."""
        zone_ids = {z[0] for z in TAXI_ZONES_DATA}
        popular = [132, 138, 161, 162, 163, 164, 186, 230, 234, 236, 237, 239]
        for zone_id in popular:
            assert zone_id in zone_ids, f"Zone {zone_id} not in data"


class TestTaxiZonesGeneration:
    """Tests for taxi zones table generation."""

    @pytest.fixture
    def downloader(self, seed):
        """Create downloader for testing."""
        tmpdir = tempfile.mkdtemp()
        dl = NYCTaxiDataDownloader(
            scale_factor=0.01,
            output_dir=tmpdir,
            year=2019,
            months=[1],
            seed=seed,
        )
        yield dl
        import shutil

        shutil.rmtree(tmpdir, ignore_errors=True)

    def test_generates_taxi_zones_csv(self, downloader):
        """Should generate taxi_zones.csv."""
        path = downloader._generate_taxi_zones()
        assert path.exists()
        assert path.name == "taxi_zones.csv"

    def test_taxi_zones_csv_content(self, downloader):
        """Taxi zones CSV should have correct content."""
        path = downloader._generate_taxi_zones()

        with open(path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        assert len(rows) == len(TAXI_ZONES_DATA)
        assert "location_id" in rows[0]
        assert "borough" in rows[0]
        assert "zone" in rows[0]


class TestSyntheticDataGeneration:
    """Tests for synthetic data generation."""

    @pytest.fixture
    def downloader(self, seed):
        """Create downloader for testing."""
        tmpdir = tempfile.mkdtemp()
        dl = NYCTaxiDataDownloader(
            scale_factor=0.01,
            output_dir=tmpdir,
            year=2019,
            months=[1],
            seed=seed,
        )
        yield dl
        import shutil

        shutil.rmtree(tmpdir, ignore_errors=True)

    def test_synthetic_generation_produces_rows(self, downloader):
        """Synthetic generation should produce rows."""
        output_path = downloader.output_dir / "test_trips.csv"

        with open(output_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["trip_id", "vendor_id", "pickup_datetime", "total_amount"])
            count = downloader._generate_synthetic_month(writer, 0)

        assert count > 0
        assert output_path.exists()

    def test_synthetic_data_has_expected_columns(self, downloader):
        """Synthetic data should have trip columns."""
        output_path = downloader.output_dir / "test_trips.csv"

        with open(output_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            # Full header
            header = [
                "trip_id",
                "vendor_id",
                "pickup_datetime",
                "dropoff_datetime",
                "passenger_count",
                "trip_distance",
                "pickup_location_id",
                "dropoff_location_id",
                "rate_code_id",
                "store_and_fwd_flag",
                "payment_type",
                "fare_amount",
                "extra",
                "mta_tax",
                "tip_amount",
                "tolls_amount",
                "improvement_surcharge",
                "congestion_surcharge",
                "airport_fee",
                "total_amount",
            ]
            writer.writerow(header)
            downloader._generate_synthetic_month(writer, 0)

        with open(output_path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            row = next(reader)
            assert "pickup_datetime" in row
            assert "total_amount" in row


class TestDataDownload:
    """Tests for full data download/generation."""

    @pytest.fixture(scope="class")
    def downloader_with_data(self):
        """Create downloader with small settings and pre-downloaded data.

        Class-scoped to avoid redundant downloads (4-5s per call).
        """
        tmpdir = tempfile.mkdtemp()
        dl = NYCTaxiDataDownloader(
            scale_factor=0.01,
            output_dir=tmpdir,
            year=2019,
            months=[1],
            seed=42,
            force_redownload=True,
        )
        result = dl.download()
        yield dl, result
        import shutil

        shutil.rmtree(tmpdir, ignore_errors=True)

    def test_download_returns_table_files(self, downloader_with_data):
        """download() should return dict of table paths."""
        downloader, result = downloader_with_data
        assert isinstance(result, dict)
        assert "taxi_zones" in result
        assert "trips" in result

    def test_download_creates_files(self, downloader_with_data):
        """download() should create actual files."""
        downloader, result = downloader_with_data
        for table_name, path in result.items():
            assert Path(path).exists(), f"File for {table_name} not created"


class TestDownloadStats:
    """Tests for get_download_stats."""

    def test_stats_structure(self, seed):
        """Stats should have expected structure."""
        with tempfile.TemporaryDirectory() as tmpdir:
            downloader = NYCTaxiDataDownloader(
                scale_factor=1.0,
                output_dir=tmpdir,
                year=2019,
                months=[1, 2, 3],
                seed=seed,
            )
            stats = downloader.get_download_stats()

        assert "scale_factor" in stats
        assert "sample_rate" in stats
        assert "year" in stats
        assert "months" in stats

    def test_stats_values(self, seed):
        """Stats should have correct values."""
        with tempfile.TemporaryDirectory() as tmpdir:
            downloader = NYCTaxiDataDownloader(
                scale_factor=2.0,
                output_dir=tmpdir,
                year=2020,
                months=[6, 7],
                seed=seed,
            )
            stats = downloader.get_download_stats()

        assert stats["scale_factor"] == 2.0
        assert stats["year"] == 2020
        assert stats["months"] == [6, 7]


class TestSourceContractIdentity:
    """Contract id, provenance labels, and stale-cache detection."""

    def test_contract_id_stable_and_pin_sensitive(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            first = NYCTaxiDataDownloader(output_dir=tmpdir)
            second = NYCTaxiDataDownloader(output_dir=tmpdir)
            other_year = NYCTaxiDataDownloader(output_dir=tmpdir, year=2020)
        assert first.source_contract_id() == second.source_contract_id()
        assert first.source_contract_id() != other_year.source_contract_id()

    def test_stats_report_tlc_when_nothing_synthetic(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            stats = NYCTaxiDataDownloader(output_dir=tmpdir).get_download_stats()
        assert stats["source"] == "nyc-tlc"
        assert stats["synthetic_months"] == []

    def test_stats_report_mixed_and_synthetic_provenance(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            downloader = NYCTaxiDataDownloader(output_dir=tmpdir, year=2020, months=[6, 7])
            downloader._record_synthetic_fallback("https://x/yellow_tripdata_2020-06.parquet")
            assert downloader.get_download_stats()["source"] == "nyc-tlc-synthetic-mixed"
            downloader._record_synthetic_fallback("https://x/yellow_tripdata_2020-07.parquet")
            stats = downloader.get_download_stats()
            assert stats["source"] == "synthetic"
            assert stats["synthetic_months"] == ["2020-06", "2020-07"]

    def test_stale_sidecar_detected(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            output_path = tmpdir / "trips.csv.gz"
            output_path.write_text("x", encoding="utf-8")
            current = NYCTaxiDataDownloader(output_dir=tmpdir)
            current._write_contract_sidecar(output_path)
            assert current._read_persisted_contract_id(output_path) == current.source_contract_id()
            other = NYCTaxiDataDownloader(output_dir=tmpdir, year=2020)
            assert other._read_persisted_contract_id(output_path) != other.source_contract_id()

    def test_missing_sidecar_reads_none(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            downloader = NYCTaxiDataDownloader(output_dir=tmpdir)
            assert downloader._read_persisted_contract_id(Path(tmpdir) / "trips.csv.gz") is None
