"""NYC Taxi OLAP benchmark implementation.

Implements NYC Taxi benchmark using real TLC trip data for OLAP analytics.
Provides authentic multi-dimensional workloads with temporal and
geographic dimensions.

Based on NYC Taxi & Limousine Commission data:
https://www.nyc.gov/site/tlc/about/tlc-trip-record-data.page

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import csv
import logging
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Union

from benchbox.base import BaseBenchmark, GeneratorOutputDirMixin
from benchbox.core.nyctaxi.downloader import GreenTaxiDataDownloader, HVFHVDataDownloader, NYCTaxiDataDownloader
from benchbox.core.nyctaxi.queries import NYCTaxiQueryManager
from benchbox.core.nyctaxi.schema import (
    NYC_TAXI_SCHEMA,
    TaxiType,
    get_create_tables_sql,
)
from benchbox.utils.compression_mixin import extract_compression_kwargs
from benchbox.utils.datagen_manifest import DataGenerationManifest, resolve_compression_metadata
from benchbox.utils.path_utils import get_benchmark_runs_datagen_path

if TYPE_CHECKING:
    from benchbox.core.connection import DatabaseConnection


class NYCTaxiBenchmark(GeneratorOutputDirMixin, BaseBenchmark):
    """NYC Taxi OLAP benchmark implementation.

    Uses real NYC TLC trip data for OLAP analytics workloads. Supports three
    taxi data types: Yellow (TPEP), Green (LPEP), and High Volume For-Hire
    Vehicle (HVFHV - Uber/Lyft). Default is Yellow Taxi only for backwards
    compatibility.

    **Query counts by configuration:**
    - Yellow only (default): 25 OLAP queries
    - + Green: +4 borough-focused Green Taxi queries
    - + HVFHV: +4 rideshare-specific HVFHV queries
    - + Green + HVFHV: +6 cross-type comparison queries (market share, geography,
      pricing, temporal trends)

    **Usage - Yellow Taxi only (backwards compatible):**

        >>> benchmark = NYCTaxiBenchmark(scale_factor=1.0)
        >>> data_files = benchmark.generate_data()
        >>> queries = benchmark.get_queries()  # 25 Yellow Taxi queries

    **Usage - Multi-type (Green + HVFHV + cross-type analytics):**

        >>> from benchbox.core.nyctaxi.schema import TaxiType
        >>> benchmark = NYCTaxiBenchmark(
        ...     scale_factor=1.0,
        ...     taxi_types=[TaxiType.YELLOW, TaxiType.GREEN, TaxiType.HVFHV],
        ... )
        >>> data_files = benchmark.generate_data()
        >>> queries = benchmark.get_queries()  # 39 queries across all types

    **Scale Factors:**
        - SF=1.0 targets roughly 10% of the Yellow Taxi corpus, which keeps the
          default benchmark near BenchBox's ~1GB uncompressed baseline.
        - Scale factors below 1.0 provide smaller deterministic samples for CI
          and development.
        - Scale factors above 10 saturate at the full available dataset.

    **Data availability:**
        - Yellow Taxi (TPEP): 2019-present
        - Green Taxi (LPEP): 2014-present
        - HVFHV (Uber/Lyft): February 2019-present

    Attributes:
        scale_factor: Scale factor controlling data size
        year: Year of data to use
        taxi_types: Active taxi types (default: [TaxiType.YELLOW])
        tables: Dictionary of table names to file paths
    """

    # Available years for validation
    AVAILABLE_YEARS = list(range(2019, 2026))

    # Nested downloaders that must track output_dir reassignment.
    OUTPUT_DIR_GENERATOR_ATTRS = ("downloader", "green_downloader", "hvfhv_downloader")

    def __init__(
        self,
        scale_factor: float = 1.0,
        output_dir: Union[str, Path] | None = None,
        year: int = 2019,
        months: list[int] | None = None,
        seed: int | None = None,
        verbose: int | bool = 0,
        quiet: bool = False,
        force_regenerate: bool = False,
        taxi_types: list[TaxiType] | None = None,
        **kwargs: Any,
    ) -> None:
        """Initialize NYC Taxi benchmark.

        Args:
            scale_factor: Scale factor (1.0 = ~10% of annual Yellow Taxi trips)
            output_dir: Directory for data files
            year: Year of data to use (2019-2025)
            months: Specific months to use (1-12), None for all
            seed: Random seed for reproducibility
            verbose: Verbosity level
            quiet: Suppress output
            force_regenerate: Force data regeneration
            taxi_types: Taxi types to load. None defaults to [TaxiType.YELLOW] (Yellow only,
                backward-compatible). Pass [TaxiType.YELLOW, TaxiType.GREEN, TaxiType.HVFHV]
                for multi-type analytics.
            **kwargs: Additional options

        Raises:
            ValueError: If scale_factor is not positive or year is invalid
        """
        if year not in self.AVAILABLE_YEARS:
            raise ValueError(f"year must be in {self.AVAILABLE_YEARS[0]}-{self.AVAILABLE_YEARS[-1]}, got {year}")

        # Resolve through the shared helper so BENCHBOX_OUTPUT_DIR is honored at
        # construction time (matching the canonical nyctaxi_sf<N> datagen name);
        # falls back to Path.cwd()/benchmark_runs/datagen when no override is set.
        resolved_output_dir = (
            Path(output_dir) if output_dir else get_benchmark_runs_datagen_path("nyctaxi", scale_factor)
        )
        super().__init__(
            scale_factor=scale_factor,
            output_dir=resolved_output_dir,
            verbose=verbose,
            quiet=quiet,
            force_regenerate=force_regenerate,
            **kwargs,
        )

        self.year = year
        self.months = months
        self.seed = seed
        self.force_regenerate = force_regenerate
        # Default to Yellow-only for backwards compatibility
        self.taxi_types: list[TaxiType] = taxi_types if taxi_types is not None else [TaxiType.YELLOW]

        # CSV files include a header row; server-based loaders (PostgreSQL COPY) must skip it
        self.csv_has_header: bool = True

        # Benchmark metadata
        self._name = "NYC Taxi OLAP"
        self._version = "1.0"
        self._description = "NYC Taxi & Limousine Commission trip data for OLAP analytics"

        self.logger = logging.getLogger("benchbox.core.nyctaxi.benchmark")
        compression_kwargs = extract_compression_kwargs(kwargs)

        # Create Yellow Taxi data downloader (always present)
        self.downloader = NYCTaxiDataDownloader(
            scale_factor=scale_factor,
            output_dir=self.output_dir,
            year=year,
            months=months,
            seed=seed,
            verbose=verbose,
            quiet=quiet,
            force_redownload=force_regenerate,
            **compression_kwargs,
        )

        # Create optional Green and HVFHV downloaders
        self.green_downloader: GreenTaxiDataDownloader | None = None
        self.hvfhv_downloader: HVFHVDataDownloader | None = None

        if TaxiType.GREEN in self.taxi_types:
            self.green_downloader = GreenTaxiDataDownloader(
                scale_factor=scale_factor,
                output_dir=self.output_dir,
                year=year,
                months=months,
                seed=seed,
                verbose=verbose,
                quiet=quiet,
                force_redownload=force_regenerate,
                **compression_kwargs,
            )

        if TaxiType.HVFHV in self.taxi_types:
            self.hvfhv_downloader = HVFHVDataDownloader(
                scale_factor=scale_factor,
                output_dir=self.output_dir,
                year=year,
                months=months,
                seed=seed,
                verbose=verbose,
                quiet=quiet,
                force_redownload=force_regenerate,
                **compression_kwargs,
            )

        # Determine date range for queries
        if months:
            start_month = min(months)
            end_month = max(months)
        else:
            start_month = 1
            end_month = 12

        import calendar

        start_date = datetime(year, start_month, 1)
        # Use last day of the end month (28-31 depending on month)
        _, last_day = calendar.monthrange(year, end_month)
        end_date = datetime(year, end_month, last_day)

        # Initialize query manager - enable type-specific queries based on taxi_types
        self.query_manager = NYCTaxiQueryManager(
            start_date=start_date,
            end_date=end_date,
            seed=seed,
            include_green_queries=TaxiType.GREEN in self.taxi_types,
            include_hvfhv_queries=TaxiType.HVFHV in self.taxi_types,
            include_cross_type_queries=(TaxiType.GREEN in self.taxi_types and TaxiType.HVFHV in self.taxi_types),
        )

        # Track generated table files
        self.tables: dict[str, Path] = {}

    def generate_data(self) -> list[Union[str, Path]]:
        """Download/generate NYC Taxi benchmark data.

        Downloads data for all configured taxi_types. By default only Yellow Taxi
        data is downloaded (backwards-compatible). Pass taxi_types=[TaxiType.YELLOW,
        TaxiType.GREEN, TaxiType.HVFHV] to generate multi-type data.

        Returns:
            List of paths to data files
        """
        self.log_verbose(
            f"Generating NYC Taxi data (SF={self.scale_factor}, types={[t.value for t in self.taxi_types]})"
        )

        # Always download Yellow Taxi + taxi_zones
        self.tables = self.downloader.download()

        if self.verbose_enabled:
            stats = self.downloader.get_download_stats()
            self.logger.info(f"Data ready: year={stats['year']}, sample_rate={stats['sample_rate']:.4f}")

        # Download Green Taxi if requested
        if self.green_downloader is not None:
            self.log_verbose("Downloading Green Taxi data...")
            green_path = self.green_downloader.download()
            self.tables["green_trips"] = green_path

        # Download HVFHV if requested
        if self.hvfhv_downloader is not None:
            self.log_verbose("Downloading HVFHV data...")
            hvfhv_path = self.hvfhv_downloader.download()
            self.tables["hvfhv_trips"] = hvfhv_path

        self._write_manifest()
        return list(self.tables.values())

    def _write_manifest(self) -> None:
        if not self.tables:
            return

        yellow_stats = self.downloader.get_download_stats()
        row_counts = dict(yellow_stats.get("row_counts", {}))

        if self.green_downloader is not None:
            row_counts.update(self.green_downloader.get_download_stats().get("row_counts", {}))

        if self.hvfhv_downloader is not None:
            row_counts.update(self.hvfhv_downloader.get_download_stats().get("row_counts", {}))

        # Skip manifest when all downloaders reused cached data (no row counts collected)
        if not row_counts:
            return

        manifest = DataGenerationManifest(
            output_dir=self.output_dir,
            benchmark="nyctaxi",
            scale_factor=self.scale_factor,
            compression=resolve_compression_metadata(self.downloader),
            parallel=1,
            seed=self.seed,
        )

        for table, path in self.tables.items():
            manifest.add_entry(
                table,
                path,
                row_count=row_counts.get(table, 0),
                metadata={"csv_has_header": True, "csv_null_marker": None},
            )

        manifest.write()

    def get_queries(self, dialect: str | None = None) -> dict[str, str]:
        """Get all benchmark queries.

        Args:
            dialect: Target SQL dialect. When 'clickhouse' or 'starrocks', replaces queries that
                use EXTRACT(DOW/EPOCH …) with platform-native equivalents.

        Returns:
            Dictionary mapping query IDs to query strings
        """
        import benchbox.sql_compat.rules.query_source.nyctaxi_variants  # noqa: F401
        from benchbox.sql_compat.actions import CompatAction
        from benchbox.sql_compat.context import CompatibilityContext, Phase
        from benchbox.sql_compat.registry import REGISTRY
        from benchbox.sql_compat.rules.query_source.nyctaxi_variants import (
            CLICKHOUSE_RUSH_HOUR_SQL,
            CLICKHOUSE_TRIPS_BY_DOW_SQL,
            CLICKHOUSE_WEEKDAY_WEEKEND_SQL,
            STARROCKS_RUSH_HOUR_SQL,
            STARROCKS_TRIP_DURATION_SQL,
            STARROCKS_TRIPS_BY_DOW_SQL,
            STARROCKS_WEEKDAY_WEEKEND_SQL,
        )

        queries = self.query_manager.get_queries()
        if not dialect:
            return queries

        d = dialect.lower()
        qm = self.query_manager
        _variants: dict[str, dict[str, str]] = {
            "starrocks": {
                "trips-by-day-of-week": STARROCKS_TRIPS_BY_DOW_SQL,
                "weekday-weekend-comparison": STARROCKS_WEEKDAY_WEEKEND_SQL,
                "rush-hour-analysis": STARROCKS_RUSH_HOUR_SQL,
                "trip-duration-analysis": STARROCKS_TRIP_DURATION_SQL,
            },
            "clickhouse": {
                "trips-by-day-of-week": CLICKHOUSE_TRIPS_BY_DOW_SQL,
                "weekday-weekend-comparison": CLICKHOUSE_WEEKDAY_WEEKEND_SQL,
                "rush-hour-analysis": CLICKHOUSE_RUSH_HOUR_SQL,
            },
        }
        # Iterate both platforms independently - a real dialect string never matches both.
        for platform, platform_variants in _variants.items():
            if platform not in d:
                continue
            for query_id, legacy_sql in platform_variants.items():
                if query_id not in queries:
                    continue
                ctx = CompatibilityContext(
                    platform=platform,
                    platform_version=None,
                    benchmark="nyctaxi",
                    query_id=query_id,
                    phase=Phase.QUERY_SOURCE,
                    mode="sql",
                    dialect=dialect,
                )
                registry_decision = REGISTRY.resolve(ctx)
                if registry_decision is not None:
                    if registry_decision.action is CompatAction.SELECT_VARIANT:
                        variant_template = registry_decision.payload.variant_sql  # type: ignore[union-attr]
                    else:
                        continue  # registry says NATIVE - keep original
                else:
                    variant_template = legacy_sql  # no rule: use legacy SQL
                query_def = qm._active_queries[query_id]
                params = qm._generate_params(query_def)
                queries[query_id] = variant_template.format(**params)
        return queries

    def get_query(
        self,
        query_id: Union[int, str],
        *,
        params: dict[str, Any] | None = None,
        **kwargs,
    ) -> str:
        """Get a specific benchmark query.

        Args:
            query_id: Query identifier (e.g., "trips-per-hour")
            params: Optional parameter overrides
            **kwargs: Additional arguments

        Returns:
            Parameterized query string

        Raises:
            ValueError: If query_id is unknown
        """
        query_key = str(query_id)
        return self.query_manager.get_query(query_key, params)

    def get_schema(self) -> dict[str, dict[str, Any]]:
        """Get the NYC Taxi schema for active taxi types.

        Returns:
            Schema dictionary with table definitions for active tables
        """
        active_tables = self._get_active_tables()
        return {k: v for k, v in NYC_TAXI_SCHEMA.items() if k in active_tables}

    def get_create_tables_sql(
        self,
        dialect: str = "standard",
        include_constraints: bool = True,
        time_partitioning: bool = False,
        tuning_config: Any = None,
    ) -> str:
        """Get SQL to create all benchmark tables.

        Args:
            dialect: SQL dialect (standard, duckdb, clickhouse, postgres)
            include_constraints: Include PRIMARY KEY constraints
            time_partitioning: Add time-based partitioning
            tuning_config: Optional tuning configuration (not used)

        Returns:
            SQL script for creating tables
        """
        return get_create_tables_sql(
            dialect=dialect,
            include_constraints=include_constraints,
            time_partitioning=time_partitioning,
            taxi_types=self.taxi_types,
        )

    def get_benchmark_info(self) -> dict[str, Any]:
        """Get benchmark metadata.

        Returns:
            Dictionary with benchmark information
        """
        return {
            "name": "NYC Taxi OLAP",
            "description": "NYC Taxi & Limousine Commission trip data for OLAP analytics",
            "reference": "https://www.nyc.gov/site/tlc/about/tlc-trip-record-data.page",
            "version": "1.0",
            "scale_factor": self.scale_factor,
            "year": self.year,
            "months": self.months or list(range(1, 13)),
            "num_queries": self.query_manager.get_query_count(),
            "query_categories": self.query_manager.get_categories(),
            "tables": self._get_active_tables(),
            "taxi_types": [t.value for t in self.taxi_types],
            "data_type": "real",  # Uses real TLC data, not synthetic
            "dimensions": {
                "temporal": "pickup/dropoff timestamps",
                "geographic": "TLC taxi zones",
                "financial": "fares, tips, surcharges",
            },
        }

    def _get_active_tables(self) -> list[str]:
        """Return list of tables active for the current taxi_types configuration."""
        tables = ["taxi_zones", "trips"]
        if TaxiType.GREEN in self.taxi_types:
            tables.append("green_trips")
        if TaxiType.HVFHV in self.taxi_types:
            tables.append("hvfhv_trips")
        return tables

    def get_query_info(self, query_id: str) -> dict[str, Any]:
        """Get metadata for a specific query.

        Args:
            query_id: Query identifier

        Returns:
            Dictionary with query metadata
        """
        return self.query_manager.get_query_info(query_id)

    def get_queries_by_category(self, category: str) -> list[str]:
        """Get query IDs for a specific category.

        Available categories:
        - temporal: Time-based aggregations
        - geographic: Zone-level analytics
        - financial: Revenue and tip analysis
        - characteristics: Trip characteristics
        - rates: Rate code analysis
        - vendor: Vendor comparisons
        - complex: Multi-dimensional queries
        - point: Single-value lookups
        - baseline: Full table scans

        Args:
            category: Query category name

        Returns:
            List of query IDs in that category
        """
        return self.query_manager.get_queries_by_category(category)

    def get_download_stats(self) -> dict:
        """Get statistics about the data download.

        Returns:
            Statistics dictionary
        """
        return self.downloader.get_download_stats()

    def _load_data(self, connection: DatabaseConnection) -> None:
        """Load NYC Taxi data into the database.

        This method loads the generated NYC Taxi data files (.csv format) into the database
        using a simple, database-agnostic approach with INSERT statements.

        Args:
            connection: DatabaseConnection wrapper for database operations

        Raises:
            ValueError: If data hasn't been generated yet
            Exception: If data loading fails
        """
        logger = logging.getLogger(__name__)

        # Check if data has been generated
        if not self.tables:
            raise ValueError("No data has been generated. Call generate_data() first.")

        logger.info("Loading NYC Taxi data into database...")

        # Create database schema first
        try:
            schema_sql = self.get_create_tables_sql()
            # Handle databases that don't support multiple statements at once
            if ";" in schema_sql:
                statements = [stmt.strip() for stmt in schema_sql.split(";") if stmt.strip()]
                for statement in statements:
                    connection.execute(statement)
            else:
                connection.execute(schema_sql)
            connection.commit()
            logger.info("Created NYC Taxi database schema")
        except Exception as e:
            logger.error(f"Failed to create database schema: {e}")
            raise

        # Load data for each table
        total_rows = 0
        loaded_tables = 0

        # Load tables in dependency order (dimension tables first, then fact tables)
        table_order = ["taxi_zones", "trips"]
        if TaxiType.GREEN in self.taxi_types:
            table_order.append("green_trips")
        if TaxiType.HVFHV in self.taxi_types:
            table_order.append("hvfhv_trips")

        for table_name in table_order:
            if table_name not in self.tables:
                logger.warning(f"Skipping {table_name} - no data file found")
                continue

            data_file = Path(self.tables[table_name])
            if not data_file.exists():
                logger.warning(f"Skipping {table_name} - data file does not exist: {data_file}")
                continue

            try:
                logger.info(f"Loading data for {table_name}...")
                rows_loaded = self._load_table_data(connection, table_name, data_file)

                total_rows += rows_loaded
                loaded_tables += 1
                logger.info(f"Loaded {rows_loaded:,} rows into {table_name}")

            except Exception as e:
                logger.error(f"Failed to load data for {table_name}: {e}")
                raise

        # Commit all changes
        try:
            connection.commit()
            logger.info(f"Successfully loaded {total_rows:,} total rows across {loaded_tables} tables")
        except Exception as e:
            logger.error(f"Failed to commit data loading transaction: {e}")
            raise

    def _load_table_data(self, connection: DatabaseConnection, table_name: str, data_file: Path) -> int:
        """Load data into a database table using INSERT statements.

        Args:
            connection: DatabaseConnection wrapper
            table_name: Name of the table to load data into
            data_file: Path to the CSV data file

        Returns:
            Number of rows loaded
        """
        # Get table schema to determine column count (supports all taxi type tables)
        if table_name not in NYC_TAXI_SCHEMA:
            raise ValueError(f"Unknown table: {table_name}")
        table_schema = NYC_TAXI_SCHEMA[table_name]
        column_names = list(table_schema["columns"].keys())
        num_columns = len(column_names)

        # Prepare insert statement with parameter placeholders
        placeholders = ", ".join(["?" for _ in range(num_columns)])
        insert_sql = f"INSERT INTO {table_name} VALUES ({placeholders})"

        rows_loaded = 0

        with open(data_file, newline="", encoding="utf-8") as f:
            reader = csv.reader(f)
            # Skip header row
            next(reader, None)

            rows_skipped = 0
            for row in reader:
                # Validate row has correct number of columns
                if len(row) != num_columns:
                    rows_skipped += 1
                    continue

                # Execute individual INSERT
                connection.execute(insert_sql, row)
                rows_loaded += 1

        if rows_skipped:
            logging.getLogger(__name__).warning(
                "Skipped %d malformed rows in %s (expected %d columns)",
                rows_skipped,
                table_name,
                num_columns,
            )
        return rows_loaded


# ---------------------------------------------------------------------------
# Register benchmark-specific CLI option specs
# ---------------------------------------------------------------------------

from benchbox.core.hooks.benchmark_hooks import (  # noqa: E402
    BenchmarkHookRegistry,
    BenchmarkOptionSpec,
    parse_enum_list,
    parse_int,
    parse_int_list,
)

BenchmarkHookRegistry.register_option_specs(
    "nyctaxi",
    BenchmarkOptionSpec(
        name="taxi_types",
        parser=parse_enum_list(TaxiType),
        help="Taxi data types to load (yellow,green,hvfhv)",
        aliases=("taxi-types",),
    ),
    BenchmarkOptionSpec(
        name="year",
        parser=parse_int,
        default=2019,
        help="Year of TLC data (2019-2025)",
    ),
    BenchmarkOptionSpec(
        name="months",
        parser=parse_int_list,
        help="Months to include, comma-separated (1-12)",
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
