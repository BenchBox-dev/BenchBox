"""AMPLab Big Data Benchmark data generator.

This module generates synthetic web analytics data for the AMPLab benchmark,
including web page rankings, user visits, and document content.

The generator creates:
- RANKINGS table with page URLs and PageRank-style scores
- USERVISITS table with user interaction logs
- DOCUMENTS table with web page content

Data characteristics match the original AMPLab benchmark specification
for testing big data processing systems.

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


class AMPLabDataGenerator(CompressionMixin, CloudStorageGeneratorMixin):
    """Generator for AMPLab benchmark data."""

    def __init__(
        self,
        scale_factor: float = 1.0,
        output_dir: Path | None = None,
        *,
        verbose: int | bool = 0,
        quiet: bool = False,
        **kwargs,
    ) -> None:
        """Initialize the AMPLab data generator.

        Args:
            scale_factor: Scale factor for data generation (1.0 = standard size)
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

        # Data size constants (base sizes for scale_factor = 1.0)
        self.base_rankings = 100000  # 100K pages
        self.base_uservisits = 1000000  # 1M visits
        self.base_documents = 50000  # 50K documents

        # Initialize random seed for reproducible data
        random.seed(42)

        # Sample data for generation
        self._domains = [
            "example.com",
            "website.org",
            "portal.net",
            "site.co",
            "page.info",
            "blog.me",
            "news.tv",
            "shop.biz",
            "forum.us",
            "wiki.edu",
            "social.io",
            "tech.ai",
            "data.ml",
            "cloud.dev",
            "app.xyz",
        ]

        self._countries = [
            "USA",
            "CHN",
            "IND",
            "BRA",
            "RUS",
            "JPN",
            "DEU",
            "GBR",
            "FRA",
            "ITA",
            "CAN",
            "KOR",
            "ESP",
            "AUS",
            "MEX",
            "IDN",
            "NLD",
            "SAU",
            "TUR",
            "CHE",
        ]

        self._languages = [
            "en-US",
            "zh-CN",
            "hi-IN",
            "pt-BR",
            "ru-RU",
            "ja-JP",
            "de-DE",
            "en-GB",
            "fr-FR",
            "it-IT",
            "en-CA",
            "ko-KR",
            "es-ES",
            "en-AU",
        ]

        self._user_agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
            "Mozilla/5.0 (iPhone; CPU iPhone OS 14_7_1 like Mac OS X)",
            "Mozilla/5.0 (Android 11; Mobile; rv:68.0) Gecko/68.0 Firefox/88.0",
        ]

        self._search_words = [
            "database",
            "analytics",
            "web",
            "data",
            "search",
            "engine",
            "query",
            "information",
            "processing",
            "system",
            "technology",
            "software",
            "application",
            "service",
            "platform",
            "solution",
            "business",
            "science",
            "machine",
            "learning",
            "artificial",
            "intelligence",
        ]

        self._content_words = [
            "web",
            "data",
            "system",
            "information",
            "technology",
            "computer",
            "internet",
            "digital",
            "online",
            "software",
            "application",
            "service",
            "platform",
            "solution",
            "business",
            "analysis",
            "processing",
            "query",
            "database",
            "search",
            "engine",
            "algorithm",
            "machine",
            "learning",
        ]

        # Row counts captured during generation for manifest output
        self._table_row_counts: dict[str, int] = {}

    def generate_data(self, tables: list[str] | None = None) -> dict[str, str]:
        """Generate AMPLab data files.

        Args:
            tables: Optional list of table names to generate. If None, generates all.

        Returns:
            Dictionary mapping table names to file paths
        """
        # Use centralized cloud/local generation handler
        table_paths = self._handle_cloud_or_local_generation(
            self.output_dir,
            lambda output_dir: self._generate_data_local(output_dir, tables),
            False,  # verbose=False for AMPLab
        )

        # Persist manifest metadata for generated tables
        self._write_manifest(table_paths)

        # Convert Path-like objects to strings for compatibility with existing callers
        return {table: str(path) for table, path in table_paths.items()}

    def _generate_data_local(self, output_dir: Path, tables: list[str] | None = None) -> dict[str, Path]:
        """Generate data locally (original implementation)."""
        if tables is None:
            tables = ["rankings", "uservisits", "documents"]

        # Temporarily modify instance output_dir to use provided output_dir
        original_output_dir = self.output_dir
        self.output_dir = output_dir
        try:
            self.output_dir.mkdir(parents=True, exist_ok=True)

            file_paths: dict[str, Path] = {}
            self._table_row_counts = {}

            # Generate in dependency order
            if "rankings" in tables:
                path, count = self._generate_rankings_data()
                file_paths["rankings"] = path
                self._table_row_counts["rankings"] = count
            if "documents" in tables:
                path, count = self._generate_documents_data()
                file_paths["documents"] = path
                self._table_row_counts["documents"] = count
            if "uservisits" in tables:
                path, count = self._generate_uservisits_data()
                file_paths["uservisits"] = path
                self._table_row_counts["uservisits"] = count

            # Print compression report if enabled
            if self.should_use_compression() and file_paths:
                self.print_compression_report(file_paths)

            return file_paths
        finally:
            # Restore original output_dir
            self.output_dir = original_output_dir

    def _generate_url(self, url_id: int) -> str:
        """Generate a URL for a given ID."""
        domain = random.choice(self._domains)
        paths = ["page", "article", "post", "item", "content", "view"]
        path = random.choice(paths)
        return f"http://{domain}/{path}/{url_id}"

    def _generate_ip_address(self) -> str:
        """Generate a random IP address."""
        return f"{random.randint(1, 255)}.{random.randint(0, 255)}.{random.randint(0, 255)}.{random.randint(1, 254)}"

    def _generate_content(self, min_words: int = 50, max_words: int = 500) -> str:
        """Generate random content text."""
        num_words = random.randint(min_words, max_words)
        words = []
        for _ in range(num_words):
            words.append(random.choice(self._content_words))
        return " ".join(words)

    def _generate_rankings_data(self) -> tuple[PathLike, int]:
        """Generate the RANKINGS table data."""
        filename = self.get_compressed_filename("rankings.tbl")
        file_path = self.output_dir / filename
        num_rankings = int(self.base_rankings * self.scale_factor)

        with self.open_output_file(file_path, "wt") as f:
            writer = csv.writer(f, delimiter="|")

            for i in range(1, num_rankings + 1):
                page_url = self._generate_url(i)

                # Generate PageRank-style score (power law distribution)
                page_rank = int(random.paretovariate(1.16) * 10)  # Power law with alpha=1.16
                page_rank = max(1, min(page_rank, 10000))  # Cap between 1 and 10000

                # Average duration in seconds (30s to 10 minutes)
                avg_duration = random.randint(30, 600)

                row = [page_url, page_rank, avg_duration]
                writer.writerow(row)

        return file_path, num_rankings

    def _generate_uservisits_data(self) -> tuple[PathLike, int]:
        """Generate the USERVISITS table data."""
        filename = self.get_compressed_filename("uservisits.tbl")
        file_path = self.output_dir / filename
        num_visits = int(self.base_uservisits * self.scale_factor)
        num_rankings = int(self.base_rankings * self.scale_factor)

        # Date range: 3 months of data
        start_date = datetime(2000, 1, 1)
        end_date = datetime(2000, 3, 31)
        total_days = (end_date - start_date).days

        with self.open_output_file(file_path, "wt") as f:
            writer = csv.writer(f, delimiter="|")

            for _i in range(num_visits):
                source_ip = self._generate_ip_address()

                # Reference existing URLs from rankings (80% of time)
                if random.random() < 0.8 and num_rankings > 0:
                    url_id = random.randint(1, num_rankings)
                    dest_url = self._generate_url(url_id)
                else:
                    # Generate new URL not in rankings
                    dest_url = self._generate_url(random.randint(num_rankings + 1, num_rankings + 50000))

                # Random date in range
                random_days = random.randint(0, total_days)
                visit_date = start_date + timedelta(days=random_days)

                # Ad revenue (most visits generate little/no revenue)
                if random.random() < 0.1:  # 10% of visits generate revenue
                    ad_revenue = round(random.uniform(0.01, 5.00), 2)
                else:
                    ad_revenue = 0.00

                user_agent = random.choice(self._user_agents)
                country_code = random.choice(self._countries)
                language_code = random.choice(self._languages)

                # Search word (50% of visits have search terms)
                search_word = random.choice(self._search_words) if random.random() < 0.5 else ""

                # Duration in seconds (10s to 30 minutes)
                duration = random.randint(10, 1800)

                row = [
                    source_ip,
                    dest_url,
                    visit_date.strftime("%Y-%m-%d"),
                    ad_revenue,
                    user_agent,
                    country_code,
                    language_code,
                    search_word,
                    duration,
                ]

                writer.writerow(row)

        return file_path, num_visits

    def _generate_documents_data(self) -> tuple[PathLike, int]:
        """Generate the DOCUMENTS table data."""
        filename = self.get_compressed_filename("documents.tbl")
        file_path = self.output_dir / filename
        num_documents = int(self.base_documents * self.scale_factor)

        with self.open_output_file(file_path, "wt") as f:
            writer = csv.writer(f, delimiter="|")

            for i in range(1, num_documents + 1):
                url = self._generate_url(i)

                # Generate content of varying lengths
                if random.random() < 0.1:  # 10% very long content
                    content = self._generate_content(500, 2000)
                elif random.random() < 0.3:  # 30% medium content
                    content = self._generate_content(200, 500)
                else:  # 60% short content
                    content = self._generate_content(50, 200)

                row = [url, content]
                writer.writerow(row)

        return file_path, num_documents

    def _write_manifest(self, table_paths: dict[str, Path]) -> None:
        """Write manifest describing generated AMPLab datasets."""
        write_generator_manifest(self, "amplab", table_paths, self._table_row_counts)
