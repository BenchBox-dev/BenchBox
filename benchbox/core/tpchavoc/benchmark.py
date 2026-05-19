"""TPC-Havoc benchmark implementation module.

Provides TPC-Havoc benchmark implementation that generates
TPC-H query variants to stress query optimizers.

Copyright 2026 Joe Harris / BenchBox Project

This implementation is derived from TPC Benchmark™ H (TPC-H) - Copyright © Transaction Processing Performance Council

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import contextlib
from pathlib import Path
from typing import Any, Union

from benchbox.core.tpch.benchmark import TPCHBenchmark
from benchbox.core.tpchavoc.queries import TPCHavocQueryManager
from benchbox.core.tpchavoc.validation import ResultValidator, ValidationReport
from benchbox.sql_compat.rules.execution_filter.lakesail_tpchavoc import LAKESAIL_TPCHAVOC_SKIPS
from benchbox.sql_compat.rules.execution_filter.postgres_tpchavoc import POSTGRES_TPCHAVOC_SKIPS


class TPCHavocBenchmark(TPCHBenchmark):
    """TPC-Havoc benchmark implementation.

    Extends TPC-H benchmark with query variants that stress
    query optimizers while maintaining result equivalence.

    TPC-Havoc provides 10 structural variants for each TPC-H query (1-22).
    Each variant is semantically equivalent but uses different SQL constructs
    to stress different optimizer components (join orders, subquery strategies,
    aggregation methods, etc.).

    Usage:
        Execute TPC-Havoc queries through platform adapters following the
        BenchBox architecture pattern:

        >>> from benchbox import TPCHavoc
        >>> from benchbox.platforms.duckdb import DuckDBAdapter
        >>>
        >>> # Initialize benchmark and platform
        >>> benchmark = TPCHavoc(scale_factor=1.0)
        >>> adapter = DuckDBAdapter(database=":memory:")
        >>>
        >>> # Load data using platform adapter
        >>> adapter.load_benchmark(benchmark)
        >>>
        >>> # Execute original TPC-H query
        >>> original_query = benchmark.get_query(1)
        >>> original_results = adapter.execute_query(original_query)
        >>>
        >>> # Execute TPC-Havoc variant
        >>> variant_query = benchmark.get_query_variant(query_id=1, variant_id=1)
        >>> variant_results = adapter.execute_query(variant_query)
        >>>
        >>> # Validate result equivalence
        >>> is_valid = benchmark.validate_variant_equivalence(
        ...     query_id=1,
        ...     variant_id=1,
        ...     original_results=original_results,
        ...     variant_results=variant_results
        ... )
        >>>
        >>> # Export all variants for analysis
        >>> exported = benchmark.export_variant_queries(
        ...     output_dir="./queries",
        ...     format="sql"
        ... )

    Attributes:
        scale_factor: Scale factor (1.0 = ~1GB)
        output_dir: Data output directory
        query_manager: TPC-Havoc query manager
        data_generator: TPC-H data generator (inherited)
        tables: Table name to data file path mapping
        validator: Result validator for variant equivalence
    """

    def __init__(
        self,
        scale_factor: float = 1.0,
        output_dir: Union[str, Path] | None = None,
        verbose: int | bool = 0,
        parallel: int = 1,
        validation_tolerance: float = 1e-10,
        **kwargs: Any,
    ) -> None:
        """Initialize TPC-Havoc benchmark instance.

        Args:
            scale_factor: Scale factor (1.0 = ~1GB)
            output_dir: Data output directory
            verbose: Verbosity level (-v=1, -vv=2)
            parallel: Parallel processes for data generation
            validation_tolerance: Tolerance for floating-point result validation
            **kwargs: Additional options
        """
        super().__init__(
            scale_factor=scale_factor,
            output_dir=output_dir,
            verbose=verbose,
            parallel=parallel,
            **kwargs,
        )

        # Override inherited TPC-H name
        self._name = "TPC-Havoc Benchmark"

        # Replace the TPC-H query manager with TPC-Havoc query manager
        self.query_manager = TPCHavocQueryManager()

        # Initialize validation components
        self.validator = ResultValidator(tolerance=validation_tolerance)
        self.validation_report = ValidationReport()

    def get_platform_skip_queries(self, platform_name: str) -> list[str]:
        """Return platform-specific TPC-Havoc variants excluded by compatibility policy."""
        platform = platform_name.lower().replace("_", "-")
        if platform == "lakesail":
            return list(LAKESAIL_TPCHAVOC_SKIPS)
        if platform in {"pg-duckdb", "pg-mooncake", "timescaledb"}:
            return list(POSTGRES_TPCHAVOC_SKIPS)
        return []

    def get_query(
        self,
        query_id,
        *,
        seed: int | None = None,
        scale_factor: float | None = None,
        **kwargs,
    ) -> str:
        """Get TPC-Havoc query by ID.

        Overrides the parent to handle both regular query IDs (1-22) and
        variant query IDs in the format "Q_VID" (e.g., "1_v1", "1_v2").

        Args:
            query_id: Query ID as int (1-22) or string ("1_v1", "1_v2", etc.)
            seed: Random number generator seed for parameter generation
            scale_factor: Scale factor for parameter calculations
            **kwargs: Additional arguments

        Returns:
            The query string

        Raises:
            ValueError: If the query_id format is invalid
            TypeError: If parameters have wrong types
        """
        return self.query_manager.get_query(
            query_id,
            seed=seed,
            scale_factor=scale_factor or self.scale_factor,
            **kwargs,
        )

    def get_query_variant(self, query_id: int, variant_id: int, params: dict[str, Any] | None = None) -> str:
        """Get a specific TPC-Havoc query variant.

        Args:
            query_id: The ID of the query to retrieve (1-22)
            variant_id: The ID of the variant to retrieve (1-10)
            params: Optional parameter values to use

        Returns:
            The variant query string

        Raises:
            ValueError: If the query_id or variant_id is invalid
        """
        return self.query_manager.get_query_variant(query_id, variant_id, params)

    def get_all_variants(self, query_id: int) -> dict[int, str]:
        """Get all variants for a specific query.

        Args:
            query_id: The ID of the query to retrieve variants for (1-22)

        Returns:
            A dictionary mapping variant IDs to query strings

        Raises:
            ValueError: If the query_id is invalid or not implemented
        """
        return self.query_manager.get_all_variants(query_id)

    def get_variant_description(self, query_id: int, variant_id: int) -> str:
        """Get description of a specific variant.

        Args:
            query_id: The ID of the query (1-22)
            variant_id: The ID of the variant (1-10)

        Returns:
            Human-readable description of the variant

        Raises:
            ValueError: If the query_id or variant_id is invalid
        """
        return self.query_manager.get_variant_description(query_id, variant_id)

    def get_implemented_queries(self) -> list[int]:
        """Get list of query IDs that have variants implemented.

        Returns:
            List of query IDs with implemented variants
        """
        return self.query_manager.get_implemented_queries()

    def supports_dataframe_mode(self) -> bool:
        """TPC-Havoc supports DataFrame execution mode."""
        return True

    def get_dataframe_queries(self):
        """Get DataFrame query variants for TPC-Havoc.

        Returns the QueryRegistry containing 10 DataFrame variants for each
        TPC-H query, using the same TPC-H data and parameters as SQL mode.
        """
        from benchbox.core.tpchavoc.dataframe_queries import get_dataframe_queries

        return get_dataframe_queries()

    def get_all_variants_info(self, query_id: int) -> dict[int, dict[str, str]]:
        """Get information about all variants for a specific query.

        Args:
            query_id: The ID of the query (1-22)

        Returns:
            Dictionary mapping variant IDs to variant info

        Raises:
            ValueError: If the query_id is invalid or not implemented
        """
        return self.query_manager.get_all_variants_info(query_id)

    def validate_variant_equivalence(
        self,
        query_id: int,
        variant_id: int,
        original_results: list[tuple[Any, ...]],
        variant_results: list[tuple[Any, ...]],
        use_checksum: bool = False,
    ) -> bool:
        """Validate that a variant produces the same results as the original.

        Args:
            query_id: The query ID being validated
            variant_id: The variant ID being validated
            original_results: Results from the original TPC-H query
            variant_results: Results from the variant query
            use_checksum: Whether to use checksum validation for large result sets

        Returns:
            True if results match

        Raises:
            ValidationError: If results don't match
        """
        if use_checksum:
            return self.validator.validate_results_checksum(original_results, variant_results, query_id, variant_id)
        elif query_id == 1:
            # Use specialized validation for Query 1
            return self.validator.validate_query1_results(original_results, variant_results, variant_id)
        else:
            return self.validator.validate_results_exact(original_results, variant_results, query_id, variant_id)

    def get_benchmark_info(self) -> dict[str, Any]:
        """Get information about the TPC-Havoc benchmark.

        Returns:
            Dictionary containing benchmark metadata
        """
        implemented_queries = self.get_implemented_queries()

        variants_info = {}
        for query_id in implemented_queries:
            variants_info[query_id] = self.get_all_variants_info(query_id)

        return {
            "benchmark_name": "TPC-Havoc",
            "base_benchmark": "TPC-H",
            "scale_factor": self.scale_factor,
            "implemented_queries": implemented_queries,
            "total_queries_with_variants": len(implemented_queries),
            "variants_per_query": 10,
            "total_query_variants": len(implemented_queries) * 10,
            "variants_info": variants_info,
            "validation_tolerance": self.validator.tolerance,
            "description": (
                "TPC-Havoc generates 10 structural variants of each TPC-H query "
                "to stress different aspects of query optimizers while maintaining "
                "result equivalence."
            ),
        }

    def export_variant_queries(
        self, output_dir: Union[str, Path] | None = None, format: str = "sql"
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
        if format not in ["sql", "json"]:
            raise ValueError(f"Unsupported export format: {format}")

        output_dir = self.output_dir / "queries" if output_dir is None else Path(output_dir)

        output_dir.mkdir(parents=True, exist_ok=True)

        exported_files = {}

        for query_id in self.get_implemented_queries():
            variants = self.get_all_variants(query_id)

            for variant_id, query_text in variants.items():
                if format == "sql":
                    filename = f"q{query_id}_variant_{variant_id}.sql"
                    filepath = output_dir / filename

                    # Add header comment with variant description
                    description = self.get_variant_description(query_id, variant_id)
                    content = f"-- TPC-Havoc Query {query_id} Variant {variant_id}\n"
                    content += f"-- {description}\n\n"
                    content += query_text

                    with filepath.open("w") as f:
                        f.write(content)

                    exported_files[f"Q{query_id}.{variant_id}"] = filepath

        self.log_verbose(f"Exported {len(exported_files)} variant queries to {output_dir}")

        return exported_files

    def _check_compatible_tpch_database(self, connection) -> bool:
        """Check if an existing TPC-H database is compatible with TPC-Havoc requirements.

        TPC-Havoc extends TPC-H with query variants, so it can reuse an existing TPC-H database
        if the configuration matches (scale factor, tuning settings, constraints).

        Args:
            connection: Database connection to check

        Returns:
            True if compatible TPC-H database exists and can be reused
        """
        try:
            from benchbox.core.connection import DatabaseConnection

            # Wrap connection if needed
            if not hasattr(connection, "execute") or not hasattr(connection, "commit"):
                # Try to wrap with DatabaseConnection
                try:
                    connection = DatabaseConnection(connection)
                except Exception:
                    # If wrapping fails, assume connection is usable as-is
                    pass
        except ImportError:
            # If DatabaseConnection import fails, use connection as-is
            pass

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
                        return False
                except Exception:
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
                    return False

                self.log_verbose(
                    f"Found compatible TPC-H database with {lineitem_count:,} lineitem rows (scale factor {self.scale_factor})"
                )
                return True

            except Exception:
                return False

        except Exception:
            return False

    def _load_data(self, connection) -> None:
        """Load TPC-Havoc data into the database.

        This method first checks if a compatible TPC-H database already exists and can be reused.
        If not, it delegates to the parent TPC-H implementation to load the data.

        Args:
            connection: Database connection or DatabaseConnection wrapper
        """
        import logging

        logger = logging.getLogger(__name__)

        # Try to wrap connection if needed
        try:
            from benchbox.core.connection import DatabaseConnection

            if not hasattr(connection, "execute") or not hasattr(connection, "commit"):
                with contextlib.suppress(Exception):
                    connection = DatabaseConnection(connection)
        except ImportError:
            pass

        # Check if we can reuse an existing compatible TPC-H database
        if self._check_compatible_tpch_database(connection):
            logger.info("Reusing existing compatible TPC-H database for TPC-Havoc benchmark")
            return

        # Fall back to parent TPC-H data loading
        logger.info("Loading TPC-H data for TPC-Havoc benchmark...")
        super()._load_data(connection)

    def _validate_database_configuration_compatibility(self, other_config: dict) -> bool:
        """Validate that another benchmark's database configuration is compatible with TPC-Havoc.

        TPC-Havoc can reuse TPC-H databases with matching scale factor and configuration.

        Args:
            other_config: Configuration from another benchmark

        Returns:
            True if the configurations are compatible
        """
        # Check if it's a TPC-H compatible benchmark
        benchmark_type = other_config.get("benchmark_type", "").lower()
        if benchmark_type not in ["tpch", "tpc-h", "tpchavoc", "tpc-havoc"]:
            return False

        # Check scale factor compatibility
        other_scale = other_config.get("scale_factor")
        if other_scale != self.scale_factor:
            return False

        # Check tuning configuration compatibility
        # This would use the same logic as the platform adapter's tuning validation
        return True
