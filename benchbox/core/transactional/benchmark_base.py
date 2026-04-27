"""Shared benchmark base class for transactional benchmark families.

``TransactionalBenchmarkBase[ResultT]`` consolidates the near-identical
``TransactionPrimitivesBenchmark`` and ``WritePrimitivesBenchmark`` classes.
Subclasses inherit the shared property/data/catalog/query API and only need
to implement their spec-specific ``execute_operation``, ``setup``,
``is_setup``, and schema methods.
"""

from __future__ import annotations

from abc import abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING, Any, Generic, Optional, TypeVar, Union

if TYPE_CHECKING:
    from cloudpathlib import CloudPath

    from benchbox.utils.cloud_storage import DatabricksPath

from benchbox.base import BaseBenchmark
from benchbox.core.connection import DatabaseConnection
from benchbox.core.operations import OperationExecutor
from benchbox.core.transactional.operations_registry_base import OperationsRegistryBase
from benchbox.utils.cloud_storage import create_path_handler

PathLike = Union[Path, "CloudPath", "DatabricksPath"]
ResultT = TypeVar("ResultT")


class TransactionalBenchmarkBase(BaseBenchmark, OperationExecutor, Generic[ResultT]):
    """Base class shared by transaction_primitives and write_primitives families.

    Provides the shared property/data-generation/catalog/query API.  Subclasses
    must supply:

    - ``_benchmark_label`` class variable - human-readable name used in log
      messages (e.g. "Transaction Primitives").
    - ``_staging_tables`` class variable - the ``STAGING_TABLES`` mapping
      imported from the spec module; used by ``get_benchmark_info``.
    - ``operations_manager``, ``data_generator``, ``tables`` instance attributes
      assigned in ``__init__``.
    - Concrete ``execute_operation`` (abstract via :class:`OperationExecutor`).
    - Concrete ``setup`` and ``is_setup`` (abstract below; schema-specific SQL).
    """

    _benchmark_label: str  # e.g. "Transaction Primitives"
    _staging_tables: dict[str, Any]  # STAGING_TABLES from the spec module

    # Declared without default so type-checkers know they exist;
    # assigned by each subclass __init__.
    operations_manager: OperationsRegistryBase[Any]
    data_generator: Any
    tables: dict[str, Path]

    # ------------------------------------------------------------------
    # Abstract hooks implemented spec-locally
    # ------------------------------------------------------------------

    @abstractmethod
    def setup(
        self,
        connection: DatabaseConnection,
        force: bool = False,
        dialect: str = "standard",
    ) -> dict[str, Any]:
        """Create and populate staging tables.  Schema-specific; stay spec-local."""

    @abstractmethod
    def is_setup(self, connection: DatabaseConnection) -> bool:
        """Return True when staging tables are present and populated."""

    # ------------------------------------------------------------------
    # Data source
    # ------------------------------------------------------------------

    def get_data_source_benchmark(self) -> Optional[str]:
        """Both transactional families reuse TPC-H data."""
        return "tpch"

    # ------------------------------------------------------------------
    # output_dir property (identical across both families)
    # ------------------------------------------------------------------

    @property
    def output_dir(self) -> PathLike:
        """Return the output directory path."""
        return self._output_dir

    @output_dir.setter
    def output_dir(self, value: Union[str, Path]) -> None:
        """Set the output directory and propagate to the data generator."""
        self._output_dir = create_path_handler(value)
        if hasattr(self, "data_generator"):
            self.data_generator.output_dir = self._output_dir
            if hasattr(self.data_generator, "tpch_generator"):
                self.data_generator.tpch_generator.output_dir = self._output_dir

    # ------------------------------------------------------------------
    # Data generation (identical modulo the label string)
    # ------------------------------------------------------------------

    def generate_data(self, tables: Optional[list[str]] = None) -> list[Union[str, Path]]:
        """Generate data for this benchmark (reuses TPC-H base data).

        Args:
            tables: Optional list of tables to generate. If None, generates all.

        Returns:
            List of paths to generated data files
        """
        self.log_verbose(f"Generating {self._benchmark_label} data at scale factor {self.scale_factor}...")
        self.tables = self.data_generator.generate()
        self.log_verbose(f"Base TPC-H data available: {len(self.tables)} tables")
        return list(self.tables.values())

    def ensure_auxiliary_data_files(self) -> None:
        """Ensure auxiliary data files (bulk load test files) exist.

        Called by the runner when reusing data from a manifest to guarantee
        bulk load test files are present even if they were not generated during
        the original data-generation run.  Uses file locking to prevent
        concurrent generation conflicts.
        """
        self.log_verbose("Checking for auxiliary data files (bulk load files)...")

        bulk_files_exist = self.data_generator.check_bulk_load_files_exist()

        if not bulk_files_exist:
            self.log_verbose("Bulk load files missing - generating now...")

            if self.data_generator._acquire_bulk_load_lock(timeout=300):
                try:
                    if not self.data_generator.check_bulk_load_files_exist():
                        bulk_files = self.data_generator.generate_bulk_load_files()
                        self.log_verbose(f"✅ Generated {len(bulk_files)} bulk load files")
                    else:
                        self.log_verbose("✅ Files generated by another process")
                except Exception as e:
                    self.log_verbose(f"⚠️ Warning: Failed to generate bulk load files: {e}")
                finally:
                    self.data_generator._release_bulk_load_lock()
            else:
                self.log_verbose("⚠️ Warning: Could not acquire lock for file generation (timeout)")
        else:
            self.log_verbose("✅ Bulk load files already exist")

    # ------------------------------------------------------------------
    # Operation catalog access (satisfies OperationExecutor abstract methods)
    # ------------------------------------------------------------------

    def get_all_operations(self) -> dict[str, Any]:
        """Get all available operations.

        Returns:
            Dictionary mapping operation IDs to operation objects
        """
        return self.operations_manager.get_all_operations()

    def get_operation_categories(self) -> list[str]:
        """Get list of available operation categories.

        Returns:
            List of category names
        """
        return self.operations_manager.get_operation_categories()

    def get_operation(self, operation_id: str) -> Any:
        """Get a specific operation by ID.

        Args:
            operation_id: Operation identifier

        Returns:
            Operation object

        Raises:
            ValueError: If operation_id is invalid
        """
        return self.operations_manager.get_operation(operation_id)

    def get_operations_by_category(self, category: str) -> dict[str, Any]:
        """Get operations filtered by category.

        Args:
            category: Category name (e.g., 'insert', 'update', 'delete')

        Returns:
            Dictionary mapping operation IDs to operation objects
        """
        return self.operations_manager.get_operations_by_category(category)

    # ------------------------------------------------------------------
    # Benchmark info / query API
    # ------------------------------------------------------------------

    def get_benchmark_info(self) -> dict[str, Any]:
        """Get information about the benchmark.

        Returns:
            Dictionary containing benchmark metadata
        """
        return {
            "name": self._name,
            "version": self._version,
            "description": self._description,
            "scale_factor": self.scale_factor,
            "total_operations": self.operations_manager.get_operation_count(),
            "categories": self.get_operation_categories(),
            "tables": list(self._staging_tables.keys()),
            "data_source": "tpch",
        }

    def get_query(self, query_id: Union[int, str], **kwargs: Any) -> str:
        """Get write SQL for a specific operation.

        Args:
            query_id: Operation identifier
            **kwargs: Additional parameters (unused for write/transaction operations)

        Returns:
            Write SQL string

        Raises:
            ValueError: If query_id is invalid
        """
        operation = self.operations_manager.get_operation(str(query_id))
        return operation.write_sql

    def get_queries(self, dialect: Optional[str] = None) -> dict[str, str]:
        """Get all write operations SQL.

        Args:
            dialect: Target SQL dialect (not yet implemented for write operations)

        Returns:
            Dictionary mapping operation IDs to write SQL
        """
        operations = self.operations_manager.get_all_operations()
        return {op_id: op.write_sql for op_id, op in operations.items()}

    def get_queries_by_category(self, category: str) -> dict[str, str]:
        """Get write operations SQL filtered by category.

        Args:
            category: Operation category (insert, update, delete, ddl, transaction)

        Returns:
            Dictionary mapping operation IDs to write SQL for the category
        """
        operations = self.operations_manager.get_operations_by_category(category)
        return {op_id: op.write_sql for op_id, op in operations.items()}

    # ------------------------------------------------------------------
    # execute_operation preamble helper
    # ------------------------------------------------------------------

    def _prepare_operation(
        self,
        operation_id: str,
        connection: DatabaseConnection,
        **kwargs: Any,
    ) -> tuple[Any, Optional[str], Optional[str]]:
        """Validate connection, look up operation, auto-setup staging tables if needed.

        Both ``execute_operation`` implementations open with identical preamble
        logic.  Subclasses call this helper and then continue with their
        spec-specific SQL execution paths.

        Args:
            operation_id: ID of the operation to execute
            connection: Database connection
            **kwargs: Forwarded kwargs; reads ``platform_key`` and ``sql_override``

        Returns:
            (operation, platform_key, sql_override) tuple

        Raises:
            ValueError: If connection is None or lacks an ``execute`` method
            RuntimeError: If staging table auto-setup fails
        """
        if not connection:
            raise ValueError("Connection is None")
        if not hasattr(connection, "execute"):
            raise ValueError(f"Invalid connection type: {type(connection).__name__}")

        platform_key: Optional[str] = kwargs.get("platform_key")
        sql_override: Optional[str] = kwargs.get("sql_override")

        operation = self.operations_manager.get_operation(operation_id)

        if operation.requires_setup and not self.is_setup(connection):
            self.log_verbose("Staging tables not initialized - running setup() automatically...")
            try:
                self.setup(connection, force=False, dialect=platform_key or "standard")
                self.log_verbose("Setup completed successfully")
            except Exception as e:
                raise RuntimeError(f"Failed to initialize staging tables before executing '{operation_id}': {e}") from e

        return operation, platform_key, sql_override

    # ------------------------------------------------------------------
    # run_benchmark (identical across both families)
    # ------------------------------------------------------------------

    def run_benchmark(
        self,
        connection: DatabaseConnection,
        operation_ids: Optional[list[str]] = None,
        categories: Optional[list[str]] = None,
    ) -> list[ResultT]:
        """Run the full benchmark suite (or a subset) and return results.

        Args:
            connection: Database connection
            operation_ids: Optional list of specific operations to run
            categories: Optional list of categories to run

        Returns:
            List of OperationResult objects
        """
        if operation_ids:
            operations = {op_id: self.get_operation(op_id) for op_id in operation_ids}
        elif categories:
            operations = {}
            for category in categories:
                operations.update(self.get_operations_by_category(category))
        else:
            operations = self.get_all_operations()

        self.log_verbose(f"Running {len(operations)} write operations...")

        results: list[ResultT] = []
        for op_id in operations:
            result = self.execute_operation(op_id, connection)
            results.append(result)  # type: ignore[arg-type]

            status = "✓" if result.success and result.validation_passed else "✗"
            self.log_verbose(
                f"{status} {op_id}: {result.write_duration_ms:.2f}ms write, "
                f"{result.validation_duration_ms:.2f}ms validation"
            )

        return results
