"""TPC-Havoc benchmark implementation.

Copyright 2026 Joe Harris / BenchBox Project

This implementation is derived from TPC Benchmark™ H (TPC-H) - Copyright © Transaction Processing Performance Council

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from pathlib import Path
from typing import Any, Optional, Union

from benchbox.base import BaseBenchmark
from benchbox.core.tpchavoc.benchmark import TPCHavocBenchmark


class TPCHavoc(BaseBenchmark):
    """TPC-Havoc benchmark implementation.

    Generates TPC-H query variants to stress query optimizers
    while maintaining result equivalence.

    TPC-Havoc provides 10 structural variants for each TPC-H query (1-22).
    Each variant is semantically equivalent but uses different SQL constructs
    to stress different optimizer components.

    Example:
        >>> from benchbox import TPCHavoc
        >>> from benchbox.platforms.duckdb import DuckDBAdapter
        >>>
        >>> # Initialize benchmark and platform
        >>> benchmark = TPCHavoc(scale_factor=1.0)
        >>> adapter = DuckDBAdapter(database=":memory:")
        >>>
        >>> # Load data
        >>> adapter.load_benchmark(benchmark)
        >>>
        >>> # Get and execute query variant
        >>> variant_query = benchmark.get_query_variant(query_id=1, variant_id=1)
        >>> results = adapter.execute_query(variant_query)
        >>>
        >>> # Get variant description
        >>> desc = benchmark.get_variant_description(query_id=1, variant_id=1)
        >>> emit(desc)  # "Join order permutation: customers first"
        >>>
        >>> # Export all variants
        >>> benchmark.export_variant_queries(output_dir="./queries")

    Note:
        Query execution must be performed through platform adapters
        (DuckDBAdapter, SnowflakeAdapter, etc.). Direct execution methods
        are not provided to maintain architectural consistency.
    """

    def __init__(
        self,
        scale_factor: float = 1.0,
        output_dir: Optional[Union[str, Path]] = None,
        **kwargs: Any,
    ) -> None:
        """Initialize TPC-Havoc benchmark instance.

        Args:
            scale_factor: Scale factor (1.0 = ~1GB)
            output_dir: Data output directory
            **kwargs: Additional options

        Raises:
            ValueError: If scale_factor is not positive
            TypeError: If scale_factor is not a number
        """
        # Validate scale_factor
        if not isinstance(scale_factor, (int, float)):
            raise TypeError(f"scale_factor must be a number, got {type(scale_factor).__name__}")
        if scale_factor <= 0:
            raise ValueError(f"scale_factor must be positive, got {scale_factor}")

        super().__init__(scale_factor=scale_factor, output_dir=output_dir, **kwargs)

        # Initialize the actual implementation
        verbose = kwargs.pop("verbose", False)
        self._impl = TPCHavocBenchmark(scale_factor=scale_factor, output_dir=output_dir, verbose=verbose, **kwargs)

    def generate_data(self) -> list[Union[str, Path]]:
        """Generate TPC-Havoc benchmark data (same as TPC-H).

        Returns:
            A list of paths to the generated data files
        """
        return self._impl.generate_data()

    def get_platform_skip_queries(self, platform_name: str) -> list[str]:
        """Get platform-specific query IDs excluded by compatibility policy.

        Args:
            platform_name: Platform selector or adapter display name

        Returns:
            List of query IDs to skip on the given platform
        """
        return self._impl.get_platform_skip_queries(platform_name)

    def get_queries(self, dialect: Optional[str] = None) -> dict[str, str]:
        """Get all TPC-Havoc benchmark queries (base TPC-H queries).

        Args:
            dialect: Target SQL dialect for query translation. If None, returns original queries.

        Returns:
            A dictionary mapping query IDs (1-22) to base query strings
        """
        return self._impl.get_queries(dialect=dialect)

    def get_query(
        self,
        query_id,
        *,
        params: Optional[dict[str, Any]] = None,
        seed: Optional[int] = None,
        scale_factor: Optional[float] = None,
        dialect: Optional[str] = None,
        base_dialect: Optional[str] = None,
        **kwargs,
    ) -> str:
        """Get a specific TPC-Havoc benchmark query.

        Args:
            query_id: The ID of the query to retrieve (1-22 for base queries, or "1_v1" format for variants)
            params: Optional parameters to customize the query
            seed: Random number generator seed for parameter generation
            scale_factor: Scale factor for parameter calculations
            dialect: Target SQL dialect
            base_dialect: Source SQL dialect for translation
            **kwargs: Additional parameters

        Returns:
            The query string

        Raises:
            ValueError: If the query_id is invalid
            TypeError: If query_id is not valid format
        """
        # Validate query_id (allow both int and string formats)
        if isinstance(query_id, int):
            if not (1 <= query_id <= 22):
                raise ValueError(f"Query ID must be 1-22, got {query_id}")
        elif isinstance(query_id, str):
            # Validate variant format like "1_v1"
            if "_v" not in query_id:
                raise ValueError(f"String query ID must be in format 'Q_VID' (e.g., '1_v1'), got {query_id}")
        else:
            raise TypeError(f"query_id must be an integer or string, got {type(query_id).__name__}")

        # Validate scale_factor if provided
        if scale_factor is not None:
            if not isinstance(scale_factor, (int, float)):
                raise TypeError(f"scale_factor must be a number, got {type(scale_factor).__name__}")
            if scale_factor <= 0:
                raise ValueError(f"scale_factor must be positive, got {scale_factor}")

        # Validate seed if provided
        if seed is not None and not isinstance(seed, int):
            raise TypeError(f"seed must be an integer, got {type(seed).__name__}")

        return self._impl.get_query(
            query_id,
            seed=seed,
            scale_factor=scale_factor,
            dialect=dialect,
            base_dialect=base_dialect,
            **kwargs,
        )

    def get_query_variant(self, query_id: int, variant_id: int, params: Optional[dict[str, Any]] = None) -> str:
        """Get a specific TPC-Havoc query variant.

        Args:
            query_id: The ID of the query to retrieve (1-22)
            variant_id: The ID of the variant to retrieve (1-10)
            params: Optional parameter values to use

        Returns:
            The variant query string

        Raises:
            ValueError: If the query_id or variant_id is invalid
            TypeError: If query_id or variant_id is not an integer
        """
        # Validate inputs
        if not isinstance(query_id, int):
            raise TypeError(f"query_id must be an integer, got {type(query_id).__name__}")
        if not isinstance(variant_id, int):
            raise TypeError(f"variant_id must be an integer, got {type(variant_id).__name__}")
        if not (1 <= query_id <= 22):
            raise ValueError(f"Query ID must be 1-22, got {query_id}")
        if not (1 <= variant_id <= 10):
            raise ValueError(f"Variant ID must be 1-10, got {variant_id}")

        return self._impl.get_query_variant(query_id, variant_id, params)

    def get_all_variants(self, query_id: int) -> dict[int, str]:
        """Get all variants for a specific query.

        Args:
            query_id: The ID of the query to retrieve variants for (1-22)

        Returns:
            A dictionary mapping variant IDs to query strings

        Raises:
            ValueError: If the query_id is invalid or not implemented
            TypeError: If query_id is not an integer
        """
        if not isinstance(query_id, int):
            raise TypeError(f"query_id must be an integer, got {type(query_id).__name__}")
        if not (1 <= query_id <= 22):
            raise ValueError(f"Query ID must be 1-22, got {query_id}")

        return self._impl.get_all_variants(query_id)

    def get_variant_description(self, query_id: int, variant_id: int) -> str:
        """Get description of a specific variant.

        Args:
            query_id: The ID of the query (1-22)
            variant_id: The ID of the variant (1-10)

        Returns:
            Human-readable description of the variant

        Raises:
            ValueError: If the query_id or variant_id is invalid
            TypeError: If query_id or variant_id is not an integer
        """
        if not isinstance(query_id, int):
            raise TypeError(f"query_id must be an integer, got {type(query_id).__name__}")
        if not isinstance(variant_id, int):
            raise TypeError(f"variant_id must be an integer, got {type(variant_id).__name__}")
        if not (1 <= query_id <= 22):
            raise ValueError(f"Query ID must be 1-22, got {query_id}")
        if not (1 <= variant_id <= 10):
            raise ValueError(f"Variant ID must be 1-10, got {variant_id}")

        return self._impl.get_variant_description(query_id, variant_id)

    def get_implemented_queries(self) -> list[int]:
        """Get list of query IDs that have variants implemented.

        Returns:
            List of query IDs with implemented variants
        """
        return self._impl.get_implemented_queries()

    def get_all_variants_info(self, query_id: int) -> dict[int, dict[str, str]]:
        """Get information about all variants for a specific query.

        Args:
            query_id: The ID of the query (1-22)

        Returns:
            Dictionary mapping variant IDs to variant info

        Raises:
            ValueError: If the query_id is invalid or not implemented
            TypeError: If query_id is not an integer
        """
        if not isinstance(query_id, int):
            raise TypeError(f"query_id must be an integer, got {type(query_id).__name__}")
        if not (1 <= query_id <= 22):
            raise ValueError(f"Query ID must be 1-22, got {query_id}")

        return self._impl.get_all_variants_info(query_id)

    def get_schema(self) -> dict[str, dict[str, Any]]:
        """Get the TPC-Havoc schema (same as TPC-H).

        Returns:
            A dictionary mapping table names to table definitions
        """
        return self._impl.get_schema()

    def get_create_tables_sql(self, dialect: str = "standard", tuning_config=None) -> str:
        """Get SQL to create all TPC-Havoc tables (same as TPC-H).

        Args:
            dialect: SQL dialect to use
            tuning_config: Unified tuning configuration for constraint settings

        Returns:
            SQL script for creating all tables
        """
        return self._impl.get_create_tables_sql(dialect=dialect, tuning_config=tuning_config)

    def get_benchmark_info(self) -> dict[str, Any]:
        """Get information about the TPC-Havoc benchmark.

        Returns:
            Dictionary containing benchmark metadata
        """
        return self._impl.get_benchmark_info()

    def export_variant_queries(
        self, output_dir: Optional[Union[str, Path]] = None, format: str = "sql"
    ) -> dict[str, Path]:
        """Export all variant queries to files.

        Args:
            output_dir: Directory to export queries to (default: self.output_dir/queries)
            format: Export format ("sql", "json")

        Returns:
            Dictionary mapping query identifiers to file paths

        Raises:
            ValueError: If format is unsupported
        """
        return self._impl.export_variant_queries(output_dir, format)

    def load_data_to_database(
        self,
        connection_string: str,
        dialect: str = "standard",
        schema: Optional[str] = None,
        drop_existing: bool = False,
    ) -> None:
        """Load generated data into a database (same as TPC-H).

        Args:
            connection_string: Database connection string
            dialect: SQL dialect (standard, postgres, mysql, etc.)
            schema: Optional database schema to use
            drop_existing: Whether to drop existing tables before creating new ones

        Raises:
            ValueError: If data hasn't been generated yet
            ImportError: If required database driver is not installed
        """
        self._impl.load_data_to_database(
            connection_string=connection_string,
            dialect=dialect,
            schema=schema,
            drop_existing=drop_existing,
        )

    def run_query(
        self,
        query_id: int,
        connection_string: str,
        params: Optional[dict[str, Any]] = None,
        dialect: str = "standard",
    ) -> dict[str, Any]:
        """Run a TPC-Havoc base query against a database.

        Args:
            query_id: The ID of the query to run (1-22)
            connection_string: Database connection string
            params: Optional parameter values to use
            dialect: SQL dialect (standard, postgres, mysql, etc.)

        Returns:
            Dictionary with query results and timing information

        Raises:
            ValueError: If the query_id is invalid
            TypeError: If query_id is not an integer
            ImportError: If required database driver is not installed
        """
        # Validate query_id
        if not isinstance(query_id, int):
            raise TypeError(f"query_id must be an integer, got {type(query_id).__name__}")
        if not (1 <= query_id <= 22):
            raise ValueError(f"Query ID must be 1-22, got {query_id}")

        # Validate connection_string
        if not isinstance(connection_string, str) or not connection_string.strip():
            raise ValueError("connection_string must be a non-empty string")

        return self._impl.run_query(
            query_id=query_id,
            connection_string=connection_string,
            params=params,
            dialect=dialect,
        )

    def run_benchmark(
        self,
        connection_string: str,
        queries: Optional[list[int]] = None,
        iterations: int = 1,
        dialect: str = "standard",
        schema: Optional[str] = None,
    ) -> dict[str, Any]:
        """Run the TPC-Havoc benchmark using base queries.

        Args:
            connection_string: Database connection string
            queries: Optional list of query IDs to run (default: all implemented)
            iterations: Number of times to run each query
            dialect: SQL dialect (standard, postgres, mysql, etc.)
            schema: Optional database schema to use

        Returns:
            Dictionary with benchmark results and timing information

        Raises:
            ValueError: If any query_id is invalid or iterations is not positive
            TypeError: If query_ids are not integers
            ImportError: If required database driver is not installed
        """
        # Validate connection_string
        if not isinstance(connection_string, str) or not connection_string.strip():
            raise ValueError("connection_string must be a non-empty string")

        # Validate iterations
        if not isinstance(iterations, int):
            raise TypeError(f"iterations must be an integer, got {type(iterations).__name__}")
        if iterations < 1:
            raise ValueError(f"iterations must be positive, got {iterations}")

        # Validate queries if provided
        if queries is not None:
            if not isinstance(queries, list):
                raise TypeError(f"queries must be a list, got {type(queries).__name__}")
            for query_id in queries:
                if not isinstance(query_id, int):
                    raise TypeError(f"query_id must be an integer, got {type(query_id).__name__}")
                if not (1 <= query_id <= 22):
                    raise ValueError(f"Query ID must be 1-22, got {query_id}")

        return self._impl.run_benchmark(
            connection_string=connection_string,
            queries=queries,
            iterations=iterations,
            dialect=dialect,
            schema=schema,
        )
