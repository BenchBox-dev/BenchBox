"""H2O DB benchmark data generator.

This module generates synthetic taxi trip data that mimics the structure
and characteristics of the NYC Taxi & Limousine Commission Trip Record Data
used in the H2O DB benchmark.

The generator creates realistic taxi trip records with:
- Pickup and dropoff locations in NYC
- Realistic fare amounts and trip distances
- Proper datetime distributions
- Payment types and other trip attributes

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import csv
import random
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Union

from benchbox.core.manifest_utils import write_generator_manifest
from benchbox.utils.cloud_storage import CloudStorageGeneratorMixin, create_path_handler
from benchbox.utils.compression_mixin import CompressionMixin

if TYPE_CHECKING:
    from cloudpathlib import CloudPath


PathLike = Union[Path, "CloudPath"]


class H2ODataGenerator(CompressionMixin, CloudStorageGeneratorMixin):
    def __init__(
        self,
        scale_factor: float = 1.0,
        output_dir: Path | None = None,
        *,
        verbose: int | bool = 0,
        quiet: bool = False,
        **kwargs,
    ) -> None:

        super().__init__(**kwargs)

        self.scale_factor = scale_factor
        self.output_dir = create_path_handler(output_dir) if output_dir else Path.cwd()

        if isinstance(verbose, bool):
            self.verbose_level = 1 if verbose else 0
        else:
            self.verbose_level = int(verbose or 0)
        self.verbose_enabled = self.verbose_level >= 1 and not quiet
        self.very_verbose = self.verbose_level >= 2 and not quiet
        self.quiet = bool(quiet)

        self.base_trips = 10000000

        random.seed(42)

        self.nyc_bounds = {
            "min_lat": 40.4774,
            "max_lat": 40.9176,
            "min_lon": -74.2591,
            "max_lon": -73.7004,
        }

        self.location_ids = list(range(1, 264))

        self.vendor_ids = [1, 2]

        self.rate_codes = [1, 2, 3, 4, 5, 6]

        self.payment_types = [1, 2, 3, 4]

        self._manifest_row_counts: dict[str, int] = {}

    def generate_data(self, tables: list[str] | None = None) -> dict[str, str]:

        table_paths = self._handle_cloud_or_local_generation(
            self.output_dir,
            lambda output_dir: self._generate_data_local(output_dir, tables),
            False,
        )
        self._write_manifest(table_paths)

        return {table: str(path) for table, path in table_paths.items()}

    def _generate_data_local(self, output_dir: Path, tables: list[str] | None = None) -> dict[str, str]:

        if tables is None:
            tables = ["trips"]

        original_output_dir = self.output_dir
        self.output_dir = output_dir
        try:
            self.output_dir.mkdir(parents=True, exist_ok=True)

            file_paths: dict[str, Path] = {}
            self._manifest_row_counts = {}

            if "trips" in tables:
                file_paths["trips"] = self._generate_trips_data()

            if self.should_use_compression() and file_paths:
                self.print_compression_report(file_paths)

            return {table: str(path) for table, path in file_paths.items()}
        finally:
            self.output_dir = original_output_dir

    def _generate_trips_data(self) -> PathLike:

        filename = self.get_compressed_filename("trips.tbl")
        file_path = self.output_dir / filename
        num_trips = int(self.base_trips * self.scale_factor)

        start_date = datetime(2015, 1, 1)
        end_date = datetime(2019, 12, 31)
        total_days = (end_date - start_date).days

        with self.open_output_file(file_path, "wt") as f:
            writer = csv.writer(f, delimiter="|")

            for _ in range(num_trips):
                random_days = random.randint(0, total_days)
                pickup_date = start_date + timedelta(days=random_days)

                hour_weights = [
                    0.02,
                    0.01,
                    0.01,
                    0.01,
                    0.02,
                    0.03,
                    0.05,
                    0.07,
                    0.08,
                    0.09,
                    0.09,
                    0.08,
                    0.08,
                    0.08,
                    0.08,
                    0.09,
                    0.10,
                    0.11,
                    0.10,
                    0.09,
                    0.08,
                    0.06,
                    0.04,
                    0.03,
                ]

                hour = random.choices(range(24), weights=hour_weights)[0]
                minute = random.randint(0, 59)
                second = random.randint(0, 59)

                pickup_datetime = pickup_date.replace(hour=hour, minute=minute, second=second)

                trip_duration_minutes = random.randint(5, 120)
                dropoff_datetime = pickup_datetime + timedelta(minutes=trip_duration_minutes)

                vendor_id = random.choice(self.vendor_ids)
                passenger_count = random.choices([1, 2, 3, 4, 5, 6], weights=[0.7, 0.15, 0.08, 0.04, 0.02, 0.01])[0]

                pickup_longitude = round(
                    random.uniform(self.nyc_bounds["min_lon"], self.nyc_bounds["max_lon"]),
                    6,
                )
                pickup_latitude = round(
                    random.uniform(self.nyc_bounds["min_lat"], self.nyc_bounds["max_lat"]),
                    6,
                )
                dropoff_longitude = round(
                    random.uniform(self.nyc_bounds["min_lon"], self.nyc_bounds["max_lon"]),
                    6,
                )
                dropoff_latitude = round(
                    random.uniform(self.nyc_bounds["min_lat"], self.nyc_bounds["max_lat"]),
                    6,
                )

                lat_diff = abs(dropoff_latitude - pickup_latitude)
                lon_diff = abs(dropoff_longitude - pickup_longitude)
                trip_distance = round(((lat_diff**2 + lon_diff**2) ** 0.5) * 69, 2)
                trip_distance = max(0.1, min(trip_distance, 50.0))

                rate_code_id = random.choice(self.rate_codes)
                store_and_fwd_flag = random.choices(["Y", "N"], weights=[0.05, 0.95])[0]

                pickup_location_id = random.choice(self.location_ids)
                dropoff_location_id = random.choice(self.location_ids)

                payment_type = random.choice(self.payment_types)

                base_fare = 2.50 + (trip_distance * 2.50)
                fare_amount = round(max(base_fare, 2.50), 2)

                extra = round(random.choice([0.0, 0.50, 1.0]), 2)

                mta_tax = 0.50

                if payment_type == 1:
                    tip_amount = round(fare_amount * random.uniform(0.10, 0.25), 2)
                else:
                    tip_amount = 0.0

                tolls_amount = round(random.choices([0.0, 5.54, 8.50], weights=[0.9, 0.07, 0.03])[0], 2)
                improvement_surcharge = 0.30
                congestion_surcharge = round(random.choices([0.0, 2.50], weights=[0.7, 0.3])[0], 2)

                total_amount = round(
                    fare_amount
                    + extra
                    + mta_tax
                    + tip_amount
                    + tolls_amount
                    + improvement_surcharge
                    + congestion_surcharge,
                    2,
                )

                row = [
                    vendor_id,
                    pickup_datetime.strftime("%Y-%m-%d %H:%M:%S"),
                    dropoff_datetime.strftime("%Y-%m-%d %H:%M:%S"),
                    passenger_count,
                    trip_distance,
                    pickup_longitude,
                    pickup_latitude,
                    rate_code_id,
                    store_and_fwd_flag,
                    dropoff_longitude,
                    dropoff_latitude,
                    payment_type,
                    fare_amount,
                    extra,
                    mta_tax,
                    tip_amount,
                    tolls_amount,
                    improvement_surcharge,
                    total_amount,
                    pickup_location_id,
                    dropoff_location_id,
                    congestion_surcharge,
                ]

                writer.writerow(row)

        self._manifest_row_counts["trips"] = num_trips
        return file_path

    def _write_manifest(self, table_paths: dict[str, Path]) -> None:
        write_generator_manifest(self, "h2odb", table_paths, self._manifest_row_counts)
