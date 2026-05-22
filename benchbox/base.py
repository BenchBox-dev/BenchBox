"""Base class for all benchmarks.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional, Union

from benchbox.core.connection import DatabaseConnection
from benchbox.utils.clock import elapsed_seconds, mono_time
from benchbox.utils.cloud_storage import create_path_handler
from benchbox.utils.scale_factor import format_scale_factor
from benchbox.utils.verbosity import VerbosityMixin, compute_verbosity

BENCHMARK_API_SURFACE = "beta-public"
RUN_WITH_PLATFORM_API_SURFACE = "beta-public"

if TYPE_CHECKING:
    import sqlglot

    from benchbox.core.results.models import BenchmarkResults
    from benchbox.core.validation import ValidationResult
else:
    try:
        import sqlglot
    except ImportError:
        sqlglot = None


class BaseBenchmark(VerbosityMixin, ABC):
    """Base class for all benchmarks.

    All benchmarks inherit from this class.
    """

    api_surface = BENCHMARK_API_SURFACE
    run_with_platform_api_surface = RUN_WITH_PLATFORM_API_SURFACE

    def __init__(
        self,
        scale_factor: float = 1.0,
        output_dir: Optional[Union[str, Path]] = None,
        **kwargs: Any,
    ) -> None:
        """Initialize a benchmark.

        Args:
            scale_factor: Scale factor (1.0 = standard size)
            output_dir: Data output directory
            **kwargs: Additional options
        """
        if scale_factor <= 0:
            raise ValueError("Scale factor must be positive")

        # Validate that scale factors >= 1 are whole integers
        if scale_factor >= 1 and scale_factor != int(scale_factor):
            raise ValueError(
                f"Scale factors >= 1 must be whole integers. Got: {scale_factor}. "
                f"Use values like 1, 2, 10, etc. for large scale factors. "
                f"Use values like 0.1, 0.01, 0.001, etc. for small scale factors."
            )

        self.scale_factor = scale_factor

        if output_dir is None:
            # Use CLI-compatible default path: benchmark_runs/datagen/{benchmark}_{sf}
            benchmark_name = self._get_benchmark_name().lower()
            sf_str = format_scale_factor(scale_factor)
            self.output_dir = Path.cwd() / "benchmark_runs" / "datagen" / f"{benchmark_name}_{sf_str}"
        else:
            # Support both local and cloud storage paths
            self.output_dir = create_path_handler(output_dir)

        # Verbosity and quiet handling (normalize bool/int)
        verbose_value = kwargs.pop("verbose", 0)
        quiet_value = kwargs.pop("quiet", False)
        verbosity_settings = compute_verbosity(verbose_value, quiet_value)
        self.apply_verbosity(verbosity_settings)

        # Logger for core benchmarks
        self.logger = logging.getLogger(f"benchbox.core.{self._get_benchmark_name()}")

        # Store remaining kwargs as attributes
        for key, value in kwargs.items():
            setattr(self, key, value)

    def _validate_scale_factor_type(self, scale_factor: float) -> None:
        """Validate scale factor is a number (int or float).

        Args:
            scale_factor: Scale factor to validate

        Raises:
            TypeError: If scale_factor is not a number
        """
        if not isinstance(scale_factor, (int, float)):
            raise TypeError(f"scale_factor must be a number, got {type(scale_factor).__name__}")

    def _initialize_benchmark_implementation(
        self,
        implementation_class,
        scale_factor: float,
        output_dir: Optional[Union[str, Path]],
        **kwargs,
    ):
        """Common initialization pattern for benchmark implementations.

        Args:
            implementation_class: The benchmark implementation class to instantiate
            scale_factor: Scale factor for the benchmark
            output_dir: Directory to output generated data files
            **kwargs: Additional implementation-specific options
        """
        # Extract verbose and force_regenerate from kwargs to avoid passing them twice
        verbose = kwargs.pop("verbose", False)
        force_regenerate = kwargs.pop("force_regenerate", False)

        self._impl = implementation_class(
            scale_factor=scale_factor,
            output_dir=output_dir,
            verbose=verbose,
            force_regenerate=force_regenerate,
            **kwargs,
        )

    @property
    def tables(self) -> dict:
        """Table-to-path mappings.

        Delegates to ``_impl.tables`` when a wrapper benchmark holds an
        implementation object; otherwise returns the instance's own ``_tables``
        dict (empty dict when unset).
        """
        if hasattr(self, "_impl") and hasattr(self._impl, "tables"):
            return self._impl.tables
        return getattr(self, "_tables", {})

    @tables.setter
    def tables(self, value: dict) -> None:
        if hasattr(self, "_impl"):
            self._impl.tables = value
        else:
            self._tables = value

    @property
    def csv_delimiter(self) -> "str | None":
        """CSV delimiter. Delegates to _impl if present."""
        if hasattr(self, "_impl") and hasattr(self._impl, "csv_delimiter"):
            return self._impl.csv_delimiter
        return getattr(self, "_csv_delimiter", None)

    def get_csv_loading_config(self, table_name: str) -> "list[str] | None":
        """Get CSV loading configuration. Delegates to _impl if present."""
        if hasattr(self, "_impl") and hasattr(self._impl, "get_csv_loading_config"):
            return self._impl.get_csv_loading_config(table_name)
        return None

    def _get_benchmark_name(self) -> str:
        """Return the canonical registry ID for this benchmark class."""
        class_name = self.__class__.__name__

        try:
            from benchbox.core.benchmark_registry import get_benchmark_id_for_class_name
        except ImportError:
            benchmark_id = None
        else:
            benchmark_id = get_benchmark_id_for_class_name(class_name)
        if benchmark_id is not None:
            return benchmark_id

        # Keep unregistered tests and downstream custom benchmarks working.
        if class_name.endswith("Benchmark"):
            return class_name[:-9].lower()

        return class_name.lower()

    def get_data_source_benchmark(self) -> Optional[str]:
        """Return the canonical source benchmark when data is shared.

        Benchmarks that reuse data generated by another benchmark (for example,
        ``Primitives`` reusing ``TPC-H`` datasets) should override this method and
        return the lower-case identifier of the source benchmark. Benchmarks that
        produce their own data should return ``None`` (default).

        Delegates to _impl if present and _impl provides this method.
        """
        if hasattr(self, "_impl") and hasattr(self._impl, "get_data_source_benchmark"):
            return self._impl.get_data_source_benchmark()
        return None

    @abstractmethod
    def generate_data(self) -> list[Union[str, Path]]:
        """Generate benchmark data.

        Returns:
            List of data file paths
        """

    @abstractmethod
    def get_queries(self) -> dict[str, str]:
        """Get all benchmark queries.

        Returns:
            Dictionary mapping query IDs to query strings
        """

    @abstractmethod
    def get_query(self, query_id: Union[int, str], *, params: Optional[dict[str, Any]] = None) -> str:
        """Get a benchmark query.

        Args:
            query_id: Query ID
            params: Optional parameters

        Returns:
            Query string with parameters resolved

        Raises:
            ValueError: If query_id is invalid
        """

    def _load_data(self, connection: DatabaseConnection) -> None:
        """Load benchmark data into database.

        Each benchmark implements this method for its data loading.

        Args:
            connection: Database connection

        Raises:
            NotImplementedError: If not implemented by subclass
        """
        # Default implementation - benchmarks should override
        # Non-abstract for backward compatibility
        # Raises NotImplementedError if not overridden
        raise NotImplementedError(
            f"{self.__class__.__name__} must implement _load_data() method to support database execution functionality"
        )

    def setup_database(self, connection: DatabaseConnection) -> None:
        """Set up database with schema and data.

        Creates necessary database schema and loads
        benchmark data into the database.

        Args:
            connection: Database connection to set up

        Raises:
            ValueError: If data generation fails
            Exception: If database setup fails
        """
        logger = logging.getLogger(__name__)

        try:
            logger.info("Setting up database schema and loading data...")
            start_time = mono_time()

            # Generate data if not already generated
            if not hasattr(self, "_data_generated") or not self._data_generated:
                logger.info("Generating benchmark data...")
                self.generate_data()
                self._data_generated = True

            # Load data into database
            self._load_data(connection)

            setup_time = elapsed_seconds(start_time)
            logger.info(f"Database setup completed in {setup_time:.2f} seconds")

        except Exception as e:
            logger.error(f"Database setup failed: {str(e)}")
            raise

    def run_query(
        self,
        query_id: Union[int, str],
        connection: DatabaseConnection,
        params: Optional[dict[str, Any]] = None,
        fetch_results: bool = False,
    ) -> dict[str, Any]:
        """Execute single query and return timing and results.

        Args:
            query_id: ID of the query to execute
            connection: Database connection to execute query on
            params: Optional parameters for query customization
            fetch_results: Whether to fetch and return query results

        Returns:
            Dictionary containing:
                - query_id: Executed query ID
                - execution_time: Time taken to execute query in seconds
                - query_text: Executed query text
                - results: Query results if fetch_results=True, otherwise None
                - row_count: Number of rows returned (if results fetched)

        Raises:
            ValueError: If query_id is invalid
            Exception: If query execution fails
        """
        logger = logging.getLogger(__name__)

        try:
            # Get the query text
            query_text = self.get_query(query_id, params=params)

            logger.debug(f"Executing query {query_id}")
            start_time = mono_time()

            # Execute the query
            cursor = connection.execute(query_text)

            # Fetch results if requested
            results = None
            row_count = 0
            if fetch_results:
                results = connection.fetchall(cursor)
                row_count = len(results) if results else 0

            execution_time = elapsed_seconds(start_time)

            logger.info(f"Query {query_id} completed in {execution_time:.3f} seconds")
            if fetch_results:
                logger.debug(f"Query {query_id} returned {row_count} rows")

            return {
                "query_id": query_id,
                "execution_time_seconds": execution_time,
                "query_text": query_text,
                "results": results,
                "row_count": row_count,
            }

        except Exception as e:
            logger.error(f"Query {query_id} execution failed: {str(e)}")
            raise

    def run_benchmark(
        self,
        connection: DatabaseConnection,
        query_ids: Optional[list[Union[int, str]]] = None,
        fetch_results: bool = False,
        setup_database: bool = True,
    ) -> dict[str, Any]:
        """Run the complete benchmark suite.

        Args:
            connection: Database connection to execute queries on
            query_ids: Optional list of specific query IDs to run (defaults to all)
            fetch_results: Whether to fetch and return query results
            setup_database: Whether to set up the database first

        Returns:
            Dictionary containing:
                - benchmark_name: Name of the benchmark
                - total_execution_time: Total time for all queries
                - total_queries: Number of queries executed
                - successful_queries: Number of queries that succeeded
                - failed_queries: Number of queries that failed
                - query_results: List of individual query results
                - setup_time: Time taken for database setup (if performed)

        Raises:
            Exception: If benchmark execution fails
        """
        logger = logging.getLogger(__name__)

        benchmark_start_time = mono_time()
        setup_time = 0.0

        try:
            # Set up database if requested
            if setup_database:
                logger.info("Setting up database for benchmark...")
                setup_start_time = mono_time()
                self.setup_database(connection)
                setup_time = elapsed_seconds(setup_start_time)

            # Determine which queries to run
            if query_ids is None:
                all_queries = self.get_queries()
                query_ids = list(all_queries.keys())

            logger.info(f"Running benchmark with {len(query_ids)} queries...")

            # Execute all queries
            query_results = []
            successful_queries = 0
            failed_queries = 0

            for query_id in query_ids:
                try:
                    result = self.run_query(query_id, connection, fetch_results=fetch_results)
                    query_results.append(result)
                    successful_queries += 1

                except Exception as e:
                    logger.error(f"Query {query_id} failed: {str(e)}")
                    failed_queries += 1
                    # Include failed query in results
                    query_results.append(
                        {
                            "query_id": query_id,
                            "execution_time_seconds": 0.0,
                            "query_text": None,
                            "results": None,
                            "row_count": 0,
                            "error": str(e),
                        }
                    )

            total_execution_time = elapsed_seconds(benchmark_start_time) - setup_time

            # Calculate summary statistics
            query_times = [r["execution_time_seconds"] for r in query_results if "error" not in r]

            benchmark_result = {
                "benchmark_name": self.__class__.__name__,
                "total_execution_time": total_execution_time,
                "total_queries": len(query_ids),
                "successful_queries": successful_queries,
                "failed_queries": failed_queries,
                "query_results": query_results,
                "setup_time": setup_time,
                "average_query_time": sum(query_times) / len(query_times) if query_times else 0.0,
                "min_query_time": min(query_times) if query_times else 0.0,
                "max_query_time": max(query_times) if query_times else 0.0,
            }

            logger.info(f"Benchmark completed: {successful_queries}/{len(query_ids)} queries successful")
            logger.info(f"Total execution time: {total_execution_time:.2f} seconds")

            return benchmark_result

        except Exception as e:
            logger.error(f"Benchmark execution failed: {str(e)}")
            raise

    def run_with_platform(self, platform_adapter, **run_config):
        """Run complete benchmark using platform-specific optimizations.

        This method provides a unified interface for running benchmarks
        using database platform adapters that handle connection management,
        data loading optimizations, and query execution.

        This is the standard method that all benchmarks should support for
        integration with the CLI and other orchestration tools.

        Args:
            platform_adapter: Platform adapter instance (e.g., DuckDBAdapter)
            **run_config: Configuration options:
                - categories: List of query categories to run (if benchmark supports)
                - query_subset: List of specific query IDs to run
                - connection: Connection configuration
                - benchmark_type: Type hint for optimizations ('olap', 'oltp', etc.)

        Returns:
            BenchmarkResults object with execution results

        Example:
            from benchbox.platforms import DuckDBAdapter

            benchmark = SomeBenchmark(scale_factor=0.1)
            adapter = DuckDBAdapter()
            results = benchmark.run_with_platform(adapter)
        """
        # Set default benchmark type based on benchmark characteristics
        default_benchmark_type = self._get_default_benchmark_type()
        run_config.setdefault("benchmark_type", default_benchmark_type)

        # Execute using the platform adapter
        return platform_adapter.run_benchmark(self, **run_config)

    def _get_default_benchmark_type(self) -> str:
        """Get the default benchmark type for platform optimizations.

        Subclasses can override this to specify their workload characteristics.

        Returns:
            Default benchmark type ('olap', 'oltp', 'mixed', 'analytics')
        """
        # Most benchmarks in BenchBox are OLAP-focused
        return "olap"

    def format_results(self, benchmark_result: dict[str, Any]) -> str:
        """Format benchmark results for display.

        Args:
            benchmark_result: Result dictionary from run_benchmark()

        Returns:
            Formatted string representation of the results
        """
        lines = []
        lines.append(f"Benchmark: {benchmark_result['benchmark_name']}")
        lines.append("=" * 50)

        lines.append(f"Total Queries: {benchmark_result['total_queries']}")
        lines.append(f"Successful: {benchmark_result['successful_queries']}")
        lines.append(f"Failed: {benchmark_result['failed_queries']}")

        if benchmark_result["setup_time"] > 0:
            lines.append(f"Setup Time: {benchmark_result['setup_time']:.2f}s")

        lines.append(f"Total Execution Time: {benchmark_result['total_execution_time']:.2f}s")
        lines.append(f"Average Query Time: {benchmark_result['average_query_time']:.3f}s")
        lines.append(f"Min Query Time: {benchmark_result['min_query_time']:.3f}s")
        lines.append(f"Max Query Time: {benchmark_result['max_query_time']:.3f}s")

        lines.append("\nQuery Details:")
        lines.append("-" * 30)

        for result in benchmark_result["query_results"]:
            query_id = result["query_id"]
            if "error" in result:
                lines.append(f"Query {query_id}: FAILED - {result['error']}")
            else:
                exec_time = result["execution_time_seconds"]
                row_count = result["row_count"]
                lines.append(f"Query {query_id}: {exec_time:.3f}s ({row_count} rows)")

        return "\n".join(lines)

    def _format_time(self, seconds: float) -> str:
        """Format execution time for display.

        Args:
            seconds: Time in seconds

        Returns:
            Formatted time string
        """
        if seconds < 1:
            return f"{seconds * 1000:.1f}ms"
        elif seconds < 60:
            return f"{seconds:.2f}s"
        else:
            minutes = int(seconds // 60)
            remaining_seconds = seconds % 60
            return f"{minutes}m {remaining_seconds:.1f}s"

    def translate_query(self, query_id: Union[int, str], dialect: str) -> str:
        """Translate a query to a specific SQL dialect.

        Args:
            query_id: The ID of the query to translate
            dialect: The target SQL dialect

        Returns:
            The translated query string

        Raises:
            ValueError: If the query_id is invalid
            ImportError: If sqlglot is not installed
            ValueError: If the dialect is not supported
        """
        if sqlglot is None:
            raise ImportError("sqlglot is required for query translation. Install it with `pip install sqlglot`.")

        from benchbox.utils.dialect_utils import normalize_dialect_for_sqlglot

        query = self.get_query(query_id)

        # Normalize dialect for SQLGlot compatibility
        normalized_dialect = normalize_dialect_for_sqlglot(dialect)

        # Apply translation for specific SQL syntax
        try:
            # Use identify=True to quote identifiers and prevent reserved keyword conflicts
            translated = sqlglot.transpile(query, read="postgres", write=normalized_dialect, identify=True)[0]
            return translated
        except (ValueError, AttributeError) as e:
            raise ValueError(f"Error translating to dialect '{dialect}': {e}") from e

    @property
    def benchmark_name(self) -> str:
        """Get the human-readable benchmark name."""
        # Try to get from implementation first, then fallback to class name
        if hasattr(self, "_impl"):
            if hasattr(self._impl, "_name"):
                return self._impl._name
            elif hasattr(self._impl, "benchmark_name"):
                return self._impl.benchmark_name
        # For classes without _impl (like core implementation classes)
        return getattr(self, "_name", type(self).__name__)

    def create_enhanced_benchmark_result(
        self,
        platform: str,
        query_results: list[dict[str, Any]],
        execution_metadata: Optional[dict[str, Any]] = None,
        phases: Optional[dict[str, dict[str, Any]]] = None,
        resource_utilization: Optional[dict[str, Any]] = None,
        performance_characteristics: Optional[dict[str, Any]] = None,
        duration_seconds: Optional[float] = None,
        **kwargs: Any,
    ) -> "BenchmarkResults":
        """Create a BenchmarkResults object with standardized fields.

        This centralizes the logic for creating benchmark results that was previously
        duplicated across platform adapters and CLI orchestrator.

        Args:
            platform: Platform name (e.g., "DuckDB", "ClickHouse")
            query_results: List of query execution results
            execution_metadata: Optional execution metadata
            phases: Optional phase tracking information
            resource_utilization: Optional resource usage metrics
            performance_characteristics: Optional performance analysis
            duration_seconds: Optional explicit total duration override in seconds
            **kwargs: Additional fields to override defaults

        Returns:
            Fully configured BenchmarkResults object
        """
        # Delegate to implementation's create method if available, otherwise use our own
        if hasattr(self, "_impl") and hasattr(self._impl, "create_enhanced_benchmark_result"):
            return self._impl.create_enhanced_benchmark_result(
                platform=platform,
                query_results=query_results,
                execution_metadata=execution_metadata,
                phases=phases,
                resource_utilization=resource_utilization,
                performance_characteristics=performance_characteristics,
                duration_seconds=duration_seconds,
                **kwargs,
            )

        # Fallback implementation for wrapper class delegates to shared result factory.
        from benchbox.core.results.result_factory import build_enhanced_benchmark_result

        result = build_enhanced_benchmark_result(
            benchmark=self,
            platform=platform,
            query_results=query_results,
            execution_metadata=execution_metadata,
            phases=phases,
            resource_utilization=resource_utilization,
            performance_characteristics=performance_characteristics,
            duration_seconds=duration_seconds,
            **kwargs,
        )
        self._attach_performance_snapshot(result, performance_characteristics, **kwargs)
        return result

    def create_minimal_benchmark_result(
        self,
        *,
        validation_status: str,
        validation_details: Optional[dict[str, Any]] = None,
        duration_seconds: float = 0.0,
        platform: str = "unknown",
        execution_metadata: Optional[dict[str, Any]] = None,
        system_profile: Optional[dict[str, Any]] = None,
        phases: Optional[dict[str, dict[str, Any]]] = None,
        **overrides: Any,
    ) -> "BenchmarkResults":
        """Create a minimal BenchmarkResults instance for error and interrupt paths."""

        metadata: dict[str, Any] = {
            "result_type": "minimal",
            "status": validation_status,
        }
        base_identifier = str(getattr(self, "name", self.benchmark_name))
        metadata.setdefault(
            "benchmark_id",
            base_identifier.lower().replace(" ", "_").replace("-", "_"),
        )
        if execution_metadata:
            metadata.update(execution_metadata)

        result = self.create_enhanced_benchmark_result(
            platform=platform,
            query_results=[],
            execution_metadata=metadata,
            phases=phases,
            duration_seconds=duration_seconds,
            validation_status=validation_status,
            validation_details=validation_details or {},
            system_profile=system_profile or {},
            **overrides,
        )
        result._benchmark_id_override = metadata["benchmark_id"]
        return result

    # ------------------------------------------------------------------
    # Validation helpers (core-facing)
    # ------------------------------------------------------------------

    def _resolve_output_dir(self, output_dir: Optional[Union[str, Path]] = None) -> Union[Path, Any]:
        """Resolve and cache the benchmark output directory handler."""

        candidate = output_dir if output_dir is not None else getattr(self, "output_dir", None)
        if candidate is None:
            raise RuntimeError(
                "Benchmark output directory is not configured. Set 'benchmark.output_dir' or pass output_root to the lifecycle runner."
            )

        handler = create_path_handler(candidate)
        self.output_dir = handler
        return handler

    def validate_preflight(
        self,
        *,
        output_dir: Optional[Union[str, Path]] = None,
        benchmark_name: Optional[str] = None,
    ) -> "ValidationResult":
        """Run preflight validation for this benchmark."""

        from benchbox.core.validation import DataValidationEngine

        resolved_dir = self._resolve_output_dir(output_dir)
        engine = DataValidationEngine()
        benchmark_id = (benchmark_name or self._get_benchmark_name()).lower()
        return engine.validate_preflight_conditions(benchmark_id, self.scale_factor, resolved_dir)

    def validate_manifest(
        self,
        *,
        manifest_path: Optional[Union[str, Path]] = None,
        benchmark_name: Optional[str] = None,
    ) -> "ValidationResult":
        """Validate generated manifest for this benchmark."""

        from benchbox.core.validation import DataValidationEngine, ValidationResult as CoreValidationResult

        resolved_dir = self._resolve_output_dir()
        manifest_candidate = manifest_path
        if manifest_candidate is None and hasattr(resolved_dir, "joinpath"):
            manifest_candidate = resolved_dir.joinpath("_datagen_manifest.json")

        if manifest_candidate is None:
            return CoreValidationResult(
                is_valid=False,
                errors=["Manifest path is not available"],
                warnings=[],
                details={"benchmark": (benchmark_name or self._get_benchmark_name())},
            )

        engine = DataValidationEngine()
        manifest_path_obj = Path(manifest_candidate) if isinstance(manifest_candidate, str) else manifest_candidate
        return engine.validate_generated_data(manifest_path_obj)

    def validate_loaded_data(
        self,
        connection: Any,
        *,
        benchmark_name: Optional[str] = None,
    ) -> "ValidationResult":
        """Validate post-load database state for this benchmark."""

        from benchbox.core.validation import DatabaseValidationEngine

        engine = DatabaseValidationEngine()
        benchmark_id = (benchmark_name or self._get_benchmark_name()).lower()
        return engine.validate_loaded_data(connection, benchmark_id, self.scale_factor)

    def _create_result_builder(
        self,
        platform: str,
        execution_metadata: dict[str, Any],
        normalize_benchmark_id: Any,
        **kwargs: Any,
    ) -> Any:
        """Create and configure the ResultBuilder with benchmark and platform info."""
        from benchbox.core.results.builder import (
            BenchmarkInfoInput,
            ResultBuilder,
            RunConfigInput,
        )
        from benchbox.core.results.platform_info import PlatformInfoInput

        benchmark_name = self.benchmark_name
        short_name = benchmark_name[:-10] if benchmark_name.lower().endswith(" benchmark") else benchmark_name
        benchmark_id = execution_metadata.get("benchmark_id") or normalize_benchmark_id(benchmark_name)

        platform_info = kwargs.get("platform_info", {}) or {}
        platform_input = PlatformInfoInput(
            name=platform,
            platform_version=platform_info.get("platform_version") or platform_info.get("version") or "unknown",
            client_library_version=platform_info.get("client_library_version")
            or platform_info.get("client_version")
            or "unknown",
            execution_mode=execution_metadata.get("mode", "sql"),
            config=platform_info if isinstance(platform_info, dict) else {},
        )

        builder = ResultBuilder(
            benchmark=BenchmarkInfoInput(
                name=short_name,
                scale_factor=self.scale_factor,
                test_type=kwargs.get("test_execution_type", "standard"),
                benchmark_id=benchmark_id,
                display_name=short_name,
                compliance_class=getattr(self, "compliance_class", None),
            ),
            platform=platform_input,
            execution_id=kwargs.get("execution_id"),
        )

        run_cfg = execution_metadata.get("run_config") if isinstance(execution_metadata, dict) else None
        if isinstance(run_cfg, dict):
            compression = run_cfg.get("compression") or {}
            builder.set_run_config(
                RunConfigInput(
                    compression_type=compression.get("type"),
                    compression_level=compression.get("level"),
                    seed=run_cfg.get("seed"),
                    phases=run_cfg.get("phases"),
                    query_subset=run_cfg.get("query_subset"),
                    tuning_mode=run_cfg.get("tuning_mode"),
                    tuning_config=run_cfg.get("tuning_config"),
                    platform_options=run_cfg.get("platform_options"),
                    table_mode=run_cfg.get("table_mode"),
                )
            )

        return builder

    def _populate_builder(
        self,
        builder: Any,
        execution_metadata: dict[str, Any],
        query_results: list[dict[str, Any]],
        normalize_query_result: Any,
        duration_seconds: Optional[float] = None,
        **kwargs: Any,
    ) -> None:
        """Populate builder with query results, metadata, and ancillary config."""
        for qr in query_results:
            builder.add_query_result(normalize_query_result(qr))

        table_statistics = kwargs.get("table_statistics", {}) or {}
        for table_name, row_count in table_statistics.items():
            builder.add_table_stats(table_name, row_count)

        if kwargs.get("data_loading_time"):
            builder.set_loading_time(float(kwargs.get("data_loading_time", 0.0)) * 1000)
        if duration_seconds is not None:
            builder.set_total_duration(duration_seconds)

        builder.set_execution_metadata(execution_metadata)
        builder.set_validation_status(kwargs.get("validation_status", "UNKNOWN"), kwargs.get("validation_details", {}))
        builder.set_system_profile(kwargs.get("system_profile", {}))
        builder.set_tuning_info(
            tunings_applied=kwargs.get("tunings_applied"),
            config_hash=kwargs.get("tuning_config_hash"),
            source_file=kwargs.get("tuning_source_file"),
        )
        builder.add_plan_capture_stats(
            kwargs.get("query_plans_captured", 0),
            kwargs.get("plan_capture_failures", 0),
            kwargs.get("plan_capture_errors", []),
        )

    def _apply_phases_to_builder(self, builder: Any, phases: Any, ExecutionPhases: type) -> None:
        """Apply execution phase information to the builder."""
        phases_obj = phases if isinstance(phases, ExecutionPhases) else None
        if phases_obj:
            builder.set_execution_phases(phases_obj)
        if isinstance(phases, dict):
            for phase_name, phase_data in phases.items():
                if isinstance(phase_data, dict):
                    extra = {k: v for k, v in phase_data.items() if k not in ("status", "duration_ms")}
                    builder.set_phase_status(
                        phase_name,
                        phase_data.get("status", "NOT_RUN"),
                        phase_data.get("duration_ms"),
                        **extra,
                    )

    def _attach_performance_snapshot(
        self,
        result: "BenchmarkResults",
        performance_characteristics: Optional[dict[str, Any]],
        **kwargs: Any,
    ) -> None:
        """Attach performance snapshot data to the built result."""
        snapshot_payload = kwargs.get("performance_snapshot")
        if snapshot_payload is not None:
            try:
                from benchbox.monitoring.performance import PerformanceSnapshot, attach_snapshot_to_result

                if isinstance(snapshot_payload, PerformanceSnapshot):
                    attach_snapshot_to_result(result, snapshot_payload)
                elif isinstance(snapshot_payload, dict):
                    result.performance_summary = dict(snapshot_payload)
                    if not result.performance_characteristics:
                        result.performance_characteristics = dict(snapshot_payload)
            except ImportError:
                if isinstance(snapshot_payload, dict):
                    result.performance_summary = dict(snapshot_payload)
                    if not result.performance_characteristics:
                        result.performance_characteristics = dict(snapshot_payload)
        elif performance_characteristics and not result.performance_summary:
            result.performance_summary = dict(performance_characteristics)
