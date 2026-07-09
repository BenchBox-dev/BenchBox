"""ClickBench data generation.

This module provides functionality to generate synthetic web analytics data
that mimics the ClickBench dataset structure and distributions.

The generated data represents web analytics logs with realistic patterns for:
- User sessions and behavior
- Browser and device information
- Referrer and search data
- Geographic and demographic attributes
- Technical performance metrics

Note: The actual ClickBench benchmark uses a specific dataset with 99,997,497 records
derived from real web analytics data. This generator creates similar synthetic data
for testing and development purposes.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import csv
import random
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Optional, Union

from benchbox.core.manifest_utils import write_generator_manifest
from benchbox.utils.cloud_storage import CloudStorageGeneratorMixin, create_path_handler
from benchbox.utils.compression_mixin import CompressionMixin

if TYPE_CHECKING:
    from cloudpathlib import CloudPath

# Type alias for paths that could be local or cloud
PathLike = Union[Path, "CloudPath"]


class ClickBenchDataGenerator(CompressionMixin, CloudStorageGeneratorMixin):
    """Generator for ClickBench-style web analytics data."""

    def __init__(self, scale_factor: float = 1.0, output_dir: Optional[Path] = None, **kwargs) -> None:
        """Initialize the ClickBench data generator.

        Args:
            scale_factor: Scale factor for data generation (1.0 = ~1M records for testing)
            output_dir: Directory to output generated files
            **kwargs: Additional arguments including compression options
        """
        # Initialize compression mixin
        super().__init__(**kwargs)

        self.scale_factor = scale_factor
        self.output_dir = create_path_handler(output_dir) if output_dir else Path.cwd()

        # Base record counts (scaled down from actual ClickBench for testing)
        self.base_records = int(1_000_000 * scale_factor)  # 1M records at scale 1.0

        # Pre-generate some realistic data distributions
        self._init_data_distributions()

        # Row counts tracked for manifest emission
        self._table_row_counts: dict[str, int] = {}

    def _init_data_distributions(self) -> None:
        """Initialize realistic data distributions for web analytics."""

        # Sample search phrases
        self.search_phrases = [
            "",
            "google",
            "facebook",
            "youtube",
            "amazon",
            "news",
            "weather",
            "sports",
            "shopping",
            "travel",
            "music",
            "movies",
            "games",
            "finance",
            "health",
            "education",
            "technology",
            "business",
        ] + [""] * 50  # Most entries are empty

        # Sample mobile phone models
        self.mobile_models = [
            "",
            "iPhone",
            "Samsung Galaxy",
            "Google Pixel",
            "OnePlus",
            "Huawei",
            "Xiaomi",
            "LG",
            "Sony",
            "Nokia",
        ] + [""] * 20  # Most entries are empty

        # Sample URLs
        self.urls = [
            "https://example.com/",
            "https://example.com/home",
            "https://example.com/about",
            "https://example.com/products",
            "https://example.com/contact",
            "https://google.com/search",
            "https://facebook.com/feed",
            "https://youtube.com/watch",
        ]

        # Sample page titles
        self.titles = [
            "Home Page",
            "About Us",
            "Products",
            "Services",
            "Contact",
            "News",
            "Blog",
            "Support",
            "Login",
            "Register",
            "Search Results",
            "Product Details",
            "Shopping Cart",
        ]

        # Sample referers
        self.referers = [
            "",
            "https://google.com/",
            "https://facebook.com/",
            "https://twitter.com/",
            "https://linkedin.com/",
            "https://reddit.com/",
            "https://stackoverflow.com/",
        ] + [""] * 10  # Many entries are empty

        # Sample browser languages and countries
        self.browser_languages = ["en", "ru", "zh", "es", "fr", "de", "ja", "pt"]
        self.browser_countries = ["US", "RU", "CN", "DE", "GB", "FR", "IN", "BR"]

        # Resolution distributions (common screen resolutions)
        self.resolutions = [
            (1920, 1080),
            (1366, 768),
            (1280, 720),
            (1440, 900),
            (1024, 768),
            (1600, 900),
            (1280, 1024),
            (1920, 1200),
        ]

    def generate_data(self, tables: Optional[list[str]] = None) -> dict[str, str]:
        """Generate ClickBench data files.

        Args:
            tables: List of tables to generate (only 'hits' is supported)

        Returns:
            Dictionary mapping table names to file paths
        """
        # Use centralized cloud/local generation handler
        table_paths = self._handle_cloud_or_local_generation(
            self.output_dir,
            lambda output_dir: self._generate_data_local(output_dir, tables),
            False,  # verbose=False for ClickBench
        )

        self._write_manifest(table_paths)

        return {table: str(path) for table, path in table_paths.items()}

    def _generate_data_local(self, output_dir: Path, tables: Optional[list[str]] = None) -> dict[str, Path]:
        """Generate data locally (original implementation)."""
        # Seed for reproducible data (SSBDataGenerator seeds similarly). Without
        # this the `random.*` row values differ every run, making top-N /
        # tie-sensitive queries (e.g. the cross-surface equivalence gate)
        # non-deterministic. Seeded per generation call so reused generator
        # instances still produce identical data; like the other generators this
        # seeds the module-global RNG.
        random.seed(42)
        if tables is None:
            tables = ["hits"]

        if "hits" not in tables:
            tables = ["hits"]  # ClickBench only has one table

        # Temporarily modify instance output_dir to use provided output_dir
        original_output_dir = self.output_dir
        self.output_dir = output_dir
        try:
            self.output_dir.mkdir(parents=True, exist_ok=True)

            file_paths: dict[str, Path] = {}
            self._table_row_counts = {}

            if "hits" in tables:
                path, count = self._generate_hits_data()
                file_paths["hits"] = path
                self._table_row_counts["hits"] = count

            # Print compression report if enabled
            if self.should_use_compression() and file_paths:
                self.print_compression_report(file_paths)

            return file_paths
        finally:
            # Restore original output_dir
            self.output_dir = original_output_dir

    def _generate_hits_data(self) -> tuple[PathLike, int]:
        """Generate the main hits table data.

        Returns:
            Tuple of (path to generated hits.csv file, number of records)
        """
        filename = self.get_compressed_filename("hits.csv")
        file_path = self.output_dir / filename

        # Generate realistic base timestamp
        base_time = datetime(2013, 7, 1)  # ClickBench data is from July 2013

        with self.open_output_file(file_path, "wt") as f:
            writer = csv.writer(f, delimiter="|")

            for i in range(self.base_records):
                # Generate event time within the month
                event_time = base_time + timedelta(
                    days=random.randint(0, 30),
                    hours=random.randint(0, 23),
                    minutes=random.randint(0, 59),
                    seconds=random.randint(0, 59),
                )

                # Generate realistic web analytics record
                record = self._generate_hit_record(i, event_time)
                writer.writerow(record)

        return file_path, self.base_records

    def _generate_hit_record(self, index: int, event_time: datetime) -> list:
        """Generate a single hit record.

        Args:
            index: Record index for generating unique IDs
            event_time: Event timestamp

        Returns:
            List of field values for the record
        """
        # Generate correlated user session data
        user_id = random.randint(1, 1000000)
        session_id = random.randint(1, 10000000)

        # Geographic data (correlated)
        region_id = random.randint(1, 1000)

        # Resolution (pick from common resolutions)
        resolution = random.choice(self.resolutions)

        # Browser and device info
        is_mobile = random.choice([0, 1])
        mobile_phone = 1 if is_mobile else 0
        mobile_model = random.choice(self.mobile_models) if is_mobile else ""

        # Web analytics data
        url = random.choice(self.urls)
        title = random.choice(self.titles)
        referer = random.choice(self.referers)
        search_phrase = random.choice(self.search_phrases)

        # Generate the complete record (105 fields)
        record = [
            session_id,  # WatchID
            random.choice([0, 1]),  # JavaEnable
            title,  # Title
            1,  # GoodEvent
            event_time.strftime("%Y-%m-%d %H:%M:%S"),  # EventTime
            event_time.strftime("%Y-%m-%d"),  # EventDate
            random.randint(1, 1000),  # CounterID
            random.randint(1, 4294967295),  # ClientIP
            region_id,  # RegionID
            user_id,  # UserID
            0,  # CounterClass
            random.randint(1, 50),  # OS
            random.randint(1, 1000),  # UserAgent
            url,  # URL
            referer,  # Referer
            random.choice([0, 1]),  # IsRefresh
            random.randint(0, 100),  # RefererCategoryID
            region_id,  # RefererRegionID
            random.randint(0, 100),  # URLCategoryID
            region_id,  # URLRegionID
            resolution[0],  # ResolutionWidth
            resolution[1],  # ResolutionHeight
            random.choice([16, 24, 32]),  # ResolutionDepth
            random.randint(0, 20),  # FlashMajor
            random.randint(0, 20),  # FlashMinor
            "",  # FlashMinor2
            random.randint(0, 10),  # NetMajor
            random.randint(0, 20),  # NetMinor
            random.randint(1, 100),  # UserAgentMajor
            "",  # UserAgentMinor
            random.choice([0, 1]),  # CookieEnable
            random.choice([0, 1]),  # JavascriptEnable
            is_mobile,  # IsMobile
            mobile_phone,  # MobilePhone
            mobile_model,  # MobilePhoneModel
            "",  # Params
            random.randint(1, 65535),  # IPNetworkID
            random.randint(-1, 10),  # TraficSourceID
            random.randint(0, 50),  # SearchEngineID
            search_phrase,  # SearchPhrase
            random.randint(0, 20),  # AdvEngineID
            random.choice([0, 1]),  # IsArtifical
            resolution[0],  # WindowClientWidth
            resolution[1],  # WindowClientHeight
            random.randint(-12, 12),  # ClientTimeZone
            event_time.strftime("%Y-%m-%d %H:%M:%S"),  # ClientEventTime
            random.randint(0, 5),  # SilverlightVersion1
            random.randint(0, 50),  # SilverlightVersion2
            random.randint(0, 50000),  # SilverlightVersion3
            random.randint(0, 100),  # SilverlightVersion4
            "UTF-8",  # PageCharset
            random.randint(1, 1000),  # CodeVersion
            random.choice([0, 1]),  # IsLink
            random.choice([0, 1]),  # IsDownload
            random.choice([0, 1]),  # IsNotBounce
            random.randint(1, 999999999999999999),  # FUniqID
            url,  # OriginalURL
            random.randint(1, 2147483647),  # HID
            random.choice([0, 1]),  # IsOldCounter
            random.choice([0, 1]),  # IsEvent
            random.choice([0, 1]),  # IsParameter
            random.choice([0, 1]),  # DontCountHits
            random.choice([0, 1]),  # WithHash
            random.choice(["S", "F"]),  # HitColor
            event_time.strftime("%Y-%m-%d %H:%M:%S"),  # LocalEventTime
            random.randint(18, 65),  # Age
            random.choice([0, 1, 2]),  # Sex
            random.randint(0, 10),  # Income
            random.randint(0, 65535),  # Interests
            random.randint(0, 255),  # Robotness
            random.randint(1, 4294967295),  # RemoteIP
            random.randint(1, 2147483647),  # WindowName
            random.randint(1, 2147483647),  # OpenerName
            random.randint(1, 100),  # HistoryLength
            random.choice(self.browser_languages),  # BrowserLanguage
            random.choice(self.browser_countries),  # BrowserCountry
            "",  # SocialNetwork
            "",  # SocialAction
            random.choice([0, 200, 404, 500]),  # HTTPError
            random.randint(0, 10000),  # SendTiming
            random.randint(0, 1000),  # DNSTiming
            random.randint(0, 5000),  # ConnectTiming
            random.randint(0, 10000),  # ResponseStartTiming
            random.randint(0, 15000),  # ResponseEndTiming
            random.randint(0, 20000),  # FetchTiming
            random.randint(0, 50),  # SocialSourceNetworkID
            "",  # SocialSourcePage
            random.randint(0, 1000000),  # ParamPrice
            "",  # ParamOrderID
            random.choice(["USD", "EUR", "RUB", ""]),  # ParamCurrency
            random.randint(0, 10),  # ParamCurrencyID
            "",  # OpenstatServiceName
            "",  # OpenstatCampaignID
            "",  # OpenstatAdID
            "",  # OpenstatSourceID
            "",  # UTMSource
            "",  # UTMMedium
            "",  # UTMCampaign
            "",  # UTMContent
            "",  # UTMTerm
            "",  # FromTag
            random.choice([0, 1]),  # HasGCLID
            random.randint(1, 9223372036854775807),  # RefererHash
            random.randint(1, 9223372036854775807),  # URLHash
            random.randint(0, 2147483647),  # CLID
        ]

        return record

    def _write_manifest(self, table_paths: dict[str, Path]) -> None:
        """Write manifest describing generated ClickBench dataset."""
        write_generator_manifest(
            self,
            "clickbench",
            table_paths,
            self._table_row_counts,
            metadata={"csv_delimiter": "|", "csv_null_marker": None},
        )
