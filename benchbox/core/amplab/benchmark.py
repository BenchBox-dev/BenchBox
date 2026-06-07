"""AMPLab Big Data Benchmark implementation.

Provides AMPLab Big Data Benchmark implementation that tests big data processing systems using web analytics workloads.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional, Union

from benchbox.base import BaseBenchmark, GeneratorOutputDirMixin
from benchbox.core.amplab.generator import AMPLabDataGenerator
from benchbox.core.amplab.queries import AMPLabQueryManager
from benchbox.core.amplab.schema import TABLES, get_all_create_table_sql
from benchbox.core.benchmark_mixins import DataGenerationMixin
from benchbox.core.query_catalog_base import TranslatableQueryMixin
from benchbox.core.query_utils import get_queries_with_translation
from benchbox.core.simple_benchmark_mixin import SimpleBenchmarkMixin
from benchbox.core.utils.tuning import extract_constraint_flags

if TYPE_CHECKING:
    from benchbox.core.tuning.interface import UnifiedTuningConfiguration


class AMPLabBenchmark(
    GeneratorOutputDirMixin, TranslatableQueryMixin, SimpleBenchmarkMixin, DataGenerationMixin, BaseBenchmark
):
    """AMPLab Big Data Benchmark implementation.

    Tests big data processing systems using web analytics workloads.

    The benchmark consists of:
    - 3 tables: rankings, uservisits, documents
    - Multiple query types: scan, join, and analytics queries
    - Focus on big data processing performance

    Attributes:
        scale_factor: Scale factor for the benchmark (1.0 = standard size)
        output_dir: Directory to output generated data and results
        query_manager: AMPLab query manager
        data_generator: AMPLab data generator
    """

    _benchmark_label = "AMPLab"
    _table_load_order = ["rankings", "documents", "uservisits"]

    def __init__(
        self,
        scale_factor: float = 1.0,
        output_dir: Optional[Union[str, Path]] = None,
        **config: Any,
    ):
        """Initialize AMPLab benchmark.

        Args:
            scale_factor: Scale factor for data generation (1.0 = standard size)
            output_dir: Directory for generated data files
            **config: Additional configuration options
        """
        # Extract quiet from config to prevent duplicate kwarg error
        config = dict(config)
        quiet = config.pop("quiet", False)

        super().__init__(scale_factor, output_dir=output_dir, quiet=quiet, **config)

        self._name = "AMPLab Big Data Benchmark"
        self._version = "1.0"
        self._description = "AMPLab Big Data Benchmark - Tests big data processing systems with web analytics workloads"

        # Initialize components
        self.query_manager: AMPLabQueryManager = AMPLabQueryManager()
        self.data_generator = AMPLabDataGenerator(
            scale_factor,
            self.output_dir,
            **config,
        )

        # Data files mapping
        self.tables = {}

    def _get_table_schema(self) -> dict[str, dict]:
        """Provide schema mapping for shared data generation/loading mixin."""
        return TABLES

    def _get_data_loading_batch_size(self) -> int | None:
        """Load larger AMPLab tables in chunks for better memory behavior."""
        return 10000

    def get_query(self, query_id: Union[int, str], *, params: Optional[dict[str, Any]] = None) -> str:
        """Get the SQL text for a specific AMPLab query.

        Args:
            query_id: Query identifier (e.g., "1", "2", "3", etc.)
            params: Optional parameter values to use in the query

        Returns:
            The SQL text of the query with parameters substituted

        Raises:
            ValueError: If the query_id is not valid
        """
        return self.query_manager.get_query(str(query_id), params)

    def get_queries(self, dialect: Optional[str] = None) -> dict[str, str]:
        """Get all available AMPLab queries.

        Args:
            dialect: Target SQL dialect for query translation. If None, returns original queries.

        Returns:
            A dictionary mapping query identifiers to their SQL text
        """
        return get_queries_with_translation(self.query_manager, dialect, self.translate_query_text)

    # translate_query_text() is inherited from TranslatableQueryMixin

    def get_all_queries(self) -> dict[str, str]:
        """Get all available AMPLab queries.

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
        """Execute an AMPLab query on the given database connection.

        Args:
            query_id: Query identifier (e.g., "1", "2", "3", etc.)
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
        """Get the AMPLab schema definitions.

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
        """Get CREATE TABLE SQL for all AMPLab tables.

        Args:
            dialect: SQL dialect to use
            tuning_config: Unified tuning configuration for constraint settings

        Returns:
            Complete SQL schema creation script
        """
        enable_primary_keys, enable_foreign_keys = extract_constraint_flags(tuning_config)
        return get_all_create_table_sql(dialect, enable_primary_keys, enable_foreign_keys)

    def get_csv_loading_config(self, table_name: str) -> list[str]:
        """Get CSV loading configuration for AMPLab tables.

        AMPLab uses pipe (|) delimiter for all CSV files.

        Args:
            table_name: Name of the table being loaded

        Returns:
            List of CSV loading configuration parameters
        """
        return ["delim='|'"]
