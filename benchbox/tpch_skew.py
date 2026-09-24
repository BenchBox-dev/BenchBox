"""TPC-H Skew benchmark implementation.

This module provides the public interface for the TPC-H Skew benchmark,
which extends TPC-H with configurable data skew patterns.

Based on the research: "Introducing Skew into the TPC-H Benchmark"
Reference: https://www.tpc.org/tpctc/tpctc2011/slides_and_papers/introducing_skew_into_the_tpc_h_benchmark.pdf

Example:
    >>> from benchbox import TPCHSkew
    >>> from benchbox.platforms.duckdb import DuckDBAdapter
    >>>
    >>> # Create benchmark with moderate skew (default)
    >>> benchmark = TPCHSkew(scale_factor=1.0)
    >>>
    >>> # Or use a specific preset
    >>> benchmark = TPCHSkew(scale_factor=1.0, skew_preset="heavy")
    >>>
    >>> # Or use custom configuration
    >>> from benchbox.core.tpch_skew import SkewConfiguration
    >>> config = SkewConfiguration(skew_factor=0.7, distribution_type="zipfian")
    >>> benchmark = TPCHSkew(scale_factor=1.0, skew_config=config)
    >>>
    >>> # Generate skewed data
    >>> data_files = benchmark.generate_data()
    >>>
    >>> # Run benchmark using platform adapter
    >>> adapter = DuckDBAdapter(database=":memory:")
    >>> adapter.load_benchmark(benchmark)
    >>> results = adapter.run_benchmark(benchmark)
    >>>
    >>> # Get skew information
    >>> emit(benchmark.get_skew_info())

Copyright 2026 Joe Harris / BenchBox Project

TPC Benchmark™ H (TPC-H) - Copyright © Transaction Processing Performance Council
This implementation extends the TPC-H specification with skew distributions.

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from pathlib import Path
from typing import Any, Optional, Union

from benchbox.base import BaseBenchmark
from benchbox.core.tpch_skew.benchmark import TPCHSkewBenchmark
from benchbox.core.tpch_skew.skew_config import SkewConfiguration


class TPCHSkew(BaseBenchmark):
    """TPC-H Skew benchmark implementation.

    Extends TPC-H with configurable data skew to test database
    performance under realistic data distribution patterns.

    Available skew presets:
    - none: Uniform distribution (standard TPC-H)
    - light: Light skew (z=0.2)
    - moderate: Moderate skew (z=0.5) [default]
    - heavy: Heavy skew (z=0.8)
    - extreme: Extreme skew (z=1.0, Zipf's law)
    - realistic: Realistic e-commerce patterns

    Official TPC-H specification: http://www.tpc.org/tpch
    Skew methodology: https://www.tpc.org/tpctc/tpctc2011/
    """

    def __init__(
        self,
        scale_factor: float = 1.0,
        output_dir: Optional[Union[str, Path]] = None,
        skew_preset: Optional[str] = None,
        skew_config: Optional[SkewConfiguration] = None,
        **kwargs: Any,
    ) -> None:
        """Initialize TPC-H Skew benchmark instance.

        Args:
            scale_factor: Scale factor for the benchmark (1.0 = ~1GB)
            output_dir: Directory to output generated data files
            skew_preset: Preset name ("none", "light", "moderate", "heavy",
                        "extreme", "realistic"). Default: "moderate"
            skew_config: Custom SkewConfiguration (overrides preset)
            **kwargs: Additional implementation-specific options:
                - verbose: int|bool - Verbosity level
                - parallel: int - Parallel processes for data generation
                - force_regenerate: bool - Force data regeneration

        Raises:
            ValueError: If scale_factor is not positive or preset is invalid
            TypeError: If scale_factor is not a number
        """
        # Validate scale_factor type
        self._validate_scale_factor_type(scale_factor)

        super().__init__(scale_factor=scale_factor, output_dir=output_dir, **kwargs)

        # Initialize the actual implementation
        self._initialize_benchmark_implementation(
            TPCHSkewBenchmark,
            scale_factor,
            output_dir,
            skew_preset=skew_preset,
            skew_config=skew_config,
            **kwargs,
        )

    def generate_data(self) -> list[Union[str, Path]]:
        """Generate TPC-H benchmark data with skew applied.

        Returns:
            A list of paths to the generated data files
        """
        return self._impl.generate_data()

    def get_queries(self, dialect: Optional[str] = None, base_dialect: Optional[str] = None) -> dict[str, str]:
        """Get all TPC-H benchmark queries.

        The standard TPC-H queries (1-22) are used unchanged,
        allowing comparison between uniform and skewed data.

        Args:
            dialect: Target SQL dialect for translation
            base_dialect: Source SQL dialect (default: netezza)

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
            params: Optional parameters to customize the query
            seed: Random number generator seed for parameter generation
            scale_factor: Scale factor for parameter calculations
            dialect: Target SQL dialect
            base_dialect: Source SQL dialect (default: netezza)
            **kwargs: Additional parameters

        Returns:
            The query string

        Raises:
            ValueError: If the query_id is invalid (not 1-22)
            TypeError: If query_id is not an integer
        """
        # Validate query_id
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

    def get_schema(self) -> dict[str, dict[str, Any]]:
        """Get the TPC-H schema.

        The schema is identical to standard TPC-H.

        Returns:
            Dictionary mapping table names to table definitions
        """
        return self._impl.get_schema()

    def get_create_tables_sql(self, dialect: str = "standard", tuning_config=None) -> str:
        """Get SQL to create all TPC-H tables.

        Args:
            dialect: SQL dialect to use
            tuning_config: Unified tuning configuration

        Returns:
            SQL script for creating all tables
        """
        return self._impl.get_create_tables_sql(dialect=dialect, tuning_config=tuning_config)

    def get_skew_info(self) -> dict[str, Any]:
        """Get information about the skew configuration.

        Returns:
            Dictionary containing:
            - preset: Name of preset used
            - skew_factor: Overall skew factor (0-1)
            - distribution_type: Type of distribution used
            - attribute_skew_enabled: Whether attribute skew is enabled
            - join_skew_enabled: Whether join skew is enabled
            - temporal_skew_enabled: Whether temporal skew is enabled
            - config_summary: Detailed configuration summary
        """
        return self._impl.get_skew_info()

    def manifest_matches_datagen_identity(self, manifest: dict[str, Any]) -> bool:
        """Return whether ``manifest`` was generated from this skew configuration."""
        return self._impl.manifest_matches_datagen_identity(manifest)

    def get_benchmark_info(self) -> dict[str, Any]:
        """Get information about the benchmark.

        Returns:
            Dictionary containing benchmark metadata
        """
        return self._impl.get_benchmark_info()

    @property
    def tables(self) -> dict[str, Path]:
        """Get the mapping of table names to data file paths.

        Returns:
            Dictionary mapping table names to paths of generated data files
        """
        return getattr(self._impl, "tables", {})

    @property
    def skew_preset(self) -> str:
        """Get the skew preset name.

        Returns:
            Name of the skew preset used
        """
        return self._impl.skew_preset

    @property
    def skew_config(self) -> SkewConfiguration:
        """Get the skew configuration.

        Returns:
            The SkewConfiguration instance
        """
        return self._impl.skew_config

    def compare_with_uniform(
        self,
        adapter,
        queries: Optional[list[int]] = None,
        iterations: int = 1,
    ) -> dict[str, Any]:
        """Run comparison between skewed and uniform TPC-H data.

        This method orchestrates running the same queries on both uniform
        (standard TPC-H) and skewed data to measure performance differences.
        It uses the existing TPCHBenchmark for uniform data generation.

        Args:
            adapter: Platform adapter to use for query execution
            queries: List of query IDs to run (1-22). Default: all 22 queries
            iterations: Number of times to run each query for averaging. Default: 1

        Returns:
            Dictionary with comparison results:
            - queries: List of query IDs compared
            - scale_factor: Scale factor used
            - skew_preset: Skew preset name
            - skew_config: Skew configuration details
            - uniform_results: Query timing results on uniform data
            - skewed_results: Query timing results on skewed data
            - comparison: Per-query comparison with timing ratios
            - summary: Aggregate statistics including avg_ratio, geometric_mean_ratio

        Raises:
            ValueError: If adapter is None, queries are invalid, or iterations < 1
            RuntimeError: If benchmark execution fails

        Example:
            >>> from benchbox import TPCHSkew
            >>> from benchbox.platforms.duckdb import DuckDBAdapter
            >>>
            >>> benchmark = TPCHSkew(scale_factor=0.01, skew_preset="heavy")
            >>> adapter = DuckDBAdapter(database=":memory:")
            >>>
            >>> # Compare queries 1, 6, and 14
            >>> results = benchmark.compare_with_uniform(adapter, queries=[1, 6, 14])
            >>> emit(results["summary"]["avg_ratio"])
        """
        return self._impl.compare_with_uniform(
            adapter=adapter,
            queries=queries,
            iterations=iterations,
        )

    @staticmethod
    def get_available_presets() -> list[str]:
        """Get list of available skew presets.

        Returns:
            List of preset names: ["none", "light", "moderate", "heavy", "extreme", "realistic"]
        """
        return TPCHSkewBenchmark.get_available_presets()

    @staticmethod
    def get_preset_description(preset_name: str) -> str:
        """Get description of a skew preset.

        Args:
            preset_name: Name of the preset

        Returns:
            Human-readable description

        Raises:
            ValueError: If preset name is invalid
        """
        return TPCHSkewBenchmark.get_preset_description(preset_name)
