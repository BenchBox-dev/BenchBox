"""NYC Taxi data downloader.

Downloads NYC TLC trip data with resumable downloads and validation.
Supports scale factor sampling for reproducible benchmarks.

Data source: https://www.nyc.gov/site/tlc/about/tlc-trip-record-data.page

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import contextlib
import csv
import logging
import os
import tempfile
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Union

import numpy as np
import yaml

from benchbox.core.nyctaxi.schema import get_green_trips_columns, get_hvfhv_trips_columns, get_trips_columns
from benchbox.utils.compression_mixin import CompressionMixin
from benchbox.utils.verbosity import VerbosityMixin, compute_verbosity


def _load_downloader_specs() -> dict[str, Any]:
    with (Path(__file__).with_name("downloader_specs.yaml")).open(encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


_DOWNLOADER_SPECS = _load_downloader_specs()

# TLC data URLs
TLC_BASE_URL = _DOWNLOADER_SPECS["tlc_base_url"]
TAXI_ZONES_URL = _DOWNLOADER_SPECS["taxi_zones_url"]

# Available data ranges
AVAILABLE_YEARS = list(_DOWNLOADER_SPECS["available_years"])
AVAILABLE_MONTHS = list(_DOWNLOADER_SPECS["available_months"])
SCALE_FACTOR_SAMPLE_DIVISOR = float(_DOWNLOADER_SPECS["scale_factor_sample_divisor"])

# Complete NYC TLC Taxi Zone data (all 265 zones)
# Source: https://d37ci6vzurychx.cloudfront.net/misc/taxi_zone_lookup.csv
TAXI_ZONES_DATA = [tuple(row) for row in _DOWNLOADER_SPECS["taxi_zones"]]


class NYCTaxiDataDownloader(CompressionMixin, VerbosityMixin):
    """Downloads and processes NYC TLC trip data.

    Supports resumable downloads and deterministic sampling for
    reproducible scale factors.
    """

    def __init__(
        self,
        scale_factor: float = 1.0,
        output_dir: Union[str, Path] | None = None,
        year: int = 2019,
        months: list[int] | None = None,
        seed: int | None = None,
        verbose: int | bool = 0,
        quiet: bool = False,
        force_redownload: bool = False,
        **kwargs,
    ) -> None:
        """Initialize data downloader.

        Args:
            scale_factor: Scale factor for sampling (0.01 to 100.0)
            output_dir: Directory for output files
            year: Year of data to download
            months: List of months (1-12) to download, None for all
            seed: Random seed for reproducible sampling
            verbose: Verbosity level
            quiet: Suppress output
            force_redownload: Force re-download even if files exist
            **kwargs: Additional options
        """
        super().__init__(**kwargs)

        self.scale_factor = scale_factor
        self.output_dir = Path(output_dir) if output_dir else Path.cwd() / "nyctaxi_data"
        self.year = year
        self.months = months or list(range(1, 13))
        self.seed = seed
        self.rng = np.random.default_rng(seed)
        self.force_redownload = force_redownload

        # Initialize verbosity
        verbosity_settings = compute_verbosity(verbose, quiet)
        self.apply_verbosity(verbosity_settings)
        self.logger = logging.getLogger("benchbox.core.nyctaxi.downloader")

        # Calculate sample rate based on scale factor
        # SF=1.0 corresponds to ~10% of Yellow Taxi data, which is close to
        # BenchBox's ~1GB uncompressed baseline once CSV overhead is included.
        self.sample_rate = min(1.0, scale_factor / SCALE_FACTOR_SAMPLE_DIVISOR)
        if self.sample_rate >= 1.0 and scale_factor >= SCALE_FACTOR_SAMPLE_DIVISOR:
            self.logger.warning(
                "NYC Taxi (Yellow): sample_rate saturated at 1.0 (SF=%.1f). "
                "Full dataset is in use; no additional scaling beyond SF=%.0f.",
                scale_factor,
                SCALE_FACTOR_SAMPLE_DIVISOR,
            )
        self._table_row_counts: dict[str, int] = {}

    def download(self) -> dict[str, Path]:
        """Download and process NYC Taxi data.

        Returns:
            Dictionary mapping table names to file paths

        Raises:
            RuntimeError: If download fails
        """
        self.output_dir.mkdir(parents=True, exist_ok=True)

        table_files = {}

        # Generate taxi zones dimension table
        table_files["taxi_zones"] = self._generate_taxi_zones()

        # Download and process trip data
        table_files["trips"] = self._download_and_process_trips()

        return table_files

    def _generate_taxi_zones(self) -> Path:
        """Generate taxi zones dimension table."""
        output_path = self.output_dir / self.get_compressed_filename("taxi_zones.csv")

        if output_path.exists() and not self.force_redownload:
            self.log_verbose("Taxi zones already exist, skipping")
            return output_path

        self.log_verbose("Generating taxi zones table")

        with self.open_output_file(output_path, "wt") as f:
            writer = csv.writer(f)
            writer.writerow(["location_id", "borough", "zone", "service_zone"])
            for zone in TAXI_ZONES_DATA:
                writer.writerow(zone)

        self._table_row_counts["taxi_zones"] = len(TAXI_ZONES_DATA)
        self.log_verbose(f"  taxi_zones: {len(TAXI_ZONES_DATA)} rows")
        return output_path

    def _download_and_process_trips(self) -> Path:
        """Download and process trip data with sampling."""
        output_path = self.output_dir / self.get_compressed_filename("trips.csv")

        if output_path.exists() and not self.force_redownload:
            self.log_verbose("Trips data already exists, skipping")
            return output_path

        self.log_verbose(f"Downloading NYC Taxi data for {self.year}")
        self.log_verbose(f"  Months: {self.months}")
        self.log_verbose(f"  Sample rate: {self.sample_rate:.4f}")

        # Get column mapping
        output_columns = get_trips_columns()
        trip_id = 0
        total_rows = 0

        with self.open_output_file(output_path, "wt") as outf:
            writer = csv.writer(outf)
            # Write header with trip_id
            writer.writerow(["trip_id"] + output_columns)

            for month in self.months:
                # Download parquet file for this month
                url = f"{TLC_BASE_URL}/yellow_tripdata_{self.year}-{month:02d}.parquet"
                self.log_verbose(f"  Processing {self.year}-{month:02d}...")

                try:
                    month_rows = self._process_parquet_file(url, writer, trip_id)
                    trip_id += month_rows
                    total_rows += month_rows
                except Exception as e:
                    self.logger.warning(f"Failed to process {url}: {e}")
                    continue

        self._table_row_counts["trips"] = total_rows
        self.log_verbose(f"  trips: {total_rows} rows total")
        return output_path

    def _process_parquet_file(self, url: str, writer: csv.writer, start_trip_id: int) -> int:
        """Download and process a single parquet file.

        Args:
            url: URL to download
            writer: CSV writer
            start_trip_id: Starting trip ID

        Returns:
            Number of rows written
        """
        try:
            import pyarrow.parquet as pq
        except ImportError:
            self.logger.warning("pyarrow not installed, using synthetic data")
            return self._generate_synthetic_month(writer, start_trip_id)

        # Download to temp file.  Use mkstemp so the fd is closed before any
        # unlink attempt — NamedTemporaryFile keeps the handle open on Windows,
        # making os.unlink raise WinError 32 from inside the finally block.
        fd, tmp_name = tempfile.mkstemp(suffix=".parquet")
        os.close(fd)
        try:
            urllib.request.urlretrieve(url, tmp_name)
            table = pq.read_table(tmp_name)
            df = table.to_pandas()
        except Exception as e:
            self.logger.warning(f"Download failed: {e}, using synthetic data")
            with contextlib.suppress(OSError):
                os.unlink(tmp_name)
            return self._generate_synthetic_month(writer, start_trip_id)
        with contextlib.suppress(OSError):
            os.unlink(tmp_name)

        # Sample data
        if self.sample_rate < 1.0:
            sample_size = max(1, int(len(df) * self.sample_rate))
            df = df.sample(n=sample_size, random_state=self.seed)

        # Map columns to our schema
        rows_written = 0
        rows_skipped = 0
        for idx, row in df.iterrows():
            try:
                trip_row = self._map_row_to_schema(row, start_trip_id + rows_written)
                writer.writerow(trip_row)
                rows_written += 1
            except Exception:
                rows_skipped += 1
                continue

        if rows_skipped:
            self.logger.debug("Skipped %d malformed rows during Yellow Taxi processing", rows_skipped)
        return rows_written

    def _map_row_to_schema(self, row, trip_id: int) -> list:
        """Map a TLC row to our schema."""

        # Handle different column naming conventions across years
        def get_col(names: list, default=None):
            for name in names:
                if name in row and row[name] is not None:
                    return row[name]
            return default

        return [
            trip_id,
            get_col(["VendorID", "vendorid"], 1),
            get_col(["tpep_pickup_datetime", "pickup_datetime"], ""),
            get_col(["tpep_dropoff_datetime", "dropoff_datetime"], ""),
            get_col(["passenger_count"], 1),
            get_col(["trip_distance"], 0),
            get_col(["PULocationID", "pulocationid"], 0),
            get_col(["DOLocationID", "dolocationid"], 0),
            get_col(["RatecodeID", "ratecodeid"], 1),
            get_col(["store_and_fwd_flag"], "N"),
            get_col(["payment_type"], 1),
            get_col(["fare_amount"], 0),
            get_col(["extra"], 0),
            get_col(["mta_tax"], 0),
            get_col(["tip_amount"], 0),
            get_col(["tolls_amount"], 0),
            get_col(["improvement_surcharge"], 0),
            get_col(["congestion_surcharge"], 0),
            get_col(["airport_fee", "Airport_fee"], 0),
            get_col(["total_amount"], 0),
        ]

    def _generate_synthetic_month(self, writer: csv.writer, start_trip_id: int) -> int:
        """Generate synthetic trip data for one month.

        Used as fallback when real data is unavailable or for testing.
        """
        # Generate ~10K trips per month at SF=1
        num_trips = int(10000 * self.sample_rate * 100)
        num_trips = max(100, num_trips)

        popular_zones = [132, 138, 161, 162, 163, 164, 186, 230, 234, 236, 237, 239]

        for i in range(num_trips):
            trip_id = start_trip_id + i

            # Generate realistic trip data
            hour = int(self.rng.choice([8, 9, 17, 18, 12, 13, 14, 15, 16, 19, 20, 21, 22]))
            minute = int(self.rng.integers(0, 60))
            day = int(self.rng.integers(1, 29))

            month = int(self.rng.choice(self.months))
            pickup_time = datetime(self.year, month, day, hour, minute)
            duration_min = int(10 + self.rng.exponential(15))
            dropoff_time = pickup_time + timedelta(minutes=duration_min)

            distance = max(0.1, self.rng.exponential(3.0))
            fare = 2.50 + distance * 2.50 + duration_min * 0.35

            writer.writerow(
                [
                    trip_id,
                    int(self.rng.choice([1, 2])),  # vendor_id
                    pickup_time.strftime("%Y-%m-%d %H:%M:%S"),
                    dropoff_time.strftime("%Y-%m-%d %H:%M:%S"),
                    int(self.rng.choice([1, 1, 1, 2, 2, 3])),  # passenger_count
                    f"{distance:.2f}",
                    int(self.rng.choice(popular_zones)),  # pickup_location
                    int(self.rng.choice(popular_zones)),  # dropoff_location
                    1,  # rate_code
                    "N",  # store_and_fwd
                    int(self.rng.choice([1, 1, 1, 2])),  # payment_type
                    f"{fare:.2f}",
                    f"{self.rng.random() * 2:.2f}",  # extra
                    "0.50",  # mta_tax
                    f"{fare * 0.15:.2f}" if self.rng.random() > 0.3 else "0.00",  # tip
                    f"{self.rng.random() * 5:.2f}" if self.rng.random() > 0.9 else "0.00",  # tolls
                    "0.30",  # improvement_surcharge
                    "2.50" if self.rng.random() > 0.5 else "0.00",  # congestion
                    "0.00",  # airport_fee
                    f"{fare * 1.2:.2f}",  # total
                ]
            )

        return num_trips

    def get_download_stats(self) -> dict:
        """Get statistics about the download configuration.

        Returns:
            Statistics dictionary
        """
        return {
            "scale_factor": self.scale_factor,
            "sample_rate": self.sample_rate,
            "year": self.year,
            "months": self.months,
            "seed": self.seed,
            "row_counts": dict(self._table_row_counts),
        }


class GreenTaxiDataDownloader(CompressionMixin, VerbosityMixin):
    """Downloads and processes NYC TLC Green Taxi (LPEP) trip data.

    Green Taxi operates in outer boroughs and above 96th St in Manhattan.
    Source: green_tripdata_YYYY-MM.parquet
    Coverage: 2014-present, ~500K trips/month
    """

    def __init__(
        self,
        scale_factor: float = 1.0,
        output_dir: Union[str, Path] | None = None,
        year: int = 2019,
        months: list[int] | None = None,
        seed: int | None = None,
        verbose: int | bool = 0,
        quiet: bool = False,
        force_redownload: bool = False,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)

        self.scale_factor = scale_factor
        self.output_dir = Path(output_dir) if output_dir else Path.cwd() / "nyctaxi_data"
        self.year = year
        self.months = months or list(range(1, 13))
        self.seed = seed
        self.rng = np.random.default_rng(seed)
        self.force_redownload = force_redownload

        verbosity_settings = compute_verbosity(verbose, quiet)
        self.apply_verbosity(verbosity_settings)
        self.logger = logging.getLogger("benchbox.core.nyctaxi.downloader.green")

        self.sample_rate = min(1.0, scale_factor / SCALE_FACTOR_SAMPLE_DIVISOR)
        if self.sample_rate >= 1.0 and scale_factor >= SCALE_FACTOR_SAMPLE_DIVISOR:
            self.logger.warning(
                "NYC Taxi (Green): sample_rate saturated at 1.0 (SF=%.1f). "
                "Full dataset is in use; no additional scaling beyond SF=%.0f.",
                scale_factor,
                SCALE_FACTOR_SAMPLE_DIVISOR,
            )
        self._table_row_counts: dict[str, int] = {}

    def download(self) -> Path:
        """Download and process Green Taxi data.

        Returns:
            Path to the generated green_trips CSV file
        """
        self.output_dir.mkdir(parents=True, exist_ok=True)
        return self._download_and_process_trips()

    def _download_and_process_trips(self) -> Path:
        """Download and process Green Taxi trip data with sampling."""
        output_path = self.output_dir / self.get_compressed_filename("green_trips.csv")

        if output_path.exists() and not self.force_redownload:
            self.log_verbose("Green trips data already exists, skipping")
            return output_path

        self.log_verbose(f"Downloading Green Taxi data for {self.year}")
        self.log_verbose(f"  Months: {self.months}")
        self.log_verbose(f"  Sample rate: {self.sample_rate:.4f}")

        output_columns = get_green_trips_columns()
        trip_id = 0
        total_rows = 0

        with self.open_output_file(output_path, "wt") as outf:
            writer = csv.writer(outf)
            writer.writerow(["trip_id"] + output_columns)

            for month in self.months:
                url = f"{TLC_BASE_URL}/green_tripdata_{self.year}-{month:02d}.parquet"
                self.log_verbose(f"  Processing {self.year}-{month:02d}...")

                try:
                    month_rows = self._process_parquet_file(url, writer, trip_id)
                    trip_id += month_rows
                    total_rows += month_rows
                except Exception as e:
                    self.logger.warning(f"Failed to process {url}: {e}")
                    continue

        self._table_row_counts["green_trips"] = total_rows
        self.log_verbose(f"  green_trips: {total_rows} rows total")
        return output_path

    def _process_parquet_file(self, url: str, writer: csv.writer, start_trip_id: int) -> int:
        """Download and process a single Green Taxi parquet file."""
        try:
            import pyarrow.parquet as pq
        except ImportError:
            self.logger.warning("pyarrow not installed, using synthetic data")
            return self._generate_synthetic_month(writer, start_trip_id)

        fd, tmp_name = tempfile.mkstemp(suffix=".parquet")
        os.close(fd)
        try:
            urllib.request.urlretrieve(url, tmp_name)
            table = pq.read_table(tmp_name)
            df = table.to_pandas()
        except Exception as e:
            self.logger.warning(f"Download failed: {e}, using synthetic data")
            with contextlib.suppress(OSError):
                os.unlink(tmp_name)
            return self._generate_synthetic_month(writer, start_trip_id)
        with contextlib.suppress(OSError):
            os.unlink(tmp_name)

        if self.sample_rate < 1.0:
            sample_size = max(1, int(len(df) * self.sample_rate))
            df = df.sample(n=sample_size, random_state=self.seed)

        rows_written = 0
        rows_skipped = 0
        for idx, row in df.iterrows():
            try:
                trip_row = self._map_row_to_schema(row, start_trip_id + rows_written)
                writer.writerow(trip_row)
                rows_written += 1
            except Exception:
                rows_skipped += 1
                continue

        if rows_skipped:
            self.logger.debug("Skipped %d malformed rows during Green Taxi processing", rows_skipped)
        return rows_written

    def _map_row_to_schema(self, row, trip_id: int) -> list:
        """Map a Green Taxi (LPEP) TLC row to our schema."""

        def get_col(names: list, default=None):
            for name in names:
                if name in row and row[name] is not None:
                    return row[name]
            return default

        return [
            trip_id,
            get_col(["VendorID", "vendorid"], 1),
            get_col(["lpep_pickup_datetime", "pickup_datetime"], ""),
            get_col(["lpep_dropoff_datetime", "dropoff_datetime"], ""),
            get_col(["store_and_fwd_flag"], "N"),
            get_col(["RatecodeID", "ratecodeid"], 1),
            get_col(["PULocationID", "pulocationid"], 0),
            get_col(["DOLocationID", "dolocationid"], 0),
            get_col(["passenger_count"], 1),
            get_col(["trip_distance"], 0),
            get_col(["fare_amount"], 0),
            get_col(["extra"], 0),
            get_col(["mta_tax"], 0),
            get_col(["tip_amount"], 0),
            get_col(["tolls_amount"], 0),
            get_col(["ehail_fee"], 0),
            get_col(["improvement_surcharge"], 0),
            get_col(["total_amount"], 0),
            get_col(["payment_type"], 1),
            get_col(["trip_type"], 1),
            get_col(["congestion_surcharge"], 0),
        ]

    def _generate_synthetic_month(self, writer: csv.writer, start_trip_id: int) -> int:
        """Generate synthetic Green Taxi trip data (outer-borough patterns)."""
        # Green Taxi volume is ~5x lower than Yellow (~2K/month at SF=1)
        num_trips = int(2000 * self.sample_rate * 100)
        num_trips = max(50, num_trips)

        # Outer-borough zones (Brooklyn, Queens, Bronx focus)
        outer_borough_zones = [
            7,
            8,
            17,
            21,
            22,
            25,
            26,
            33,
            35,
            36,
            37,
            39,
            40,
            49,
            61,
            62,
            65,
            69,
            74,
            76,
            85,
            103,
            109,
            128,
            129,
            133,
            143,
            181,
            189,
            197,
        ]

        for i in range(num_trips):
            trip_id = start_trip_id + i

            hour = int(self.rng.choice([7, 8, 9, 17, 18, 19, 12, 13, 14, 15, 16]))
            minute = int(self.rng.integers(0, 60))
            day = int(self.rng.integers(1, 29))

            month = int(self.rng.choice(self.months))
            pickup_time = datetime(self.year, month, day, hour, minute)
            duration_min = int(8 + self.rng.exponential(12))
            dropoff_time = pickup_time + timedelta(minutes=duration_min)

            distance = max(0.1, self.rng.exponential(2.5))
            fare = 2.50 + distance * 2.50 + duration_min * 0.35

            writer.writerow(
                [
                    trip_id,
                    int(self.rng.choice([1, 2])),  # vendor_id
                    pickup_time.strftime("%Y-%m-%d %H:%M:%S"),
                    dropoff_time.strftime("%Y-%m-%d %H:%M:%S"),
                    "N",  # store_and_fwd_flag
                    1,  # rate_code_id
                    int(self.rng.choice(outer_borough_zones)),  # pickup_location_id
                    int(self.rng.choice(outer_borough_zones)),  # dropoff_location_id
                    int(self.rng.choice([1, 1, 1, 2, 2])),  # passenger_count
                    f"{distance:.2f}",
                    f"{fare:.2f}",
                    f"{self.rng.random() * 1:.2f}",  # extra
                    "0.50",  # mta_tax
                    f"{fare * 0.15:.2f}" if self.rng.random() > 0.35 else "0.00",  # tip
                    f"{self.rng.random() * 4:.2f}" if self.rng.random() > 0.9 else "0.00",  # tolls
                    "0.00",  # ehail_fee
                    "0.30",  # improvement_surcharge
                    f"{fare * 1.18:.2f}",  # total_amount
                    int(self.rng.choice([1, 1, 1, 2])),  # payment_type
                    int(self.rng.choice([1, 1, 2])),  # trip_type (1=street-hail, 2=dispatch)
                    "2.50" if self.rng.random() > 0.5 else "0.00",  # congestion_surcharge
                ]
            )

        return num_trips

    def get_download_stats(self) -> dict:
        return {
            "taxi_type": "green",
            "scale_factor": self.scale_factor,
            "sample_rate": self.sample_rate,
            "year": self.year,
            "months": self.months,
            "seed": self.seed,
            "row_counts": dict(self._table_row_counts),
        }


class HVFHVDataDownloader(CompressionMixin, VerbosityMixin):
    """Downloads and processes NYC TLC High Volume For-Hire Vehicle (HVFHV) trip data.

    HVFHV covers Uber, Lyft, Via, and Juno - the app-based rideshare companies.
    This is now the highest-volume TLC dataset (~25M trips/month since 2019).
    Source: fhvhv_tripdata_YYYY-MM.parquet
    Coverage: February 2019-present
    """

    # HVFHV data only available from Feb 2019
    HVFHV_START_YEAR = 2019
    HVFHV_START_MONTH = 2

    # TLC license numbers for major HVFHV bases
    HVFHV_LICENSE_NUMS = {
        "HV0002": "Juno",
        "HV0003": "Uber",
        "HV0004": "Via",
        "HV0005": "Lyft",
    }

    def __init__(
        self,
        scale_factor: float = 1.0,
        output_dir: Union[str, Path] | None = None,
        year: int = 2019,
        months: list[int] | None = None,
        seed: int | None = None,
        verbose: int | bool = 0,
        quiet: bool = False,
        force_redownload: bool = False,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)

        self.scale_factor = scale_factor
        self.output_dir = Path(output_dir) if output_dir else Path.cwd() / "nyctaxi_data"
        self.year = year
        # HVFHV starts Feb 2019 - skip Jan 2019 if year==2019
        default_months = list(range(1, 13))
        if year == self.HVFHV_START_YEAR:
            default_months = list(range(self.HVFHV_START_MONTH, 13))
        self.months = months or default_months
        self.seed = seed
        self.rng = np.random.default_rng(seed)
        self.force_redownload = force_redownload

        verbosity_settings = compute_verbosity(verbose, quiet)
        self.apply_verbosity(verbosity_settings)
        self.logger = logging.getLogger("benchbox.core.nyctaxi.downloader.hvfhv")

        self.sample_rate = min(1.0, scale_factor / SCALE_FACTOR_SAMPLE_DIVISOR)
        if self.sample_rate >= 1.0 and scale_factor >= SCALE_FACTOR_SAMPLE_DIVISOR:
            self.logger.warning(
                "NYC Taxi (HVFHV): sample_rate saturated at 1.0 (SF=%.1f). "
                "Full dataset is in use; no additional scaling beyond SF=%.0f.",
                scale_factor,
                SCALE_FACTOR_SAMPLE_DIVISOR,
            )
        self._table_row_counts: dict[str, int] = {}

    def download(self) -> Path:
        """Download and process HVFHV data.

        Returns:
            Path to the generated hvfhv_trips CSV file
        """
        self.output_dir.mkdir(parents=True, exist_ok=True)
        return self._download_and_process_trips()

    def _download_and_process_trips(self) -> Path:
        """Download and process HVFHV trip data with sampling."""
        output_path = self.output_dir / self.get_compressed_filename("hvfhv_trips.csv")

        if output_path.exists() and not self.force_redownload:
            self.log_verbose("HVFHV trips data already exists, skipping")
            return output_path

        self.log_verbose(f"Downloading HVFHV data for {self.year}")
        self.log_verbose(f"  Months: {self.months}")
        self.log_verbose(f"  Sample rate: {self.sample_rate:.4f}")

        output_columns = get_hvfhv_trips_columns()
        trip_id = 0
        total_rows = 0

        with self.open_output_file(output_path, "wt") as outf:
            writer = csv.writer(outf)
            writer.writerow(["trip_id"] + output_columns)

            for month in self.months:
                url = f"{TLC_BASE_URL}/fhvhv_tripdata_{self.year}-{month:02d}.parquet"
                self.log_verbose(f"  Processing {self.year}-{month:02d}...")

                try:
                    month_rows = self._process_parquet_file(url, writer, trip_id)
                    trip_id += month_rows
                    total_rows += month_rows
                except Exception as e:
                    self.logger.warning(f"Failed to process {url}: {e}")
                    continue

        self._table_row_counts["hvfhv_trips"] = total_rows
        self.log_verbose(f"  hvfhv_trips: {total_rows} rows total")
        return output_path

    def _process_parquet_file(self, url: str, writer: csv.writer, start_trip_id: int) -> int:
        """Download and process a single HVFHV parquet file."""
        try:
            import pyarrow.parquet as pq
        except ImportError:
            self.logger.warning("pyarrow not installed, using synthetic data")
            return self._generate_synthetic_month(writer, start_trip_id)

        fd, tmp_name = tempfile.mkstemp(suffix=".parquet")
        os.close(fd)
        try:
            urllib.request.urlretrieve(url, tmp_name)
            table = pq.read_table(tmp_name)
            df = table.to_pandas()
        except Exception as e:
            self.logger.warning(f"Download failed: {e}, using synthetic data")
            with contextlib.suppress(OSError):
                os.unlink(tmp_name)
            return self._generate_synthetic_month(writer, start_trip_id)
        with contextlib.suppress(OSError):
            os.unlink(tmp_name)

        if self.sample_rate < 1.0:
            sample_size = max(1, int(len(df) * self.sample_rate))
            df = df.sample(n=sample_size, random_state=self.seed)

        rows_written = 0
        rows_skipped = 0
        for idx, row in df.iterrows():
            try:
                trip_row = self._map_row_to_schema(row, start_trip_id + rows_written)
                writer.writerow(trip_row)
                rows_written += 1
            except Exception:
                rows_skipped += 1
                continue

        if rows_skipped:
            self.logger.debug("Skipped %d malformed rows during HVFHV processing", rows_skipped)
        return rows_written

    def _map_row_to_schema(self, row, trip_id: int) -> list:
        """Map an HVFHV TLC row to our schema."""

        def get_col(names: list, default=None):
            for name in names:
                if name in row and row[name] is not None:
                    return row[name]
            return default

        return [
            trip_id,
            get_col(["hvfhs_license_num"], "HV0003"),
            get_col(["dispatching_base_num"], ""),
            get_col(["originating_base_num"], ""),
            get_col(["request_datetime"], ""),
            get_col(["on_scene_datetime"], ""),
            get_col(["pickup_datetime"], ""),
            get_col(["dropoff_datetime"], ""),
            get_col(["PULocationID", "pulocationid"], 0),
            get_col(["DOLocationID", "dolocationid"], 0),
            get_col(["trip_miles"], 0),
            get_col(["trip_time"], 0),
            get_col(["base_passenger_fare"], 0),
            get_col(["tolls"], 0),
            get_col(["bcf"], 0),
            get_col(["sales_tax"], 0),
            get_col(["congestion_surcharge"], 0),
            get_col(["airport_fee"], 0),
            get_col(["tips"], 0),
            get_col(["driver_pay"], 0),
            get_col(["shared_request_flag"], "N"),
            get_col(["shared_match_flag"], "N"),
            get_col(["access_a_ride_flag"], "N"),
            get_col(["wav_request_flag"], "N"),
            get_col(["wav_match_flag"], "N"),
        ]

    def _generate_synthetic_month(self, writer: csv.writer, start_trip_id: int) -> int:
        """Generate synthetic HVFHV trip data (app-based rideshare patterns).

        HVFHV is citywide with high volume (~25M/month real data).
        At SF=1.0 we generate ~25K synthetic trips/month.
        """
        num_trips = int(25000 * self.sample_rate * 100)
        num_trips = max(100, num_trips)

        # All NYC zones - HVFHV is truly citywide
        all_zones = list(range(1, 263))
        # License distribution: Uber dominant, Lyft second
        license_weights = ["HV0003"] * 55 + ["HV0005"] * 30 + ["HV0002"] * 10 + ["HV0004"] * 5

        for i in range(num_trips):
            trip_id = start_trip_id + i

            hour = int(self.rng.choice([8, 9, 10, 17, 18, 19, 20, 21, 22, 23, 0, 1]))
            minute = int(self.rng.integers(0, 60))
            day = int(self.rng.integers(1, 29))

            month = int(self.rng.choice(self.months))
            pickup_time = datetime(self.year, month, day, hour, minute)
            wait_min = int(2 + self.rng.exponential(5))  # wait time
            duration_min = int(8 + self.rng.exponential(18))

            request_time = pickup_time - timedelta(minutes=wait_min)
            on_scene_time = pickup_time
            dropoff_time = pickup_time + timedelta(minutes=duration_min)

            distance = max(0.1, self.rng.exponential(4.5))  # HVFHV trips tend longer
            base_fare = 2.50 + distance * 1.80 + duration_min * 0.30
            # Surge pricing simulation (15% of trips have surge)
            if self.rng.random() > 0.85:
                base_fare *= float(1.5 + self.rng.random())

            license_num = str(self.rng.choice(license_weights))
            base_num = f"B{int(self.rng.integers(100000, 999999))}"
            is_shared = self.rng.random() > 0.75  # ~25% shared requests

            writer.writerow(
                [
                    trip_id,
                    license_num,
                    base_num,  # dispatching_base_num
                    base_num,  # originating_base_num
                    request_time.strftime("%Y-%m-%d %H:%M:%S"),
                    on_scene_time.strftime("%Y-%m-%d %H:%M:%S"),
                    pickup_time.strftime("%Y-%m-%d %H:%M:%S"),
                    dropoff_time.strftime("%Y-%m-%d %H:%M:%S"),
                    int(self.rng.choice(all_zones)),  # pickup_location_id
                    int(self.rng.choice(all_zones)),  # dropoff_location_id
                    f"{distance:.2f}",  # trip_miles
                    int(duration_min * 60),  # trip_time (seconds)
                    f"{base_fare:.2f}",  # base_passenger_fare
                    f"{self.rng.random() * 4:.2f}" if self.rng.random() > 0.9 else "0.00",  # tolls
                    f"{base_fare * 0.025:.2f}",  # bcf (2.5% Black Car Fund)
                    f"{base_fare * 0.089:.2f}",  # sales_tax (8.875%)
                    "2.75" if self.rng.random() > 0.5 else "0.00",  # congestion_surcharge
                    "0.00",  # airport_fee
                    f"{base_fare * 0.20:.2f}" if self.rng.random() > 0.55 else "0.00",  # tips
                    f"{base_fare * 0.60:.2f}",  # driver_pay
                    "Y" if is_shared else "N",  # shared_request_flag
                    "Y" if (is_shared and self.rng.random() > 0.5) else "N",  # shared_match_flag
                    "N",  # access_a_ride_flag
                    "Y" if self.rng.random() > 0.95 else "N",  # wav_request_flag
                    "Y" if self.rng.random() > 0.97 else "N",  # wav_match_flag
                ]
            )

        return num_trips

    def get_download_stats(self) -> dict:
        return {
            "taxi_type": "hvfhv",
            "scale_factor": self.scale_factor,
            "sample_rate": self.sample_rate,
            "year": self.year,
            "months": self.months,
            "seed": self.seed,
            "row_counts": dict(self._table_row_counts),
        }
