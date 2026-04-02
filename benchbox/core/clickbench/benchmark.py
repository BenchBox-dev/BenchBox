"""ClickBench (ClickHouse Analytics Benchmark) implementation.

Provides ClickBench benchmark implementation that tests analytical database performance using web analytics data.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional, Union

from benchbox.base import BaseBenchmark
from benchbox.core.benchmark_mixins import DataGenerationMixin
from benchbox.core.clickbench.generator import ClickBenchDataGenerator
from benchbox.core.clickbench.queries import ClickBenchQueryManager
from benchbox.core.clickbench.schema import TABLES, get_create_table_sql
from benchbox.core.query_utils import get_queries_with_translation
from benchbox.core.simple_benchmark_mixin import SimpleBenchmarkMixin
from benchbox.core.utils.tuning import extract_constraint_flags

if TYPE_CHECKING:
    from benchbox.core.tuning.interface import UnifiedTuningConfiguration


class ClickBenchBenchmark(SimpleBenchmarkMixin, DataGenerationMixin, BaseBenchmark):
    """ClickBench (ClickHouse Analytics Benchmark) implementation.

    Tests analytical database performance using web analytics data.

    The benchmark consists of:
    - A single flat table with web analytics data (~100M records in original)
    - 43 analytical queries covering various performance patterns
    - Realistic data distributions based on production web analytics

    Attributes:
        scale_factor: Scale factor for the benchmark (1.0 = ~1M records for testing)
        output_dir: Directory to output generated data and results
        query_manager: ClickBench query manager
        data_generator: ClickBench data generator
    """

    _benchmark_label = "ClickBench"
    _table_load_order = ["hits"]

    def __init__(
        self,
        scale_factor: float = 1.0,
        output_dir: Optional[Union[str, Path]] = None,
        **config: Any,
    ):
        """Initialize ClickBench benchmark.

        Args:
            scale_factor: Scale factor for data generation (1.0 = ~1M records for testing)
            output_dir: Directory for generated data files
            **config: Additional configuration options
        """
        # Extract quiet from config to prevent duplicate kwarg error
        config = dict(config)
        quiet = config.pop("quiet", False)

        super().__init__(scale_factor=scale_factor, output_dir=output_dir, quiet=quiet, **config)

        self._name = "ClickBench"
        self._version = "1.0"
        self._description = "ClickBench - Analytics benchmark for DBMS with web analytics workload"

        # Initialize components
        self.query_manager: ClickBenchQueryManager = ClickBenchQueryManager()
        self.data_generator = ClickBenchDataGenerator(scale_factor, self.output_dir, **config)

        # Data files mapping
        self.tables = {}

    def _get_table_schema(self) -> dict[str, dict]:
        """Provide schema mapping for shared data generation/loading mixin."""
        return TABLES

    def get_queries(self, dialect: Optional[str] = None) -> dict[str, str]:
        """Get all available ClickBench queries.

        Args:
            dialect: Target SQL dialect for translation (e.g., 'duckdb', 'bigquery', 'snowflake')
                    If None, returns queries in their original format.

        Returns:
            A dictionary mapping query identifiers to their SQL text
        """
        return get_queries_with_translation(self.query_manager, dialect, self.translate_query_text)

    def translate_query_text(self, query: str, dialect: str) -> str:
        """Translate a query string to a specific SQL dialect."""
        try:
            import sqlglot  # type: ignore[import-untyped]

            # ClickBench queries are designed for ClickHouse, use 'clickhouse' as source
            translated = sqlglot.transpile(  # type: ignore[attr-defined]
                query, read="clickhouse", write=dialect.lower()
            )[0]
            return translated
        except ImportError:
            # sqlglot not available, return original query
            return query
        except Exception:
            # Translation failed, return original query
            return query

    def get_query(self, query_id: Union[int, str], *, params: Optional[dict[str, Any]] = None) -> str:
        """Get the SQL text for a specific ClickBench query.

        Args:
            query_id: Query identifier (e.g., "Q1", "Q2", etc.)
            params: Optional parameter values (not supported for ClickBench)

        Returns:
            The SQL text of the query

        Raises:
            ValueError: If the query_id is not valid or params are provided
        """
        if params is not None:
            raise ValueError("ClickBench queries are static and don't accept parameters")
        return self.query_manager.get_query(str(query_id))

    def get_all_queries(self) -> dict[str, str]:
        """Get all available ClickBench queries.

        Returns:
            A dictionary mapping query identifiers to their SQL text
        """
        return self.query_manager.get_all_queries()

    def execute_query(
        self,
        query_id: Union[int, str],
        connection: Any,
        params: Optional[dict[str, Any]] = None,
    ) -> Any:
        """Execute a ClickBench query on the given database connection.

        Args:
            query_id: Query identifier (e.g., "Q1", "Q2", etc.)
            connection: Database connection to use for execution
            params: Optional parameters to use in the query

        Returns:
            Query results from the database

        Raises:
            ValueError: If the query_id is not valid
        """
        sql = self.get_query(query_id, params=params)

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
        """Get the ClickBench schema definitions.

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
        """Get CREATE TABLE SQL for the ClickBench hits table.

        Args:
            dialect: SQL dialect to use
            tuning_config: Unified tuning configuration for constraint settings

        Returns:
            Complete SQL schema creation script
        """
        enable_primary_keys, enable_foreign_keys = extract_constraint_flags(tuning_config)
        return get_create_table_sql(dialect, enable_primary_keys, enable_foreign_keys)

    def get_query_categories(self) -> dict[str, list[str]]:
        """Get ClickBench queries organized by category.

        Returns:
            Dictionary mapping category names to lists of query IDs
        """
        return self.query_manager.get_query_categories()

    @property
    def csv_delimiter(self) -> str:
        """ClickBench uses pipe-delimited CSV files."""
        return "|"

    def get_csv_loading_config(self, table_name: str) -> list[str]:
        """Get CSV loading configuration for ClickBench tables.

        ClickBench requires special handling to preserve empty strings rather than
        converting them to NULL values. This is essential because:
        - ClickBench schema defines all fields as NOT NULL
        - ClickBench queries use '<> \'\'' patterns to filter empty strings
        - Official ClickBench specification expects empty strings for missing data

        Args:
            table_name: Name of the table being loaded

        Returns:
            List of CSV loading configuration parameters for DuckDB
        """
        return [
            "delim='|'",  # ClickBench uses pipe delimiter
            "header=false",  # No header row
            "nullstr='__NULL__'",  # Use a marker that won't appear in real data for NULLs
            "ignore_errors=true",  # Continue on parse errors
            "auto_detect=true",  # Auto-detect types
        ]
