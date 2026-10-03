# Copyright 2026 Joe Harris / BenchBox Project

# Licensed under the MIT License. See LICENSE file in the project root for details.

import random
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional, Union

from benchbox.core.manifest_utils import write_delimited_manifest
from benchbox.utils.cloud_storage import CloudStorageGeneratorMixin, create_path_handler
from benchbox.utils.compression_mixin import CompressionMixin

if TYPE_CHECKING:
    from cloudpathlib import CloudPath


PathLike = Union[Path, "CloudPath"]


_CSV_LINE_TERMINATOR = "\r\n"


def quote_clickbench_field(value: Any, delimiter: str = "|") -> str:

    if value is None:
        return '""'
    text = value if isinstance(value, str) else str(value)
    if text == "":
        return '""'
    if any(char in text for char in (delimiter, '"', "\n", "\r")):
        return '"' + text.replace('"', '""') + '"'
    return text


def format_clickbench_row(record: list, delimiter: str = "|") -> str:

    return delimiter.join(quote_clickbench_field(value, delimiter) for value in record) + _CSV_LINE_TERMINATOR


class ClickBenchDataGenerator(CompressionMixin, CloudStorageGeneratorMixin):
    def __init__(self, scale_factor: float = 1.0, output_dir: Optional[Path] = None, **kwargs) -> None:

        super().__init__(**kwargs)

        self.scale_factor = scale_factor
        self.output_dir = create_path_handler(output_dir) if output_dir else Path.cwd()

        self.base_records = int(1_000_000 * scale_factor)

        self._init_data_distributions()

        self._table_row_counts: dict[str, int] = {}

    def _init_data_distributions(self) -> None:

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
        ] + [""] * 50

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
        ] + [""] * 20

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

        self.referers = [
            "",
            "https://google.com/",
            "https://facebook.com/",
            "https://twitter.com/",
            "https://linkedin.com/",
            "https://reddit.com/",
            "https://stackoverflow.com/",
        ] + [""] * 10

        self.browser_languages = ["en", "ru", "zh", "es", "fr", "de", "ja", "pt"]
        self.browser_countries = ["US", "RU", "CN", "DE", "GB", "FR", "IN", "BR"]

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

        table_paths = self._handle_cloud_or_local_generation(
            self.output_dir,
            lambda output_dir: self._generate_data_local(output_dir, tables),
            False,
        )

        self._write_manifest(table_paths)

        return {table: str(path) for table, path in table_paths.items()}

    def _generate_data_local(self, output_dir: Path, tables: Optional[list[str]] = None) -> dict[str, Path]:

        random.seed(42)
        if tables is None:
            tables = ["hits"]

        if "hits" not in tables:
            tables = ["hits"]

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

            if self.should_use_compression() and file_paths:
                self.print_compression_report(file_paths)

            return file_paths
        finally:
            self.output_dir = original_output_dir

    def _generate_hits_data(self) -> tuple[PathLike, int]:

        filename = self.get_compressed_filename("hits.csv")
        file_path = self.output_dir / filename

        base_time = datetime(2013, 7, 1)

        with self.open_output_file(file_path, "wt") as f:
            for i in range(self.base_records):
                event_time = base_time + timedelta(
                    days=random.randint(0, 30),
                    hours=random.randint(0, 23),
                    minutes=random.randint(0, 59),
                    seconds=random.randint(0, 59),
                )

                record = self._generate_hit_record(i, event_time)
                f.write(format_clickbench_row(record))

        return file_path, self.base_records

    def _generate_hit_record(self, index: int, event_time: datetime) -> list:

        user_id = random.randint(1, 1000000)
        session_id = random.randint(1, 10000000)

        region_id = random.randint(1, 1000)

        resolution = random.choice(self.resolutions)

        is_mobile = random.choice([0, 1])
        mobile_phone = 1 if is_mobile else 0
        mobile_model = random.choice(self.mobile_models) if is_mobile else ""

        url = random.choice(self.urls)
        title = random.choice(self.titles)
        referer = random.choice(self.referers)
        search_phrase = random.choice(self.search_phrases)

        record = [
            session_id,
            random.choice([0, 1]),
            title,
            1,
            event_time.strftime("%Y-%m-%d %H:%M:%S"),
            event_time.strftime("%Y-%m-%d"),
            random.randint(1, 1000),
            random.randint(1, 4294967295),
            region_id,
            user_id,
            0,
            random.randint(1, 50),
            random.randint(1, 1000),
            url,
            referer,
            random.choice([0, 1]),
            random.randint(0, 100),
            region_id,
            random.randint(0, 100),
            region_id,
            resolution[0],
            resolution[1],
            random.choice([16, 24, 32]),
            random.randint(0, 20),
            random.randint(0, 20),
            "",
            random.randint(0, 10),
            random.randint(0, 20),
            random.randint(1, 100),
            "",
            random.choice([0, 1]),
            random.choice([0, 1]),
            is_mobile,
            mobile_phone,
            mobile_model,
            "",
            random.randint(1, 65535),
            random.randint(-1, 10),
            random.randint(0, 50),
            search_phrase,
            random.randint(0, 20),
            random.choice([0, 1]),
            resolution[0],
            resolution[1],
            random.randint(-12, 12),
            event_time.strftime("%Y-%m-%d %H:%M:%S"),
            random.randint(0, 5),
            random.randint(0, 50),
            random.randint(0, 50000),
            random.randint(0, 100),
            "UTF-8",
            random.randint(1, 1000),
            random.choice([0, 1]),
            random.choice([0, 1]),
            random.choice([0, 1]),
            random.randint(1, 999999999999999999),
            url,
            random.randint(1, 2147483647),
            random.choice([0, 1]),
            random.choice([0, 1]),
            random.choice([0, 1]),
            random.choice([0, 1]),
            random.choice([0, 1]),
            random.choice(["S", "F"]),
            event_time.strftime("%Y-%m-%d %H:%M:%S"),
            random.randint(18, 65),
            random.choice([0, 1, 2]),
            random.randint(0, 10),
            random.randint(0, 65535),
            random.randint(0, 255),
            random.randint(1, 4294967295),
            random.randint(1, 2147483647),
            random.randint(1, 2147483647),
            random.randint(1, 100),
            random.choice(self.browser_languages),
            random.choice(self.browser_countries),
            "",
            "",
            random.choice([0, 200, 404, 500]),
            random.randint(0, 10000),
            random.randint(0, 1000),
            random.randint(0, 5000),
            random.randint(0, 10000),
            random.randint(0, 15000),
            random.randint(0, 20000),
            random.randint(0, 50),
            "",
            random.randint(0, 1000000),
            "",
            random.choice(["USD", "EUR", "RUB", ""]),
            random.randint(0, 10),
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            random.choice([0, 1]),
            random.randint(1, 9223372036854775807),
            random.randint(1, 9223372036854775807),
            random.randint(0, 2147483647),
        ]

        return record

    def _write_manifest(self, table_paths: dict[str, Path]) -> None:

        write_delimited_manifest(
            self, "clickbench", table_paths, self._table_row_counts, null_marker="__NULL__", quote='"'
        )
