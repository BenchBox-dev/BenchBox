"""Read Primitives benchmark implementation.

Tests fundamental database read operations using TPC-H schema
with primitive SELECT query patterns.

Copyright 2026 Joe Harris / BenchBox Project

This implementation is derived from TPC Benchmark™ H (TPC-H) - Copyright © Transaction Processing Performance Council

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional, Union

from benchbox.base import BaseBenchmark
from benchbox.core.benchmark_mixins import DataGenerationMixin
from benchbox.core.query_catalog_base import QuerySkippedError, TranslatableQueryMixin

if TYPE_CHECKING:
    from cloudpathlib import CloudPath

    from benchbox.core.dataframe.query import QueryRegistry
    from benchbox.core.tuning.interface import UnifiedTuningConfiguration
    from benchbox.utils.cloud_storage import DatabricksPath

from benchbox.core.connection import DatabaseConnection
from benchbox.core.read_primitives.generator import ReadPrimitivesDataGenerator
from benchbox.core.read_primitives.queries import ReadPrimitivesQueryManager
from benchbox.core.read_primitives.schema import TABLES, get_all_create_table_sql
from benchbox.core.utils.tuning import extract_constraint_flags
from benchbox.utils.cloud_storage import create_path_handler
from benchbox.utils.file_format import get_delimiter_for_file, is_tpc_format
from benchbox.utils.path_utils import get_benchmark_runs_datagen_path

# Type alias for paths that could be local or cloud
PathLike = Union[Path, "CloudPath", "DatabricksPath"]


class ReadPrimitivesBenchmark(TranslatableQueryMixin, DataGenerationMixin, BaseBenchmark):
    """Read Primitives benchmark implementation.

    Uses TPC-H schema with 8 tables and 80+ primitive read queries.
    Tests aggregation, joins, filters, window functions, analytics.

    Attributes:
        scale_factor: Scale factor (1.0 = ~6M lineitem rows)
        output_dir: Data output directory
        query_manager: Query manager
        data_generator: Data generator
    """

    def __init__(
        self,
        scale_factor: float = 1.0,
        output_dir: Optional[Union[str, Path]] = None,
        **config: Any,
    ):
        """Initialize Read Primitives benchmark.

        Args:
            scale_factor: Scale factor (1.0 = standard size)
            output_dir: Data output directory
            **config: Additional configuration
        """
        # Extract quiet from config to prevent duplicate kwarg error
        config = dict(config)
        quiet = config.pop("quiet", False)

        super().__init__(scale_factor, quiet=quiet, **config)

        self._name = "Read Primitives Benchmark"
        self._version = "1.0"
        self._description = (
            "Read Primitives benchmark - Testing fundamental database read operations using TPC-H schema"
        )

        # Setup directories
        if output_dir is None:
            # Read Primitives reuses the canonical TPC-H datagen directory
            output_dir = get_benchmark_runs_datagen_path("tpch", scale_factor)

        self.output_dir = output_dir

        # Initialize components
        self.query_manager: ReadPrimitivesQueryManager = ReadPrimitivesQueryManager()
        self.data_generator = ReadPrimitivesDataGenerator(scale_factor, self.output_dir, **config)

        # Data files mapping
        self.tables = {}

    def get_data_source_benchmark(self) -> Optional[str]:
        """Read Primitives benchmark shares TPC-H data."""
        return "tpch"

    def supports_dataframe_mode(self) -> bool:
        """Read Primitives supports DataFrame execution mode."""
        return True

    @property
    def output_dir(self) -> PathLike:
        """Get the output directory."""
        return self._output_dir

    @output_dir.setter
    def output_dir(self, value: Union[str, Path]) -> None:
        """Set the output directory and update data generator."""
        self._output_dir = create_path_handler(value)
        # Configure data generator with new path
        if hasattr(self, "data_generator"):
            self.data_generator.output_dir = self._output_dir
            # Also update the underlying TPC-H generator
            if hasattr(self.data_generator, "tpch_generator"):
                self.data_generator.tpch_generator.output_dir = self._output_dir

    def _get_table_schema(self) -> dict[str, dict]:
        """Provide schema mapping for shared data generation/loading mixin."""
        return TABLES

    def get_query(self, query_id: Union[int, str], *, params: Optional[dict[str, Any]] = None) -> str:
        """Get SQL text for a specific Read Primitives query.

        Args:
            query_id: Query identifier (e.g., "aggregation_simple", "window_growing_frame", etc.)
            params: Optional parameter values (not supported for Read Primitives)

        Returns:
            SQL text of the query

        Raises:
            ValueError: If query_id is not valid or params are provided
        """
        if params is not None:
            raise ValueError("Read Primitives queries are static and don't accept parameters")
        return self.query_manager.get_query(str(query_id))

    def _get_query_safe(self, query_id: str) -> str:
        """Safely get query with fallback for unknown queries.

        Args:
            query_id: Query identifier

        Returns:
            SQL text of the query, or fallback SQL for unknown queries
        """
        try:
            return self.get_query(query_id)
        except ValueError:
            # Fallback SQL for unknown queries
            return f"-- Unknown query: {query_id}\nSELECT 'unknown_query' AS result;"

    def get_queries(self, dialect: Optional[str] = None) -> dict[str, str]:
        """Get all available Read Primitives queries.

        Args:
            dialect: Target SQL dialect for query translation. If None, returns original queries.

        Returns:
            A dictionary mapping query identifiers to their SQL text
        """
        base_queries = self.query_manager.get_all_queries()

        if dialect:
            translated_queries = {}
            for query_id in base_queries.keys():
                is_variant = self.query_manager.has_variant(query_id, dialect)
                try:
                    query_sql = self.query_manager.get_query(query_id, dialect=dialect)
                except QuerySkippedError:
                    continue
                if is_variant:
                    # Catalog variants are authored as final target SQL for their dialect.
                    # Bypassing source→dialect translation preserves platform-specific syntax
                    # (e.g. ClickHouse length(array)/quantile(p)(col), DuckDB list_*/ROW/len,
                    # Redshift window workarounds, BigQuery UNNEST forms).
                    translated_queries[query_id] = query_sql
                else:
                    translated_queries[query_id] = self.translate_query_text(query_sql, dialect)
            return translated_queries

        return base_queries

    # translate_query_text() is inherited from TranslatableQueryMixin

    def get_all_queries(self) -> dict[str, str]:
        """Get all available Read Primitives queries.

        Returns:
            A dictionary mapping query identifiers to their SQL text
        """
        return self.query_manager.get_all_queries()

    def get_queries_by_category(self, category: str) -> dict[str, str]:
        """Get queries filtered by category.

        Args:
            category: Category name (e.g., 'aggregation', 'window', 'join')

        Returns:
            Dictionary mapping query IDs to SQL text for the category
        """
        return self.query_manager.get_queries_by_category(category)

    def get_query_categories(self) -> list[str]:
        """Get list of available query categories.

        Returns:
            List of category names
        """
        return self.query_manager.get_query_categories()

    def execute_query(
        self,
        query_id: Union[int, str],
        connection: Any,
        params: Optional[dict[str, Any]] = None,
    ) -> Any:
        """Execute a Read Primitives query on the given database connection.

        Args:
            query_id: Query identifier (e.g., "aggregation_simple", "window_growing_frame", etc.)
            connection: Database connection to use for execution
            params: Optional parameters to use in the query (currently unused)

        Returns:
            Query results from the database

        Raises:
            ValueError: If the query_id is not valid
        """
        sql = self.get_query(query_id)

        # Execute query using connection
        if hasattr(connection, "execute"):
            # Direct database connection
            cursor = connection.execute(sql)
            return cursor.fetchall()
        elif hasattr(connection, "cursor"):
            # Connection with cursor method
            cursor = connection.cursor()
            cursor.execute(sql)
            return cursor.fetchall()
        else:
            raise ValueError("Unsupported connection type")

    def get_schema(self, dialect: str = "standard") -> dict[str, dict]:
        """Get the Read Primitives schema definitions.

        Args:
            dialect: SQL dialect to use for data types

        Returns:
            Dictionary mapping table names to their schema definitions
        """
        return TABLES

    def get_create_tables_sql(
        self,
        dialect: str = "standard",
        tuning_config: Optional["UnifiedTuningConfiguration"] = None,
    ) -> str:
        """Get CREATE TABLE SQL for all Read Primitives tables.

        Args:
            dialect: SQL dialect to use
            tuning_config: Unified tuning configuration for constraint settings

        Returns:
            Complete SQL schema creation script
        """
        try:
            enable_primary_keys, enable_foreign_keys = extract_constraint_flags(tuning_config)
        except AttributeError as e:
            self.logger.error(
                f"Failed to extract constraint settings from tuning_config: {e}. "
                f"tuning_config type: {type(tuning_config)}"
            )
            raise RuntimeError(
                f"Invalid tuning_config object (missing primary_keys or foreign_keys attributes): {e}"
            ) from e

        return get_all_create_table_sql(
            dialect=dialect,
            enable_primary_keys=enable_primary_keys,
            enable_foreign_keys=enable_foreign_keys,
        )

    def run_benchmark(
        self,
        connection: Any,
        queries: Optional[list[str]] = None,
        iterations: int = 1,
        categories: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        """Run the complete Read Primitives benchmark.

        Args:
            connection: Database connection to use
            queries: Optional list of query IDs to run. If None, runs all.
            iterations: Number of times to run each query
            categories: Optional list of categories to run. If specified, overrides queries.

        Returns:
            Dictionary containing benchmark results
        """
        import time

        # Determine which queries to run
        if categories:
            queries = []
            for category in categories:
                category_queries = self.get_queries_by_category(category)
                queries.extend(category_queries.keys())
        elif queries is None:
            queries = list(self.query_manager.get_all_queries().keys())

        results = {
            "benchmark": "Read Primitives",
            "scale_factor": self.scale_factor,
            "iterations": iterations,
            "categories": categories,
            "queries": {},
        }

        for query_id in queries:
            # Look up actual category from catalog instead of parsing from query_id
            try:
                category = self.query_manager.get_query_category(query_id)
            except ValueError:
                category = "unknown"

            query_results = {
                "query_id": query_id,
                "category": category,
                "iterations": [],
                "avg_time": 0,
                "min_time": float("inf"),
                "max_time": 0,
                "sql_text": self._get_query_safe(query_id),  # Add actual SQL text
            }

            for i in range(iterations):
                start_time = time.perf_counter()
                try:
                    result = self.execute_query(query_id, connection)
                    end_time = time.perf_counter()
                    execution_time = end_time - start_time

                    query_results["iterations"].append(
                        {
                            "iteration": i + 1,
                            "time": execution_time,
                            "rows": len(result) if result else 0,
                            "success": True,
                        }
                    )

                    query_results["min_time"] = min(query_results["min_time"], execution_time)
                    query_results["max_time"] = max(query_results["max_time"], execution_time)

                except Exception as e:
                    query_results["iterations"].append(
                        {
                            "iteration": i + 1,
                            "time": 0,
                            "error": str(e),
                            "success": False,
                        }
                    )

            # Calculate average time for successful iterations
            iterations_list: list[dict[str, Any]] = query_results["iterations"]  # type: ignore[assignment]
            successful_iterations = [iter_result for iter_result in iterations_list if iter_result["success"]]
            if successful_iterations:
                successful_times = [iter_result["time"] for iter_result in successful_iterations]
                successful_rows = [iter_result.get("rows", 0) for iter_result in successful_iterations]
                query_results["avg_time"] = sum(successful_times) / len(successful_times)
                query_results["rows_returned"] = (
                    int(sum(successful_rows) / len(successful_rows)) if successful_rows else 0
                )

            results["queries"][query_id] = query_results

        return results

    def run_category_benchmark(self, connection: Any, category: str, iterations: int = 1) -> dict[str, Any]:
        """Run benchmark for a specific query category.

        Args:
            connection: Database connection to use
            category: Category name to run (e.g., 'aggregation', 'window', 'join')
            iterations: Number of times to run each query

        Returns:
            Dictionary containing benchmark results for the category
        """
        return self.run_benchmark(connection, None, iterations, [category])

    def get_benchmark_info(self) -> dict[str, Any]:
        """Get information about the benchmark.

        Returns:
            Dictionary containing benchmark metadata
        """
        return {
            "name": self._name,
            "version": self._version,
            "description": self._description,
            "scale_factor": self.scale_factor,
            "total_queries": len(self.query_manager.get_all_queries()),
            "categories": self.get_query_categories(),
            "tables": list(TABLES.keys()),
            "schema": "TPC-H",
        }

    def _check_compatible_tpch_database(self, connection: DatabaseConnection) -> bool:
        """Check if an existing TPC-H database is compatible with Read Primitives requirements.

        Read Primitives uses TPC-H schema and data, so it can reuse an existing TPC-H database
        if the configuration matches (scale factor, tuning settings, constraints).

        Args:
            connection: DatabaseConnection wrapper for database operations

        Returns:
            True if compatible TPC-H database exists and can be reused
        """
        import logging

        logger = logging.getLogger(__name__)

        try:
            # Check if TPC-H tables exist with correct schema
            required_tables = [
                "region",
                "nation",
                "customer",
                "supplier",
                "part",
                "partsupp",
                "orders",
                "lineitem",
            ]

            for table_name in required_tables:
                try:
                    # Check if table exists by querying it
                    result = connection.execute(f"SELECT COUNT(*) FROM {table_name} LIMIT 1")
                    if not result:
                        logger.debug(f"Table {table_name} does not exist or is empty")
                        return False
                except Exception:
                    logger.debug(f"Table {table_name} does not exist")
                    return False

            # Validate row counts are reasonable for our scale factor
            try:
                # Check lineitem table as the main indicator
                result = connection.execute("SELECT COUNT(*) FROM lineitem")
                lineitem_count = result[0][0] if result else 0

                # Expected lineitem rows: ~6M per scale factor (with 20% tolerance)
                expected_min = int(6000000 * self.scale_factor * 0.8)
                expected_max = int(6000000 * self.scale_factor * 1.2)

                if not (expected_min <= lineitem_count <= expected_max):
                    logger.debug(
                        f"Lineitem row count {lineitem_count:,} not compatible with scale factor {self.scale_factor} (expected {expected_min:,}-{expected_max:,})"
                    )
                    return False

                logger.info(
                    f"Found compatible TPC-H database with {lineitem_count:,} lineitem rows (scale factor {self.scale_factor})"
                )
                return True

            except Exception as e:
                logger.debug(f"Could not validate row counts: {e}")
                return False

        except Exception as e:
            logger.debug(f"Database compatibility check failed: {e}")
            return False

    def _load_data(self, connection: DatabaseConnection) -> None:
        """Load Read Primitives data into the database.

        This method first checks if a compatible TPC-H database already exists and can be reused.
        If not, it loads the generated Read Primitives data files (.csv/.tbl format) into the database
        using a simple, database-agnostic approach with INSERT statements.

        Args:
            connection: DatabaseConnection wrapper for database operations

        Raises:
            ValueError: If data hasn't been generated yet
            Exception: If data loading fails
        """
        import logging

        logger = logging.getLogger(__name__)

        # Check if we can reuse an existing compatible TPC-H database
        if self._check_compatible_tpch_database(connection):
            logger.info("Reusing existing compatible TPC-H database for Read Primitives benchmark")
            return

        # Check if data has been generated
        if not self.tables:
            raise ValueError("No data has been generated. Call generate_data() first.")

        logger.info("Loading Read Primitives data into database...")

        # Create database schema first
        try:
            schema_sql = self.get_create_tables_sql()
            # Handle databases that don't support multiple statements at once
            if ";" in schema_sql:
                # Split by semicolons and execute each statement separately
                statements = [stmt.strip() for stmt in schema_sql.split(";") if stmt.strip()]
                for statement in statements:
                    connection.execute(statement)
            else:
                connection.execute(schema_sql)
            connection.commit()
            logger.info("✅ Created Read Primitives database schema")
        except Exception as e:
            logger.error(f"Failed to create database schema: {e}")
            raise

        # Load data for each table
        total_rows = 0
        loaded_tables = 0

        # Load tables in dependency order (same as TPC-H)
        table_order = [
            "region",
            "nation",
            "customer",
            "supplier",
            "part",
            "partsupp",
            "orders",
            "lineitem",
        ]

        for table_name in table_order:
            if table_name not in self.tables:
                logger.warning(f"Skipping {table_name} - no data file found")
                continue

            data_file = Path(self.tables[table_name])
            # For TPC-H data, prefer .tbl files over .csv files due to embedded commas
            tbl_file = data_file.with_suffix(".tbl")
            if tbl_file.exists():
                data_file = tbl_file
            elif not data_file.exists():
                logger.warning(f"Skipping {table_name} - data file does not exist: {data_file}")
                continue

            try:
                logger.info(f"Loading data for {table_name.upper()}...")
                rows_loaded = self._load_table_data(connection, table_name, data_file)

                total_rows += rows_loaded
                loaded_tables += 1
                logger.info(f"✅ Loaded {rows_loaded:,} rows into {table_name.upper()}")

            except Exception as e:
                logger.error(f"Failed to load data for {table_name}: {e}")
                raise

        # Commit all changes
        try:
            connection.commit()
            logger.info(f"✅ Successfully loaded {total_rows:,} total rows across {loaded_tables} tables")
        except Exception as e:
            logger.error(f"Failed to commit data loading transaction: {e}")
            raise

    def _load_table_data(self, connection: DatabaseConnection, table_name: str, data_file: Path) -> int:
        """Load data into a database table using simple INSERT statements.

        Args:
            connection: DatabaseConnection wrapper
            table_name: Name of the table to load data into
            data_file: Path to the data file

        Returns:
            Number of rows loaded
        """
        import csv

        # Get table schema to determine column count
        table_schema = TABLES[table_name]
        num_columns = len(table_schema["columns"])

        # Prepare insert statement with parameter placeholders
        placeholders = ", ".join(["?" for _ in range(num_columns)])
        insert_sql = f"INSERT INTO {table_name} VALUES ({placeholders})"

        rows_loaded = 0

        # Determine delimiter based on file format (handles compression)
        delimiter = get_delimiter_for_file(data_file)

        with open(data_file, newline="", encoding="utf-8") as f:
            reader = csv.reader(f, delimiter=delimiter)

            for row in reader:
                # Handle trailing pipe in TPC format files (.tbl, .dat)
                if is_tpc_format(data_file) and row and row[-1] == "":
                    row = row[:-1]  # Remove trailing empty column

                # Validate row has correct number of columns
                if len(row) != num_columns:
                    continue  # Skip malformed rows

                # Execute individual INSERT
                connection.execute(insert_sql, row)
                rows_loaded += 1

        return rows_loaded

    def _get_default_benchmark_type(self) -> str:
        """Read Primitives benchmark uses mixed workload optimizations."""
        return "mixed"

    def _validate_database_configuration_compatibility(self, other_config: dict) -> bool:
        """Validate that another benchmark's database configuration is compatible with Read Primitives.

        Read Primitives can reuse TPC-H databases with matching scale factor and configuration.

        Args:
            other_config: Configuration from another benchmark

        Returns:
            True if the configurations are compatible
        """
        # Check if it's a TPC-H compatible benchmark
        benchmark_type = other_config.get("benchmark_type", "").lower()
        if benchmark_type not in ["tpch", "tpc-h", "primitives", "read_primitives"]:
            return False

        # Check scale factor compatibility
        other_scale = other_config.get("scale_factor")
        if other_scale != self.scale_factor:
            return False

        # Check tuning configuration compatibility
        # This would use the same logic as the platform adapter's tuning validation
        return True

    def get_dataframe_queries(self) -> "QueryRegistry":
        """Get DataFrame query implementations for Read Primitives.

        Returns the QueryRegistry containing DataFrame implementations of
        Read Primitives queries for both expression-family (Polars, PySpark,
        DataFusion) and pandas-family (Pandas, Modin, Dask) platforms.

        Note: 13 optimizer queries are SQL-only and not included in the
        DataFrame registry, as they test SQL query planning behavior.

        Returns:
            QueryRegistry with Read Primitives DataFrame queries

        Example:
            >>> benchmark = ReadPrimitivesBenchmark(scale_factor=0.01)
            >>> registry = benchmark.get_dataframe_queries()
            >>> len(registry)  # Number of DataFrame queries
            32
        """
        from benchbox.core.read_primitives.dataframe_queries import get_dataframe_queries

        return get_dataframe_queries()

    def get_dataframe_skip_queries(self) -> list[str]:
        """Get query IDs that should be skipped for DataFrame execution.

        These are SQL-only queries (optimizer tests) that test SQL query
        planning behavior and are not applicable to DataFrame execution.

        Returns:
            List of query IDs to skip for DataFrame mode
        """
        from benchbox.core.read_primitives.dataframe_queries import get_skip_for_dataframe

        return get_skip_for_dataframe()

    def get_expression_family_skip_queries(self) -> list[str]:
        """Get query IDs that should be skipped for expression-family platforms.

        Currently only map queries are skipped because Polars has no native
        Map dtype. All list/array, struct, and string-split queries are now
        supported through the unified expression API.

        Returns:
            List of query IDs to skip for expression-family platforms (map queries only)
        """
        from benchbox.core.read_primitives.dataframe_queries import get_skip_for_expression_family

        return get_skip_for_expression_family()

    def get_platform_skip_queries(self, platform_name: str) -> list[str]:
        """Get query IDs to skip for a specific platform in all execution modes.

        These skips apply to both SQL and DataFrame execution.

        Returns:
            List of query IDs to exclude from execution on the given platform
        """
        name = platform_name.lower()
        if name == "lakesail":
            # LakeSail/Sail hangs indefinitely on LEFT JOINs with an empty
            # build side - a known Sail bug with empty-relation optimization.
            return ["empty_build_join"]
        return []

    def get_df_platform_skip_queries(self, platform_name: str) -> list[str]:
        """Get query IDs to skip for a specific platform in DataFrame mode only.

        Returns:
            List of query IDs to exclude from DataFrame execution on the given platform
        """
        name = platform_name.lower()
        if name == "datafusion":
            from benchbox.core.read_primitives.dataframe_queries import get_skip_for_datafusion

            return get_skip_for_datafusion()
        if name == "polars":
            from benchbox.core.read_primitives.dataframe_queries import get_skip_for_polars

            return get_skip_for_polars()
        if name == "pyspark":
            from benchbox.core.read_primitives.dataframe_queries import get_skip_for_pyspark

            return get_skip_for_pyspark()
        return []
