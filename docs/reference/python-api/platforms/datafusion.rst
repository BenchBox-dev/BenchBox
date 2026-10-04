Apache DataFusion Platform Adapter
===================================

.. tags:: reference, python-api, sql-platform

The DataFusion adapter provides in-memory analytical query execution using Apache DataFusion's fast query engine.

Overview
--------

DataFusion is a fast, embeddable query engine written in Rust with Python bindings, providing:

- **In-memory execution** - Optimized for analytical workloads
- **Dual format support** - CSV direct loading or Parquet conversion
- **PostgreSQL-compatible SQL** - Broad SQL dialect compatibility
- **PyArrow integration** - Native Arrow columnar format support
- **Automatic optimization** - Query planning and execution optimization

Common use cases:

- In-process analytics without database overhead
- Rapid prototyping and development
- PyArrow-based data workflows
- OLAP benchmark testing
- Memory-constrained environments (CSV mode)

Quick Start
-----------

Basic usage:

.. code-block:: python

    from benchbox import TPCH
    from benchbox.platforms.datafusion import DataFusionAdapter

    adapter = DataFusionAdapter(
        working_dir="./datafusion_working",
        memory_limit="16G",
        data_format="parquet"
    )

    benchmark = TPCH(scale_factor=1.0)
    results = benchmark.run_with_platform(adapter)

API Reference
-------------

DataFusionAdapter Class
~~~~~~~~~~~~~~~~~~~~~~~

.. py:class:: benchbox.platforms.datafusion.DataFusionAdapter(**config)

   In-process DataFusion adapter.  ``working_dir`` defaults to
   ``"./datafusion_working"``, ``memory_limit`` to ``"16G"``,
   ``target_partitions`` to the CPU count, ``data_format`` to ``"parquet"``,
   and ``batch_size`` to ``8192``.  ``parquet_pushdown`` and
   ``repartition_joins`` default to ``True``.  A missing optional driver raises
   ``ImportError``; a locked working directory can raise ``RuntimeError``.

   Example::

      adapter = DataFusionAdapter(working_dir="./datafusion", data_format="parquet")

   This adapter uses ``NoConstraintEnforcementMixin``: constraint configuration
   is accepted as informational rather than enforced.  See :doc:`common` for
   the shared lifecycle.

.. py:method:: benchbox.platforms.datafusion.DataFusionAdapter.create_connection(**connection_config) -> Any

   Create DataFusion SessionContext with optimized configuration.

.. py:method:: benchbox.platforms.datafusion.DataFusionAdapter.create_schema(benchmark, connection: Any) -> float

   Create schema using DataFusion.

   Note: For DataFusion, actual table creation happens during load_data() via
   CREATE EXTERNAL TABLE. This method validates the schema is available.

.. py:method:: benchbox.platforms.datafusion.DataFusionAdapter.materialize_schema_only_tables(benchmark, connection: Any) -> dict[str, int]

   Creates the schema-only tables required by DataFusion and returns a table-to-row-count mapping.

.. py:method:: benchbox.platforms.datafusion.DataFusionAdapter.load_data(benchmark, connection: Any, data_dir: Path) -> tuple[dict[str, int], float, dict[str, Any] | None]

   Load data into DataFusion.

   Supports CSV, Parquet, Delta Lake, and Iceberg formats.
   Directory-based formats (delta/iceberg) are auto-detected from the file path.

.. py:method:: benchbox.platforms.datafusion.DataFusionAdapter.create_external_tables(benchmark: Any, connection: Any, data_dir: Path) -> tuple[dict[str, int], float, dict[str, Any] | None]

   Alias external-table mode to DataFusion's existing external registration path.

.. py:method:: benchbox.platforms.datafusion.DataFusionAdapter.execute_query(connection: Any, query: str, query_id: str, benchmark_type: str | None = None, scale_factor: float | None = None, validate_row_count: bool = True, stream_id: int | None = None) -> dict[str, Any]

   Execute query with detailed timing and result collection.

.. py:method:: benchbox.platforms.datafusion.DataFusionAdapter.check_database_exists(**connection_config) -> bool

   Check if DataFusion working directory exists with data.

.. py:method:: benchbox.platforms.datafusion.DataFusionAdapter.drop_database(**connection_config) -> None

   Drop DataFusion working directory and all data.

Static member inventory
-----------------------

.. py:property:: benchbox.platforms.datafusion.DataFusionAdapter.platform_name

   Returns this adapter's registered platform identifier for selection, metadata, and capability lookup.

.. py:method:: benchbox.platforms.datafusion.DataFusionAdapter.get_target_dialect(self) -> str

   Get the target SQL dialect for DataFusion.

   Returns platform dialect identifier so catalog variants can target DataFusion.
   SQL translation normalizes this to PostgreSQL semantics where needed.

.. py:method:: benchbox.platforms.datafusion.DataFusionAdapter.preprocess_operation_sql(self, operation_id: str, operation: Any) -> str | None

   Preprocess write operation SQL for DataFusion compatibility.

   Rewrites COPY-based bulk load SQL to CREATE EXTERNAL TABLE pattern.
   Returns None for non-bulk_load operations (no preprocessing needed).

   :param operation_id: Operation identifier
   :param operation: WriteOperation object with category, write_sql, file_dependencies

   :returns: Transformed SQL string, or None if no preprocessing needed

.. py:staticmethod:: benchbox.platforms.datafusion.DataFusionAdapter.add_cli_arguments(parser) -> None

   Add DataFusion-specific CLI arguments.

.. py:classmethod:: benchbox.platforms.datafusion.DataFusionAdapter.from_config(config: dict[str, Any])

   Create DataFusion adapter from unified configuration.

.. py:method:: benchbox.platforms.datafusion.DataFusionAdapter.get_platform_info(self, connection: Any=None) -> dict[str, Any]

   Get DataFusion platform information.

.. py:method:: benchbox.platforms.datafusion.DataFusionAdapter.configure_for_benchmark(self, connection: Any, benchmark_type: str) -> None

   Apply DataFusion-specific optimizations based on benchmark type.

.. py:method:: benchbox.platforms.datafusion.DataFusionAdapter.get_query_plan(self, connection: Any, query: str) -> str | None

   Get DataFusion query execution plan using EXPLAIN.

   DataFusion's EXPLAIN returns a DataFrame with columns (plan_type, plan).
   We reconstruct the pipe-delimited text format expected by DataFusionQueryPlanParser.

.. py:method:: benchbox.platforms.datafusion.DataFusionAdapter.get_query_plan_parser(self)

   Get DataFusion query plan parser.

.. py:method:: benchbox.platforms.datafusion.DataFusionAdapter.validate_platform_capabilities(self, benchmark_type: str)

   Validate DataFusion-specific capabilities for the benchmark.

.. py:attribute:: benchbox.platforms.datafusion.DataFusionAdapter.driver_isolation_capability

   Declares whether this adapter can run through an isolated driver runtime; the value controls runtime-resolution support.

.. py:attribute:: benchbox.platforms.datafusion.DataFusionAdapter.supports_external_tables

   Advertises whether the adapter implements external-table creation.

.. py:attribute:: benchbox.platforms.datafusion.DataFusionAdapter.plan_capture_phase_eligible

   Advertises whether benchmark plan capture is available for this adapter.

.. py:method:: benchbox.platforms.base.no_constraint_mixin.NoConstraintEnforcementMixin.apply_constraint_configuration(self, primary_key_config: Any, foreign_key_config: Any, connection: Any) -> None

   Records that the adapter does not enforce primary- or foreign-key constraints; callers must not rely on these constraints.

.. py:method:: benchbox.platforms.base.no_constraint_mixin.NoConstraintEnforcementMixin.apply_platform_optimizations(self, platform_config: Any, connection: Any) -> None

   Applies the DataFusion platform optimizations supported by the active tuning configuration.

Constructor Configuration
~~~~~~~~~~~~~~~~~~~~~~~~~

Pass keyword configuration through ``DataFusionAdapter(**config)``.

- ``working_dir`` defaults to ``"./datafusion_working"`` and is created
  during construction.
- ``memory_limit`` defaults to ``"16G"``; ``target_partitions`` defaults to
  ``os.cpu_count()`` when the key is absent.
- ``data_format`` defaults to ``"parquet"``; ``temp_dir`` is optional.
- ``batch_size`` defaults to 8192. ``parquet_pushdown`` and
  ``repartition_joins`` default to ``True``.
- Inherited ``force_recreate`` defaults to ``False``; ``tuning_config``
  supplies the shared tuning configuration. See :doc:`common`.

Configuration Examples
----------------------

Basic Configuration
~~~~~~~~~~~~~~~~~~~

In-memory analytics with default settings:

.. code-block:: python

    from benchbox.platforms.datafusion import DataFusionAdapter

    adapter = DataFusionAdapter()

    adapter = DataFusionAdapter(
        working_dir="/fast/ssd/datafusion"
    )

The first adapter uses the defaults (Parquet format, 16G memory). The second sets a custom working directory.

Performance Optimized
~~~~~~~~~~~~~~~~~~~~~

Optimized for high-performance benchmarks:

.. code-block:: python

    import os

    adapter = DataFusionAdapter(
        working_dir="/fast/nvme/datafusion",
        memory_limit="64G",
        target_partitions=os.cpu_count(),
        data_format="parquet",
        batch_size=16384,
        temp_dir="/fast/ssd/temp"
    )

``target_partitions=os.cpu_count()`` uses all cores, Parquet is a columnar format with compression, and ``batch_size=16384`` uses larger batches for throughput.

Memory Constrained
~~~~~~~~~~~~~~~~~~

Optimized for memory-limited environments:

.. code-block:: python

    adapter = DataFusionAdapter(
        memory_limit="4G",
        target_partitions=4,
        data_format="csv",
        batch_size=4096
    )

Data Format Selection
~~~~~~~~~~~~~~~~~~~~~

Choose between CSV and Parquet formats:

.. code-block:: python

    adapter_parquet = DataFusionAdapter(
        data_format="parquet",
        memory_limit="16G"
    )

    adapter_csv = DataFusionAdapter(
        data_format="csv",
        memory_limit="8G"
    )

Parquet is recommended for query performance. CSV gives a faster initial load and a lower memory footprint.

Configuration from Unified Config
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Create adapter from BenchBox's unified configuration dictionary:

.. code-block:: python

    from benchbox.platforms.datafusion import DataFusionAdapter

    config = {
        "benchmark": "tpch",
        "scale_factor": 10.0,
        "output_dir": "/data/benchmarks",
        "memory_limit": "32G",
        "partitions": 16,
        "format": "parquet",
        "batch_size": 16384,
        "force": False
    }

    adapter = DataFusionAdapter.from_config(config)

**Configuration Keys**:

- **benchmark** (str): Benchmark name (e.g., "tpch", "tpcds")
- **scale_factor** (float): Benchmark scale factor
- **output_dir** (str, optional): Output directory for benchmark data
- **memory_limit** (str): Memory limit (e.g., "16G", "32G")
- **partitions** (int, optional): Number of parallel partitions
- **format** (str): Data format ("csv" or "parquet")
- **batch_size** (int): RecordBatch size
- **temp_dir** (str, optional): Temporary directory for disk spilling
- **force** (bool): Force recreate existing data
- **working_dir** (str, optional): Explicit working directory path

The ``from_config()`` method automatically generates appropriate paths based on
benchmark name and scale factor when ``working_dir`` is not explicitly provided.

Data Loading
------------

DataFusion supports two data loading strategies:

CSV Mode (Direct Loading)
~~~~~~~~~~~~~~~~~~~~~~~~~~

Directly registers CSV files as external tables:

.. code-block:: python

    adapter = DataFusionAdapter(data_format="csv")

The CSV reader handles the TPC format automatically: pipe-delimited fields (``|``), a trailing delimiter and no header row.


**Characteristics**:

- Fast initial load (seconds)
- Lower memory usage
- Slower query execution
- Good for one-time queries or memory-constrained environments

Parquet Mode (Conversion)
~~~~~~~~~~~~~~~~~~~~~~~~~~

Converts CSV to Parquet format first:

.. code-block:: python

    adapter = DataFusionAdapter(data_format="parquet")

The conversion process is:

1. Read the CSV files with PyArrow.
2. Handle trailing delimiters.
3. Apply the schema from the benchmark.
4. Write compressed Parquet files.
5. Register the Parquet tables in DataFusion.


**Characteristics**:

- One-time conversion overhead (30-60 seconds for SF=1)
- Better query performance due to columnar format
- Automatic columnar compression (~50-80% size reduction)
- Suited for repeated query execution

Performance Comparison
~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    adapter_csv = DataFusionAdapter(data_format="csv")

    adapter_parquet = DataFusionAdapter(data_format="parquet")

For scale factor 1, CSV mode loads in about 5 seconds and is the query-time baseline. Parquet mode loads in about 30 seconds, and its queries are faster than CSV (varies by query).

Query Execution
---------------

Execute Queries
~~~~~~~~~~~~~~~

Execute SQL queries directly:

.. code-block:: python

    from benchbox.platforms.datafusion import DataFusionAdapter

    adapter = DataFusionAdapter()
    connection = adapter.create_connection()

    df = connection.sql("SELECT COUNT(*) FROM lineitem")
    result_batches = df.collect()

    row_count = result_batches[0].column(0)[0]
    print(f"Row count: {row_count}")

Execute with Validation
~~~~~~~~~~~~~~~~~~~~~~~

Execute queries with automatic row count validation:

.. code-block:: python

    result = adapter.execute_query(
        connection,
        query="SELECT * FROM lineitem WHERE l_shipdate > '1995-01-01'",
        query_id="q1",
        benchmark_type="tpch",
        scale_factor=1.0,
        validate_row_count=True
    )

    print(f"Status: {result['status']}")
    print(f"Execution time: {result['execution_time']:.3f}s")
    print(f"Rows returned: {result['rows_returned']}")

    if result['validation_result']:
        print(f"Expected rows: {result['validation_result'].expected_row_count}")

Dry-Run Mode
~~~~~~~~~~~~

Preview queries without execution:

.. code-block:: python

    from benchbox import TPCH

    adapter = DataFusionAdapter(dry_run_mode=True)

    benchmark = TPCH(scale_factor=1.0)
    results = benchmark.run_with_platform(adapter)

    for query_id, sql in adapter.captured_sql.items():
        print(f"{query_id}: {sql[:100]}...")

Queries are validated but not executed, and the SQL is available in ``adapter.captured_sql``.

Platform Information
--------------------

Get Platform Details
~~~~~~~~~~~~~~~~~~~~

Retrieve DataFusion version and configuration:

.. code-block:: python

    adapter = DataFusionAdapter(memory_limit="16G")
    connection = adapter.create_connection()

    info = adapter.get_platform_info(connection)

    print(f"Platform: {info['platform_name']}")
    print(f"Version: {info['platform_version']}")
    print(f"Memory limit: {info['configuration']['memory_limit']}")
    print(f"Partitions: {info['configuration']['target_partitions']}")
    print(f"Data format: {info['configuration']['data_format']}")

Validate Capabilities
~~~~~~~~~~~~~~~~~~~~~

Check platform capabilities before running benchmarks:

.. code-block:: python

    validation = adapter.validate_platform_capabilities("tpch")

    if validation.is_valid:
        print("Platform ready for TPC-H benchmark")
    else:
        print("Validation errors:")
        for error in validation.errors:
            print(f"  - {error}")

    if validation.warnings:
        print("Warnings:")
        for warning in validation.warnings:
            print(f"  - {warning}")

    print(f"DataFusion version: {validation.details.get('datafusion_version')}")

Advanced Features
-----------------

Custom Configuration
~~~~~~~~~~~~~~~~~~~~

Configure DataFusion SessionContext options:

.. code-block:: python

    adapter = DataFusionAdapter(
        memory_limit="32G",
        target_partitions=16,
        batch_size=16384
    )

The adapter also configures these automatically: Parquet optimizations (pruning and pushdown) and identifier normalization (lowercase, for TPC compatibility).

Working Directory Management
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Manage DataFusion working directory:

.. code-block:: python

    exists = adapter.check_database_exists()

    if exists:
        print("Existing DataFusion data found")

        adapter.drop_database()

    adapter = DataFusionAdapter(force_recreate=True)

Drop existing data if needed, or create the adapter with ``force_recreate=True``.

PyArrow Integration
~~~~~~~~~~~~~~~~~~~

DataFusion uses PyArrow for data representation:

.. code-block:: python

    import pyarrow as pa
    import pyarrow.parquet as pq

    adapter = DataFusionAdapter(data_format="parquet")
    connection = adapter.create_connection()

    df = connection.sql("SELECT * FROM lineitem LIMIT 10")
    batches = df.collect()

    table = pa.Table.from_batches(batches)
    print(f"Schema: {table.schema}")
    print(f"Rows: {table.num_rows}")

    pandas_df = table.to_pandas()

Advanced Features
-----------------

Manual Connection Management
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

For advanced use cases requiring connection reuse:

.. code-block:: python

    from benchbox.platforms.datafusion import DataFusionAdapter

    adapter = DataFusionAdapter(memory_limit="16G", data_format="parquet")
    connection = adapter.create_connection()

    result1 = connection.sql("SELECT COUNT(*) FROM lineitem").collect()
    result2 = connection.sql("SELECT AVG(l_extendedprice) FROM lineitem").collect()

**When to use**:

- Executing multiple custom queries without benchmark overhead
- Testing individual queries during development
- Building custom benchmark workflows
- Integrating with existing DataFusion SessionContext

**Note**: ``benchmark.run_with_platform(adapter)`` handles connection lifecycle automatically and is recommended for most use cases.

Best Practices
--------------

Memory Management
~~~~~~~~~~~~~~~~~

1. **Set appropriate memory limits** for your system:

   .. code-block:: python

       import psutil
       available_memory = psutil.virtual_memory().available
       memory_limit = f"{int(available_memory * 0.7 / 1024**3)}G"

       adapter = DataFusionAdapter(memory_limit=memory_limit)

2. **Use CSV format** for memory-constrained environments:

   .. code-block:: python

       adapter = DataFusionAdapter(
           data_format="csv",
           memory_limit="4G"
       )

3. **Configure temp directory** for disk spilling:

   .. code-block:: python

       adapter = DataFusionAdapter(
           memory_limit="16G",
           temp_dir="/fast/ssd/temp"
       )

Performance Optimization
~~~~~~~~~~~~~~~~~~~~~~~~

1. **Use Parquet format** for repeated query execution:

   .. code-block:: python

       adapter = DataFusionAdapter(data_format="parquet")

2. **Match partitions to CPU cores**:

   .. code-block:: python

       import os
       adapter = DataFusionAdapter(
           target_partitions=os.cpu_count()
       )

3. **Use fast storage** for working directory:

   .. code-block:: python

       adapter = DataFusionAdapter(
           working_dir="/fast/nvme/datafusion",
           data_format="parquet"
       )

4. **Tune batch size** for your workload:

   .. code-block:: python

       adapter = DataFusionAdapter(
           batch_size=4096,
           memory_limit="4G"
       )

       adapter = DataFusionAdapter(
           batch_size=16384,
           memory_limit="32G"
       )

   **Batch Size Guidelines**:

   **4096**: Best for interactive queries and memory-constrained environments
   **8192** (default): Good balance for most analytical workloads
   **16384**: Optimal for high-throughput batch processing with sufficient RAM
   **Trade-off**: Larger batches = higher memory usage but better vectorized execution

Scale Factor Recommendations
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

**Small Scale (SF < 1)**:

.. code-block:: python

    adapter = DataFusionAdapter(
        memory_limit="4G",
        target_partitions=4,
        data_format="csv"
    )

**Medium Scale (SF 1-10)**:

.. code-block:: python

    adapter = DataFusionAdapter(
        memory_limit="16G",
        target_partitions=8,
        data_format="parquet"
    )

**Large Scale (SF 10+)**:

.. code-block:: python

    adapter = DataFusionAdapter(
        memory_limit="64G",
        target_partitions=16,
        data_format="parquet",
        temp_dir="/fast/ssd/temp",
        batch_size=16384
    )

Common Issues
-------------

Out of Memory Errors
~~~~~~~~~~~~~~~~~~~~

**Problem**: Query fails with out of memory error

**Solution**:

.. code-block:: python

    adapter = DataFusionAdapter(
        memory_limit="8G",
        data_format="csv"
    )

    adapter = DataFusionAdapter(
        memory_limit="8G",
        temp_dir="/large/disk/temp"
    )

The first adapter reduces the memory limit and uses CSV format. The second enables disk spilling through ``temp_dir``.

Slow Query Performance
~~~~~~~~~~~~~~~~~~~~~~

**Problem**: Queries execute slowly

**Solutions**:

.. code-block:: python

    adapter = DataFusionAdapter(data_format="parquet")

    adapter = DataFusionAdapter(target_partitions=16)

    adapter = DataFusionAdapter(
        working_dir="/fast/nvme/datafusion"
    )

SQL Feature Errors
~~~~~~~~~~~~~~~~~~

**Problem**: Some queries fail with SQL errors

**Solution**:

.. code-block:: python

    validation = adapter.validate_platform_capabilities("tpcds")

    if validation.warnings:
        print("Platform warnings:")
        for warning in validation.warnings:
            print(f"  - {warning}")

DataFusion uses the PostgreSQL dialect, so some advanced SQL features may not be supported.


See Also
--------

Platform Documentation
~~~~~~~~~~~~~~~~~~~~~~

- :doc:`/platforms/datafusion` - Comprehensive DataFusion platform guide
- :doc:`/platforms/platform-selection-guide` - Platform selection guide
- :doc:`/platforms/comparison-matrix` - Platform comparison
- :doc:`duckdb` - Similar in-process analytics platform

Benchmark Guides
~~~~~~~~~~~~~~~~

- :doc:`/benchmarks/tpc-h` - TPC-H benchmark
- :doc:`/benchmarks/tpc-ds` - TPC-DS benchmark
- :doc:`/benchmarks/index` - All benchmarks

API Reference
~~~~~~~~~~~~~

- :doc:`../base` - Base platform adapter interface
- :doc:`/reference/python-api/index` - Python API overview

External Resources
~~~~~~~~~~~~~~~~~~

- `Apache DataFusion Documentation <https://datafusion.apache.org/>`_ - Official docs
- `DataFusion Python Bindings <https://datafusion.apache.org/python/>`_ - Python API
- `Apache Arrow <https://arrow.apache.org/>`_ - Arrow columnar format
