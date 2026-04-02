"""Metadata Primitives benchmark implementation.

Tests database metadata introspection operations using INFORMATION_SCHEMA views
and platform-specific catalog commands (SHOW, DESCRIBE, PRAGMA).

Unlike Read/Write/Transaction Primitives that test data operations, this benchmark
focuses on metadata operations critical for data catalog integration, schema discovery,
IDE autocomplete, BI tool connectivity, and data governance workflows.

Complexity Testing:
The benchmark supports stress testing metadata operations under various complexity
conditions using the MetadataGenerator class. This allows measuring how introspection
performance scales with:
- Wide tables (100-1000+ columns)
- Nested view hierarchies (multiple levels of view dependencies)
- Complex data types (ARRAY, STRUCT, MAP)
- Large catalogs (100-500+ tables)
- Foreign key constraints

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from benchbox.base import BaseBenchmark
from benchbox.core.connection import DatabaseConnection
from benchbox.core.metadata_primitives.complexity import (
    AclGrant,
    GeneratedMetadata,
    MetadataComplexityConfig,
    PermissionDensity,
    get_complexity_preset,
)
from benchbox.core.metadata_primitives.ddl import (
    generate_create_role_sql,
    generate_drop_role_sql,
    generate_grant_sql,
    generate_revoke_sql,
    supports_acl,
)
from benchbox.core.metadata_primitives.generator import MetadataGenerator
from benchbox.core.metadata_primitives.queries import MetadataPrimitivesQueryManager
from benchbox.core.metadata_primitives.schema import (
    get_create_tables_sql as get_base_schema_sql,
    get_schema as get_base_schema,
    get_table_names as get_base_table_names,
)

logger = logging.getLogger(__name__)


@dataclass
class MetadataQueryResult:
    """Result of executing a single metadata query.

    Attributes:
        query_id: Query identifier
        category: Query category
        execution_time_ms: Query execution time in milliseconds
        row_count: Number of rows returned
        success: Whether query executed successfully
        error: Error message if query failed
    """

    query_id: str
    category: str
    execution_time_ms: float
    row_count: int = 0
    success: bool = True
    error: str | None = None


@dataclass
class MetadataBenchmarkResult:
    """Results from running the Metadata Primitives benchmark.

    Attributes:
        total_queries: Total number of queries executed
        successful_queries: Number of queries that completed successfully
        failed_queries: Number of queries that failed
        total_time_ms: Total execution time in milliseconds
        results: List of individual query results
        category_summary: Aggregated results by category
        acl_mutation_results: Results from ACL mutation tests (GRANT/REVOKE timing)
        acl_mutation_summary: Aggregated ACL mutation statistics
    """

    total_queries: int = 0
    successful_queries: int = 0
    failed_queries: int = 0
    total_time_ms: float = 0.0
    results: list[MetadataQueryResult] = field(default_factory=list)
    category_summary: dict[str, dict[str, Any]] = field(default_factory=dict)
    acl_mutation_results: list[AclMutationResult] = field(default_factory=list)
    acl_mutation_summary: dict[str, Any] = field(default_factory=dict)


@dataclass
class ComplexityBenchmarkResult:
    """Results from running the complexity benchmark.

    Attributes:
        complexity_config: Configuration used for complexity testing
        generated_metadata: Metadata structures created for testing
        setup_time_ms: Time to create metadata structures
        teardown_time_ms: Time to cleanup metadata structures
        benchmark_result: Underlying benchmark results
    """

    complexity_config: MetadataComplexityConfig
    generated_metadata: GeneratedMetadata
    setup_time_ms: float = 0.0
    teardown_time_ms: float = 0.0
    benchmark_result: MetadataBenchmarkResult | None = None


@dataclass
class AclMutationResult:
    """Result of a single GRANT/REVOKE operation.

    Attributes:
        operation: Operation type ("GRANT", "REVOKE", "CREATE_ROLE", "DROP_ROLE")
        target_type: Object type ("table", "column", "role", "schema")
        target_name: Name of the object
        grantee: Role or user receiving/losing the grant
        privileges: List of privileges involved
        execution_time_ms: Operation execution time in milliseconds
        success: Whether operation completed successfully
        error: Error message if operation failed
    """

    operation: str
    target_type: str
    target_name: str
    grantee: str
    privileges: list[str] = field(default_factory=list)
    execution_time_ms: float = 0.0
    success: bool = True
    error: str | None = None


@dataclass
class AclBenchmarkResult:
    """Results from ACL benchmark operations.

    Tracks timing for both ACL mutations (GRANT/REVOKE) and ACL introspection
    queries.

    Attributes:
        setup_time_ms: Time to create roles and grants
        teardown_time_ms: Time to revoke grants and drop roles
        mutation_results: List of individual GRANT/REVOKE results
        introspection_results: Results from ACL introspection queries
        summary: Aggregated statistics
    """

    setup_time_ms: float = 0.0
    teardown_time_ms: float = 0.0
    mutation_results: list[AclMutationResult] = field(default_factory=list)
    introspection_results: MetadataBenchmarkResult | None = None
    summary: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Calculate summary statistics if not provided."""
        if not self.summary and self.mutation_results:
            self._calculate_summary()

    def _calculate_summary(self) -> None:
        """Calculate summary statistics from mutation results."""
        total_ops = len(self.mutation_results)
        successful_ops = sum(1 for r in self.mutation_results if r.success)
        failed_ops = total_ops - successful_ops

        if total_ops == 0:
            self.summary = {
                "total_operations": 0,
                "successful_operations": 0,
                "failed_operations": 0,
            }
            return

        times = [r.execution_time_ms for r in self.mutation_results]
        grants = [r for r in self.mutation_results if r.operation == "GRANT"]
        revokes = [r for r in self.mutation_results if r.operation == "REVOKE"]

        self.summary = {
            "total_operations": total_ops,
            "successful_operations": successful_ops,
            "failed_operations": failed_ops,
            "total_time_ms": sum(times),
            "avg_time_ms": sum(times) / len(times),
            "min_time_ms": min(times),
            "max_time_ms": max(times),
            "grants_count": len(grants),
            "revokes_count": len(revokes),
            "grants_per_second": len(grants) / (sum(r.execution_time_ms for r in grants) / 1000)
            if grants and sum(r.execution_time_ms for r in grants) > 0
            else 0.0,
        }


class MetadataPrimitivesBenchmark(BaseBenchmark):
    """Metadata Primitives benchmark implementation.

    Tests metadata introspection operations across database platforms:
    - Schema discovery (list databases, schemas, tables, views)
    - Column introspection (column metadata, types, constraints)
    - Table statistics (row counts, sizes, storage info)
    - Query introspection (execution plans)

    Unlike other primitives benchmarks, this benchmark does not require
    data generation - it queries the database's own catalog metadata.

    Attributes:
        query_manager: Query manager for loading catalog queries
    """

    def __init__(
        self,
        scale_factor: float = 1.0,
        output_dir: str | Path | None = None,
        **config: Any,
    ):
        """Initialize Metadata Primitives benchmark.

        Args:
            scale_factor: Not used for metadata primitives (included for API compatibility)
            output_dir: Not used for metadata primitives (included for API compatibility)
            **config: Additional configuration (quiet, etc.)
        """
        config = dict(config)
        quiet = config.pop("quiet", False)

        super().__init__(scale_factor, quiet=quiet, **config)

        self._name = "Metadata Primitives Benchmark"
        self._version = "1.0"
        self._description = "Metadata Primitives benchmark - Testing database catalog introspection performance"

        self.query_manager = MetadataPrimitivesQueryManager()

    def get_data_source_benchmark(self) -> str | None:
        """Metadata Primitives does not require any data generation."""
        return None

    def generate_data(
        self,
        tables: list[str] | None = None,
        output_format: str = "csv",
    ) -> dict[str, str]:
        """No data generation needed for Metadata Primitives.

        This benchmark queries database catalog metadata, not user data.

        Returns:
            Empty dictionary (no data files to generate)
        """
        return {}

    def get_create_tables_sql(
        self,
        dialect: str = "standard",
        tuning_config: Any = None,
    ) -> str:
        """Generate CREATE TABLE SQL for the Metadata Primitives schema.

        Creates TPC-H and TPC-DS schemas to provide a rich metadata
        environment for testing INFORMATION_SCHEMA queries.

        Args:
            dialect: Target SQL dialect
            tuning_config: Tuning configuration for constraint settings

        Returns:
            SQL script to create all tables (TPC-H + TPC-DS)
        """
        return get_base_schema_sql(dialect=dialect, tuning_config=tuning_config)

    def get_table_names(self) -> list[str]:
        """Get all table names in the Metadata Primitives schema.

        Returns:
            List of table names (TPC-H + TPC-DS tables)
        """
        return get_base_table_names()

    def get_schema(self) -> dict[str, dict[str, Any]]:
        """Get schema metadata for all tables.

        Returns:
            Dictionary mapping table names to their metadata (columns, types)
        """
        return get_base_schema()

    def get_query(self, query_id: int | str, *, params: dict[str, Any] | None = None) -> str:
        """Get SQL text for a specific Metadata Primitives query.

        Args:
            query_id: Query identifier (e.g., "schema_list_tables", "column_for_table")
            params: Optional parameter values (not supported for Metadata Primitives)

        Returns:
            SQL text of the query

        Raises:
            ValueError: If query_id is not valid or params are provided
        """
        if params is not None:
            raise ValueError("Metadata Primitives queries are static and don't accept parameters")
        return self.query_manager.get_query(str(query_id))

    def get_queries(self, dialect: str | None = None) -> dict[str, str]:
        """Get all available Metadata Primitives queries.

        Args:
            dialect: Target SQL dialect. If provided, returns dialect-specific
                    variants where available and excludes unsupported queries.

        Returns:
            Dictionary mapping query identifiers to their SQL text
        """
        if dialect:
            return self.query_manager.get_queries_for_dialect(dialect)
        return self.query_manager.get_all_queries()

    def get_queries_by_category(self, category: str) -> dict[str, str]:
        """Get queries filtered by category.

        Args:
            category: Category name (e.g., 'schema', 'column', 'stats', 'query')

        Returns:
            Dictionary mapping query IDs to SQL text for the category
        """
        return self.query_manager.get_queries_by_category(category)

    def get_query_categories(self) -> list[str]:
        """Get list of available query categories.

        Returns:
            List of category names (schema, column, stats, query)
        """
        return self.query_manager.get_query_categories()

    def execute_query(
        self,
        query_id: str,
        connection: DatabaseConnection,
        dialect: str | None = None,
    ) -> MetadataQueryResult:
        """Execute a single metadata query and return timing results.

        Args:
            query_id: Query identifier
            connection: Database connection to execute against
            dialect: Target dialect for query variants

        Returns:
            MetadataQueryResult with execution timing and status
        """
        entry = self.query_manager.get_query_entry(query_id)
        category = entry.category

        # Get dialect-appropriate SQL
        try:
            sql = self.query_manager.get_query(query_id, dialect=dialect)
        except ValueError as e:
            # Query not supported on this dialect
            return MetadataQueryResult(
                query_id=query_id,
                category=category,
                execution_time_ms=0.0,
                row_count=0,
                success=False,
                error=str(e),
            )

        # Execute and time the query
        start_time = time.perf_counter()
        try:
            if hasattr(connection, "execute"):
                cursor = connection.execute(sql)
            else:
                cursor = connection.cursor()
                cursor.execute(sql)

            # Fetch results to ensure complete execution
            results = cursor.fetchall()
            row_count = len(results)

            elapsed_ms = (time.perf_counter() - start_time) * 1000

            return MetadataQueryResult(
                query_id=query_id,
                category=category,
                execution_time_ms=elapsed_ms,
                row_count=row_count,
                success=True,
            )

        except Exception as e:
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            return MetadataQueryResult(
                query_id=query_id,
                category=category,
                execution_time_ms=elapsed_ms,
                row_count=0,
                success=False,
                error=str(e),
            )

    def run_benchmark(
        self,
        connection: DatabaseConnection,
        dialect: str | None = None,
        categories: list[str] | None = None,
        query_ids: list[str] | None = None,
        iterations: int = 1,
    ) -> MetadataBenchmarkResult:
        """Run the Metadata Primitives benchmark.

        Args:
            connection: Database connection to execute against
            dialect: Target dialect for query variants
            categories: Optional list of categories to run (default: all)
            query_ids: Optional specific query IDs to run (overrides categories)
            iterations: Number of times to run each query (default: 1)

        Returns:
            MetadataBenchmarkResult with all query timings and summary
        """
        queries_to_run = self._select_queries_to_run(dialect=dialect, categories=categories, query_ids=query_ids)

        result = MetadataBenchmarkResult()
        all_results: list[MetadataQueryResult] = []

        for query_id in queries_to_run:
            for _ in range(iterations):
                query_result = self.execute_query(query_id, connection, dialect=dialect)
                all_results.append(query_result)

                if query_result.success:
                    result.successful_queries += 1
                else:
                    result.failed_queries += 1

                result.total_time_ms += query_result.execution_time_ms

        result.total_queries = len(all_results)
        result.results = all_results
        result.category_summary = self._build_category_summary(all_results)

        # Run ACL mutation tests at the end (on supported platforms)
        if dialect and supports_acl(dialect):
            acl_results = self._run_default_acl_mutations(connection, dialect)
            result.acl_mutation_results = acl_results
            result.acl_mutation_summary = self._build_acl_summary(acl_results)

        return result

    def _select_queries_to_run(
        self,
        *,
        dialect: str | None,
        categories: list[str] | None,
        query_ids: list[str] | None,
    ) -> list[str]:
        """Resolve the query IDs to execute for a benchmark run."""
        if query_ids:
            return query_ids
        if categories:
            queries_to_run: list[str] = []
            for category in categories:
                queries_to_run.extend(self.query_manager.get_queries_by_category(category).keys())
            return queries_to_run
        if dialect:
            return list(self.query_manager.get_queries_for_dialect(dialect).keys())
        return list(self.query_manager.get_all_queries().keys())

    def _build_category_summary(self, all_results: list[MetadataQueryResult]) -> dict[str, dict[str, float | int]]:
        """Aggregate per-category execution statistics."""
        category_summary: dict[str, dict[str, float | int]] = {}
        for query_result in all_results:
            entry = category_summary.setdefault(
                query_result.category,
                {
                    "total_queries": 0,
                    "successful": 0,
                    "failed": 0,
                    "total_time_ms": 0.0,
                    "avg_time_ms": 0.0,
                    "min_time_ms": 0.0,
                    "max_time_ms": 0.0,
                },
            )
            total_queries = int(entry["total_queries"]) + 1
            total_time_ms = float(entry["total_time_ms"]) + query_result.execution_time_ms
            min_time_ms = (
                query_result.execution_time_ms
                if total_queries == 1
                else min(float(entry["min_time_ms"]), query_result.execution_time_ms)
            )
            max_time_ms = max(float(entry["max_time_ms"]), query_result.execution_time_ms)
            successful = int(entry["successful"]) + int(query_result.success)
            failed = total_queries - successful
            entry.update(
                {
                    "total_queries": total_queries,
                    "successful": successful,
                    "failed": failed,
                    "total_time_ms": total_time_ms,
                    "avg_time_ms": total_time_ms / total_queries,
                    "min_time_ms": min_time_ms,
                    "max_time_ms": max_time_ms,
                }
            )
        return category_summary

    # =========================================================================
    # Complexity Testing Methods
    # =========================================================================

    def setup_complexity(
        self,
        connection: DatabaseConnection,
        dialect: str,
        config: MetadataComplexityConfig | str,
    ) -> GeneratedMetadata:
        """Set up metadata structures for complexity testing.

        Creates tables, views, and other database objects based on the
        complexity configuration. These structures can then be queried
        using the complexity-specific query categories.

        Args:
            connection: Database connection to create structures
            dialect: Target SQL dialect
            config: Complexity configuration or preset name (e.g., 'wide_tables')

        Returns:
            GeneratedMetadata tracking all created objects

        Example:
            >>> benchmark = MetadataPrimitivesBenchmark()
            >>> generated = benchmark.setup_complexity(conn, "duckdb", "wide_tables")
            >>> result = benchmark.run_benchmark(conn, "duckdb", categories=["wide_table"])
            >>> benchmark.teardown_complexity(conn, "duckdb", generated)
        """
        if isinstance(config, str):
            config = get_complexity_preset(config)

        generator = MetadataGenerator()
        return generator.setup(connection, dialect, config)

    def teardown_complexity(
        self,
        connection: DatabaseConnection,
        dialect: str,
        generated: GeneratedMetadata,
    ) -> None:
        """Tear down metadata structures created for complexity testing.

        Removes all tables and views created by setup_complexity().

        Args:
            connection: Database connection
            dialect: Target SQL dialect
            generated: Metadata tracking object from setup_complexity()
        """
        generator = MetadataGenerator()
        generator.teardown(connection, dialect, generated)

    def cleanup_benchmark_objects(
        self,
        connection: DatabaseConnection,
        dialect: str,
        prefix: str = "benchbox_",
    ) -> int:
        """Clean up all benchmark objects with given prefix.

        Useful for cleaning up stale test objects from previous runs.

        Args:
            connection: Database connection
            dialect: Target SQL dialect
            prefix: Prefix to match (default: benchbox_)

        Returns:
            Number of objects dropped
        """
        generator = MetadataGenerator()
        return generator.cleanup_all(connection, dialect, prefix)

    def run_complexity_benchmark(
        self,
        connection: DatabaseConnection,
        dialect: str,
        config: MetadataComplexityConfig | str,
        iterations: int = 1,
        categories: list[str] | None = None,
    ) -> ComplexityBenchmarkResult:
        """Run a full complexity benchmark with setup and teardown.

        This is a convenience method that:
        1. Creates complexity structures based on configuration
        2. Runs the benchmark against complexity-specific queries
        3. Cleans up the created structures

        Args:
            connection: Database connection
            dialect: Target SQL dialect
            config: Complexity configuration or preset name
            iterations: Number of times to run each query
            categories: Optional list of categories to run. If not specified,
                       automatically selects categories based on the config.

        Returns:
            ComplexityBenchmarkResult with timing and results

        Example:
            >>> benchmark = MetadataPrimitivesBenchmark()
            >>> result = benchmark.run_complexity_benchmark(
            ...     conn, "duckdb", "wide_tables", iterations=3
            ... )
            >>> emit(f"Setup: {result.setup_time_ms:.1f}ms")
            >>> emit(f"Queries: {result.benchmark_result.total_queries}")
        """
        if isinstance(config, str):
            config = get_complexity_preset(config)

        # Auto-select categories based on config if not specified
        if categories is None:
            categories = self._get_complexity_categories(config)

        # Setup
        logger.info(f"Setting up complexity structures: {config.to_dict()}")
        setup_start = time.perf_counter()
        generator = MetadataGenerator()
        generated = generator.setup(connection, dialect, config)
        setup_time_ms = (time.perf_counter() - setup_start) * 1000

        logger.info(
            f"Created {generated.total_objects} objects "
            f"({len(generated.tables)} tables, {len(generated.views)} views) "
            f"in {setup_time_ms:.1f}ms"
        )

        # Run benchmark
        benchmark_result = None
        try:
            benchmark_result = self.run_benchmark(
                connection,
                dialect=dialect,
                categories=categories,
                iterations=iterations,
            )
        finally:
            # Always teardown
            logger.info("Tearing down complexity structures...")
            teardown_start = time.perf_counter()
            generator.teardown(connection, dialect, generated)
            teardown_time_ms = (time.perf_counter() - teardown_start) * 1000
            logger.info(f"Teardown completed in {teardown_time_ms:.1f}ms")

        return ComplexityBenchmarkResult(
            complexity_config=config,
            generated_metadata=generated,
            setup_time_ms=setup_time_ms,
            teardown_time_ms=teardown_time_ms,
            benchmark_result=benchmark_result,
        )

    def _get_complexity_categories(self, config: MetadataComplexityConfig) -> list[str]:
        """Determine which query categories to run based on complexity config.

        Args:
            config: Complexity configuration

        Returns:
            List of category names to run
        """
        categories = []

        # Wide table queries
        if config.width_factor > 0:
            categories.append("wide_table")

        # Large catalog queries
        if config.catalog_size > 1:
            categories.append("large_catalog")

        # View hierarchy queries
        if config.view_depth > 0:
            categories.append("view_hierarchy")

        # Complex type queries
        from benchbox.core.metadata_primitives.complexity import TypeComplexity

        if config.type_complexity != TypeComplexity.SCALAR:
            categories.append("complex_type")

        # Constraint queries
        from benchbox.core.metadata_primitives.complexity import ConstraintDensity

        if config.constraint_density != ConstraintDensity.NONE:
            categories.append("constraint")

        # ACL queries
        if config.acl_role_count > 0:
            categories.append("acl")

        return categories

    def get_complexity_categories(self) -> list[str]:
        """Get list of complexity-specific query categories.

        These are categories designed to work with generated metadata structures.

        Returns:
            List of complexity category names
        """
        return [
            "wide_table",
            "view_hierarchy",
            "complex_type",
            "large_catalog",
            "constraint",
            "acl",
        ]

    # =========================================================================
    # ACL Benchmark Methods
    # =========================================================================

    def run_acl_benchmark(
        self,
        connection: DatabaseConnection,
        dialect: str,
        config: MetadataComplexityConfig | str,
        iterations: int = 1,
    ) -> AclBenchmarkResult:
        """Run a full ACL benchmark measuring GRANT/REVOKE performance.

        This benchmark:
        1. Creates test roles
        2. Measures GRANT statement performance
        3. Runs ACL introspection queries
        4. Measures REVOKE statement performance
        5. Cleans up roles

        Args:
            connection: Database connection
            dialect: Target SQL dialect
            config: Complexity configuration or preset name
            iterations: Number of times to run each query

        Returns:
            AclBenchmarkResult with timing measurements
        """
        if isinstance(config, str):
            config = get_complexity_preset(config)

        if not supports_acl(dialect):
            logger.warning(f"Dialect '{dialect}' does not support ACL operations")
            return AclBenchmarkResult(summary={"error": f"Dialect '{dialect}' does not support ACL operations"})

        if config.acl_role_count == 0:
            logger.warning("ACL benchmark requires acl_role_count > 0")
            return AclBenchmarkResult(summary={"error": "ACL benchmark requires acl_role_count > 0"})

        mutation_results: list[AclMutationResult] = []
        created_roles: list[str] = []
        created_grants: list[AclGrant] = []

        # Phase 1: Create roles and measure timing
        setup_start = time.perf_counter()

        for i in range(config.acl_role_count):
            role_name = f"{config.prefix}role_{i:04d}"
            result = self._measure_create_role(connection, dialect, role_name)
            mutation_results.append(result)
            if result.success:
                created_roles.append(role_name)

        # Phase 2: Create tables for grants (if not already existing)
        # Use minimal tables for grant testing
        test_tables = self._create_grant_test_tables(connection, dialect, config)

        # Phase 3: Measure GRANT performance
        grants_to_create = self._get_grants_per_table(config.acl_permission_density)
        privileges = ["SELECT", "INSERT", "UPDATE"]

        for table_name in test_tables:
            for i, role_name in enumerate(created_roles[:grants_to_create]):
                priv_set = privileges[: (i % len(privileges)) + 1]
                result = self._measure_grant(connection, dialect, role_name, table_name, priv_set)
                mutation_results.append(result)
                if result.success:
                    created_grants.append(AclGrant(role_name, "table", table_name, priv_set))

        setup_time_ms = (time.perf_counter() - setup_start) * 1000

        # Phase 4: Run ACL introspection queries
        introspection_results = self.run_benchmark(
            connection,
            dialect=dialect,
            categories=["acl"],
            iterations=iterations,
        )

        # Phase 5: Measure REVOKE and cleanup
        teardown_start = time.perf_counter()

        # Revoke grants
        for grant in reversed(created_grants):
            result = self._measure_revoke(connection, dialect, grant.grantee, grant.object_name, grant.privileges)
            mutation_results.append(result)

        # Drop test tables
        self._drop_grant_test_tables(connection, dialect, test_tables)

        # Drop roles
        for role_name in reversed(created_roles):
            result = self._measure_drop_role(connection, dialect, role_name)
            mutation_results.append(result)

        teardown_time_ms = (time.perf_counter() - teardown_start) * 1000

        return AclBenchmarkResult(
            setup_time_ms=setup_time_ms,
            teardown_time_ms=teardown_time_ms,
            mutation_results=mutation_results,
            introspection_results=introspection_results,
        )

    def _measure_create_role(
        self,
        connection: DatabaseConnection,
        dialect: str,
        role_name: str,
    ) -> AclMutationResult:
        """Measure CREATE ROLE timing."""
        sql = generate_create_role_sql(role_name, dialect)

        if sql.startswith("--"):
            return AclMutationResult(
                operation="CREATE_ROLE",
                target_type="role",
                target_name=role_name,
                grantee=role_name,
                success=False,
                error="CREATE ROLE not supported on this platform",
            )

        start = time.perf_counter()
        try:
            self._execute(connection, sql)
            elapsed_ms = (time.perf_counter() - start) * 1000
            return AclMutationResult(
                operation="CREATE_ROLE",
                target_type="role",
                target_name=role_name,
                grantee=role_name,
                execution_time_ms=elapsed_ms,
                success=True,
            )
        except Exception as e:
            elapsed_ms = (time.perf_counter() - start) * 1000
            return AclMutationResult(
                operation="CREATE_ROLE",
                target_type="role",
                target_name=role_name,
                grantee=role_name,
                execution_time_ms=elapsed_ms,
                success=False,
                error=str(e),
            )

    def _measure_drop_role(
        self,
        connection: DatabaseConnection,
        dialect: str,
        role_name: str,
    ) -> AclMutationResult:
        """Measure DROP ROLE timing."""
        sql = generate_drop_role_sql(role_name, dialect)

        if sql.startswith("--"):
            return AclMutationResult(
                operation="DROP_ROLE",
                target_type="role",
                target_name=role_name,
                grantee=role_name,
                success=False,
                error="DROP ROLE not supported on this platform",
            )

        start = time.perf_counter()
        try:
            self._execute(connection, sql)
            elapsed_ms = (time.perf_counter() - start) * 1000
            return AclMutationResult(
                operation="DROP_ROLE",
                target_type="role",
                target_name=role_name,
                grantee=role_name,
                execution_time_ms=elapsed_ms,
                success=True,
            )
        except Exception as e:
            elapsed_ms = (time.perf_counter() - start) * 1000
            return AclMutationResult(
                operation="DROP_ROLE",
                target_type="role",
                target_name=role_name,
                grantee=role_name,
                execution_time_ms=elapsed_ms,
                success=False,
                error=str(e),
            )

    def _measure_grant(
        self,
        connection: DatabaseConnection,
        dialect: str,
        grantee: str,
        object_name: str,
        privileges: list[str],
    ) -> AclMutationResult:
        """Measure GRANT timing."""
        sql = generate_grant_sql(
            grantee=grantee,
            object_name=object_name,
            privileges=privileges,
            dialect=dialect,
        )

        start = time.perf_counter()
        try:
            self._execute(connection, sql)
            elapsed_ms = (time.perf_counter() - start) * 1000
            return AclMutationResult(
                operation="GRANT",
                target_type="table",
                target_name=object_name,
                grantee=grantee,
                privileges=privileges,
                execution_time_ms=elapsed_ms,
                success=True,
            )
        except Exception as e:
            elapsed_ms = (time.perf_counter() - start) * 1000
            return AclMutationResult(
                operation="GRANT",
                target_type="table",
                target_name=object_name,
                grantee=grantee,
                privileges=privileges,
                execution_time_ms=elapsed_ms,
                success=False,
                error=str(e),
            )

    def _measure_revoke(
        self,
        connection: DatabaseConnection,
        dialect: str,
        grantee: str,
        object_name: str,
        privileges: list[str],
    ) -> AclMutationResult:
        """Measure REVOKE timing."""
        sql = generate_revoke_sql(
            grantee=grantee,
            object_name=object_name,
            privileges=privileges,
            dialect=dialect,
        )

        start = time.perf_counter()
        try:
            self._execute(connection, sql)
            elapsed_ms = (time.perf_counter() - start) * 1000
            return AclMutationResult(
                operation="REVOKE",
                target_type="table",
                target_name=object_name,
                grantee=grantee,
                privileges=privileges,
                execution_time_ms=elapsed_ms,
                success=True,
            )
        except Exception as e:
            elapsed_ms = (time.perf_counter() - start) * 1000
            return AclMutationResult(
                operation="REVOKE",
                target_type="table",
                target_name=object_name,
                grantee=grantee,
                privileges=privileges,
                execution_time_ms=elapsed_ms,
                success=False,
                error=str(e),
            )

    def _get_grants_per_table(self, density: PermissionDensity) -> int:
        """Get number of grants per table based on density setting."""
        density_map = {
            PermissionDensity.NONE: 0,
            PermissionDensity.SPARSE: 2,
            PermissionDensity.MODERATE: 7,
            PermissionDensity.DENSE: 20,
        }
        return density_map.get(density, 0)

    def _create_grant_test_tables(
        self,
        connection: DatabaseConnection,
        dialect: str,
        config: MetadataComplexityConfig,
    ) -> list[str]:
        """Create minimal test tables for GRANT testing."""
        test_tables: list[str] = []
        num_tables = min(5, config.catalog_size) if config.catalog_size > 0 else 3

        for i in range(num_tables):
            table_name = f"{config.prefix}acl_test_{i:04d}"
            sql = f"CREATE TABLE IF NOT EXISTS {table_name} (id INTEGER PRIMARY KEY, name VARCHAR(100));"
            try:
                self._execute(connection, sql)
                test_tables.append(table_name)
            except Exception as e:
                logger.warning(f"Could not create test table {table_name}: {e}")

        return test_tables

    def _drop_grant_test_tables(
        self,
        connection: DatabaseConnection,
        dialect: str,
        table_names: list[str],
    ) -> None:
        """Drop test tables created for GRANT testing."""
        for table_name in table_names:
            try:
                sql = f"DROP TABLE IF EXISTS {table_name};"
                self._execute(connection, sql)
            except Exception as e:
                logger.warning(f"Could not drop test table {table_name}: {e}")

    def _run_default_acl_mutations(
        self,
        connection: DatabaseConnection,
        dialect: str,
    ) -> list[AclMutationResult]:
        """Run default ACL mutation tests (CREATE ROLE, GRANT, REVOKE, DROP ROLE).

        This runs a minimal set of ACL operations to measure mutation performance
        as part of the standard benchmark run.

        Args:
            connection: Database connection
            dialect: Target SQL dialect

        Returns:
            List of AclMutationResult with timing for each operation
        """
        results: list[AclMutationResult] = []
        created_roles: list[str] = []
        created_grants: list[tuple[str, str, list[str]]] = []  # (role, table, privs)

        # Create 3 test roles
        role_names = [
            "benchbox_test_role_reader",
            "benchbox_test_role_writer",
            "benchbox_test_role_admin",
        ]

        for role_name in role_names:
            result = self._measure_create_role(connection, dialect, role_name)
            results.append(result)
            if result.success:
                created_roles.append(role_name)

        # Create a test table for grants
        test_table = "benchbox_acl_mutation_test"
        try:
            self._execute(
                connection,
                f"CREATE TABLE IF NOT EXISTS {test_table} (id INTEGER, data VARCHAR(100));",
            )
        except Exception as e:
            logger.warning(f"Could not create ACL test table: {e}")
            # Clean up roles and return
            for role_name in reversed(created_roles):
                results.append(self._measure_drop_role(connection, dialect, role_name))
            return results

        # Issue GRANTs with different privilege sets
        privilege_sets = [
            ["SELECT"],
            ["SELECT", "INSERT"],
            ["SELECT", "INSERT", "UPDATE", "DELETE"],
        ]

        for role_name, privs in zip(created_roles, privilege_sets):
            result = self._measure_grant(connection, dialect, role_name, test_table, privs)
            results.append(result)
            if result.success:
                created_grants.append((role_name, test_table, privs))

        # Revoke all grants
        for role_name, table_name, privs in reversed(created_grants):
            result = self._measure_revoke(connection, dialect, role_name, table_name, privs)
            results.append(result)

        # Drop test table
        try:
            self._execute(connection, f"DROP TABLE IF EXISTS {test_table};")
        except Exception as e:
            logger.warning(f"Could not drop ACL test table: {e}")

        # Drop roles
        for role_name in reversed(created_roles):
            result = self._measure_drop_role(connection, dialect, role_name)
            results.append(result)

        return results

    def _build_acl_summary(self, results: list[AclMutationResult]) -> dict[str, Any]:
        """Build summary statistics from ACL mutation results.

        Args:
            results: List of ACL mutation results

        Returns:
            Summary dictionary with aggregated statistics
        """
        if not results:
            return {}

        total_ops = len(results)
        successful_ops = sum(1 for r in results if r.success)
        failed_ops = total_ops - successful_ops

        times = [r.execution_time_ms for r in results if r.success]

        # Group by operation type
        by_operation: dict[str, list[AclMutationResult]] = {}
        for r in results:
            by_operation.setdefault(r.operation, []).append(r)

        operation_summary = {}
        for op, op_results in by_operation.items():
            op_times = [r.execution_time_ms for r in op_results if r.success]
            operation_summary[op] = {
                "count": len(op_results),
                "successful": sum(1 for r in op_results if r.success),
                "failed": sum(1 for r in op_results if not r.success),
                "total_time_ms": sum(op_times) if op_times else 0.0,
                "avg_time_ms": sum(op_times) / len(op_times) if op_times else 0.0,
            }

        return {
            "total_operations": total_ops,
            "successful_operations": successful_ops,
            "failed_operations": failed_ops,
            "total_time_ms": sum(times) if times else 0.0,
            "avg_time_ms": sum(times) / len(times) if times else 0.0,
            "min_time_ms": min(times) if times else 0.0,
            "max_time_ms": max(times) if times else 0.0,
            "by_operation": operation_summary,
        }

    def _execute(self, connection: DatabaseConnection, sql: str) -> Any:
        """Execute SQL statement on connection."""
        if hasattr(connection, "execute"):
            return connection.execute(sql)
        elif hasattr(connection, "cursor"):
            cursor = connection.cursor()
            cursor.execute(sql)
            return cursor
        else:
            raise TypeError(f"Unsupported connection type: {type(connection)}")

    # =========================================================================
    # DataFrame Support Methods
    # =========================================================================

    def supports_dataframe_mode(self) -> bool:
        """Check if this benchmark supports DataFrame execution mode.

        Returns:
            True - Metadata Primitives supports DataFrame mode via the
            DataFrameMetadataOperationsManager for schema introspection,
            catalog operations, and lakehouse metadata.
        """
        return True

    def get_dataframe_operations(
        self,
        platform_name: str,
        spark_session: Any = None,
    ) -> Any:
        """Get DataFrame metadata operations manager for a platform.

        Returns a DataFrameMetadataOperationsManager configured for the given
        platform. Use this to execute metadata introspection operations on
        DataFrame platforms.

        Args:
            platform_name: Platform name (e.g., "polars-df", "pyspark-df")
            spark_session: SparkSession instance (required for pyspark-df catalog ops)

        Returns:
            DataFrameMetadataOperationsManager instance

        Raises:
            ValueError: If platform doesn't support DataFrame operations

        Example:
            >>> benchmark = MetadataPrimitivesBenchmark()
            >>> ops = benchmark.get_dataframe_operations("polars-df")
            >>> result = ops.execute_get_schema(df)
        """
        from benchbox.core.metadata_primitives.dataframe_operations import (
            get_dataframe_metadata_manager,
        )

        manager = get_dataframe_metadata_manager(platform_name, spark_session=spark_session)
        if manager is None:
            raise ValueError(
                f"Platform '{platform_name}' does not support DataFrame metadata operations. "
                f"Supported platforms: polars-df, pandas-df, pyspark-df, datafusion-df"
            )
        return manager

    def get_dataframe_capabilities(
        self,
        platform_name: str,
        spark_session: Any = None,
    ) -> Any:
        """Get DataFrame metadata capabilities for a platform.

        Returns the DataFrameMetadataCapabilities describing what metadata
        operations are supported on the given platform.

        Args:
            platform_name: Platform name (e.g., "polars-df", "pyspark-df")
            spark_session: SparkSession instance (required for pyspark-df capability detection)

        Returns:
            DataFrameMetadataCapabilities instance

        Example:
            >>> benchmark = MetadataPrimitivesBenchmark()
            >>> caps = benchmark.get_dataframe_capabilities("polars-df")
            >>> if caps.supports_catalog:
            ...     # Run catalog operations
        """
        from benchbox.core.metadata_primitives.dataframe_operations import (
            get_dataframe_metadata_manager,
        )

        manager = get_dataframe_metadata_manager(platform_name, spark_session=spark_session)
        if manager is None:
            from benchbox.core.metadata_primitives.dataframe_operations import (
                get_platform_capabilities,
            )

            return get_platform_capabilities(platform_name)
        return manager.get_capabilities()

    def run_dataframe_benchmark(
        self,
        platform_name: str,
        dataframes: dict[str, Any],
        spark_session: Any = None,
        categories: list[str] | None = None,
        iterations: int = 1,
    ) -> MetadataBenchmarkResult:
        """Run Metadata Primitives benchmark on DataFrame platforms.

        Executes metadata introspection operations on the provided DataFrames
        and returns timing results.

        Args:
            platform_name: Platform name (e.g., "polars-df", "pyspark-df")
            dataframes: Dictionary mapping table names to DataFrames
            spark_session: SparkSession instance (required for pyspark-df catalog ops)
            categories: Optional list of operation categories to run
                       ("schema", "catalog", "lakehouse", "complexity")
            iterations: Number of times to run each operation (default: 1)

        Returns:
            MetadataBenchmarkResult with all operation timings and summary

        Example:
            >>> import polars as pl
            >>> benchmark = MetadataPrimitivesBenchmark()
            >>> dfs = {"orders": pl.read_parquet("orders.parquet")}
            >>> result = benchmark.run_dataframe_benchmark("polars-df", dfs)
        """
        from benchbox.core.metadata_primitives.dataframe_operations import (
            OPERATION_CATEGORIES,
            MetadataOperationCategory,
            MetadataOperationType,
        )

        manager = self.get_dataframe_operations(platform_name, spark_session=spark_session)
        capabilities = manager.get_capabilities()

        # Determine which operations to run
        operations_to_run: list[MetadataOperationType] = []

        if categories:
            # Filter by category
            category_set = {MetadataOperationCategory(c.lower()) for c in categories}
            for op in MetadataOperationType:
                if OPERATION_CATEGORIES.get(op) in category_set:
                    if capabilities.supports_operation(op):
                        operations_to_run.append(op)
        else:
            # Run all supported operations
            operations_to_run = capabilities.get_supported_operations()

        result = MetadataBenchmarkResult()
        all_results: list[MetadataQueryResult] = []

        # Schema introspection operations run on each DataFrame
        schema_ops = {
            MetadataOperationType.LIST_COLUMNS,
            MetadataOperationType.GET_DTYPES,
            MetadataOperationType.GET_SCHEMA,
            MetadataOperationType.DESCRIBE_STATS,
            MetadataOperationType.ROW_COUNT,
            MetadataOperationType.COLUMN_COUNT,
        }

        for _ in range(iterations):
            for op in operations_to_run:
                if op in schema_ops:
                    # Run schema ops on each DataFrame
                    for table_name, df in dataframes.items():
                        df_result = self._execute_dataframe_operation(manager, op, df, table_name)
                        query_result = self._convert_df_result_to_query_result(df_result, table_name)
                        all_results.append(query_result)

                        if query_result.success:
                            result.successful_queries += 1
                        else:
                            result.failed_queries += 1
                        result.total_time_ms += query_result.execution_time_ms

                elif op in {
                    MetadataOperationType.LIST_DATABASES,
                    MetadataOperationType.LIST_TABLES,
                }:
                    # Catalog ops don't need a DataFrame
                    df_result = self._execute_catalog_operation(manager, op)
                    query_result = self._convert_df_result_to_query_result(df_result, "catalog")
                    all_results.append(query_result)

                    if query_result.success:
                        result.successful_queries += 1
                    else:
                        result.failed_queries += 1
                    result.total_time_ms += query_result.execution_time_ms

        result.total_queries = len(all_results)
        result.results = all_results

        # Build category summary
        self._build_dataframe_category_summary(result, all_results)

        return result

    def _execute_dataframe_operation(
        self,
        manager: Any,
        operation: Any,
        dataframe: Any,
        table_name: str,
    ) -> Any:
        """Execute a single DataFrame metadata operation.

        Args:
            manager: DataFrameMetadataOperationsManager
            operation: MetadataOperationType
            dataframe: The DataFrame to introspect
            table_name: Name of the table (for logging)

        Returns:
            DataFrameMetadataResult
        """
        from benchbox.core.metadata_primitives.dataframe_operations import (
            MetadataOperationType,
        )

        op_map = {
            MetadataOperationType.LIST_COLUMNS: manager.execute_list_columns,
            MetadataOperationType.GET_DTYPES: manager.execute_get_dtypes,
            MetadataOperationType.GET_SCHEMA: manager.execute_get_schema,
            MetadataOperationType.DESCRIBE_STATS: manager.execute_describe_stats,
            MetadataOperationType.ROW_COUNT: manager.execute_row_count,
            MetadataOperationType.COLUMN_COUNT: manager.execute_column_count,
        }

        if operation in op_map:
            return op_map[operation](dataframe)

        # Unsupported operation
        from benchbox.core.metadata_primitives.dataframe_operations import (
            DataFrameMetadataResult,
        )

        return DataFrameMetadataResult.failure_result(
            operation,
            f"Operation {operation.value} not supported for DataFrame introspection",
        )

    def _execute_catalog_operation(
        self,
        manager: Any,
        operation: Any,
    ) -> Any:
        """Execute a catalog metadata operation.

        Args:
            manager: DataFrameMetadataOperationsManager
            operation: MetadataOperationType

        Returns:
            DataFrameMetadataResult
        """
        from benchbox.core.metadata_primitives.dataframe_operations import (
            MetadataOperationType,
        )

        if operation == MetadataOperationType.LIST_DATABASES:
            return manager.execute_list_databases()
        elif operation == MetadataOperationType.LIST_TABLES:
            return manager.execute_list_tables()

        from benchbox.core.metadata_primitives.dataframe_operations import (
            DataFrameMetadataResult,
        )

        return DataFrameMetadataResult.failure_result(
            operation,
            f"Catalog operation {operation.value} not implemented",
        )

    def _convert_df_result_to_query_result(
        self,
        df_result: Any,
        table_name: str,
    ) -> MetadataQueryResult:
        """Convert DataFrameMetadataResult to MetadataQueryResult.

        Args:
            df_result: DataFrameMetadataResult
            table_name: Name of the table

        Returns:
            MetadataQueryResult
        """
        from benchbox.core.metadata_primitives.dataframe_operations import (
            OPERATION_CATEGORIES,
        )

        category = OPERATION_CATEGORIES.get(df_result.operation_type)
        category_str = category.value if category else "schema"

        return MetadataQueryResult(
            query_id=f"df_{df_result.operation_type.value}_{table_name}",
            category=category_str,
            execution_time_ms=df_result.duration_ms,
            row_count=df_result.result_count,
            success=df_result.success,
            error=df_result.error_message,
        )

    def _build_dataframe_category_summary(
        self,
        result: MetadataBenchmarkResult,
        all_results: list[MetadataQueryResult],
    ) -> None:
        """Build category summary from DataFrame benchmark results.

        Args:
            result: MetadataBenchmarkResult to update
            all_results: List of MetadataQueryResult
        """
        category_times: dict[str, list[float]] = {}
        category_counts: dict[str, int] = {}
        category_successes: dict[str, int] = {}

        for qr in all_results:
            cat = qr.category
            if cat not in category_times:
                category_times[cat] = []
                category_counts[cat] = 0
                category_successes[cat] = 0

            category_times[cat].append(qr.execution_time_ms)
            category_counts[cat] += 1
            if qr.success:
                category_successes[cat] += 1

        for cat in category_times:
            times = category_times[cat]
            result.category_summary[cat] = {
                "total_queries": category_counts[cat],
                "successful": category_successes[cat],
                "failed": category_counts[cat] - category_successes[cat],
                "total_time_ms": sum(times),
                "avg_time_ms": sum(times) / len(times) if times else 0.0,
                "min_time_ms": min(times) if times else 0.0,
                "max_time_ms": max(times) if times else 0.0,
            }


__all__ = [
    "AclBenchmarkResult",
    "AclMutationResult",
    "ComplexityBenchmarkResult",
    "MetadataBenchmarkResult",
    "MetadataPrimitivesBenchmark",
    "MetadataQueryResult",
]
