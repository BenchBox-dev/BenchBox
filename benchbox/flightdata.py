"""Flight Data OLAP benchmark.

US Bureau of Transportation Statistics On-Time Performance data for aviation analytics.
Uses real BTS data (or synthetic fallback) covering decades of US domestic flight history.

Example:
    >>> from benchbox import FlightData
    >>> from benchbox.platforms.duckdb import DuckDBAdapter
    >>>
    >>> # Create benchmark (SF=1 ≈ 1.5 years of data, ~10M flights)
    >>> benchmark = FlightData(scale_factor=1.0)
    >>>
    >>> # Download/generate data
    >>> data_files = benchmark.generate_data()
    >>>
    >>> # Run with platform adapter
    >>> adapter = DuckDBAdapter()
    >>> adapter.load_benchmark(benchmark)
    >>>
    >>> # Execute queries
    >>> for query_id, query in benchmark.get_queries().items():
    ...     result = adapter.execute_query(query)

Scale factors:
- SF=0.01: ~1 week    ~140K flights   ~10MB    (synthetic, CI)
- SF=0.1:  ~2 months  ~1.2M flights   ~100MB   (development)
- SF=1.0:  ~1.5 years ~10M flights    ~1GB     (standard)
- SF=10:   ~15 years  ~100M flights   ~10GB    (large scale)
- SF=100:  Full data  ~200M flights   ~15-20GB (maximum)

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from pathlib import Path
from typing import Any, Optional, Union

from benchbox.base import BaseBenchmark
from benchbox.core.flightdata.benchmark import FlightDataBenchmark


class FlightData(BaseBenchmark):
    """Flight Data OLAP benchmark for US aviation analytics.

    Implements BTS On-Time Performance workloads:
    - 20 representative OLAP queries
    - On-time performance analysis
    - Delay cause attribution
    - Route and airport analytics
    - Seasonal and temporal patterns
    - Carrier comparisons

    Query categories:
        - ontime: On-time performance (5 queries)
        - delay: Delay analysis (4 queries)
        - routes: Route analytics (4 queries)
        - temporal: Time patterns (4 queries)
        - carriers: Carrier comparisons (3 queries)
    """

    def __init__(
        self,
        scale_factor: float = 1.0,
        output_dir: Optional[Union[str, Path]] = None,
        end_year: int = 2024,
        **kwargs: Any,
    ) -> None:
        """Initialize Flight Data benchmark.

        Args:
            scale_factor: Scale factor (1.0 ≈ 1.5 years of data, ~10M flights)
            output_dir: Directory for data files
            end_year: Most recent year to include (default: 2024)
            **kwargs: Additional options:
                - seed: Random seed for reproducibility
                - verbose: Verbosity level
                - force_regenerate: Force data regeneration
        """
        super().__init__(scale_factor=scale_factor, output_dir=output_dir, **kwargs)

        self._initialize_benchmark_implementation(
            FlightDataBenchmark,
            scale_factor,
            output_dir,
            end_year=end_year,
            **kwargs,
        )

    def generate_data(self) -> list[Union[str, Path]]:
        """Download or generate flight data.

        Downloads real BTS data when SF >= 0.1, uses synthetic data for
        smaller scale factors or when BTS is unavailable.

        Returns:
            List of paths to data files (flights.csv, airlines.csv, airports.csv)
        """
        return self._impl.generate_data()

    def get_queries(self, dialect: Optional[str] = None) -> dict[str, str]:
        """Get all benchmark queries.

        Args:
            dialect: SQL dialect (not used - queries are standard SQL)

        Returns:
            Dictionary mapping query keys to parameterized SQL strings
        """
        return self._impl.get_queries(dialect)

    def get_query(
        self,
        query_id: Union[int, str],
        *,
        params: Optional[dict[str, Any]] = None,
        **kwargs: Any,
    ) -> str:
        """Get a specific benchmark query.

        Args:
            query_id: Query key (e.g., "ontime-by-carrier") or numeric ID ("1"-"20")
            params: Optional parameter overrides
            **kwargs: Additional arguments

        Returns:
            Parameterized SQL string

        Raises:
            ValueError: If query_id is not found
        """
        return self._impl.get_query(query_id, params=params, **kwargs)

    def get_schema(self) -> dict[str, Any]:
        """Get the flight data schema.

        Returns:
            Schema dictionary with table definitions:
            - flights: Fact table with 27 columns
            - airlines: Carrier dimension table
            - airports: Airport dimension table with coordinates
        """
        return self._impl.get_schema()

    def get_create_tables_sql(
        self,
        dialect: str = "standard",
        tuning_config: Any = None,
    ) -> str:
        """Get SQL to create all benchmark tables.

        Args:
            dialect: SQL dialect (standard, duckdb, postgres, clickhouse, snowflake)
            tuning_config: Optional tuning configuration

        Returns:
            SQL script for creating tables
        """
        return self._impl.get_create_tables_sql(dialect=dialect, tuning_config=tuning_config)

    def get_benchmark_info(self) -> dict[str, Any]:
        """Get benchmark metadata.

        Returns:
            Dictionary with benchmark information including scale factor,
            date range, query count, and data source details.
        """
        return self._impl.get_benchmark_info()

    def get_query_info(self, query_id: str) -> dict[str, Any]:
        """Get metadata for a specific query.

        Args:
            query_id: Query identifier

        Returns:
            Dictionary with name, description, category, and key
        """
        return self._impl.get_query_info(query_id)

    def get_queries_by_category(self, category: str) -> list[str]:
        """Get query keys for a specific category.

        Available categories:
        - ontime: On-time performance (5 queries)
        - delay: Delay analysis (4 queries)
        - routes: Route analytics (4 queries)
        - temporal: Temporal patterns (4 queries)
        - carriers: Carrier comparisons (3 queries)

        Args:
            category: Category name

        Returns:
            List of query keys in that category
        """
        return self._impl.get_queries_by_category(category)

    def get_download_stats(self) -> dict[str, Any]:
        """Get statistics about data download/generation.

        Returns:
            Dictionary with months downloaded, synthetic, and total flights
        """
        return self._impl.get_download_stats()

    @property
    def tables(self) -> dict[str, Path]:
        """Get mapping of table names to data file paths."""
        return getattr(self._impl, "tables", {})
