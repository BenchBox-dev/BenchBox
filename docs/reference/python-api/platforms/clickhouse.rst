ClickHouse Platform Adapter
===========================

.. tags:: reference, python-api, clickhouse

The ClickHouse adapter provides high-performance columnar database execution for analytical benchmarks.

Overview
--------

ClickHouse is an open-source column-oriented database management system that provides:

- **Columnar architecture** - Optimized for analytical queries
- **Scalability** - Support for petabyte-scale datasets
- **Flexible deployment** - Server mode or embedded local mode
- **Compression** - Columnar compression for storage efficiency
- **OLAP focus** - Designed for analytical workloads

The ClickHouse adapter supports two modes:

- **Server mode** - Connect to ClickHouse server (local or remote)
- **Local mode** - Embedded execution using chDB library

Common use cases:

- Analytical workloads
- Large-scale benchmarking (100GB+)
- Performance comparison with other columnar databases
- Real-time analytics applications

Quick Start
-----------

Server Mode (Default)
~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from benchbox.tpch import TPCH
    from benchbox.platforms.clickhouse import ClickHouseAdapter

    # Connect to ClickHouse server
    adapter = ClickHouseAdapter(
        host="localhost",
        port=9000,
        database="benchmark",
        username="default",
        password=""
    )

    # Run benchmark
    benchmark = TPCH(scale_factor=1.0)
    results = benchmark.run_with_platform(adapter)

Local Mode (Embedded)
~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from benchbox.platforms.clickhouse import ClickHouseAdapter

    # Embedded ClickHouse with chDB
    adapter = ClickHouseAdapter(
        mode="local",
        data_path="./benchmark.chdb"  # Optional persistent storage
    )

    # Run benchmark
    benchmark = TPCH(scale_factor=0.1)
    results = benchmark.run_with_platform(adapter)

API Reference
-------------

ClickHouseAdapter Class
~~~~~~~~~~~~~~~~~~~~~~~

.. autoclass:: benchbox.platforms.clickhouse.ClickHouseAdapter
   :members:
   :undoc-members:
   :show-inheritance:

Constructor Parameters
~~~~~~~~~~~~~~~~~~~~~~

**Server Mode**:

.. code-block:: python

    ClickHouseAdapter(
        mode: str = "server",
        host: str = "localhost",
        port: int = 9000,
        database: str = "default",
        username: str = "default",
        password: str = "",
        secure: bool = False,
        compression: bool = False,
        max_memory_usage: str = "8GB",
        max_execution_time: int = 300,
        max_threads: int = 8
    )

**Local Mode**:

.. code-block:: python

    ClickHouseAdapter(
        mode: str = "local",
        data_path: Optional[str] = None,
        max_memory_usage: str = "4GB",
        max_execution_time: int = 300,
        max_threads: int = 4
    )

Parameters:

**Connection (Server Mode)**:

- **mode** (str): Connection mode - "server" (default) or "local"
- **host** (str): Server hostname or IP address. Default: "localhost"
- **port** (int): Native protocol port. Default: 9000 (HTTP: 8123)
- **database** (str): Database name. Default: "default"
- **username** (str): Username for authentication. Default: "default"
- **password** (str): Password for authentication. Default: ""
- **secure** (bool): Use TLS/SSL connection. Default: False
- **compression** (bool): Enable compression (disabled by default due to Python 3.13+ compatibility). Default: False

**Performance**:

- **max_memory_usage** (str): Maximum memory per query. Default: "8GB" (server), "4GB" (local)
- **max_execution_time** (int): Query timeout in seconds. Default: 300
- **max_threads** (int): Maximum query threads. Default: 8 (server), 4 (local)

**Local Mode**:

- **data_path** (str, optional): Path for persistent chDB storage. Default: None (in-memory)

Configuration Examples
----------------------

Server Mode - Local Development
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from benchbox.platforms.clickhouse import ClickHouseAdapter

    # Default local server
    adapter = ClickHouseAdapter(
        host="localhost",
        port=9000,
        database="benchmark"
    )

    # With authentication
    adapter = ClickHouseAdapter(
        host="localhost",
        port=9000,
        database="benchmark",
        username="benchmark_user",
        password="secure_password"
    )

Server Mode - Production
~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    # Production server with TLS
    adapter = ClickHouseAdapter(
        host="clickhouse.example.com",
        port=9440,  # Secure native port
        database="production_benchmarks",
        username="admin",
        password="production_password",
        secure=True,
        max_memory_usage="32GB",
        max_threads=16
    )

Local Mode - Development
~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    # In-memory execution (fast, no persistence)
    adapter = ClickHouseAdapter(mode="local")

    # Persistent storage (data survives restarts)
    adapter = ClickHouseAdapter(
        mode="local",
        data_path="./benchmarks/clickhouse_local.chdb"
    )

Performance Tuning
~~~~~~~~~~~~~~~~~~

.. code-block:: python

    # High-performance configuration
    adapter = ClickHouseAdapter(
        host="localhost",
        database="benchmark",
        max_memory_usage="64GB",     # Increase for large datasets
        max_execution_time=600,      # 10 minute timeout
        max_threads=32,              # Use all available cores
        compression=False            # Disabled by default for compatibility
    )

Data Loading
------------

Bulk Loading from Files
~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from benchbox.platforms.clickhouse import ClickHouseAdapter

    adapter = ClickHouseAdapter(host="localhost", database="benchmark")
    conn = adapter.create_connection()

    # Load from CSV
    conn.execute("""
        CREATE TABLE lineitem (
            l_orderkey UInt32,
            l_partkey UInt32,
            l_suppkey UInt32,
            l_linenumber UInt8,
            l_quantity Decimal(15, 2),
            l_extendedprice Decimal(15, 2),
            l_discount Decimal(15, 2),
            l_tax Decimal(15, 2),
            l_returnflag String,
            l_linestatus String,
            l_shipdate Date,
            l_commitdate Date,
            l_receiptdate Date,
            l_shipinstruct String,
            l_shipmode String,
            l_comment String
        ) ENGINE = MergeTree()
        ORDER BY (l_orderkey, l_linenumber)
    """)

    # Bulk insert from CSV file
    conn.execute("""
        INSERT INTO lineitem
        FROM INFILE 'data/lineitem.tbl'
        FORMAT CSV
    """)

Loading from S3
~~~~~~~~~~~~~~~

.. code-block:: python

    # ClickHouse can read directly from S3
    conn.execute("""
        CREATE TABLE lineitem AS
        SELECT * FROM s3(
            'https://s3.amazonaws.com/bucket/lineitem/*.parquet',
            'Parquet'
        )
    """)

    # With credentials
    conn.execute("""
        CREATE TABLE lineitem AS
        SELECT * FROM s3(
            'https://s3.amazonaws.com/bucket/lineitem/*.parquet',
            'aws_access_key_id',
            'aws_secret_access_key',
            'Parquet'
        )
    """)

Query Execution
---------------

Execute Queries Directly
~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from benchbox.platforms.clickhouse import ClickHouseAdapter

    adapter = ClickHouseAdapter(host="localhost", database="benchmark")
    conn = adapter.create_connection()

    # Simple query
    result = conn.execute("SELECT COUNT(*) FROM lineitem")
    row_count = result[0][0]  # Result is list of tuples

    # Complex analytical query
    result = conn.execute("""
        SELECT
            l_returnflag,
            l_linestatus,
            sum(l_quantity) as sum_qty,
            sum(l_extendedprice) as sum_base_price,
            count(*) as count_order
        FROM lineitem
        WHERE l_shipdate <= '1998-09-01'
        GROUP BY l_returnflag, l_linestatus
        ORDER BY l_returnflag, l_linestatus
    """)

Query Plans and Optimization
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    # Get query plan
    plan = conn.execute("""
        EXPLAIN
        SELECT * FROM lineitem
        WHERE l_shipdate > '1995-01-01'
    """)
    for row in plan:
        print(row[0])

    # Analyze query pipeline
    pipeline = conn.execute("""
        EXPLAIN PIPELINE
        SELECT COUNT(*) FROM lineitem
        GROUP BY l_orderkey
    """)

Advanced Features
-----------------

Table Engines
~~~~~~~~~~~~~

.. code-block:: python

    # MergeTree (most common for analytics)
    conn.execute("""
        CREATE TABLE orders (
            o_orderkey UInt32,
            o_custkey UInt32,
            o_orderstatus String,
            o_totalprice Decimal(15, 2),
            o_orderdate Date
        ) ENGINE = MergeTree()
        ORDER BY (o_orderdate, o_orderkey)
        PARTITION BY toYYYYMM(o_orderdate)
    """)

    # ReplacingMergeTree (deduplication)
    conn.execute("""
        CREATE TABLE customer_updates (
            c_custkey UInt32,
            c_name String,
            c_address String,
            update_timestamp DateTime
        ) ENGINE = ReplacingMergeTree(update_timestamp)
        ORDER BY c_custkey
    """)

Materialized Views
~~~~~~~~~~~~~~~~~~

.. code-block:: python

    # Create materialized view for pre-aggregation
    conn.execute("""
        CREATE MATERIALIZED VIEW orders_by_date
        ENGINE = SummingMergeTree()
        ORDER BY order_date
        AS SELECT
            toDate(o_orderdate) AS order_date,
            count() AS order_count,
            sum(o_totalprice) AS total_revenue
        FROM orders
        GROUP BY order_date
    """)

Distributed Queries
~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    # Query across multiple shards (cluster setup required)
    result = conn.execute("""
        SELECT
            l_returnflag,
            count() AS cnt
        FROM cluster('benchmark_cluster', default.lineitem)
        GROUP BY l_returnflag
    """)

Best Practices
--------------

Memory Management
~~~~~~~~~~~~~~~~~

1. **Set appropriate memory limits** per query:

   .. code-block:: python

       adapter = ClickHouseAdapter(
           host="localhost",
           max_memory_usage="16GB"  # Per query limit
       )

2. **Monitor memory usage** during execution:

   .. code-block:: python

       # Check memory usage
       result = conn.execute("""
           SELECT
               query,
               memory_usage,
               formatReadableSize(memory_usage) AS readable_memory
           FROM system.processes
           WHERE user = currentUser()
       """)

3. **Use external aggregation** for large GROUP BY:

   .. code-block:: python

       # Enable external aggregation automatically
       conn.execute("SET max_bytes_before_external_group_by = 10000000000")

Performance Optimization
~~~~~~~~~~~~~~~~~~~~~~~~

1. **Choose optimal table engine** and ordering key:

   .. code-block:: python

       # Good: Order by commonly filtered columns
       CREATE TABLE lineitem (...)
       ENGINE = MergeTree()
       ORDER BY (l_shipdate, l_orderkey)

       # Better: Include all filter columns
       ORDER BY (l_shipdate, l_returnflag, l_orderkey)

2. **Use appropriate data types**:

   .. code-block:: python

       # Prefer smaller types
       UInt8 instead of UInt32 for small integers
       Date instead of DateTime for date-only fields
       LowCardinality(String) for repeated strings

3. **Partition large tables**:

   .. code-block:: python

       CREATE TABLE lineitem (...)
       ENGINE = MergeTree()
       PARTITION BY toYYYYMM(l_shipdate)  # Monthly partitions
       ORDER BY (l_orderkey, l_linenumber)

Connection Management
~~~~~~~~~~~~~~~~~~~~~

1. **Reuse connections** for multiple queries:

   .. code-block:: python

       adapter = ClickHouseAdapter(host="localhost")
       conn = adapter.create_connection()

       # Run multiple queries
       for query_id in range(1, 23):
           result = conn.execute(queries[query_id])

       # Close when done
       adapter.close_connection(conn)

2. **Set connection timeouts** appropriately:

   .. code-block:: python

       # Long-running benchmarks need longer timeouts
       adapter = ClickHouseAdapter(
           host="localhost",
           max_execution_time=600  # 10 minutes
       )

Common Issues
-------------

Connection Refused
~~~~~~~~~~~~~~~~~~

**Problem**: Cannot connect to ClickHouse server

**Solutions**:

.. code-block:: bash

    # 1. Check if server is running
    ps aux | grep clickhouse-server

    # 2. Start server if not running
    sudo service clickhouse-server start

    # 3. Check port is listening
    netstat -ln | grep 9000

    # 4. Test connection
    clickhouse-client --host=localhost --port=9000

.. code-block:: python

    # Verify connection in Python
    import socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    result = sock.connect_ex(('localhost', 9000))
    if result == 0:
        print("Port 9000 is open")
    else:
        print("Cannot connect to port 9000")

Memory Limit Exceeded
~~~~~~~~~~~~~~~~~~~~~

**Problem**: Query fails with "Memory limit exceeded"

**Solutions**:

.. code-block:: python

    # 1. Increase memory limit
    adapter = ClickHouseAdapter(
        host="localhost",
        max_memory_usage="32GB"
    )

    # 2. Enable external operations
    conn = adapter.create_connection()
    conn.execute("SET max_bytes_before_external_group_by = 20000000000")
    conn.execute("SET max_bytes_before_external_sort = 20000000000")

    # 3. Reduce scale factor for testing
    benchmark = TPCH(scale_factor=0.1)  # Start small

Local Mode Import Error
~~~~~~~~~~~~~~~~~~~~~~~

**Problem**: "chdb is not installed" error in local mode

**Solution**:

.. code-block:: bash

    # Install chDB
    uv pip install chdb

    # Or switch to server mode
    adapter = ClickHouseAdapter(mode="server", host="localhost")

Slow Query Performance
~~~~~~~~~~~~~~~~~~~~~~

**Problem**: Queries execute slowly

**Solutions**:

.. code-block:: python

    # 1. Increase thread count
    adapter = ClickHouseAdapter(
        host="localhost",
        max_threads=16  # Use more CPU cores
    )

    # 2. Check query plan
    plan = conn.execute("EXPLAIN SELECT ...")
    # Look for FullScanStep (table scan) - may need better ORDER BY

    # 3. Enable query profiling
    conn.execute("SET log_queries = 1")
    conn.execute("SET log_query_threads = 1")

    # Run query
    result = conn.execute("SELECT ...")

    # Check query log
    log = conn.execute("""
        SELECT
            query,
            query_duration_ms,
            memory_usage,
            read_rows,
            read_bytes
        FROM system.query_log
        WHERE type = 'QueryFinish'
        ORDER BY event_time DESC
        LIMIT 1
    """)

See Also
--------

Platform Documentation
~~~~~~~~~~~~~~~~~~~~~~

- :doc:`/platforms/platform-selection-guide` - Choosing ClickHouse vs other platforms
- :doc:`/platforms/quick-reference` - Quick setup for all platforms
- :doc:`/platforms/comparison-matrix` - Feature comparison
- :doc:`/platforms/clickhouse-local-mode` - Local mode guide

Benchmark Guides
~~~~~~~~~~~~~~~~

- :doc:`/benchmarks/tpc-h` - TPC-H on ClickHouse
- :doc:`/benchmarks/tpc-ds` - TPC-DS on ClickHouse
- :doc:`/benchmarks/clickbench` - ClickBench on ClickHouse

API Reference
~~~~~~~~~~~~~

- :doc:`duckdb` - DuckDB adapter for comparison
- :doc:`../base` - Base benchmark interface
- :doc:`../index` - Python API overview
- :doc:`/usage/api-reference` - High-level API guide

External Resources
~~~~~~~~~~~~~~~~~~

- `ClickHouse Documentation <https://clickhouse.com/docs>`_ - Official ClickHouse docs
- `ClickHouse Performance Guide <https://clickhouse.com/docs/optimize/query-optimization>`_ - Performance tuning
- `chDB Documentation <https://github.com/chdb-io/chdb>`_ - Local mode library
- `ClickHouse Table Engines <https://clickhouse.com/docs/engines/table-engines>`_ - Storage engines
