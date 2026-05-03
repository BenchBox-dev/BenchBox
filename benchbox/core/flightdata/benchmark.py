"""Flight Data OLAP benchmark implementation.

Implements the US Aviation On-Time Performance benchmark using BTS data.
Provides 20 analytical queries covering delays, routes, carriers, and
temporal patterns.

Data source: US Bureau of Transportation Statistics (BTS) TranStats
https://www.transtats.bts.gov/ontime/

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import csv
import logging
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, Any, Union

from benchbox.base import BaseBenchmark
from benchbox.core.flightdata.downloader import LAST_AVAILABLE_YEAR, FlightDataDownloader
from benchbox.core.flightdata.queries import FlightDataQueryManager
from benchbox.core.flightdata.schema import FLIGHT_SCHEMA, get_create_tables_sql
from benchbox.utils.compression_mixin import extract_compression_kwargs

if TYPE_CHECKING:
    from benchbox.core.connection import DatabaseConnection
    from benchbox.core.dataframe.query import QueryRegistry


class FlightDataBenchmark(BaseBenchmark):
    """US Aviation On-Time Performance OLAP benchmark.

    Uses BTS On-Time Performance data for realistic aviation analytics:
    - 20 OLAP queries across 5 categories
    - On-time performance analysis
    - Delay cause attribution
    - Route and airport performance
    - Seasonal and temporal patterns
    - Carrier comparisons

    Scale Factors:
        SF=0.01: 1 month synthetic/dev sample
        SF=0.1:  ~4 months of BTS data
        SF=1.0:  ~3.4 years ~24M flights ~1GB
        SF>=10:  approaches the full historical corpus

    Query categories:
        - ontime: On-time performance analysis (5 queries)
        - delay: Delay cause and pattern analysis (4 queries)
        - routes: Route performance and connectivity (4 queries)
        - temporal: Day/month/hour patterns (4 queries)
        - carriers: Carrier comparison and ranking (3 queries)
    """

    def __init__(
        self,
        scale_factor: float = 1.0,
        output_dir: Union[str, Path] | None = None,
        end_year: int = LAST_AVAILABLE_YEAR,
        seed: int | None = None,
        verbose: int | bool = 0,
        quiet: bool = False,
        force_regenerate: bool = False,
        **kwargs: Any,
    ) -> None:
        """Initialize Flight Data benchmark.

        Args:
            scale_factor: Scale factor (1.0 ≈ 1GB, ~24M flights)
            output_dir: Directory for data files
            end_year: Most recent year to include (works backwards from here)
            seed: Random seed for reproducibility (synthetic data + sampling)
            verbose: Verbosity level
            quiet: Suppress output
            force_regenerate: Force data regeneration
            **kwargs: Additional options
        """
        resolved_output_dir = (
            Path(output_dir) if output_dir else Path.cwd() / "benchmark_runs" / "datagen" / f"flightdata_{scale_factor}"
        )
        super().__init__(
            scale_factor=scale_factor,
            output_dir=resolved_output_dir,
            verbose=verbose,
            quiet=quiet,
            force_regenerate=force_regenerate,
            **kwargs,
        )

        self.end_year = end_year
        self.seed = seed
        self.force_regenerate = force_regenerate

        self._name = "Flight Data OLAP"
        self._version = "1.0"
        self._description = "US BTS On-Time Performance data for aviation analytics"

        self.logger = logging.getLogger("benchbox.core.flightdata.benchmark")

        compression_kwargs = extract_compression_kwargs(kwargs)
        self.downloader = FlightDataDownloader(
            scale_factor=scale_factor,
            output_dir=self.output_dir,
            seed=seed,
            verbose=verbose,
            quiet=quiet,
            force_redownload=force_regenerate,
            **compression_kwargs,
        )

        # Date range for queries based on scale factor
        months_seq = self.downloader.months
        if months_seq:
            oldest_year, oldest_month = months_seq[-1]
            newest_year, newest_month = months_seq[0]
            self._query_start_date = f"{oldest_year}-{oldest_month:02d}-01"
            if newest_month == 12:
                exclusive_end = date(newest_year + 1, 1, 1)
            else:
                exclusive_end = date(newest_year, newest_month + 1, 1)
            self._query_end_date = exclusive_end.isoformat()
        else:
            self._query_start_date = f"{end_year - 1}-01-01"
            self._query_end_date = f"{end_year + 1}-01-01"

        self.query_manager = FlightDataQueryManager(
            start_date=self._query_start_date,
            end_date=self._query_end_date,
        )

        self.tables: dict[str, Path | list[Path]] = {}
        self.csv_has_header: bool = True

    def generate_data(self) -> list[Union[str, Path]]:
        """Download or generate flight data files.

        Returns:
            List of paths to data files (flights.csv, airlines.csv, airports.csv)
        """
        self.log_verbose(f"Generating Flight Data (SF={self.scale_factor}, {self.downloader.num_months} months)")
        self.tables = self.downloader.download()
        stats = self.downloader.get_download_stats()
        self.log_verbose(
            f"Flight data ready: {stats['total_flights']:,} flights, "
            f"{stats['months_downloaded']} downloaded, {stats['months_synthetic']} synthetic"
        )
        return self._flatten_table_paths(self.tables)

    def ensure_auxiliary_data_files(self) -> None:
        """Repair legacy reusable FlightData cache layouts after manifest reuse."""
        repaired = self.downloader.repair_reusable_layout()
        if repaired:
            self.tables = repaired

    @staticmethod
    def _flatten_table_paths(tables: dict[str, Path | list[Path]]) -> list[Path]:
        paths: list[Path] = []
        for table_path in tables.values():
            if isinstance(table_path, list):
                paths.extend(table_path)
            else:
                paths.append(table_path)
        return paths

    def get_csv_loading_config(self, table_name: str) -> list[str]:
        """Return native CSV loader settings for FlightData source files."""
        return ["delim=','", "header=true", "auto_detect=true", "ignore_errors=true"]

    def get_queries(self, dialect: str | None = None) -> dict[str, str]:
        """Get all benchmark queries.

        Args:
            dialect: SQL dialect (ignored - flight data queries use standard SQL only)

        Returns:
            Dictionary mapping query keys to parameterized SQL strings
        """
        if dialect is not None:
            self.logger.debug("Flight data queries use standard SQL; dialect %r ignored", dialect)
        return self.query_manager.get_queries()

    def get_query(
        self,
        query_id: Union[int, str],
        *,
        params: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> str:
        """Get a specific benchmark query.

        Args:
            query_id: Query key (e.g., "ontime-by-carrier") or numeric ID ("1")
            params: Optional parameter overrides
            **kwargs: Additional arguments

        Returns:
            Parameterized SQL string

        Raises:
            ValueError: If query_id is not found
        """
        return self.query_manager.get_query(str(query_id), params)

    def get_schema(self) -> dict[str, dict[str, Any]]:
        """Get the flight data schema.

        Returns:
            Schema dictionary with table definitions
        """
        return FLIGHT_SCHEMA

    def get_create_tables_sql(
        self,
        dialect: str = "standard",
        include_constraints: bool = True,
        tuning_config: Any = None,
    ) -> str:
        """Get SQL to create all benchmark tables.

        Args:
            dialect: SQL dialect (standard, duckdb, postgres, clickhouse, snowflake)
            include_constraints: Include PRIMARY KEY constraints
            tuning_config: Optional tuning configuration (not used)

        Returns:
            SQL script for creating tables
        """
        return get_create_tables_sql(dialect=dialect, include_constraints=include_constraints)

    def get_benchmark_info(self) -> dict[str, Any]:
        """Get benchmark metadata.

        Returns:
            Dictionary with benchmark information
        """
        stats = self.downloader.get_download_stats()
        return {
            "name": "Flight Data OLAP",
            "description": "US BTS On-Time Performance data for aviation analytics",
            "reference": "https://www.transtats.bts.gov/ontime/",
            "version": "1.0",
            "scale_factor": self.scale_factor,
            "end_year": self.end_year,
            "num_months": stats["num_months"],
            "query_start_date": self._query_start_date,
            "query_end_date": self._query_end_date,
            "num_queries": self.query_manager.get_query_count(),
            "query_categories": self.query_manager.get_categories(),
            "tables": ["flights", "airlines", "airports"],
            "data_type": "real_or_synthetic",
        }

    def get_query_info(self, query_id: str) -> dict[str, Any]:
        """Get metadata for a specific query.

        Args:
            query_id: Query identifier

        Returns:
            Dictionary with query metadata
        """
        return self.query_manager.get_query_info(query_id)

    def get_queries_by_category(self, category: str) -> list[str]:
        """Get query keys for a specific category.

        Available categories: ontime, delay, routes, temporal, carriers

        Args:
            category: Query category name

        Returns:
            List of query keys in that category
        """
        return self.query_manager.get_queries_by_category(category)

    def get_download_stats(self) -> dict[str, Any]:
        """Get statistics about the data download/generation."""
        return self.downloader.get_download_stats()

    def get_dataframe_queries(self) -> QueryRegistry:
        """Get DataFrame query implementations for FlightData.

        Returns the QueryRegistry containing DataFrame implementations of all
        20 FlightData queries for both expression-family (Polars, PySpark,
        DataFusion) and pandas-family (Pandas, Modin, Dask) platforms.

        Returns:
            QueryRegistry with all 20 FlightData DataFrame queries
        """
        from benchbox.core.flightdata.dataframe_queries import (
            get_dataframe_queries,
            set_parameter_overrides,
        )

        # Clear any stale overrides from a prior run before setting new ones.
        set_parameter_overrides(None)

        # Sync benchmark parameters (dates) to the DataFrame query engine.
        # FlightData derives dates from the directory names or downloader.
        start_date, end_date = self._get_date_range()
        set_parameter_overrides({"start_date": start_date, "end_date": end_date})

        return get_dataframe_queries()

    def _get_date_range(self) -> tuple[date, date]:
        """Get the effective start and end dates for the benchmark data.

        Returns:
            Tuple of (start_date, end_date)
        """
        query_start = getattr(self, "_query_start_date", None)
        query_end = getattr(self, "_query_end_date", None)
        if isinstance(query_start, str) and isinstance(query_end, str):
            return date.fromisoformat(query_start), date.fromisoformat(query_end)

        # Fallback for partially initialized benchmark objects in tests.
        self.logger.warning("FlightData: query date range not initialized; falling back to default date range (2018).")
        return date(2018, 1, 1), date(2019, 1, 1)

    def _load_data(self, connection: DatabaseConnection) -> None:
        """Load flight data into the database.

        Args:
            connection: DatabaseConnection wrapper

        Raises:
            ValueError: If data hasn't been generated yet
        """
        if not self.tables:
            raise ValueError("No data has been generated. Call generate_data() first.")

        self.logger.info("Loading flight data into database...")

        # Create schema
        schema_sql = self.get_create_tables_sql()
        if ";" in schema_sql:
            for stmt in schema_sql.split(";"):
                stmt = stmt.strip()
                if stmt:
                    connection.execute(stmt)
        else:
            connection.execute(schema_sql)
        connection.commit()

        self.logger.info("Created flight data schema")

        # Load dimension tables first, then fact table
        table_order = ["airlines", "airports", "flights"]
        total_rows = 0

        for table_name in table_order:
            if table_name not in self.tables:
                self.logger.warning(f"Skipping {table_name} - no data file")
                continue

            table_paths = self.tables[table_name]
            data_files = table_paths if isinstance(table_paths, list) else [table_paths]
            table_rows = 0
            for data_file_raw in data_files:
                data_file = Path(data_file_raw)
                if not data_file.exists():
                    self.logger.warning(f"Skipping {table_name} - file not found: {data_file}")
                    continue

                table_rows += self._load_table_data(connection, table_name, data_file)
            total_rows += table_rows
            self.logger.info(f"Loaded {table_rows:,} rows into {table_name}")

        connection.commit()
        self.logger.info(f"Loaded {total_rows:,} total rows across {len(table_order)} tables")

    def _load_table_data(self, connection: DatabaseConnection, table_name: str, data_file: Path) -> int:
        """Load a single CSV file into a database table.

        Args:
            connection: DatabaseConnection wrapper
            table_name: Table to load into
            data_file: CSV file path

        Returns:
            Number of rows loaded
        """
        schema = FLIGHT_SCHEMA[table_name]
        num_columns = len(schema["columns"])
        placeholders = ", ".join(["?" for _ in range(num_columns)])
        insert_sql = f"INSERT INTO {table_name} VALUES ({placeholders})"

        rows_loaded = 0
        rows_skipped = 0
        with open(data_file, newline="", encoding="utf-8") as f:
            reader = csv.reader(f)
            next(reader, None)  # skip header
            for row in reader:
                if len(row) != num_columns:
                    rows_skipped += 1
                    continue
                connection.execute(insert_sql, row)
                rows_loaded += 1

        if rows_skipped:
            self.logger.warning(
                "Skipped %d malformed rows in %s (expected %d columns)",
                rows_skipped,
                table_name,
                num_columns,
            )
        return rows_loaded


# ---------------------------------------------------------------------------
# Register benchmark-specific CLI option specs
# ---------------------------------------------------------------------------

from benchbox.cli.benchmark_hooks import (  # noqa: E402
    BenchmarkHookRegistry,
    BenchmarkOptionSpec,
    parse_int,
)

BenchmarkHookRegistry.register_option_specs(
    "flightdata",
    BenchmarkOptionSpec(
        name="end_year",
        parser=parse_int,
        default=LAST_AVAILABLE_YEAR,
        help=f"Last year of flight data to include (default: {LAST_AVAILABLE_YEAR})",
        aliases=("end-year",),
    ),
    BenchmarkOptionSpec(
        name="seed",
        parser=parse_int,
        help="Random seed for reproducibility",
    ),
    BenchmarkOptionSpec(
        name="force_regenerate",
        parser=lambda v: v.strip().lower() in ("true", "1", "yes"),
        help="Force data regeneration",
        aliases=("force-regenerate",),
    ),
)
