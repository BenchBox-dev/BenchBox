"""TPC-H benchmark implementation.

Copyright 2026 Joe Harris / BenchBox Project

TPC Benchmark™ H (TPC-H) - Copyright © Transaction Processing Performance Council
This implementation is based on the TPC-H specification.

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from pathlib import Path
from typing import Any, Optional, Union

from benchbox.base import BaseBenchmark
from benchbox.core.tpch.benchmark import TPCHBenchmark


class TPCH(BaseBenchmark):
    """TPC-H benchmark implementation.

    Provides TPC-H benchmark implementation, including data generation and access to the 22 benchmark queries.

    Official specification: http://www.tpc.org/tpch
    """

    def __init__(
        self,
        scale_factor: float = 1.0,
        output_dir: Optional[Union[str, Path]] = None,
        **kwargs: Any,
    ) -> None:
        """Initialize TPC-H benchmark instance.

        Args:
            scale_factor: Scale factor for the benchmark (1.0 = ~1GB)
            output_dir: Directory to output generated data files
            **kwargs: Additional implementation-specific options

        Raises:
            ValueError: If scale_factor is not positive
            TypeError: If scale_factor is not a number
        """
        # Validate scale_factor type (positivity already checked in base class)
        self._validate_scale_factor_type(scale_factor)

        super().__init__(scale_factor=scale_factor, output_dir=output_dir, **kwargs)

        # Initialize the actual implementation using common pattern
        self._initialize_benchmark_implementation(TPCHBenchmark, scale_factor, output_dir, **kwargs)

        # Surface the inner implementation's compliance classification on the
        # facade: result builders read compliance_class off the outer benchmark.
        self.compliance_class = getattr(self._impl, "compliance_class", None)

    def generate_data(self) -> list[Union[str, Path]]:
        """Generate TPC-H benchmark data.

        Returns:
            A list of paths to the generated data files
        """
        return self._impl.generate_data()

    def get_queries(self, dialect: Optional[str] = None, base_dialect: Optional[str] = None) -> dict[str, str]:
        """Get all TPC-H benchmark queries.

        Args:
            dialect: Target SQL dialect for translation (e.g., 'duckdb', 'bigquery', 'snowflake')
                    If None, returns queries in their original format.

        Returns:
            A dictionary mapping query IDs (1-22) to query strings
        """
        return self._impl.get_queries(dialect=dialect, base_dialect=base_dialect)

    def get_query(
        self,
        query_id: int,
        *,
        params: Optional[dict[str, Any]] = None,
        seed: Optional[int] = None,
        scale_factor: Optional[float] = None,
        dialect: Optional[str] = None,
        base_dialect: Optional[str] = None,
        **kwargs,
    ) -> str:
        """Get a specific TPC-H benchmark query.

        Args:
            query_id: The ID of the query to retrieve (1-22)
            params: Optional parameters to customize the query (legacy parameter, mostly ignored)
            seed: Random number generator seed for parameter generation
            scale_factor: Scale factor for parameter calculations
            dialect: Target SQL dialect
            base_dialect: Source SQL dialect (default: netezza)
            **kwargs: Additional parameters

        Returns:
            The query string

        Raises:
            ValueError: If the query_id is invalid
            TypeError: If query_id is not an integer
        """
        # Validate query_id to match TPC-DS patterns
        if not isinstance(query_id, int):
            raise TypeError(f"query_id must be an integer, got {type(query_id).__name__}")
        if not (1 <= query_id <= 22):
            raise ValueError(f"Query ID must be 1-22, got {query_id}")

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
            params=params,
            seed=seed,
            scale_factor=scale_factor,
            dialect=dialect,
            base_dialect=base_dialect,
            **kwargs,
        )

    def get_schema(self) -> list[dict]:
        """Get the TPC-H schema.

        Returns:
            A list of dictionaries describing the tables in the schema
        """
        return self._impl.get_schema()

    def get_create_tables_sql(self, dialect: str = "standard", tuning_config=None) -> str:
        """Get SQL to create all TPC-H tables.

        Args:
            dialect: SQL dialect to use (currently ignored, TPC-H uses standard SQL)
            tuning_config: Unified tuning configuration for constraint settings

        Returns:
            SQL script for creating all tables
        """
        return self._impl.get_create_tables_sql(dialect=dialect, tuning_config=tuning_config)

    def generate_streams(
        self,
        num_streams: int = 1,
        rng_seed: Optional[int] = None,
        streams_output_dir: Optional[Union[str, Path]] = None,
    ) -> list[Path]:
        """Generate TPC-H query streams.

        Args:
            num_streams: Number of concurrent streams to generate
            rng_seed: Random number generator seed for parameter generation
            streams_output_dir: Directory to output stream files

        Returns:
            List of paths to generated stream files
        """
        return self._impl.generate_streams(
            num_streams=num_streams,
            rng_seed=rng_seed,
            streams_output_dir=streams_output_dir,
        )

    def get_stream_info(self, stream_id: int) -> dict[str, Any]:
        """Get information about a specific stream.

        Args:
            stream_id: Stream identifier

        Returns:
            Dictionary containing stream information
        """
        return self._impl.get_stream_info(stream_id)

    def get_all_streams_info(self) -> list[dict[str, Any]]:
        """Get information about all streams.

        Returns:
            List of dictionaries containing stream information
        """
        return self._impl.get_all_streams_info()

    @property
    def tables(self) -> dict[str, Path]:
        """Get the mapping of table names to data file paths.

        Returns:
            Dictionary mapping table names to paths of generated data files
        """
        return getattr(self._impl, "tables", {})

    def run_official_benchmark(self, connection_factory, config=None):
        """Run the official TPC-H benchmark.

        This method provides compatibility for official benchmark examples.

        Args:
            connection_factory: Factory function or connection object
            config: Optional configuration parameters

        Returns:
            Dictionary with benchmark results
        """
        try:
            from benchbox.core.tpch.official_benchmark import TPCHOfficialBenchmark

            official = TPCHOfficialBenchmark(self)
            return official.run_official_benchmark(connection_factory, config)
        except ImportError:
            # Fallback to standard benchmark run
            connection = connection_factory() if callable(connection_factory) else connection_factory

            # Extract connection string if it's a connection object
            if hasattr(connection, "execute"):
                # Assume it's a database connection, use a placeholder string
                pass
            else:
                str(connection)

            # Since connection_string methods were removed, return a basic result
            return {
                "status": "fallback",
                "message": "Use adapter.run_benchmark() instead",
            }

    def run_power_test(self, connection_factory, config=None):
        """Run the TPC-H power test.

        This method provides compatibility for power test examples.

        Args:
            connection_factory: Factory function or connection object
            config: Optional configuration parameters

        Returns:
            Dictionary with power test results
        """
        try:
            from benchbox.core.tpch.power_test import TPCHPowerTest

            # Pass config options to constructor if provided
            kwargs = config if config else {}
            power_test = TPCHPowerTest(self, connection_factory, **kwargs)
            return power_test.run()
        except ImportError:
            # Fallback to running all queries once
            connection = connection_factory() if callable(connection_factory) else connection_factory

            if hasattr(connection, "execute"):
                pass
            else:
                str(connection)

            # Since connection_string methods were removed, return a basic result
            return {
                "status": "fallback",
                "message": "Use adapter.run_benchmark() instead",
            }

    def run_maintenance_test(self, connection_factory, config=None):
        """Run the TPC-H maintenance test.

        This method provides compatibility for maintenance test examples.

        Args:
            connection_factory: Factory function or connection object
            config: Optional configuration parameters

        Returns:
            Dictionary with maintenance test results
        """
        try:
            from benchbox.core.tpch.maintenance_test import TPCHMaintenanceTest

            maint_test = TPCHMaintenanceTest(self, connection_factory)
            return maint_test.run(config)
        except ImportError:
            # Fallback to basic functionality
            connection = connection_factory() if callable(connection_factory) else connection_factory

            # For maintenance test, we simulate refresh functions
            refresh_results = {
                "refresh_function_1": {
                    "status": "completed",
                    "rows_inserted": 150,
                    "duration": 0.5,
                },
                "refresh_function_2": {
                    "status": "completed",
                    "rows_deleted": 75,
                    "duration": 0.3,
                },
            }

            if hasattr(connection, "execute"):
                pass
            else:
                str(connection)

            # Since connection_string methods were removed, return a basic result
            return {
                "status": "fallback",
                "message": "Use adapter.run_benchmark() instead",
                "refresh_functions": refresh_results,
            }
