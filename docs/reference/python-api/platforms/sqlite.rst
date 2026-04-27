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

    # In-memory database (fastest, no persistence)
    adapter = SQLiteAdapter(database_path=":memory:")

    # Run benchmark
    benchmark = TPCH(scale_factor=0.1)
    results = benchmark.run_with_platform(adapter)

File-Based Mode
~~~~~~~~~~~~~~~

.. code-block:: python

    from benchbox.tpch import TPCH
    from benchbox.platforms.sqlite import SQLiteAdapter

    # Persistent file-based database
    adapter = SQLiteAdapter(
        database_path="./benchmarks/tpch.db",
        timeout=30.0
    )

    # Run benchmark
    benchmark = TPCH(scale_factor=1.0)
    results = benchmark.run_with_platform(adapter)

API Reference
-------------

SQLiteAdapter Class
~~~~~~~~~~~~~~~~~~~

.. autoclass:: benchbox.platforms.sqlite.SQLiteAdapter
   :members:
   :undoc-members:
   :show-inheritance:

Constructor Parameters
~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    SQLiteAdapter(
        database_path: str = ":memory:",
        timeout: float = 30.0,
        check_same_thread: bool = False
    )

Parameters:

**Database Configuration**:

- **database_path** (str): Database file path or ":memory:" for in-memory mode. Default: ":memory:"
- **timeout** (float): Connection timeout in seconds. Default: 30.0
- **check_same_thread** (bool): Enable thread safety checks. Default: False

Configuration Examples
----------------------

Development Testing
~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    # Fast in-memory testing for development
    adapter = SQLiteAdapter(database_path=":memory:")

    # Quick benchmark validation
    from benchbox.tpch import TPCH
    benchmark = TPCH(scale_factor=0.01)  # Tiny scale for speed
    results = benchmark.run_with_platform(adapter)

    print(f"Validation complete in {results.total_execution_time:.2f}s")

Persistent Storage
~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from pathlib import Path

    # Store results in file for later analysis
    db_path = Path("./data/benchmarks.db")
    db_path.parent.mkdir(parents=True, exist_ok=True)

    adapter = SQLiteAdapter(
        database_path=str(db_path),
        timeout=60.0  # Longer timeout for file I/O
    )

CI/CD Pipeline
~~~~~~~~~~~~~~

.. code-block:: python

    import os
    from benchbox.platforms.sqlite import SQLiteAdapter
    from benchbox.tpch import TPCH

    # Fast CI testing
    if os.getenv("CI"):
        adapter = SQLiteAdapter(database_path=":memory:")
        benchmark = TPCH(scale_factor=0.01)
    else:
        # Local development with larger dataset
        adapter = SQLiteAdapter(database_path="./dev_benchmark.db")
        benchmark = TPCH(scale_factor=0.1)

    results = benchmark.run_with_platform(adapter)

    # Assert benchmark quality
    assert results.successful_queries == results.total_queries
    assert results.total_execution_time < 60.0  # CI time limit

Multi-threaded Access
~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    # Enable for multi-threaded applications
    adapter = SQLiteAdapter(
        database_path="./benchmark.db",
        check_same_thread=False,  # Allow access from multiple threads
        timeout=120.0  # Higher timeout for concurrent access
    )

Connection Management
---------------------

Basic Connection
~~~~~~~~~~~~~~~~

.. code-block:: python

    from benchbox.platforms.sqlite import SQLiteAdapter

    adapter = SQLiteAdapter(database_path="./benchmark.db")

    # Create connection
    conn = adapter.create_connection()

    # Connection is auto-configured with optimizations:
    # - WAL journal mode
    # - NORMAL synchronous mode
    # - Foreign keys enabled
    # - Cache size: 10000 pages
    # - Temp storage: MEMORY

Query Execution
~~~~~~~~~~~~~~~

.. code-block:: python

    from benchbox.platforms.sqlite import SQLiteAdapter

    adapter = SQLiteAdapter(database_path=":memory:")
    conn = adapter.create_connection()

    # Execute query
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

    # Generate data
    benchmark = TPCH(scale_factor=0.1)
    data_dir = Path("./tpch_data")
    benchmark.generate_data(data_dir)

    # Load into SQLite
    adapter = SQLiteAdapter(database_path="./tpch.db")
    conn = adapter.create_connection()

    # Create schema
    adapter.create_schema(benchmark, conn)

    # Load data
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

    -- Write-Ahead Logging for better concurrency
    PRAGMA journal_mode = WAL;

    -- Normal durability (faster than FULL)
    PRAGMA synchronous = NORMAL;

    -- Large cache (10K pages) for reduced disk I/O
    PRAGMA cache_size = 10000;

    -- In-memory temp tables
    PRAGMA temp_store = MEMORY;

    -- Enable foreign key constraints
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
        """Test all benchmark queries for correctness."""
        adapter = SQLiteAdapter(database_path=":memory:")
        benchmark = TPCH(scale_factor=0.01)  # Small scale for speed

        results = benchmark.run_with_platform(adapter)

        # Validate all queries succeeded
        assert results.successful_queries == results.total_queries

        # Validate reasonable performance
        assert results.average_query_time < 1.0  # 1s per query at SF=0.01

        return results

    # Run in test suite
    test_benchmark_queries()

Development Workflow
~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from benchbox.platforms.sqlite import SQLiteAdapter

    # 1. Start with in-memory for quick iterations
    adapter = SQLiteAdapter(database_path=":memory:")

    # 2. Validate query logic
    # ... test queries ...

    # 3. Move to file-based for persistent testing
    adapter = SQLiteAdapter(database_path="./dev_test.db")

    # 4. Graduate to production platform (DuckDB, ClickHouse, etc.)

Resource Management
~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from benchbox.platforms.sqlite import SQLiteAdapter

    adapter = SQLiteAdapter(database_path="./benchmark.db")

    try:
        conn = adapter.create_connection()
        # ... benchmark operations ...
    finally:
        # Close connection
        conn.close()

        # Optional: Delete temporary database
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

    # 1. Increase timeout
    adapter = SQLiteAdapter(
        database_path="./benchmark.db",
        timeout=120.0  # Wait up to 2 minutes
    )

    # 2. Use WAL mode (already enabled by default)
    # WAL mode allows concurrent reads

    # 3. Avoid concurrent writes
    # SQLite only supports one writer at a time

Memory Error
~~~~~~~~~~~~

**Problem**: Out of memory with large datasets

**Solutions**:

.. code-block:: python

    # 1. Use smaller scale factor
    benchmark = TPCH(scale_factor=0.1)  # Not 1.0 or higher

    # 2. Use file-based instead of in-memory
    adapter = SQLiteAdapter(database_path="./benchmark.db")  # Not ":memory:"

    # 3. Process data in chunks
    # (Not directly supported; consider using DuckDB instead)

Slow Query Performance
~~~~~~~~~~~~~~~~~~~~~~

**Problem**: Queries take longer than expected

**Solutions**:

.. code-block:: python

    # 1. Reduce scale factor
    benchmark = TPCH(scale_factor=0.1)

    # 2. Add indexes for common joins
    conn.execute("CREATE INDEX idx_lineitem_orderkey ON lineitem(l_orderkey)")
    conn.execute("ANALYZE")

    # 3. Consider using DuckDB for analytical queries (columnar storage)
    from benchbox.platforms.duckdb import DuckDBAdapter
    adapter = DuckDBAdapter()  # Optimized for OLAP workloads

Missing Tables
~~~~~~~~~~~~~~

**Problem**: "no such table" error

**Solutions**:

.. code-block:: python

    # 1. Ensure schema is created before data loading
    adapter.create_schema(benchmark, conn)
    adapter.load_data(benchmark, conn, data_dir)

    # 2. Check if using existing database with old schema
    adapter = SQLiteAdapter(
        database_path="./benchmark.db",
        drop_database_before_connect=True  # Recreate database
    )

Feature Not Supported
~~~~~~~~~~~~~~~~~~~~~

**Problem**: "Power test not implemented for SQLite adapter"

**Explanation**: SQLite adapter is designed for basic testing only. Advanced TPC features (power test, throughput test, maintenance test) are not implemented.

**Solution**:

.. code-block:: python

    # For full TPC-H/TPC-DS compliance testing, use enterprise platforms
    from benchbox.platforms.duckdb import DuckDBAdapter
    adapter = DuckDBAdapter()  # Supports all TPC tests

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
