SQLite Platform Adapter
=======================

.. tags:: reference, python-api, sqlite

The SQLite adapter provides lightweight testing and development capabilities with embedded database functionality.

Overview
--------

SQLite is a self-contained, serverless, zero-configuration SQL database engine that offers:

- **Embedded database** - No server process required
- **In-memory mode** - Fast testing with no disk I/O
- **File-based mode** - Persistent storage in single file
- **Zero configuration** - No setup or administration
- **ACID compliant** - Full transactional support
- **Cross-platform** - Runs on all platforms

Common use cases:

- Development and testing workflows
- Small-scale benchmarks (< 10GB data)
- CI/CD pipeline testing
- Proof-of-concept work
- Educational and learning purposes

.. note::
   SQLite is not designed for production-scale OLAP workloads. Use ClickHouse, DuckDB, or cloud platforms for large-scale benchmarking.

Quick Start
-----------

In-Memory Mode
~~~~~~~~~~~~~~

.. code-block:: python

    from benchbox.tpch import TPCH
    from benchbox.platforms.sqlite import SQLiteAdapter

    adapter = SQLiteAdapter(database_path=":memory:")

    benchmark = TPCH(scale_factor=0.1)
    results = benchmark.run_with_platform(adapter)

File-Based Mode
~~~~~~~~~~~~~~~

.. code-block:: python

    from benchbox.tpch import TPCH
    from benchbox.platforms.sqlite import SQLiteAdapter

    adapter = SQLiteAdapter(
        database_path="./benchmarks/tpch.db",
        timeout=30.0
    )

    benchmark = TPCH(scale_factor=1.0)
    results = benchmark.run_with_platform(adapter)

API Reference
-------------

SQLiteAdapter Class
~~~~~~~~~~~~~~~~~~~

.. py:class:: benchbox.platforms.sqlite.SQLiteAdapter(**config)

   SQLite adapter for an in-memory or file-backed database.  ``database_path``
   defaults to ``":memory:"``; ``timeout`` defaults to ``30.0`` seconds; and
   ``check_same_thread`` defaults to ``False``.  Construction raises
   ``ImportError`` when Python's SQLite support is unavailable.

   Example::

      adapter = SQLiteAdapter(database_path="benchmark.db", timeout=60.0)

   See :doc:`common` for the shared lifecycle.

.. py:method:: benchbox.platforms.sqlite.SQLiteAdapter.get_database_path(**connection_config) -> str | None

   Get the database file path for SQLite.

.. py:method:: benchbox.platforms.sqlite.SQLiteAdapter.create_connection(**connection_config) -> Any

   Create SQLite connection.

.. py:method:: benchbox.platforms.sqlite.SQLiteAdapter.create_schema(benchmark, connection: Any) -> float

   Create schema using benchmark's SQL definitions.

.. py:method:: benchbox.platforms.sqlite.SQLiteAdapter.load_data(benchmark, connection: Any, data_dir: Path) -> tuple[dict[str, int], float, dict[str, Any] | None]

   Load benchmark data into SQLite.

.. py:method:: benchbox.platforms.sqlite.SQLiteAdapter.execute_query(connection: Any, query: str, query_id: str, benchmark_type: str | None = None, scale_factor: float | None = None, validate_row_count: bool = True, stream_id: int | None = None) -> dict[str, Any]

   Execute a single query and return detailed results.

.. py:method:: benchbox.platforms.sqlite.SQLiteAdapter.get_query_plan(connection: Any, query: str) -> str | None

   Get SQLite query execution plan using EXPLAIN QUERY PLAN.

   Reconstructs the tree-formatted text that SQLiteQueryPlanParser expects
   from the raw (id, parent, notused, detail) rows SQLite returns.

.. py:method:: benchbox.platforms.sqlite.SQLiteAdapter.apply_table_tunings(table_tuning: TableTuning, connection: Any) -> None

   Apply tuning configurations to SQLite (limited support).

.. py:method:: benchbox.platforms.sqlite.SQLiteAdapter.run_power_test(benchmark, **kwargs) -> dict[str, Any]

   Run TPC power test (not implemented for SQLite).

.. py:method:: benchbox.platforms.sqlite.SQLiteAdapter.run_throughput_test(benchmark, **kwargs) -> dict[str, Any]

   Run TPC throughput test (not implemented for SQLite).

.. py:method:: benchbox.platforms.sqlite.SQLiteAdapter.run_maintenance_test(benchmark, **kwargs) -> dict[str, Any]

   Run TPC maintenance test (not implemented for SQLite).

Static member inventory
-----------------------

.. py:property:: benchbox.platforms.sqlite.SQLiteAdapter.platform_name

   Returns this adapter's registered platform identifier for selection, metadata, and capability lookup.

.. py:staticmethod:: benchbox.platforms.sqlite.SQLiteAdapter.add_cli_arguments(parser) -> None

   Add SQLite-specific CLI arguments.

   Kept minimal for testing; provides database path and basic options.

   NOTE: These flags (``--sqlite-database``, etc.) are legacy and are NOT
   exposed by ``benchbox run``.  Use ``--platform-option database_path=<path>``
   instead, which is registered in PlatformHookRegistry and appears in
   ``benchbox run --help``.

.. py:classmethod:: benchbox.platforms.sqlite.SQLiteAdapter.from_config(config: dict[str, Any])

   Create SQLite adapter from unified configuration.

   Handles configuration from multiple sources:
   connection_string: Path to database file (from DatabaseConfig)
   database_path: Direct path specification (from options or CLI)
   Auto-generation: Creates path in benchmark_runs/databases if needed

.. py:method:: benchbox.platforms.sqlite.SQLiteAdapter.get_platform_info(self, connection: Any=None) -> dict[str, Any]

   Get SQLite platform information.

.. py:method:: benchbox.platforms.sqlite.SQLiteAdapter.get_target_dialect(self) -> str

   Return the target SQL dialect for SQLite.

.. py:method:: benchbox.platforms.sqlite.SQLiteAdapter.generate_tuning_clause(self, table_tuning: TableTuning) -> str

   Generate SQLite-specific tuning clauses (none supported).

.. py:method:: benchbox.platforms.sqlite.SQLiteAdapter.apply_unified_tuning(self, unified_config: UnifiedTuningConfiguration, connection: Any) -> None

   Apply unified tuning configuration (limited support in SQLite).

.. py:method:: benchbox.platforms.sqlite.SQLiteAdapter.apply_platform_optimizations(self, platform_config: PlatformOptimizationConfiguration, connection: Any) -> None

   Apply SQLite-specific optimizations.

.. py:method:: benchbox.platforms.sqlite.SQLiteAdapter.apply_constraint_configuration(self, primary_key_config: PrimaryKeyConfiguration, foreign_key_config: ForeignKeyConfiguration, connection: Any) -> None

   Apply constraint configurations to SQLite.

.. py:method:: benchbox.platforms.sqlite.SQLiteAdapter.configure_for_benchmark(self, connection: Any, benchmark_type: str) -> None

   Apply SQLite optimizations for benchmark type.

.. py:method:: benchbox.platforms.sqlite.SQLiteAdapter.get_query_plan_parser(self)

   Get SQLite query plan parser.

.. py:attribute:: benchbox.platforms.sqlite.SQLiteAdapter.driver_isolation_capability

   Declares whether this adapter can run through an isolated driver runtime; the value controls runtime-resolution support.

.. py:attribute:: benchbox.platforms.sqlite.SQLiteAdapter.plan_capture_phase_eligible

   Advertises whether benchmark plan capture is available for this adapter.

.. py:attribute:: benchbox.platforms.sqlite.SQLiteAdapter.stream_connection_capability

   Declares whether concurrent benchmark streams use a shared cursor or require independent connections.

Constructor Configuration
~~~~~~~~~~~~~~~~~~~~~~~~~

Pass keyword configuration through ``SQLiteAdapter(**config)``.

- ``database_path`` defaults to ``":memory:"``.
- ``timeout`` defaults to 30.0 seconds.
- ``check_same_thread`` defaults to ``False``.

These defaults apply when the respective key is absent.

Configuration Examples
----------------------

Development Testing
~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    adapter = SQLiteAdapter(database_path=":memory:")

    from benchbox.tpch import TPCH
    benchmark = TPCH(scale_factor=0.01)
    results = benchmark.run_with_platform(adapter)

    print(f"Validation complete in {results.total_execution_time:.2f}s")

Persistent Storage
~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from pathlib import Path

    db_path = Path("./data/benchmarks.db")
    db_path.parent.mkdir(parents=True, exist_ok=True)

    adapter = SQLiteAdapter(
        database_path=str(db_path),
        timeout=60.0
    )

CI/CD Pipeline
~~~~~~~~~~~~~~

.. code-block:: python

    import os
    from benchbox.platforms.sqlite import SQLiteAdapter
    from benchbox.tpch import TPCH

    if os.getenv("CI"):
        adapter = SQLiteAdapter(database_path=":memory:")
        benchmark = TPCH(scale_factor=0.01)
    else:
        adapter = SQLiteAdapter(database_path="./dev_benchmark.db")
        benchmark = TPCH(scale_factor=0.1)

    results = benchmark.run_with_platform(adapter)

    assert results.successful_queries == results.total_queries
    assert results.total_execution_time < 60.0

Multi-threaded Access
~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    adapter = SQLiteAdapter(
        database_path="./benchmark.db",
        check_same_thread=False,
        timeout=120.0
    )

Connection Management
---------------------

Basic Connection
~~~~~~~~~~~~~~~~

.. code-block:: python

    from benchbox.platforms.sqlite import SQLiteAdapter

    adapter = SQLiteAdapter(database_path="./benchmark.db")

    conn = adapter.create_connection()


Query Execution
~~~~~~~~~~~~~~~

.. code-block:: python

    from benchbox.platforms.sqlite import SQLiteAdapter

    adapter = SQLiteAdapter(database_path=":memory:")
    conn = adapter.create_connection()

    result = adapter.execute_query(
        conn,
        "SELECT COUNT(*) FROM customer",
        "count_customers"
    )

    print(f"Status: {result['status']}")
    print(f"Execution time: {result['execution_time']:.3f}s")
    print(f"Rows: {result['rows_returned']}")

Data Loading
------------

From Generated Data
~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from benchbox.platforms.sqlite import SQLiteAdapter
    from benchbox.tpch import TPCH
    from pathlib import Path

    benchmark = TPCH(scale_factor=0.1)
    data_dir = Path("./tpch_data")
    benchmark.generate_data(data_dir)

    adapter = SQLiteAdapter(database_path="./tpch.db")
    conn = adapter.create_connection()

    adapter.create_schema(benchmark, conn)

    table_stats, load_time = adapter.load_data(benchmark, conn, data_dir)

    print(f"Loaded {sum(table_stats.values()):,} rows in {load_time:.2f}s")
    for table, count in table_stats.items():
        print(f"  {table}: {count:,} rows")

Performance Optimization
------------------------

Connection Pragmas
~~~~~~~~~~~~~~~~~~

SQLite adapter automatically applies these optimizations:

.. code-block:: sql

    PRAGMA journal_mode = WAL;

    PRAGMA synchronous = NORMAL;

    PRAGMA cache_size = 10000;

    PRAGMA temp_store = MEMORY;

    PRAGMA foreign_keys = ON;

Query Optimization Tips
~~~~~~~~~~~~~~~~~~~~~~~

1. **Use appropriate indexes**:

   .. code-block:: sql

       CREATE INDEX idx_orders_custkey ON orders(o_custkey);
       CREATE INDEX idx_lineitem_orderkey ON lineitem(l_orderkey);

2. **Analyze statistics after data load**:

   .. code-block:: python

       conn.execute("ANALYZE")
       conn.commit()

3. **Vacuum to reclaim space and defragment**:

   .. code-block:: python

       conn.execute("VACUUM")
       conn.commit()

Scale Factor Guidelines
~~~~~~~~~~~~~~~~~~~~~~~

Recommended scale factors for SQLite:

- **Development/Testing**: SF = 0.01 to 0.1 (~10MB to 100MB)
- **CI/CD Pipelines**: SF = 0.01 (~10MB, completes in seconds)
- **Local benchmarking**: SF = 0.1 to 1.0 (~100MB to 1GB)
- **Maximum practical**: SF = 10 (~10GB, slow queries)

.. warning::
   SQLite is not designed for large-scale OLAP workloads. Scale factors above 1.0 will result in slow query performance.

Best Practices
--------------

Use Case Selection
~~~~~~~~~~~~~~~~~~

**When to use SQLite adapter**:

- Development and testing
- CI/CD pipeline validation
- Learning and education
- Small datasets (< 1GB)
- Single-user applications

**When NOT to use SQLite adapter**:

- Production benchmarking
- Large-scale data (> 10GB)
- Concurrent multi-user workloads
- Performance-critical comparisons

Testing Strategy
~~~~~~~~~~~~~~~~

.. code-block:: python

    from benchbox.platforms.sqlite import SQLiteAdapter
    from benchbox.tpch import TPCH

    def test_benchmark_queries():
        adapter = SQLiteAdapter(database_path=":memory:")
        benchmark = TPCH(scale_factor=0.01)

        results = benchmark.run_with_platform(adapter)

        assert results.successful_queries == results.total_queries

        assert results.average_query_time < 1.0

        return results

    test_benchmark_queries()

Development Workflow
~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from benchbox.platforms.sqlite import SQLiteAdapter

    adapter = SQLiteAdapter(database_path=":memory:")


    adapter = SQLiteAdapter(database_path="./dev_test.db")


Resource Management
~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from benchbox.platforms.sqlite import SQLiteAdapter

    adapter = SQLiteAdapter(database_path="./benchmark.db")

    try:
        conn = adapter.create_connection()
    finally:
        conn.close()

        if adapter.database_path != ":memory:":
            import os
            if os.path.exists(adapter.database_path):
                os.remove(adapter.database_path)

Common Issues
-------------

Database Locked Error
~~~~~~~~~~~~~~~~~~~~~

**Problem**: "database is locked" error during concurrent access

**Solutions**:

.. code-block:: python

    adapter = SQLiteAdapter(
        database_path="./benchmark.db",
        timeout=120.0
    )



Memory Error
~~~~~~~~~~~~

**Problem**: Out of memory with large datasets

**Solutions**:

.. code-block:: python

    benchmark = TPCH(scale_factor=0.1)

    adapter = SQLiteAdapter(database_path="./benchmark.db")


Slow Query Performance
~~~~~~~~~~~~~~~~~~~~~~

**Problem**: Queries take longer than expected

**Solutions**:

.. code-block:: python

    benchmark = TPCH(scale_factor=0.1)

    conn.execute("CREATE INDEX idx_lineitem_orderkey ON lineitem(l_orderkey)")
    conn.execute("ANALYZE")

    from benchbox.platforms.duckdb import DuckDBAdapter
    adapter = DuckDBAdapter()

Missing Tables
~~~~~~~~~~~~~~

**Problem**: "no such table" error

**Solutions**:

.. code-block:: python

    adapter.create_schema(benchmark, conn)
    adapter.load_data(benchmark, conn, data_dir)

    adapter = SQLiteAdapter(
        database_path="./benchmark.db",
        drop_database_before_connect=True
    )

Feature Not Supported
~~~~~~~~~~~~~~~~~~~~~

**Problem**: "Power test not implemented for SQLite adapter"

**Explanation**: SQLite adapter is designed for basic testing only. Advanced TPC features (power test, throughput test, maintenance test) are not implemented.

**Solution**:

.. code-block:: python

    from benchbox.platforms.duckdb import DuckDBAdapter
    adapter = DuckDBAdapter()

See Also
--------

Platform Documentation
~~~~~~~~~~~~~~~~~~~~~~

- :doc:`/platforms/platform-selection-guide` - Choosing SQLite vs other platforms
- :doc:`/platforms/quick-reference` - Quick setup for all platforms
- :doc:`/platforms/comparison-matrix` - Feature comparison

API Reference
~~~~~~~~~~~~~

- :doc:`duckdb` - DuckDB adapter (recommended for OLAP testing)
- :doc:`clickhouse` - ClickHouse adapter
- :doc:`../base` - Base benchmark interface
- :doc:`../index` - Python API overview

Benchmarks
~~~~~~~~~~

- :doc:`/benchmarks/tpc-h` - TPC-H benchmark
- :doc:`/usage/getting-started` - Getting started guide
- :doc:`/usage/troubleshooting` - General troubleshooting

External Resources
~~~~~~~~~~~~~~~~~~

- `SQLite Documentation <https://www.sqlite.org/docs.html>`_ - Official SQLite docs
- `SQLite Query Optimizer <https://sqlite.org/optoverview.html>`_ - Performance guide
- `SQLite PRAGMA Statements <https://www.sqlite.org/pragma.html>`_ - Configuration options
- `SQLite Limitations <https://www.sqlite.org/limits.html>`_ - Size and performance limits
