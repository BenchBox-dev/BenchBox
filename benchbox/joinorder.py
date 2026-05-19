"""Join Order Benchmark top-level interface.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from pathlib import Path
from typing import Any, Optional, Union

from benchbox.base import BaseBenchmark
from benchbox.core.joinorder.benchmark import JoinOrderBenchmark


class JoinOrder(BaseBenchmark):
    """Canonical IMDb 2013 Join Order Benchmark implementation.

    This class provides access to the canonical JOB data package and complex
    join queries for cardinality estimation and join-order optimization testing.

    Reference: Viktor Leis et al. "How Good Are Query Optimizers, Really?"
    """

    def __init__(
        self,
        scale_factor: float = 1.0,
        output_dir: Optional[Union[str, Path]] = None,
        **kwargs: Any,
    ) -> None:
        """Initialize a Join Order Benchmark instance.

        Args:
            scale_factor: Canonical JoinOrder accepts only 1.0.
            output_dir: Directory for verified canonical Parquet files.
            **kwargs: Additional implementation-specific options
        """
        super().__init__(scale_factor=scale_factor, output_dir=output_dir, **kwargs)

        # Initialize the actual implementation
        verbose = kwargs.pop("verbose", False)
        self._impl = JoinOrderBenchmark(scale_factor=scale_factor, output_dir=output_dir, verbose=verbose, **kwargs)

    def generate_data(self) -> list[Path]:
        """Ensure canonical JoinOrder data is downloaded and verified.

        Returns:
            A list of paths to the generated data files
        """
        return self._impl.generate_data()

    def get_queries(self) -> dict[str, str]:
        """Get all Join Order Benchmark queries.

        Returns:
            A dictionary mapping query IDs to query strings
        """
        return self._impl.get_queries()

    def get_query(self, query_id: Union[int, str], *, params: Optional[dict[str, Any]] = None) -> str:
        """Get a specific Join Order Benchmark query.

        Args:
            query_id: The ID of the query to retrieve
            params: Optional parameters to customize the query

        Returns:
            The query string

        Raises:
            ValueError: If the query_id is invalid
        """
        return self._impl.get_query(query_id, params=params)

    def get_schema(self, dialect: str = "sqlite") -> str:
        """Get the Join Order Benchmark schema DDL.

        Args:
            dialect: Target SQL dialect

        Returns:
            DDL statements for creating all tables
        """
        return self._impl.get_create_tables_sql(dialect=dialect)

    def get_create_tables_sql(self, dialect: str = "standard", tuning_config: Any = None) -> str:
        """Get SQL to create all Join Order Benchmark tables.

        Args:
            dialect: SQL dialect to use
            tuning_config: Unified tuning configuration for constraint settings

        Returns:
            SQL script for creating all tables
        """
        return self._impl.get_create_tables_sql(dialect=dialect)


__all__ = ["JoinOrder"]
