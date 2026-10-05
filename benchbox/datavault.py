"""Data Vault benchmark implementation.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from pathlib import Path
from typing import Any, Optional, Union

from benchbox.base import BaseBenchmark
from benchbox.core.datavault.benchmark import DataVaultBenchmark


class DataVault(BaseBenchmark):
    """Data Vault 2.0 benchmark implementation based on TPC-H.

    Provides a Data Vault benchmark that transforms TPC-H's 8 tables into
    21 Data Vault tables (7 Hubs, 6 Links, 8 Satellites) and includes
    22 adapted analytical queries.

    Data Vault 2.0 is an enterprise data warehouse modeling methodology
    using Hub (business keys), Link (relationships), and Satellite
    (descriptive attributes) tables.
    """

    def __init__(
        self,
        scale_factor: float = 1.0,
        output_dir: Optional[Union[str, Path]] = None,
        **kwargs: Any,
    ) -> None:
        """Initialize Data Vault benchmark instance.

        Args:
            scale_factor: Scale factor for TPC-H source data (1.0 = ~1GB)
            output_dir: Directory to output generated data files
            **kwargs: Additional implementation-specific options
                - hash_algorithm: Hash algorithm for keys ('md5', default)
                - record_source: Source identifier for audit columns ('TPCH', default)

        Raises:
            ValueError: If scale_factor is not positive
            TypeError: If scale_factor is not a number
        """
        # Validate scale_factor type
        self._validate_scale_factor_type(scale_factor)

        super().__init__(scale_factor=scale_factor, output_dir=output_dir, **kwargs)

        # Initialize the actual implementation using common pattern
        self._initialize_benchmark_implementation(DataVaultBenchmark, scale_factor, output_dir, **kwargs)

    def generate_data(self) -> dict[str, Any]:
        """Generate Data Vault benchmark data from TPC-H source.

        This method:
        1. Generates TPC-H source data using dbgen
        2. Transforms it to Data Vault format using DuckDB

        Returns:
            Dictionary mapping table names to file paths
        """
        return self._impl.generate_data()

    def get_queries(self, dialect: Optional[str] = None) -> dict[str, str]:
        """Get all Data Vault benchmark queries.

        Args:
            dialect: Optional target SQL dialect; cloud dialects are translated
                from the DuckDB source

        Returns:
            Dictionary mapping query IDs (1-22) to query strings
        """
        queries = self._impl.get_all_queries()
        if not dialect:
            return queries
        return {k: self._impl.translate_for_dialect(v, dialect) for k, v in queries.items()}

    def get_query(
        self,
        query_id: int,
        *,
        params: Optional[dict[str, Any]] = None,
        **kwargs: Any,
    ) -> str:
        """Get a specific Data Vault benchmark query.

        Args:
            query_id: The ID of the query to retrieve (1-22)
            params: Optional parameters (not used, for API compatibility)
            **kwargs: Additional parameters; ``dialect`` selects the target SQL dialect

        Returns:
            The query string adapted for Data Vault schema

        Raises:
            ValueError: If the query_id is invalid
            TypeError: If query_id is not an integer
        """
        if not isinstance(query_id, int):
            raise TypeError(f"query_id must be an integer, got {type(query_id).__name__}")
        if not (1 <= query_id <= 22):
            raise ValueError(f"Query ID must be 1-22, got {query_id}")

        return self._impl.get_query(query_id, dialect=kwargs.get("dialect"))

    def get_schema(self) -> dict[str, Any]:
        """Get the Data Vault schema definition.

        Returns:
            Dictionary mapping table names to Table objects
        """
        return self._impl.get_schema()

    def get_create_tables_sql(self, dialect: str = "standard", tuning_config: Any = None) -> str:
        """Get SQL to create all Data Vault tables.

        Args:
            dialect: SQL dialect (for future dialect translation)
            tuning_config: Unified tuning configuration for constraint settings

        Returns:
            SQL script for creating all 21 tables
        """
        return self._impl.get_create_tables_sql(dialect=dialect, tuning_config=tuning_config)

    def get_table_loading_order(self, available_tables: Optional[list[str]] = None) -> list[str]:
        """Get table names in proper loading order.

        Data Vault tables must be loaded in order:
        1. Hubs (no dependencies)
        2. Links (depend on Hubs)
        3. Satellites (depend on Hubs/Links)

        Args:
            available_tables: Optional list of table names that are actually available.
                            If provided, only these tables are included in the order.

        Returns:
            List of table names in loading order
        """
        return self._impl.get_table_loading_order(available_tables)

    @property
    def tables(self) -> dict[str, Path]:
        """Get the mapping of table names to data file paths.

        Returns:
            Dictionary mapping table names to paths of generated data files
        """
        return getattr(self._impl, "tables", {})

    @property
    def table_count(self) -> int:
        """Get the total number of Data Vault tables.

        Returns:
            Number of tables (21)
        """
        return self._impl.get_table_count()

    @property
    def query_count(self) -> int:
        """Get the total number of benchmark queries.

        Returns:
            Number of queries (22)
        """
        return 22
