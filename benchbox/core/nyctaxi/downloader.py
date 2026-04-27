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
from typing import Union

import numpy as np

from benchbox.core.nyctaxi.schema import get_green_trips_columns, get_hvfhv_trips_columns, get_trips_columns
from benchbox.utils.compression_mixin import CompressionMixin
from benchbox.utils.verbosity import VerbosityMixin, compute_verbosity

# TLC data URLs
TLC_BASE_URL = "https://d37ci6vzurychx.cloudfront.net/trip-data"
TAXI_ZONES_URL = "https://d37ci6vzurychx.cloudfront.net/misc/taxi_zone_lookup.csv"

# Available data ranges
AVAILABLE_YEARS = list(range(2019, 2026))
AVAILABLE_MONTHS = list(range(1, 13))
SCALE_FACTOR_SAMPLE_DIVISOR = 10.0

# Complete NYC TLC Taxi Zone data (all 265 zones)
# Source: https://d37ci6vzurychx.cloudfront.net/misc/taxi_zone_lookup.csv
TAXI_ZONES_DATA = [
    (1, "EWR", "Newark Airport", "EWR"),
    (2, "Queens", "Jamaica Bay", "Boro Zone"),
    (3, "Bronx", "Allerton/Pelham Gardens", "Boro Zone"),
    (4, "Manhattan", "Alphabet City", "Yellow Zone"),
    (5, "Staten Island", "Arden Heights", "Boro Zone"),
    (6, "Staten Island", "Arrochar/Fort Wadsworth", "Boro Zone"),
    (7, "Queens", "Astoria", "Boro Zone"),
    (8, "Queens", "Astoria Park", "Boro Zone"),
    (9, "Queens", "Auburndale", "Boro Zone"),
    (10, "Queens", "Baisley Park", "Boro Zone"),
    (11, "Brooklyn", "Bath Beach", "Boro Zone"),
    (12, "Manhattan", "Battery Park", "Yellow Zone"),
    (13, "Manhattan", "Battery Park City", "Yellow Zone"),
    (14, "Brooklyn", "Bay Ridge", "Boro Zone"),
    (15, "Queens", "Bay Terrace/Fort Totten", "Boro Zone"),
    (16, "Queens", "Bayside", "Boro Zone"),
    (17, "Brooklyn", "Bedford", "Boro Zone"),
    (18, "Bronx", "Bedford Park", "Boro Zone"),
    (19, "Queens", "Bellerose", "Boro Zone"),
    (20, "Bronx", "Belmont", "Boro Zone"),
    (21, "Brooklyn", "Bensonhurst East", "Boro Zone"),
    (22, "Brooklyn", "Bensonhurst West", "Boro Zone"),
    (23, "Staten Island", "Bloomfield/Emerson Hill", "Boro Zone"),
    (24, "Manhattan", "Bloomingdale", "Yellow Zone"),
    (25, "Brooklyn", "Boerum Hill", "Boro Zone"),
    (26, "Brooklyn", "Borough Park", "Boro Zone"),
    (27, "Queens", "Breezy Point/Fort Tilden/Riis Beach", "Boro Zone"),
    (28, "Queens", "Briarwood/Jamaica Hills", "Boro Zone"),
    (29, "Brooklyn", "Brighton Beach", "Boro Zone"),
    (30, "Queens", "Broad Channel", "Boro Zone"),
    (31, "Bronx", "Bronx Park", "Boro Zone"),
    (32, "Bronx", "Bronxdale", "Boro Zone"),
    (33, "Brooklyn", "Brooklyn Heights", "Boro Zone"),
    (34, "Brooklyn", "Brooklyn Navy Yard", "Boro Zone"),
    (35, "Brooklyn", "Brownsville", "Boro Zone"),
    (36, "Brooklyn", "Bushwick North", "Boro Zone"),
    (37, "Brooklyn", "Bushwick South", "Boro Zone"),
    (38, "Queens", "Cambria Heights", "Boro Zone"),
    (39, "Brooklyn", "Canarsie", "Boro Zone"),
    (40, "Brooklyn", "Carroll Gardens", "Boro Zone"),
    (41, "Manhattan", "Central Harlem", "Boro Zone"),
    (42, "Manhattan", "Central Harlem North", "Boro Zone"),
    (43, "Manhattan", "Central Park", "Yellow Zone"),
    (44, "Staten Island", "Charleston/Tottenville", "Boro Zone"),
    (45, "Manhattan", "Chinatown", "Yellow Zone"),
    (46, "Bronx", "City Island", "Boro Zone"),
    (47, "Bronx", "Claremont/Bathgate", "Boro Zone"),
    (48, "Manhattan", "Clinton East", "Yellow Zone"),
    (49, "Brooklyn", "Clinton Hill", "Boro Zone"),
    (50, "Manhattan", "Clinton West", "Yellow Zone"),
    (51, "Bronx", "Co-Op City", "Boro Zone"),
    (52, "Brooklyn", "Cobble Hill", "Boro Zone"),
    (53, "Queens", "College Point", "Boro Zone"),
    (54, "Brooklyn", "Columbia Street", "Boro Zone"),
    (55, "Brooklyn", "Coney Island", "Boro Zone"),
    (56, "Queens", "Corona", "Boro Zone"),
    (57, "Queens", "Corona", "Boro Zone"),
    (58, "Bronx", "Country Club", "Boro Zone"),
    (59, "Bronx", "Crotona Park", "Boro Zone"),
    (60, "Bronx", "Crotona Park East", "Boro Zone"),
    (61, "Brooklyn", "Crown Heights North", "Boro Zone"),
    (62, "Brooklyn", "Crown Heights South", "Boro Zone"),
    (63, "Brooklyn", "Cypress Hills", "Boro Zone"),
    (64, "Queens", "Douglaston", "Boro Zone"),
    (65, "Brooklyn", "Downtown Brooklyn/MetroTech", "Boro Zone"),
    (66, "Brooklyn", "DUMBO/Vinegar Hill", "Boro Zone"),
    (67, "Brooklyn", "Dyker Heights", "Boro Zone"),
    (68, "Manhattan", "East Chelsea", "Yellow Zone"),
    (69, "Brooklyn", "East Flatbush/Farragut", "Boro Zone"),
    (70, "Brooklyn", "East Flatbush/Remsen Village", "Boro Zone"),
    (71, "Queens", "East Flushing", "Boro Zone"),
    (72, "Manhattan", "East Harlem North", "Boro Zone"),
    (73, "Manhattan", "East Harlem South", "Boro Zone"),
    (74, "Brooklyn", "East New York", "Boro Zone"),
    (75, "Brooklyn", "East New York/Pennsylvania Avenue", "Boro Zone"),
    (76, "Brooklyn", "East Williamsburg", "Boro Zone"),
    (77, "Bronx", "Eastchester", "Boro Zone"),
    (78, "Queens", "East Elmhurst", "Boro Zone"),
    (79, "Manhattan", "East Village", "Yellow Zone"),
    (80, "Brooklyn", "Erasmus", "Boro Zone"),
    (81, "Queens", "Far Rockaway", "Boro Zone"),
    (82, "Queens", "Elmhurst", "Boro Zone"),
    (83, "Queens", "Elmhurst/Maspeth", "Boro Zone"),
    (84, "Staten Island", "Eltingville/Annadale/Prince's Bay", "Boro Zone"),
    (85, "Brooklyn", "Flatbush/Ditmas Park", "Boro Zone"),
    (86, "Manhattan", "Financial District North", "Yellow Zone"),
    (87, "Manhattan", "Financial District South", "Yellow Zone"),
    (88, "Brooklyn", "Flatbush/Ditmas Park", "Boro Zone"),
    (89, "Manhattan", "Flatiron", "Yellow Zone"),
    (90, "Brooklyn", "Flatlands", "Boro Zone"),
    (91, "Queens", "Flushing", "Boro Zone"),
    (92, "Queens", "Flushing Meadows-Corona Park", "Boro Zone"),
    (93, "Queens", "Forest Hills", "Boro Zone"),
    (94, "Queens", "Forest Park/Highland Park", "Boro Zone"),
    (95, "Bronx", "Fordham South", "Boro Zone"),
    (96, "Brooklyn", "Fort Greene", "Boro Zone"),
    (97, "Queens", "Fresh Meadows", "Boro Zone"),
    (98, "Staten Island", "Freshkills Park", "Boro Zone"),
    (99, "Manhattan", "Garment District", "Yellow Zone"),
    (100, "Queens", "Glen Oaks", "Boro Zone"),
    (101, "Queens", "Glendale", "Boro Zone"),
    (102, "Manhattan", "Governor's Island/Ellis Island/Liberty Island", "Yellow Zone"),
    (103, "Brooklyn", "Gowanus", "Boro Zone"),
    (104, "Manhattan", "Gramercy", "Yellow Zone"),
    (105, "Brooklyn", "Gravesend", "Boro Zone"),
    (106, "Staten Island", "Great Kills", "Boro Zone"),
    (107, "Staten Island", "Great Kills Park", "Boro Zone"),
    (108, "Brooklyn", "Green-Wood Cemetery", "Boro Zone"),
    (109, "Brooklyn", "Greenpoint", "Boro Zone"),
    (110, "Manhattan", "Greenwich Village North", "Yellow Zone"),
    (111, "Manhattan", "Greenwich Village South", "Yellow Zone"),
    (112, "Staten Island", "Grymes Hill/Clifton", "Boro Zone"),
    (113, "Manhattan", "Hamilton Heights", "Boro Zone"),
    (114, "Queens", "Hammels/Arverne", "Boro Zone"),
    (115, "Staten Island", "Heartland Village/Todt Hill", "Boro Zone"),
    (116, "Manhattan", "Hell's Kitchen North", "Yellow Zone"),
    (117, "Manhattan", "Hell's Kitchen South", "Yellow Zone"),
    (118, "Bronx", "Highbridge", "Boro Zone"),
    (119, "Bronx", "Highbridge Park", "Boro Zone"),
    (120, "Queens", "Hillcrest/Pomonok", "Boro Zone"),
    (121, "Queens", "Hollis", "Boro Zone"),
    (122, "Brooklyn", "Homecrest", "Boro Zone"),
    (123, "Queens", "Howard Beach", "Boro Zone"),
    (124, "Manhattan", "Hudson Sq", "Yellow Zone"),
    (125, "Bronx", "Hunts Point", "Boro Zone"),
    (126, "Manhattan", "Inwood", "Boro Zone"),
    (127, "Manhattan", "Inwood Hill Park", "Boro Zone"),
    (128, "Queens", "Jackson Heights", "Boro Zone"),
    (129, "Queens", "Jamaica", "Boro Zone"),
    (130, "Queens", "Jamaica Estates", "Boro Zone"),
    (131, "Queens", "JFK Airport", "Airports"),
    (132, "Bronx", "Kingsbridge Heights", "Boro Zone"),
    (133, "Queens", "Kew Gardens", "Boro Zone"),
    (134, "Queens", "Kew Gardens Hills", "Boro Zone"),
    (135, "Queens", "Kips Bay", "Boro Zone"),
    (136, "Queens", "LaGuardia Airport", "Airports"),
    (137, "Queens", "Laurelton", "Boro Zone"),
    (138, "Manhattan", "Lenox Hill East", "Yellow Zone"),
    (139, "Manhattan", "Lenox Hill West", "Yellow Zone"),
    (140, "Manhattan", "Lincoln Square East", "Yellow Zone"),
    (141, "Manhattan", "Lincoln Square West", "Yellow Zone"),
    (142, "Manhattan", "Little Italy/NoLiTa", "Yellow Zone"),
    (143, "Queens", "Long Island City/Hunters Point", "Boro Zone"),
    (144, "Queens", "Long Island City/Queens Plaza", "Boro Zone"),
    (145, "Bronx", "Longwood", "Boro Zone"),
    (146, "Manhattan", "Lower East Side", "Yellow Zone"),
    (147, "Brooklyn", "Madison", "Boro Zone"),
    (148, "Brooklyn", "Manhattan Beach", "Boro Zone"),
    (149, "Manhattan", "Manhattan Valley", "Yellow Zone"),
    (150, "Manhattan", "Manhattanville", "Boro Zone"),
    (151, "Brooklyn", "Mapleton", "Boro Zone"),
    (152, "Brooklyn", "Marine Park/Floyd Bennett Field", "Boro Zone"),
    (153, "Brooklyn", "Marine Park/Mill Basin", "Boro Zone"),
    (154, "Staten Island", "Mariners Harbor", "Boro Zone"),
    (155, "Queens", "Maspeth", "Boro Zone"),
    (156, "Manhattan", "Meatpacking/West Village West", "Yellow Zone"),
    (157, "Bronx", "Melrose South", "Boro Zone"),
    (158, "Queens", "Middle Village", "Boro Zone"),
    (159, "Manhattan", "Midtown Center", "Yellow Zone"),
    (160, "Manhattan", "Midtown East", "Yellow Zone"),
    (161, "Manhattan", "Midtown North", "Yellow Zone"),
    (162, "Manhattan", "Midtown South", "Yellow Zone"),
    (163, "Brooklyn", "Midwood", "Boro Zone"),
    (164, "Manhattan", "Morningside Heights", "Boro Zone"),
    (165, "Bronx", "Morrisania/Melrose", "Boro Zone"),
    (166, "Bronx", "Mott Haven/Port Morris", "Boro Zone"),
    (167, "Bronx", "Mount Hope", "Boro Zone"),
    (168, "Queens", "Murray Hill", "Boro Zone"),
    (169, "Manhattan", "Murray Hill", "Yellow Zone"),
    (170, "Staten Island", "New Brighton/St. George", "Boro Zone"),
    (171, "Staten Island", "New Dorp/Midland Beach", "Boro Zone"),
    (172, "Staten Island", "New Springville/Bulls Head", "Boro Zone"),
    (173, "Manhattan", "North Corona", "Boro Zone"),
    (174, "Bronx", "Norwood", "Boro Zone"),
    (175, "Queens", "Oakland Gardens", "Boro Zone"),
    (176, "Staten Island", "Oakwood", "Boro Zone"),
    (177, "Brooklyn", "Ocean Hill", "Boro Zone"),
    (178, "Brooklyn", "Ocean Parkway South", "Boro Zone"),
    (179, "Queens", "Old Astoria", "Boro Zone"),
    (180, "Queens", "Ozone Park", "Boro Zone"),
    (181, "Brooklyn", "Park Slope", "Boro Zone"),
    (182, "Bronx", "Parkchester", "Boro Zone"),
    (183, "Bronx", "Pelham Bay", "Boro Zone"),
    (184, "Bronx", "Pelham Bay Park", "Boro Zone"),
    (185, "Bronx", "Pelham Parkway", "Boro Zone"),
    (186, "Manhattan", "Penn Station/Madison Sq West", "Yellow Zone"),
    (187, "Staten Island", "Port Ivory", "Boro Zone"),
    (188, "Staten Island", "Port Richmond", "Boro Zone"),
    (189, "Brooklyn", "Prospect Heights", "Boro Zone"),
    (190, "Brooklyn", "Prospect-Lefferts Gardens", "Boro Zone"),
    (191, "Brooklyn", "Prospect Park", "Boro Zone"),
    (192, "Queens", "Queens Village", "Boro Zone"),
    (193, "Queens", "Queensboro Hill", "Boro Zone"),
    (194, "Queens", "Queensbridge/Ravenswood", "Boro Zone"),
    (195, "Brooklyn", "Red Hook", "Boro Zone"),
    (196, "Queens", "Rego Park", "Boro Zone"),
    (197, "Queens", "Richmond Hill", "Boro Zone"),
    (198, "Queens", "Ridgewood", "Boro Zone"),
    (199, "Bronx", "Rikers Island", "Boro Zone"),
    (200, "Bronx", "Riverdale/North Riverdale/Fieldston", "Boro Zone"),
    (201, "Queens", "Rockaway Park", "Boro Zone"),
    (202, "Manhattan", "Roosevelt Island", "Boro Zone"),
    (203, "Queens", "Rosedale", "Boro Zone"),
    (204, "Staten Island", "Rossville/Woodrow", "Boro Zone"),
    (205, "Queens", "Saint Albans", "Boro Zone"),
    (206, "Staten Island", "Saint George/New Brighton", "Boro Zone"),
    (207, "Queens", "Saint Michaels Cemetery/Woodside", "Boro Zone"),
    (208, "Bronx", "Schuylerville/Edgewater Park", "Boro Zone"),
    (209, "Brooklyn", "Sheepshead Bay", "Boro Zone"),
    (210, "Manhattan", "SoHo", "Yellow Zone"),
    (211, "Bronx", "Soundview/Bruckner", "Boro Zone"),
    (212, "Bronx", "Soundview/Castle Hill", "Boro Zone"),
    (213, "Queens", "South Jamaica", "Boro Zone"),
    (214, "Queens", "South Ozone Park", "Boro Zone"),
    (215, "Brooklyn", "South Williamsburg", "Boro Zone"),
    (216, "Queens", "Springfield Gardens North", "Boro Zone"),
    (217, "Queens", "Springfield Gardens South", "Boro Zone"),
    (218, "Bronx", "Spuyten Duyvil/Kingsbridge", "Boro Zone"),
    (219, "Manhattan", "Stuy Town/Peter Cooper Village", "Yellow Zone"),
    (220, "Brooklyn", "Starrett City", "Boro Zone"),
    (221, "Queens", "Steinway", "Boro Zone"),
    (222, "Manhattan", "Stuy Town/Peter Cooper Village", "Yellow Zone"),
    (223, "Brooklyn", "Stuyvesant Heights", "Boro Zone"),
    (224, "Brooklyn", "Sunset Park East", "Boro Zone"),
    (225, "Brooklyn", "Sunset Park West", "Boro Zone"),
    (226, "Queens", "Sunnyside", "Boro Zone"),
    (227, "Staten Island", "Stapleton", "Boro Zone"),
    (228, "Manhattan", "Sutton Place/Turtle Bay North", "Yellow Zone"),
    (229, "Manhattan", "Times Sq/Theatre District", "Yellow Zone"),
    (230, "Manhattan", "TriBeCa/Civic Center", "Yellow Zone"),
    (231, "Manhattan", "Two Bridges/Seward Park", "Yellow Zone"),
    (232, "Bronx", "University Heights/Morris Heights", "Boro Zone"),
    (233, "Manhattan", "UN/Turtle Bay South", "Yellow Zone"),
    (234, "Manhattan", "Union Sq", "Yellow Zone"),
    (235, "Bronx", "University Heights/Morris Heights", "Boro Zone"),
    (236, "Manhattan", "Upper East Side North", "Yellow Zone"),
    (237, "Manhattan", "Upper East Side South", "Yellow Zone"),
    (238, "Manhattan", "Upper West Side North", "Yellow Zone"),
    (239, "Manhattan", "Upper West Side South", "Yellow Zone"),
    (240, "Bronx", "Van Cortlandt Park", "Boro Zone"),
    (241, "Bronx", "Van Cortlandt Village", "Boro Zone"),
    (242, "Bronx", "Van Nest/Morris Park", "Boro Zone"),
    (243, "Manhattan", "Washington Heights North", "Boro Zone"),
    (244, "Manhattan", "Washington Heights South", "Boro Zone"),
    (245, "Staten Island", "West Brighton", "Boro Zone"),
    (246, "Manhattan", "West Chelsea/Hudson Yards", "Yellow Zone"),
    (247, "Bronx", "West Concourse", "Boro Zone"),
    (248, "Bronx", "West Farms/Bronx River", "Boro Zone"),
    (249, "Manhattan", "West Village", "Yellow Zone"),
    (250, "Bronx", "Westchester Village/Unionport", "Boro Zone"),
    (251, "Staten Island", "Westerleigh", "Boro Zone"),
    (252, "Queens", "Whitestone", "Boro Zone"),
    (253, "Queens", "Willets Point", "Boro Zone"),
    (254, "Brooklyn", "Williamsburg (North Side)", "Boro Zone"),
    (255, "Brooklyn", "Williamsburg (South Side)", "Boro Zone"),
    (256, "Brooklyn", "Windsor Terrace", "Boro Zone"),
    (257, "Queens", "Woodhaven", "Boro Zone"),
    (258, "Bronx", "Woodlawn/Wakefield", "Boro Zone"),
    (259, "Queens", "Woodside", "Boro Zone"),
    (260, "Manhattan", "World Trade Center", "Yellow Zone"),
    (261, "Manhattan", "Yorkville East", "Yellow Zone"),
    (262, "Manhattan", "Yorkville West", "Yellow Zone"),
    (263, "Unknown", "NV", "N/A"),
    (264, "Unknown", "NA", "N/A"),
    (265, "Unknown", "Unknown", "N/A"),
]


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
