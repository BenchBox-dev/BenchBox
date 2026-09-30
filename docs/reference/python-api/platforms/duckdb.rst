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

    # In-memory database (default)
    adapter = DuckDBAdapter()

    # Or persistent database
    adapter = DuckDBAdapter(database_path="benchmark.duckdb")

    # Run benchmark
    benchmark = TPCH(scale_factor=0.1)
    results = benchmark.run_with_platform(adapter)

API Reference
-------------

DuckDBAdapter Class
~~~~~~~~~~~~~~~~~~~

.. autoclass:: benchbox.platforms.duckdb.DuckDBAdapter
   :members:
   :undoc-members:
   :show-inheritance:

Constructor Parameters
~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    DuckDBAdapter(
        database_path: Optional[str] = ":memory:",
        memory_limit: Optional[str] = None,
        thread_limit: Optional[int] = None,
        temp_directory: Optional[str] = None,
        enable_profiling: bool = False,
        read_only: bool = False,
        config: Optional[Dict[str, Any]] = None
    )

Parameters:

- **database_path** (str, optional): Database file path or ":memory:" for in-memory. Default: ":memory:"
- **memory_limit** (str, optional): Maximum memory usage (e.g., "4GB", "512MB"). Default: No limit
- **thread_limit** (int, optional): Maximum number of threads. Default: All available cores
- **temp_directory** (str, optional): Directory for temporary files. Default: System temp
- **enable_profiling** (bool): Enable query profiling. Default: False
- **read_only** (bool): Open database in read-only mode. Default: False
- **config** (dict, optional): Additional DuckDB configuration options

Configuration Examples
----------------------

In-Memory Database
~~~~~~~~~~~~~~~~~~

Suitable for small datasets and rapid iteration:

.. code-block:: python

    from benchbox.platforms.duckdb import DuckDBAdapter

    # Default in-memory configuration
    adapter = DuckDBAdapter()

    # With memory limit
    adapter = DuckDBAdapter(memory_limit="2GB")

    # With thread control
    adapter = DuckDBAdapter(
        memory_limit="4GB",
        thread_limit=4
    )

Persistent Database
~~~~~~~~~~~~~~~~~~~

For reusable benchmark data:

.. code-block:: python

    # Create persistent database
    adapter = DuckDBAdapter(database_path="./benchmarks/tpch.duckdb")

    # Run benchmark (data persists)
    benchmark = TPCH(scale_factor=1.0)
    results = benchmark.run_with_platform(adapter)

    # Later: reuse the same database
    adapter2 = DuckDBAdapter(database_path="./benchmarks/tpch.duckdb")
    results2 = benchmark.run_with_platform(adapter2)

Performance Tuning
~~~~~~~~~~~~~~~~~~

Configure for optimal performance:

.. code-block:: python

    adapter = DuckDBAdapter(
        database_path="benchmark.duckdb",
        memory_limit="16GB",      # Set appropriate for your system
        thread_limit=8,           # Match your CPU cores
        temp_directory="/fast/ssd/temp",  # Use fast storage
        config={
            "default_order": "DESC",
            "preserve_insertion_order": False,
            "enable_object_cache": True
        }
    )

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

    # Run benchmark
    results = benchmark.run_with_platform(adapter)

    # Profile information saved to ./profiles/

Data Loading
------------

The adapter handles data loading automatically, but you can customize the process:

Bulk Loading from Parquet
~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    import duckdb
    from benchbox.platforms.duckdb import DuckDBAdapter

    # Create adapter with custom connection
    adapter = DuckDBAdapter(database_path="benchmark.duckdb")

    # Access underlying DuckDB connection
    conn = adapter.connection

    # Custom bulk load from Parquet
    conn.execute("""
        CREATE TABLE lineitem AS
        SELECT * FROM read_parquet('data/lineitem/*.parquet')
    """)

Loading from CSV
~~~~~~~~~~~~~~~~

.. code-block:: python

    # DuckDB automatically detects CSV format
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

    # Execute arbitrary SQL
    result = adapter.connection.execute("SELECT COUNT(*) FROM lineitem")
    row_count = result.fetchone()[0]

    # Execute with parameters
    query = "SELECT * FROM orders WHERE o_orderdate > ?"
    result = adapter.connection.execute(query, ["1995-01-01"])

Query Plans and Optimization
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    # Get query plan
    explain_result = adapter.connection.execute(
        "EXPLAIN SELECT * FROM lineitem WHERE l_shipdate > '1995-01-01'"
    )
    print(explain_result.fetchall())

    # Analyze query with profiling
    adapter.connection.execute("PRAGMA enable_profiling")
    result = adapter.connection.execute("SELECT COUNT(*) FROM lineitem")
    profiling_info = adapter.connection.execute("PRAGMA profiling_output").fetchall()

Advanced Features
-----------------

Parallel Query Execution
~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    # DuckDB automatically parallelizes queries
    adapter = DuckDBAdapter(
        memory_limit="16GB",
        thread_limit=8  # Use 8 threads for parallel execution
    )

    # Complex aggregation will use all threads
    results = benchmark.run_with_platform(adapter)

Extensions and Functions
~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    import duckdb

    adapter = DuckDBAdapter()
    conn = adapter.connection

    # Load DuckDB extensions
    conn.execute("INSTALL httpfs")
    conn.execute("LOAD httpfs")

    # Now can read from S3
    conn.execute("""
        CREATE TABLE data AS
        SELECT * FROM read_parquet('s3://bucket/data/*.parquet')
    """)

Window Functions
~~~~~~~~~~~~~~~~

.. code-block:: python

    # DuckDB supports advanced window functions
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

2. **Use appropriate data types** in schema:

   .. code-block:: python

       # Prefer HUGEINT over VARCHAR for large integers
       # Use DATE/TIMESTAMP instead of VARCHAR for dates

3. **Create indexes** for filtered columns:

   .. code-block:: python

       conn.execute("CREATE INDEX idx_shipdate ON lineitem(l_shipdate)")

Data Validation
~~~~~~~~~~~~~~~

1. **Verify row counts** after loading:

   .. code-block:: python

       expected_rows = 6_000_000  # SF=1 TPC-H
       actual_rows = conn.execute("SELECT COUNT(*) FROM lineitem").fetchone()[0]
       assert actual_rows == expected_rows, f"Expected {expected_rows}, got {actual_rows}"

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

    # Set explicit memory limit
    adapter = DuckDBAdapter(memory_limit="4GB")

    # Or use persistent database with disk spilling
    adapter = DuckDBAdapter(
        database_path="benchmark.duckdb",
        memory_limit="4GB",
        temp_directory="/large/disk/temp"
    )

Slow Query Performance
~~~~~~~~~~~~~~~~~~~~~~

**Problem**: Queries execute slowly

**Solutions**:

.. code-block:: python

    # 1. Increase thread count
    adapter = DuckDBAdapter(thread_limit=8)

    # 2. Use persistent database to avoid repeated loads
    adapter = DuckDBAdapter(database_path="cached.duckdb")

    # 3. Enable profiling to identify bottlenecks
    adapter = DuckDBAdapter(enable_profiling=True)

Database Lock Errors
~~~~~~~~~~~~~~~~~~~~

**Problem**: "Database is locked" error

**Solution**:

.. code-block:: python

    # Use separate database files for concurrent access
    adapter1 = DuckDBAdapter(database_path="benchmark1.duckdb")
    adapter2 = DuckDBAdapter(database_path="benchmark2.duckdb")

    # Or use in-memory for read-only workloads
    adapter = DuckDBAdapter(database_path=":memory:")

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
