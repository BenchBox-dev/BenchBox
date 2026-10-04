DuckDB Platform Adapter
=======================

.. tags:: reference, python-api, duckdb

The DuckDB adapter provides fast, embedded analytical database execution for benchmarks.

Overview
--------

DuckDB is included by default with BenchBox, providing:

- **No additional configuration required** - Works without additional setup
- **Columnar query engine** - Optimized for analytical queries
- **In-memory or persistent** - Flexible storage options
- **ANSI SQL support** - Comprehensive analytical SQL features

Common use cases:

- Development and testing
- CI/CD pipelines
- Small to medium datasets (< 100GB)
- Local benchmarking without cloud infrastructure

Quick Start
-----------

Basic usage:

.. code-block:: python

    from benchbox.tpch import TPCH
    from benchbox.platforms.duckdb import DuckDBAdapter

    adapter = DuckDBAdapter()

    adapter = DuckDBAdapter(database_path="benchmark.duckdb")

    benchmark = TPCH(scale_factor=0.1)
    results = benchmark.run_with_platform(adapter)

The first ``DuckDBAdapter()`` call creates an in-memory database (the default).
The second creates a persistent database in ``benchmark.duckdb``. Use one or the
other, then run the benchmark with it.

API Reference
-------------

DuckDBAdapter Class
~~~~~~~~~~~~~~~~~~~

.. py:class:: benchbox.platforms.duckdb.DuckDBAdapter(**config)

   Embedded DuckDB adapter.  It supports ``database_path`` (default
   ``":memory:"``), ``memory_limit`` (default ``"4GB"``), optional
   ``max_temp_directory_size`` and ``thread_limit``, and ``progress_bar``
   (default ``False``).  ``memory_limit`` and ``max_temp_directory_size`` are
   validated strings; an invalid value raises ``ValueError``.  A missing or
   unusable driver raises ``ImportError``.

   Example::

      adapter = DuckDBAdapter(database_path=":memory:", memory_limit="4GB")

   See :doc:`common` for inherited lifecycle methods.

.. py:method:: benchbox.platforms.duckdb.DuckDBAdapter.get_database_path(**connection_config) -> str

   Get the database file path for DuckDB.

   Priority:
   1. connection_config["database_path"] if provided and not None
   2. self.database_path (set during from_config)
   3. ":memory:" as final fallback

.. py:method:: benchbox.platforms.duckdb.DuckDBAdapter.create_connection(**connection_config) -> Any

   Create optimized DuckDB connection.

.. py:method:: benchbox.platforms.duckdb.DuckDBAdapter.create_schema(benchmark, connection: Any) -> float

   Create schema using benchmark's SQL definitions.

.. py:method:: benchbox.platforms.duckdb.DuckDBAdapter.load_data(benchmark, connection: Any, data_dir: Path) -> tuple[dict[str, int], float, dict[str, Any] | None]

   Load data using DuckDB's optimized CSV reading capabilities.

.. py:method:: benchbox.platforms.duckdb.DuckDBAdapter.create_external_tables(benchmark: Any, connection: Any, data_dir: Path) -> tuple[dict[str, int], float, dict[str, Any] | None]

   Create DuckDB external views over Parquet/Delta sources.

.. py:method:: benchbox.platforms.duckdb.DuckDBAdapter.execute_query(connection: Any, query: str, query_id: str, benchmark_type: str | None = None, scale_factor: float | None = None, validate_row_count: bool = True, stream_id: int | None = None) -> dict[str, Any]

   Execute query with detailed timing and profiling.

.. py:method:: benchbox.platforms.duckdb.DuckDBAdapter.get_query_plan(connection: Any, query: str) -> str | None

   Get DuckDB query execution plan using EXPLAIN (FORMAT JSON).

   Uses plain EXPLAIN (FORMAT JSON) by default (self.analyze_plans=False) to
   capture the estimated plan with no re-execution overhead: plan fingerprints
   are structure-only, so estimated plans lose nothing for structural comparison.

   When self.analyze_plans is True (opt-in), uses EXPLAIN (ANALYZE, FORMAT JSON)
   (PostgreSQL-style combined syntax) to capture actual per-operator timing and
   cardinality from real query execution. The ANALYZE format uses different field
   names than plain EXPLAIN (FORMAT JSON): operator_timing/operator_cardinality/
   operator_name vs timing/cardinality/name. DuckDBQueryPlanParser handles both
   schemas transparently. capture_query_plan() prints a one-time run-level notice
   the first time this opt-in actually captures a plan, since it roughly doubles
   wall-clock cost for a --capture-plans run and perturbs cache state.

   Note: EXPLAIN (ANALYZE, ...) re-executes the query, adding ~1× query cost to the
   capture step. Plan fingerprints are unaffected - compute_plan_fingerprint()
   excludes timing/cardinality by design.

   DML queries (INSERT/UPDATE/DELETE/MERGE/COPY) are explained without ANALYZE
   to prevent double-execution, even when analyze_plans=True: DuckDB's
   EXPLAIN ANALYZE physically runs the statement, which would mutate data a
   second time. The plan structure is still captured (FORMAT JSON only);
   execution statistics are absent for these statements.

.. py:method:: benchbox.platforms.duckdb.DuckDBAdapter.analyze_tables(connection: Any) -> None

   Run ANALYZE on all tables for better query optimization.

.. py:method:: benchbox.platforms.duckdb.DuckDBAdapter.apply_ctas_sort(table_name: str, tuning_config: Any, connection: Any) -> bool

   CTAS-sort a table, then re-create its sort index so the footprint survives.

   The normal shared CTAS sort issues ``CREATE OR REPLACE TABLE ... ORDER BY``
   and can drop the ``idx_<table>_sort`` index ``apply_table_tunings`` built
   pre-load. When foreign keys are enabled, the shared path instead uses an
   atomic in-place rewrite that preserves the table and index identity. If
   populated dependent rows make that rewrite unsafe, the shared helper
   leaves the table unchanged rather than violating referential integrity.
   The re-create remains idempotent and covers the normal replacement path
   so introspection can corroborate the physical sort.

.. py:method:: benchbox.platforms.duckdb.DuckDBAdapter.supports_tuning_type(tuning_type) -> bool

   Check if DuckDB supports a specific tuning type.

   DuckDB supports:
   SORTING: Via ORDER BY in table definition (DuckDB 0.10+)
   PARTITIONING: Limited support, mainly through file-based partitions

   :param tuning_type: The type of tuning to check support for

   :returns: True if the tuning type is supported by DuckDB

.. py:method:: benchbox.platforms.duckdb.DuckDBAdapter.generate_tuning_clause(table_tuning) -> str

   Generate DuckDB-specific tuning clauses for CREATE TABLE statements.

   DuckDB supports:
   Sorting optimization hints (no explicit syntax in CREATE TABLE)
   Partitioning through file organization (handled at data loading level)

   :param table_tuning: The tuning configuration for the table

   :returns: SQL clause string to be appended to CREATE TABLE statement

.. py:method:: benchbox.platforms.duckdb.DuckDBAdapter.apply_table_tunings(table_name: str, table_tuning, connection: Any) -> None

   Apply tuning configurations to a DuckDB table.

   DuckDB tuning approach:
   SORTING: Create indexes on sort columns for query optimization
   PARTITIONING: Log partitioning strategy (handled at data loading level)
   CLUSTERING: Treat as secondary sorting for optimization hints
   DISTRIBUTION: Not applicable for single-node DuckDB

   :param table_tuning: The tuning configuration to apply
   :param connection: DuckDB connection

   :raises ValueError: If the tuning configuration is invalid for DuckDB

Static member inventory
-----------------------

.. py:property:: benchbox.platforms.duckdb.DuckDBAdapter.platform_name

   Returns this adapter's registered platform identifier for selection, metadata, and capability lookup.

.. py:method:: benchbox.platforms.duckdb.DuckDBAdapter.get_tuning_introspector(self)

   Corroborate the applied ledger against ``duckdb_indexes()``.

   Enables the ``applied_unverified -> applied_verified`` upgrade for DuckDB
   when the recorded ``CREATE INDEX`` statements are confirmed present in
   the catalog (see ``benchbox.platforms.duckdb_introspection``).

.. py:staticmethod:: benchbox.platforms.duckdb.DuckDBAdapter.add_cli_arguments(parser) -> None

   Add DuckDB-specific CLI arguments.

.. py:classmethod:: benchbox.platforms.duckdb.DuckDBAdapter.from_config(config: dict[str, Any])

   Create DuckDB adapter from unified configuration.

.. py:method:: benchbox.platforms.duckdb.DuckDBAdapter.get_platform_info(self, connection: Any=None) -> dict[str, Any]

   Get DuckDB platform information.

.. py:method:: benchbox.platforms.duckdb.DuckDBAdapter.configure_for_benchmark(self, connection: Any, benchmark_type: str) -> None

   Apply DuckDB-specific optimizations based on benchmark type.

.. py:method:: benchbox.platforms.duckdb.DuckDBAdapter.get_query_plan_parser(self)

   Get DuckDB query plan parser.

.. py:method:: benchbox.platforms.duckdb.DuckDBAdapter.get_target_dialect(self) -> str

   Get the target SQL dialect for this platform.

.. py:method:: benchbox.platforms.duckdb.DuckDBAdapter.apply_unified_tuning(self, tuning_config, connection) -> None

   Apply unified tuning configuration to DuckDB.

   The connection is wrapped so the CREATE INDEX statements emitted by
   ``apply_table_tunings`` land in the applied-tuning ledger (DDL phase).
   Wrapping degrades to the raw connection when no ledger is present.

   :param tuning_config: UnifiedTuningConfiguration instance
   :param connection: DuckDB connection

.. py:method:: benchbox.platforms.duckdb.DuckDBAdapter.apply_platform_optimizations(self, tuning_config, connection) -> None

   Apply DuckDB-specific platform optimizations.

   :param tuning_config: UnifiedTuningConfiguration instance
   :param connection: DuckDB connection

.. py:method:: benchbox.platforms.duckdb.DuckDBAdapter.apply_constraint_configuration(self, tuning_config, table_name: str, connection) -> None

   Apply constraint configuration for a specific table.

   Note: Constraints are applied during schema creation in DuckDB,
   so this method primarily validates the configuration.

   :param tuning_config: UnifiedTuningConfiguration instance
   :param table_name: Name of the table
   :param connection: DuckDB connection

.. py:method:: benchbox.platforms.duckdb.DuckDBAdapter.validate_platform_capabilities(self, benchmark_type: str)

   Validate DuckDB-specific capabilities for the benchmark.

   :param benchmark_type: Type of benchmark (e.g., 'tpcds', 'tpch')

   :returns: ValidationResult with DuckDB capability validation status

.. py:method:: benchbox.platforms.duckdb.DuckDBAdapter.validate_connection_health(self, connection: Any)

   Validate DuckDB connection health and capabilities.

   :param connection: DuckDB connection object

   :returns: ValidationResult with connection health status

.. py:attribute:: benchbox.platforms.duckdb.DuckDBAdapter.driver_isolation_capability

   Declares whether this adapter can run through an isolated driver runtime; the value controls runtime-resolution support.

.. py:attribute:: benchbox.platforms.duckdb.DuckDBAdapter.supports_external_tables

   Advertises whether the adapter implements external-table creation.

.. py:attribute:: benchbox.platforms.duckdb.DuckDBAdapter.plan_capture_phase_eligible

   Advertises whether benchmark plan capture is available for this adapter.

.. py:attribute:: benchbox.platforms.duckdb.DuckDBAdapter.stream_connection_capability

   Declares whether concurrent benchmark streams use a shared cursor or require independent connections.

Constructor Configuration
~~~~~~~~~~~~~~~~~~~~~~~~~

Pass keyword configuration through ``DuckDBAdapter(**config)``.

- ``database_path`` defaults to ``":memory:"``.
- ``memory_limit`` defaults to ``"4GB"`` when absent; an explicit ``None``
  leaves the limit unset. Non-``None`` values must be valid bounded size strings.
- ``max_temp_directory_size`` is optional and accepts a validated size
  string or a percentage of available disk space.
- ``thread_limit`` is optional; non-``None`` values must convert to an integer.
- ``progress_bar`` defaults to ``False``.

See the class contract above for driver availability and configuration errors.

Configuration Examples
----------------------

In-Memory Database
~~~~~~~~~~~~~~~~~~

Suitable for small datasets and rapid iteration:

.. code-block:: python

    from benchbox.platforms.duckdb import DuckDBAdapter

    adapter = DuckDBAdapter()

    adapter = DuckDBAdapter(memory_limit="2GB")

    adapter = DuckDBAdapter(
        memory_limit="4GB",
        thread_limit=4
    )

Persistent Database
~~~~~~~~~~~~~~~~~~~

For reusable benchmark data:

.. code-block:: python

    adapter = DuckDBAdapter(database_path="./benchmarks/tpch.duckdb")

    benchmark = TPCH(scale_factor=1.0)
    results = benchmark.run_with_platform(adapter)

    adapter2 = DuckDBAdapter(database_path="./benchmarks/tpch.duckdb")
    results2 = benchmark.run_with_platform(adapter2)

The first run creates the persistent database, and the data persists afterward.
The second adapter later reuses the same database.

Performance Tuning
~~~~~~~~~~~~~~~~~~

Configure for optimal performance:

.. code-block:: python

    adapter = DuckDBAdapter(
        database_path="benchmark.duckdb",
        memory_limit="16GB",
        thread_limit=8,
        temp_directory="/fast/ssd/temp",
        config={
            "default_order": "DESC",
            "preserve_insertion_order": False,
            "enable_object_cache": True
        }
    )

Set ``memory_limit`` appropriately for your system, match ``thread_limit`` to
your CPU cores, and point ``temp_directory`` at fast storage.

Profiling and Debugging
~~~~~~~~~~~~~~~~~~~~~~~

Enable query profiling for analysis:

.. code-block:: python

    adapter = DuckDBAdapter(
        enable_profiling=True,
        config={
            "enable_profiling": "json",
            "profiling_output": "./profiles"
        }
    )

    results = benchmark.run_with_platform(adapter)

Profile information is saved to ``./profiles/``.

Data Loading
------------

The adapter handles data loading automatically, but you can customize the process:

Bulk Loading from Parquet
~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    import duckdb
    from benchbox.platforms.duckdb import DuckDBAdapter

    adapter = DuckDBAdapter(database_path="benchmark.duckdb")

    conn = adapter.connection

    conn.execute("""
        CREATE TABLE lineitem AS
        SELECT * FROM read_parquet('data/lineitem/*.parquet')
    """)

Loading from CSV
~~~~~~~~~~~~~~~~

.. code-block:: python

    conn.execute("""
        CREATE TABLE customer AS
        SELECT * FROM read_csv('data/customer.tbl',
                               delim='|',
                               header=false,
                               columns={
                                   'c_custkey': 'INTEGER',
                                   'c_name': 'VARCHAR',
                                   'c_address': 'VARCHAR',
                                   'c_nationkey': 'INTEGER',
                                   'c_phone': 'VARCHAR',
                                   'c_acctbal': 'DECIMAL(15,2)',
                                   'c_mktsegment': 'VARCHAR',
                                   'c_comment': 'VARCHAR'
                               })
    """)

Query Execution
---------------

Execute Queries Directly
~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from benchbox.platforms.duckdb import DuckDBAdapter

    adapter = DuckDBAdapter()

    result = adapter.connection.execute("SELECT COUNT(*) FROM lineitem")
    row_count = result.fetchone()[0]

    query = "SELECT * FROM orders WHERE o_orderdate > ?"
    result = adapter.connection.execute(query, ["1995-01-01"])

The first statement executes arbitrary SQL, and the second executes a query with
parameters.

Query Plans and Optimization
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    explain_result = adapter.connection.execute(
        "EXPLAIN SELECT * FROM lineitem WHERE l_shipdate > '1995-01-01'"
    )
    print(explain_result.fetchall())

    adapter.connection.execute("PRAGMA enable_profiling")
    result = adapter.connection.execute("SELECT COUNT(*) FROM lineitem")
    profiling_info = adapter.connection.execute("PRAGMA profiling_output").fetchall()

Advanced Features
-----------------

Parallel Query Execution
~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    adapter = DuckDBAdapter(
        memory_limit="16GB",
        thread_limit=8
    )

    results = benchmark.run_with_platform(adapter)

DuckDB parallelizes queries automatically. ``thread_limit=8`` uses 8 threads, and
complex aggregations use all of them.

Extensions and Functions
~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    import duckdb

    adapter = DuckDBAdapter()
    conn = adapter.connection

    conn.execute("INSTALL httpfs")
    conn.execute("LOAD httpfs")

    conn.execute("""
        CREATE TABLE data AS
        SELECT * FROM read_parquet('s3://bucket/data/*.parquet')
    """)

After loading ``httpfs``, DuckDB can read directly from S3.

Window Functions
~~~~~~~~~~~~~~~~

.. code-block:: python

    query = """
        SELECT
            l_orderkey,
            l_partkey,
            l_extendedprice,
            ROW_NUMBER() OVER (PARTITION BY l_orderkey ORDER BY l_extendedprice DESC) as rn
        FROM lineitem
        WHERE l_shipdate > '1995-01-01'
    """
    result = adapter.connection.execute(query)

Best Practices
--------------

Memory Management
~~~~~~~~~~~~~~~~~

1. **Set memory limits** to prevent OOM errors:

   .. code-block:: python

       adapter = DuckDBAdapter(memory_limit="8GB")

2. **Use persistent databases** for large datasets:

   .. code-block:: python

       adapter = DuckDBAdapter(database_path="large_dataset.duckdb")

3. **Monitor memory usage** during execution:

   .. code-block:: python

       import psutil
       process = psutil.Process()
       print(f"Memory usage: {process.memory_info().rss / 1024 / 1024:.0f} MB")

Performance Optimization
~~~~~~~~~~~~~~~~~~~~~~~~

1. **Match thread count** to CPU cores:

   .. code-block:: python

       import os
       adapter = DuckDBAdapter(thread_limit=os.cpu_count())

2. **Use appropriate data types** in the schema. Prefer ``HUGEINT`` over
   ``VARCHAR`` for large integers, and use ``DATE`` or ``TIMESTAMP`` instead of
   ``VARCHAR`` for dates.

3. **Create indexes** for filtered columns:

   .. code-block:: python

       conn.execute("CREATE INDEX idx_shipdate ON lineitem(l_shipdate)")

Data Validation
~~~~~~~~~~~~~~~

1. **Verify row counts** after loading:

   .. code-block:: python

       expected_rows = 6_000_000
       actual_rows = conn.execute("SELECT COUNT(*) FROM lineitem").fetchone()[0]
       assert actual_rows == expected_rows, f"Expected {expected_rows}, got {actual_rows}"

   The expected value of 6,000,000 rows applies to TPC-H ``lineitem`` at scale
   factor 1.

2. **Check data types**:

   .. code-block:: python

       schema = conn.execute("PRAGMA table_info('lineitem')").fetchall()
       for column in schema:
           print(f"{column[1]}: {column[2]}")

Common Issues
-------------

Out of Memory Errors
~~~~~~~~~~~~~~~~~~~~

**Problem**: Query fails with out of memory error

**Solution**:

.. code-block:: python

    adapter = DuckDBAdapter(memory_limit="4GB")

    adapter = DuckDBAdapter(
        database_path="benchmark.duckdb",
        memory_limit="4GB",
        temp_directory="/large/disk/temp"
    )

Set an explicit memory limit, or use a persistent database so DuckDB can spill
to disk.

Slow Query Performance
~~~~~~~~~~~~~~~~~~~~~~

**Problem**: Queries execute slowly

**Solutions**:

.. code-block:: python

    adapter = DuckDBAdapter(thread_limit=8)

    adapter = DuckDBAdapter(database_path="cached.duckdb")

    adapter = DuckDBAdapter(enable_profiling=True)

These three options are, in order: increase the thread count, use a persistent
database to avoid repeated loads, and enable profiling to identify bottlenecks.

Database Lock Errors
~~~~~~~~~~~~~~~~~~~~

**Problem**: "Database is locked" error

**Solution**:

.. code-block:: python

    adapter1 = DuckDBAdapter(database_path="benchmark1.duckdb")
    adapter2 = DuckDBAdapter(database_path="benchmark2.duckdb")

    adapter = DuckDBAdapter(database_path=":memory:")

Use separate database files for concurrent access, or use an in-memory database
for read-only workloads.

See Also
--------

Platform Documentation
~~~~~~~~~~~~~~~~~~~~~~

- :doc:`/platforms/platform-selection-guide` - Choosing DuckDB vs other platforms
- :doc:`/platforms/quick-reference` - Quick setup for all platforms
- :doc:`/platforms/comparison-matrix` - Feature comparison

Benchmark Guides
~~~~~~~~~~~~~~~~

- :doc:`/benchmarks/tpc-h` - TPC-H on DuckDB
- :doc:`/benchmarks/tpc-ds` - TPC-DS on DuckDB
- :doc:`/benchmarks/clickbench` - ClickBench on DuckDB

API Reference
~~~~~~~~~~~~~

- :doc:`../base` - Base benchmark interface
- :doc:`/reference/python-api/index` - Python API overview
- :doc:`/reference/api-reference` - High-level API guide

External Resources
~~~~~~~~~~~~~~~~~~

- `DuckDB Documentation <https://duckdb.org/docs/>`_ - Official DuckDB docs
- `DuckDB Performance Guide <https://duckdb.org/docs/guides/performance/>`_ - Performance tuning
- `DuckDB Extensions <https://duckdb.org/docs/extensions/overview>`_ - Available extensions
