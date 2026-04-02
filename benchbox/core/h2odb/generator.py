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

# Type alias for paths that could be local or cloud
PathLike = Union[Path, "CloudPath"]


class H2ODataGenerator(CompressionMixin, CloudStorageGeneratorMixin):
    """Generator for H2O DB benchmark data."""

    def __init__(
        self,
        scale_factor: float = 1.0,
        output_dir: Path | None = None,
        *,
        verbose: int | bool = 0,
        quiet: bool = False,
        **kwargs,
    ) -> None:
        """Initialize H2O DB data generator.

        Args:
            scale_factor: Scale factor for data generation (1.0 = ~1M trips)
            output_dir: Directory to write generated data files
            **kwargs: Additional arguments including compression options
        """
        # Initialize compression mixin
        super().__init__(**kwargs)

        self.scale_factor = scale_factor
        self.output_dir = create_path_handler(output_dir) if output_dir else Path.cwd()
        # Verbosity flags
        if isinstance(verbose, bool):
            self.verbose_level = 1 if verbose else 0
        else:
            self.verbose_level = int(verbose or 0)
        self.verbose_enabled = self.verbose_level >= 1 and not quiet
        self.very_verbose = self.verbose_level >= 2 and not quiet
        self.quiet = bool(quiet)

        # Base number of trips for scale_factor = 1.0
        self.base_trips = 1000000

        # Initialize random seed for reproducible data
        random.seed(42)

        # NYC geographic bounds (approximate)
        self.nyc_bounds = {
            "min_lat": 40.4774,
            "max_lat": 40.9176,
            "min_lon": -74.2591,
            "max_lon": -73.7004,
        }

        # Common pickup/dropoff location IDs (simulating taxi zones)
        self.location_ids = list(range(1, 264))  # NYC has 263 taxi zones

        # Vendor IDs
        self.vendor_ids = [1, 2]  # Creative Mobile Technologies, VeriFone Inc.

        # Rate codes
        self.rate_codes = [1, 2, 3, 4, 5, 6]  # Standard rate, JFK, Newark, Nassau
        # /Westchester, Negotiated, Group ride

        # Payment types
        self.payment_types = [1, 2, 3, 4]  # Credit card, Cash, No charge, Dispute

        self._manifest_row_counts: dict[str, int] = {}

    def generate_data(self, tables: list[str] | None = None) -> dict[str, str]:
        """Generate H2O DB data files.

        Args:
            tables: Optional list of table names to generate. If None, generates all.

        Returns:
            Dictionary mapping table names to file paths
        """
        # Use centralized cloud/local generation handler
        table_paths = self._handle_cloud_or_local_generation(
            self.output_dir,
            lambda output_dir: self._generate_data_local(output_dir, tables),
            False,  # verbose=False for H2ODB
        )
        self._write_manifest(table_paths)

        return {table: str(path) for table, path in table_paths.items()}

    def _generate_data_local(self, output_dir: Path, tables: list[str] | None = None) -> dict[str, str]:
        """Generate data locally (original implementation)."""
        if tables is None:
            tables = ["trips"]

        # Temporarily modify instance output_dir to use provided output_dir
        original_output_dir = self.output_dir
        self.output_dir = output_dir
        try:
            self.output_dir.mkdir(parents=True, exist_ok=True)

            file_paths: dict[str, Path] = {}
            self._manifest_row_counts = {}

            if "trips" in tables:
                file_paths["trips"] = self._generate_trips_data()

            # Print compression report if enabled
            if self.should_use_compression() and file_paths:
                self.print_compression_report(file_paths)

            return {table: str(path) for table, path in file_paths.items()}
        finally:
            # Restore original output_dir
            self.output_dir = original_output_dir

    def _generate_trips_data(self) -> PathLike:
        """Generate the trips table data."""
        filename = self.get_compressed_filename("trips.tbl")
        file_path = self.output_dir / filename
        num_trips = int(self.base_trips * self.scale_factor)

        # Date range: 2015-2019 (5 years of data)
        start_date = datetime(2015, 1, 1)
        end_date = datetime(2019, 12, 31)
        total_days = (end_date - start_date).days

        with self.open_output_file(file_path, "wt") as f:
            writer = csv.writer(f, delimiter="|")

            for _ in range(num_trips):
                # Generate pickup datetime
                random_days = random.randint(0, total_days)
                pickup_date = start_date + timedelta(days=random_days)

                # Add realistic time distribution (more trips during day)
                hour_weights = [
                    0.02,
                    0.01,
                    0.01,
                    0.01,
                    0.02,
                    0.03,
                    0.05,
                    0.07,  # 0-7
                    0.08,
                    0.09,
                    0.09,
                    0.08,
                    0.08,
                    0.08,
                    0.08,
                    0.09,  # 8-15
                    0.10,
                    0.11,
                    0.10,
                    0.09,
                    0.08,
                    0.06,
                    0.04,
                    0.03,  # 16-23
                ]

                hour = random.choices(range(24), weights=hour_weights)[0]
                minute = random.randint(0, 59)
                second = random.randint(0, 59)

                pickup_datetime = pickup_date.replace(hour=hour, minute=minute, second=second)

                # Generate trip duration (5 minutes to 2 hours)
                trip_duration_minutes = random.randint(5, 120)
                dropoff_datetime = pickup_datetime + timedelta(minutes=trip_duration_minutes)

                # Basic trip attributes
                vendor_id = random.choice(self.vendor_ids)
                passenger_count = random.choices([1, 2, 3, 4, 5, 6], weights=[0.7, 0.15, 0.08, 0.04, 0.02, 0.01])[0]

                # Generate realistic coordinates within NYC bounds
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

                # Calculate approximate distance (simplified)
                lat_diff = abs(dropoff_latitude - pickup_latitude)
                lon_diff = abs(dropoff_longitude - pickup_longitude)
                trip_distance = round(((lat_diff**2 + lon_diff**2) ** 0.5) * 69, 2)  # Rough miles
                trip_distance = max(0.1, min(trip_distance, 50.0))  # Cap values

                rate_code_id = random.choice(self.rate_codes)
                store_and_fwd_flag = random.choices(["Y", "N"], weights=[0.05, 0.95])[0]

                # Location IDs
                pickup_location_id = random.choice(self.location_ids)
                dropoff_location_id = random.choice(self.location_ids)

                # Payment calculations
                payment_type = random.choice(self.payment_types)

                # Base fare calculation (roughly $2.50 + $0.50 per 1/5 mile)
                base_fare = 2.50 + (trip_distance * 2.50)
                fare_amount = round(max(base_fare, 2.50), 2)

                # Additional charges
                extra = round(random.choice([0.0, 0.50, 1.0]), 2)  # Rush hour,
                # overnight
                mta_tax = 0.50  # Standard MTA tax

                # Tip (usually for credit card payments)
                if payment_type == 1:  # Credit card
                    tip_amount = round(fare_amount * random.uniform(0.10, 0.25), 2)
                else:
                    tip_amount = 0.0

                tolls_amount = round(random.choices([0.0, 5.54, 8.50], weights=[0.9, 0.07, 0.03])[0], 2)
                improvement_surcharge = 0.30  # Standard improvement surcharge
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
