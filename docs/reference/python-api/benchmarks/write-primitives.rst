Write Primitives Benchmark API
==================================

.. tags:: reference, python-api, custom-benchmark

Complete Python API reference for the Write Primitives Benchmark.

Overview
--------

The Write Read Primitives benchmark tests fundamental database write operations using TPC-H schema as foundation. It provides comprehensive testing of INSERT, UPDATE, DELETE, BULK_LOAD, MERGE, DDL, and TRANSACTION operations with automatic validation and cleanup.

**Key Features**:

- **Data Sharing**: Reuses TPC-H data (no duplicate generation)
- **Catalog-Driven**: Operations defined in YAML catalog
- **12 Starter Operations**: Across 5 categories (INSERT, UPDATE, DELETE, DDL, TRANSACTION)
- **Automatic Validation**: Every write validated with read queries
- **Lifecycle Management**: Setup, reset, teardown, status checking
- **Extensible**: Easy to add more operations to catalog

**Reference**: See benchbox/core/write_primitives/README.md for full design

Quick Start
-----------

.. code-block:: python

    from benchbox import TPCH, WritePrimitives
    import duckdb

    # 1. Load TPC-H data first (required)
    tpch = TPCH(scale_factor=1.0)
    tpch.generate_data()

    conn = duckdb.connect("benchmark.db")
    adapter = tpch.create_adapter("duckdb")
    adapter.load_data(tpch, conn, tpch.output_dir)

    # 2. Setup Write Primitives
    bench = WritePrimitives(scale_factor=1.0)
    bench.setup(conn)

    # 3. Execute operations
    result = bench.execute_operation("insert_single_row", conn)
    print(f"Success: {result.success}, Time: {result.write_duration_ms:.2f}ms")

API Reference
-------------

WritePrimitives Class
~~~~~~~~~~~~~~~~~~~~~

.. autoclass:: benchbox.write_primitives.WritePrimitives
   :members:
   :inherited-members:

**Constructor**:

.. code-block:: python

    WritePrimitives(
        scale_factor: float = 1.0,
        output_dir: Optional[Union[str, Path]] = None,
        **kwargs
    )

**Parameters**:

- **scale_factor** (float): TPC-H scale factor (must match TPC-H data)
- **output_dir** (str | Path | None): Output directory (defaults to TPC-H path)

Lifecycle Methods
~~~~~~~~~~~~~~~~~

**setup(connection, force=False) -> dict**

Create staging tables and populate from TPC-H base tables.

**Parameters**:

- **connection**: Database connection
- **force** (bool): If True, drop existing staging tables first

**Returns**: Dict with keys ``success``, ``tables_created``, ``tables_populated``

**Raises**: ``RuntimeError`` if TPC-H tables don't exist

**Example**:

.. code-block:: python

    setup_result = bench.setup(conn, force=True)
    print(f"Tables created: {setup_result['tables_created']}")
    print(f"Rows: {setup_result['tables_populated']}")

**is_setup(connection) -> bool**

Check if staging tables are initialized and ready.

**Example**:

.. code-block:: python

    if bench.is_setup(conn):
        print("Ready to execute operations")

**reset(connection) -> None**

Truncate and repopulate staging tables to initial state.

**Example**:

.. code-block:: python

    # Reset after validation failures
    bench.reset(conn)

**teardown(connection) -> None**

Drop all staging tables.

**Example**:

.. code-block:: python

    # Cleanup when done
    bench.teardown(conn)

Operation Execution Methods
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

**execute_operation(operation_id, connection, use_transaction=True) -> OperationResult**

Execute a single write operation with validation and cleanup.

**Parameters**:

- **operation_id** (str): Operation ID (e.g., "insert_single_row")
- **connection**: Database connection
- **use_transaction** (bool): Wrap in transaction for rollback cleanup

**Returns**: ``OperationResult`` with execution metrics

**Raises**: ``ValueError`` if operation not found

**Example**:

.. code-block:: python

    result = bench.execute_operation("insert_single_row", conn)
    print(f"Operation: {result.operation_id}")
    print(f"Success: {result.success}")
    print(f"Rows affected: {result.rows_affected}")
    print(f"Write time: {result.write_duration_ms:.2f}ms")
    print(f"Validation: {result.validation_passed}")

**run_benchmark(connection, operation_ids=None, categories=None) -> list[OperationResult]**

Run multiple operations.

**Parameters**:

- **connection**: Database connection
- **operation_ids** (list[str] | None): List of specific operation IDs
- **categories** (list[str] | None): List of categories (e.g., ["insert", "update"])

**Returns**: List of ``OperationResult`` objects

**Example**:

.. code-block:: python

    # Run all operations
    results = bench.run_benchmark(conn)

    # Run only INSERT operations
    insert_results = bench.run_benchmark(conn, categories=["insert"])

    # Run specific operations
    specific_ops = ["insert_single_row", "update_single_row_pk"]
    results = bench.run_benchmark(conn, operation_ids=specific_ops)

Operation Query Methods
~~~~~~~~~~~~~~~~~~~~~~~

**get_all_operations() -> dict[str, WriteOperation]**

Get all available operations.

**Example**:

.. code-block:: python

    operations = bench.get_all_operations()
    print(f"Total operations: {len(operations)}")

**get_operation(operation_id) -> WriteOperation**

Get specific operation by ID.

**Example**:

.. code-block:: python

    op = bench.get_operation("insert_single_row")
    print(f"Category: {op.category}")

**get_operations_by_category(category) -> dict[str, WriteOperation]**

Get operations filtered by category.

**Parameters**:

- **category** (str): Category name ("insert", "update", "delete", "ddl", "transaction")

**Example**:

.. code-block:: python

    insert_ops = bench.get_operations_by_category("insert")
    print(f"INSERT operations: {len(insert_ops)}")

**get_operation_categories() -> list[str]**

Get list of available categories.

**Example**:

.. code-block:: python

    categories = bench.get_operation_categories()
    # Output: ['insert', 'update', 'delete', 'ddl', 'transaction']

**get_queries(dialect=None) -> dict[str, str]**

Get all write operation SQL.

**Example**:

.. code-block:: python

    queries = bench.get_queries()
    print(queries["insert_single_row"])

**get_query(query_id, \*\*kwargs) -> str**

Get a specific write operation SQL.

**Example**:

.. code-block:: python

    sql = bench.get_query("insert_single_row")

Schema Methods
~~~~~~~~~~~~~~

**get_schema(dialect="standard") -> dict[str, dict]**

Get staging table schema definitions.

**Example**:

.. code-block:: python

    schema = bench.get_schema(dialect="duckdb")
    for table, definition in schema.items():
        print(f"{table}: {definition['columns']}")

**get_create_tables_sql(dialect="standard") -> str**

Get SQL to create staging tables.

**Example**:

.. code-block:: python

    create_sql = bench.get_create_tables_sql(dialect="postgresql")

OperationResult Class
~~~~~~~~~~~~~~~~~~~~~

Result object returned by ``execute_operation`` and ``run_benchmark``.

**Fields**:

- **operation_id** (str): Operation identifier
- **success** (bool): Whether operation succeeded
- **write_duration_ms** (float): Write execution time in milliseconds
- **rows_affected** (int): Number of rows affected (-1 if unknown)
- **validation_duration_ms** (float): Validation time in milliseconds
- **validation_passed** (bool): Whether validation passed
- **validation_results** (list[dict]): Detailed validation results
- **cleanup_duration_ms** (float): Cleanup time in milliseconds
- **cleanup_success** (bool): Whether cleanup succeeded
- **error** (str | None): Error message if operation failed
- **cleanup_warning** (str | None): Warning for transaction cleanup failures

Operations Catalog
------------------

The benchmark includes **12 starter operations** across 5 categories:

INSERT Operations (3)
~~~~~~~~~~~~~~~~~~~~~

- **insert_single_row**: Single row INSERT with all columns
- **insert_batch_values_10**: Batch INSERT with 10 rows
- **insert_select_simple**: INSERT...SELECT with WHERE filter

UPDATE Operations (3)
~~~~~~~~~~~~~~~~~~~~~

- **update_single_row_pk**: UPDATE single row by primary key
- **update_selective_10pct**: UPDATE ~10% of rows
- **update_with_subquery**: UPDATE with correlated subquery

DELETE Operations (2)
~~~~~~~~~~~~~~~~~~~~~

- **delete_single_row_pk**: DELETE single row by primary key
- **delete_selective_10pct**: DELETE ~10% of rows

DDL Operations (3)
~~~~~~~~~~~~~~~~~~

- **ddl_create_table_simple**: CREATE TABLE with simple schema
- **ddl_truncate_table_small**: TRUNCATE small staging table
- **ddl_create_table_as_select_simple**: CTAS with simple SELECT

TRANSACTION Operations (1)
~~~~~~~~~~~~~~~~~~~~~~~~~~~

- **transaction_commit_small**: BEGIN + 10 writes + COMMIT

Staging Tables
--------------

The benchmark creates these staging tables:

**Data Tables**:

- **orders_stage**: Copy of ORDERS for UPDATE/DELETE testing
- **lineitem_stage**: Copy of LINEITEM for write testing
- **orders_new**: Source for MERGE testing
- **orders_summary**: Target for aggregated INSERT...SELECT
- **lineitem_enriched**: Target for joined INSERT...SELECT

**Metadata Tables**:

- **write_ops_log**: Audit log for all write operations
- **batch_metadata**: Tracks batch operations

Usage Examples
--------------

Complete Workflow
~~~~~~~~~~~~~~~~~

.. code-block:: python

    from benchbox import TPCH, WritePrimitives
    import duckdb

    # 1. Load TPC-H data first
    tpch = TPCH(scale_factor=1.0)
    tpch.generate_data()

    conn = duckdb.connect("benchmark.db")
    adapter = tpch.create_adapter("duckdb")
    adapter.load_data(tpch, conn, tpch.output_dir)

    # 2. Setup Write Primitives
    bench = WritePrimitives(scale_factor=1.0)
    setup_result = bench.setup(conn, force=True)
    print(f"Setup: {setup_result['success']}")
    print(f"Tables: {setup_result['tables_created']}")

    # 3. Execute single operation
    result = bench.execute_operation("insert_single_row", conn)
    print(f"Success: {result.success}")
    print(f"Time: {result.write_duration_ms:.2f}ms")
    print(f"Validation: {result.validation_passed}")

    # 4. Run all operations
    results = bench.run_benchmark(conn)
    print(f"Total: {len(results)}")
    successful = [r for r in results if r.success]
    print(f"Successful: {len(successful)}")

    # 5. Cleanup
    bench.teardown(conn)

Category-Based Testing
~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    # Test each category separately
    categories = bench.get_operation_categories()

    for category in categories:
        print(f"\nTesting {category.upper()} operations:")
        results = bench.run_benchmark(conn, categories=[category])

        for result in results:
            status = "✓" if result.success else "✗"
            print(f"  {status} {result.operation_id}: {result.write_duration_ms:.2f}ms")

        # Reset between categories
        bench.reset(conn)

Performance Analysis
~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    import time
    from statistics import mean, median

    # Run multiple iterations for stable timing
    operation_id = "insert_single_row"
    iterations = 10
    times = []

    for i in range(iterations):
        result = bench.execute_operation(operation_id, conn)
        if result.success:
            times.append(result.write_duration_ms)

        # Reset between iterations
        if i < iterations - 1:
            bench.reset(conn)

    print(f"Operation: {operation_id}")
    print(f"Iterations: {iterations}")
    print(f"Mean: {mean(times):.2f}ms")
    print(f"Median: {median(times):.2f}ms")
    print(f"Min: {min(times):.2f}ms")
    print(f"Max: {max(times):.2f}ms")

Error Handling and Recovery
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    # Handle operation failures
    result = bench.execute_operation("insert_batch_values_10", conn)

    if not result.success:
        print(f"Operation failed: {result.error}")
        if result.cleanup_warning:
            print(f"Cleanup warning: {result.cleanup_warning}")

        # Reset to recover
        print("Resetting staging tables...")
        bench.reset(conn)

    # Handle validation failures
    if not result.validation_passed:
        print("Validation failed:")
        for val_result in result.validation_results:
            if not val_result['passed']:
                print(f"  Query: {val_result['query_id']}")
                print(f"  Expected: {val_result['expected_rows']}")
                print(f"  Actual: {val_result['actual_rows']}")

        # Reset and retry
        bench.reset(conn)
        result = bench.execute_operation("insert_batch_values_10", conn)

Best Practices
--------------

1. **Always Load TPC-H First**

   .. code-block:: python

       # Wrong: Will fail
       bench = WritePrimitives()
       bench.setup(conn)  # Error: TPC-H tables not found

       # Correct: Load TPC-H first
       tpch = TPCH(scale_factor=1.0)
       tpch.generate_data()
       adapter = tpch.create_adapter("duckdb")
       adapter.load_data(tpch, conn, tpch.output_dir)

       bench = WritePrimitives(scale_factor=1.0)
       bench.setup(conn)

2. **Check Setup Status**

   .. code-block:: python

       if not bench.is_setup(conn):
           bench.setup(conn)

3. **Use Transactions for Cleanup**

   .. code-block:: python

       # Automatic rollback cleanup
       result = bench.execute_operation("insert_single_row", conn, use_transaction=True)

       # Manual cleanup (for DDL operations)
       result = bench.execute_operation("ddl_create_table_simple", conn, use_transaction=False)

4. **Reset Between Test Runs**

   .. code-block:: python

       # Reset to ensure clean state
       for operation_id in ["insert_single_row", "update_single_row_pk"]:
           result = bench.execute_operation(operation_id, conn)
           bench.reset(conn)  # Clean slate for next operation

5. **Validate and Handle Errors**

   .. code-block:: python

       result = bench.execute_operation("insert_select_simple", conn)

       if result.success and result.validation_passed:
           print(f"Success: {result.write_duration_ms:.2f}ms")
       elif not result.success:
           print(f"Failed: {result.error}")
       elif not result.validation_passed:
           print("Validation failed, check data dependencies")

Common Issues
-------------

**Issue: "Required TPC-H table not found"**
  - **Cause**: Write Primitives requires TPC-H base tables
  - **Solution**: Load TPC-H data before calling setup()

**Issue: "Staging tables not initialized"**
  - **Cause**: Trying to execute before calling setup()
  - **Solution**: Call bench.setup(conn) first

**Issue: Transaction cleanup failures**
  - **Cause**: Some operations can't be rolled back (DDL)
  - **Solution**: Use bench.reset(conn) to restore clean state

**Issue: Validation failures**
  - **Cause**: Data-dependent operations or constraint violations
  - **Solution**: Check validation_results for details, reset if needed

**Issue: rows_affected = -1**
  - **Cause**: Some databases (DuckDB) don't return rowcount
  - **Impact**: Normal behavior, doesn't affect operation success

DataFrame Support
-----------------

Write Primitives provides DataFrame support for write operations on DataFrame platforms.

**Platform Capabilities**:

.. list-table::
   :header-rows: 1
   :widths: 20 15 15 15 15 20

   * - Platform
     - INSERT
     - UPDATE
     - DELETE
     - MERGE
     - Notes
   * - Polars
     - ✓
     - ✓
     - ✓
     - ✓
     - Full support via read-modify-write
   * - Pandas
     - ✓
     - ✗
     - ✗
     - ✗
     - File-level operations only
   * - PySpark
     - ✓
     - ✓*
     - ✓*
     - ✓*
     - *Requires Delta Lake table format*

DataFrameWriteOperationsManager
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from benchbox.core.write_primitives.dataframe_operations import (
        DataFrameWriteOperationsManager,
        WriteOperationType,
        get_dataframe_write_manager,
    )

    # Create manager
    manager = DataFrameWriteOperationsManager("polars-df")

    # Check capabilities
    caps = manager.get_capabilities()
    print(f"Supports UPDATE: {caps.supports_operation(WriteOperationType.UPDATE)}")

    # Execute BULK_LOAD
    result = manager.execute_bulk_load(
        source_path="/data/raw/orders.csv",
        target_path="/data/orders",
        source_format="csv",
        target_format="parquet",
        compression="zstd",
    )

**Available Methods**:

- ``get_capabilities()`` - Get platform write capabilities
- ``supports_operation(op)`` - Check if operation is supported
- ``execute_insert(table_path, dataframe, mode)`` - Insert rows
- ``execute_update(table_path, condition, updates)`` - Update rows
- ``execute_delete(table_path, condition)`` - Delete rows
- ``execute_merge(table_path, source_df, condition, ...)`` - Merge/upsert rows
- ``execute_bulk_load(source_path, target_path, ...)`` - Bulk load files

DataFrameWriteResult
~~~~~~~~~~~~~~~~~~~~

All DataFrame write operations return a ``DataFrameWriteResult``:

.. code-block:: python

    @dataclass
    class DataFrameWriteResult:
        operation_type: WriteOperationType
        success: bool
        start_time: float
        end_time: float
        duration_ms: float
        rows_affected: int
        bytes_written: int | None = None
        compression: str | None = None
        file_count: int | None = None
        error_message: str | None = None
        validation_passed: bool = True

DataFrameWriteCapabilities
~~~~~~~~~~~~~~~~~~~~~~~~~~

Platform capabilities for write operations:

.. code-block:: python

    @dataclass
    class DataFrameWriteCapabilities:
        platform_name: str
        maintenance_caps: DataFrameMaintenanceCapabilities | None
        supports_bulk_load: bool = True
        supports_compression: bool = True
        supported_compressions: list[str]  # e.g., ["zstd", "snappy", "gzip"]
        supports_partitioning: bool = False
        supports_sorting: bool = True

See Also
--------

- :doc:`/benchmarks/write-primitives` - Write Primitives benchmark guide
- :doc:`read-primitives` - Read Primitives benchmark
- :doc:`tpch` - TPC-H benchmark (data source)
- :doc:`/reference/python-api/base` - Base benchmark interface
- :doc:`/platforms/dataframe` - DataFrame platforms overview

Future Expansion
~~~~~~~~~~~~~~~~

The catalog can be expanded to include all 101 planned operations:

- More INSERT variants (12 total planned)
- More UPDATE variants (15 total planned)
- More DELETE variants (12 total planned)
- BULK_LOAD operations (24 planned) - CSV, Parquet, compressions
- MERGE/UPSERT operations (18 planned)
- More DDL operations (12 total planned)
- More TRANSACTION operations (8 total planned)

See benchbox/core/write_primitives/README.md for full plan.
