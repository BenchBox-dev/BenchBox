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

Server Mode
~~~~~~~~~~~

Server mode is the default. It connects to a running ClickHouse server.

.. code-block:: python

    from benchbox.tpch import TPCH
    from benchbox.platforms.clickhouse import ClickHouseAdapter

    adapter = ClickHouseAdapter(
        host="localhost",
        port=9000,
        database="benchmark",
        username="default",
        password=""
    )

    benchmark = TPCH(scale_factor=1.0)
    results = benchmark.run_with_platform(adapter)

Local Mode (Embedded)
~~~~~~~~~~~~~~~~~~~~~

Local mode runs embedded ClickHouse through chDB. The ``data_path`` argument is
optional and sets persistent storage. Omit it to keep data in memory.

.. code-block:: python

    from benchbox.platforms.clickhouse import ClickHouseAdapter

    adapter = ClickHouseAdapter(
        mode="local",
        data_path="./benchmark.chdb"
    )

    benchmark = TPCH(scale_factor=0.1)
    results = benchmark.run_with_platform(adapter)

API Reference
-------------

ClickHouseAdapter Class
~~~~~~~~~~~~~~~~~~~~~~~

.. py:class:: benchbox.platforms.clickhouse.ClickHouseAdapter(**config)

   ClickHouse adapter composed from setup, workload, diagnostics, and tuning
   mixins.  Its supported configuration is interpreted by the selected client
   and deployment mode; invalid connection or driver configuration surfaces as
   driver or configuration errors.  See :doc:`common` for the shared lifecycle.

   Example::

      adapter = ClickHouseAdapter(host="localhost", database="benchmark")

.. py:method:: benchbox.platforms.clickhouse.ClickHouseAdapter.create_connection(**connection_config) -> Any

   Create ClickHouse connection based on mode.

.. py:method:: benchbox.platforms.clickhouse.ClickHouseAdapter.close_connection(connection: Any) -> None

   Close ClickHouse connection.

.. py:method:: benchbox.platforms.clickhouse.ClickHouseAdapter.create_schema(benchmark, connection: Any) -> float

   Create schema using ClickHouse-optimized table definitions.

.. py:method:: benchbox.platforms.clickhouse.ClickHouseAdapter.load_data(benchmark, connection: Any, data_dir: Path) -> tuple[dict[str, int], float, dict[str, Any] | None]

   Load data using ClickHouse's optimized CSV import capabilities.

.. py:method:: benchbox.platforms.clickhouse.ClickHouseAdapter.execute_query(connection: Any, query: str, query_id: str, benchmark_type: str | None = None, scale_factor: float | None = None, validate_row_count: bool = True, stream_id: int | None = None) -> dict[str, Any]

   Execute query with detailed timing and profiling.

.. py:method:: benchbox.platforms.clickhouse.ClickHouseAdapter.get_table_info(connection: Any, table_name: str) -> dict[str, Any]

   Get detailed table information.

.. py:method:: benchbox.platforms.clickhouse.ClickHouseAdapter.optimize_table(connection: Any, table_name: str) -> None

   Optimize table for better query performance.

.. py:method:: benchbox.platforms.clickhouse.ClickHouseAdapter.validate_session_cache_control(connection: Any) -> dict[str, Any]

   Validate that session-level cache control settings were successfully applied.

   :param connection: Active ClickHouse database connection

   :returns:     - validated: bool - Whether validation passed - cache_disabled: bool - Whether cache is actually disabled - settings: dict - Actual session settings - warnings: list[str] - Any validation warnings - errors: list[str] - Any validation errors
   :rtype: dict with

   :raises ConfigurationError: If cache control validation fails and strict_validation=True

.. py:method:: benchbox.platforms.clickhouse.ClickHouseAdapter.apply_table_tunings(table_tuning, connection: Any) -> None

   Apply ClickHouse-specific table tunings.

   ClickHouse tuning approach:
   PARTITIONING: Handled via PARTITION BY in CREATE TABLE
   SORTING: Handled via ORDER BY in CREATE TABLE
   CLUSTERING: Achieved through ORDER BY and OPTIMIZE operations
   DISTRIBUTION: Handled via distributed engine settings

   :param table_tuning: TableTuning configuration object
   :param connection: ClickHouse connection

   :raises ValueError: If the tuning configuration is invalid for ClickHouse

Static member inventory
-----------------------

.. py:method:: benchbox.platforms.clickhouse.ClickHouseAdapter.get_query_plan(self, connection, query: str) -> str | None

   Get the ClickHouse logical plan via ``EXPLAIN PLAN``.

   All three modes (local/chDB, server/clickhouse-driver, cloud/
   clickhouse-connect) expose the same ``connection.execute()`` API returning
   indexable rows, so a single base-class implementation works for all of
   them. ``EXPLAIN PLAN`` (not ``PIPELINE``) is used because it carries the
   logical operator names needed for cross-platform comparison.

   Returns the joined plan text, or ``None`` on any failure (e.g. ClickHouse
   < 20.6 without EXPLAIN support), so capture degrades gracefully.

.. py:method:: benchbox.platforms.clickhouse.ClickHouseAdapter.get_query_plan_parser(self)

   Return the ClickHouse plan parser (shared by local, server, and cloud).

.. py:method:: benchbox.platforms.clickhouse.ClickHouseAdapter.get_tuning_introspector(self)

   Read ``system.tables`` keys to corroborate the applied ledger.

   Surfaces ClickHouse ``sorting_key`` / ``partition_key`` as receipt
   evidence (see ``benchbox.platforms.clickhouse.introspection``).
   ClickHouse's key-bearing DDL runs at ``CREATE TABLE`` time outside the
   recording connection, so ``create_schema`` records the tuned statement
   onto the ledger itself; every tuned clause it carries must corroborate
   here before the run reaches ``applied_verified``.

.. py:attribute:: benchbox.platforms.clickhouse.ClickHouseAdapter.plan_capture_phase_eligible

   Advertises whether benchmark plan capture is available for this adapter.

.. py:attribute:: benchbox.platforms.clickhouse.ClickHouseAdapter.driver_isolation_capability

   Declares whether this adapter can run through an isolated driver runtime; the value controls runtime-resolution support.

.. py:attribute:: benchbox.platforms.clickhouse.ClickHouseAdapter.KNOWN_INCOMPATIBLE_QUERIES

   Maps known incompatible benchmark queries to their platform-specific exclusions.

.. py:property:: benchbox.platforms.clickhouse.metadata.ClickHouseMetadataMixin.platform_name

   Returns this adapter's registered platform identifier for selection, metadata, and capability lookup.

.. py:staticmethod:: benchbox.platforms.clickhouse.metadata.ClickHouseMetadataMixin.add_cli_arguments(parser) -> None

   Add ClickHouse-specific CLI arguments.

.. py:classmethod:: benchbox.platforms.clickhouse.metadata.ClickHouseMetadataMixin.from_config(config: dict[str, Any])

   Create ClickHouse adapter from unified configuration.

.. py:method:: benchbox.platforms.clickhouse.metadata.ClickHouseMetadataMixin.get_database_path(self, **connection_config) -> str | None

   Get database path for local mode persistence.

   Priority:
   1. connection_config["database_path"] if provided and not None
   2. self.database_path (set during from_config)
   3. None (falls through to check_server_database_exists → returns False)

.. py:method:: benchbox.platforms.clickhouse.metadata.ClickHouseMetadataMixin.get_target_dialect(self) -> str

   Return the target SQL dialect for ClickHouse.

.. py:method:: benchbox.platforms.clickhouse.metadata.ClickHouseMetadataMixin.get_platform_info(self, connection: Any=None) -> dict[str, Any]

   Get ClickHouse platform information.

   Captures comprehensive ClickHouse configuration including:
   ClickHouse version
   Server settings and configuration
   MergeTree engine settings
   Build options and compilation flags
   Table compression settings

   Supports both server and local (chDB) modes.
   Gracefully degrades if permissions are insufficient for system table queries.

.. py:method:: benchbox.platforms.clickhouse.setup.ClickHouseSetupMixin.create_connection(self, **connection_config) -> Any

   Create ClickHouse connection based on mode.

.. py:method:: benchbox.platforms.clickhouse.setup.ClickHouseSetupMixin.close_connection(self, connection: Any) -> None

   Close ClickHouse connection.

.. py:method:: benchbox.platforms.clickhouse.diagnostics.ClickHouseDiagnosticsMixin.check_server_database_exists(self, **connection_config) -> bool

   Check if database exists on ClickHouse server.

.. py:method:: benchbox.platforms.clickhouse.diagnostics.ClickHouseDiagnosticsMixin.drop_database(self, **connection_config) -> None

   Drop database on ClickHouse server.

.. py:method:: benchbox.platforms.clickhouse.diagnostics.ClickHouseDiagnosticsMixin.get_table_info(self, connection: Any, table_name: str) -> dict[str, Any]

   Get detailed table information.

.. py:method:: benchbox.platforms.clickhouse.diagnostics.ClickHouseDiagnosticsMixin.optimize_table(self, connection: Any, table_name: str) -> None

   Optimize table for better query performance.

.. py:method:: benchbox.platforms.clickhouse.workload.ClickHouseWorkloadMixin.create_schema(self, benchmark, connection: Any) -> float

   Create schema using ClickHouse-optimized table definitions.

.. py:method:: benchbox.platforms.clickhouse.workload.ClickHouseWorkloadMixin.load_data(self, benchmark, connection: Any, data_dir: Path) -> tuple[dict[str, int], float, dict[str, Any] | None]

   Load data using ClickHouse's optimized CSV import capabilities.

.. py:method:: benchbox.platforms.clickhouse.workload.ClickHouseWorkloadMixin.get_table_row_count(self, connection: Any, table: str) -> int

   Get row count using ClickHouse execute() API.

   Overrides base implementation that uses cursor() - ClickHouseLocalClient
   and ClickHouseCloudClient expose execute() but not cursor().

   :param connection: ClickHouse connection (local, server, or cloud)
   :param table: Table name

   :returns: Row count as integer, or 0 if unable to determine

.. py:method:: benchbox.platforms.clickhouse.workload.ClickHouseWorkloadMixin.delta_native_registration(self, connection: Any) -> bool

   Probe whether the server registers native Delta Lake reads.

   Runs the ``system.table_functions`` / ``system.table_engines`` probes
   from :mod:`benchbox.platforms.clickhouse.delta_lake` and applies
   :func:`has_native_delta_registration`. No caching: the probe is two light system queries, and callers that decide per statement should see
   current server state.

   :param connection: ClickHouse connection exposing ``execute()``.

   :returns: True when the server registers the ``deltaLake`` function and the ``DeltaLake`` engine.

.. py:method:: benchbox.platforms.clickhouse.workload.ClickHouseWorkloadMixin.delta_reader_for(self, connection: Any, location: str) -> DeltaReader

   Select the native or snapshot read path for a Delta location.

   Probes the server once, then resolves via
   :func:`benchbox.platforms.clickhouse.delta_lake.resolve_delta_reader` with both the base-integration verdict and the per-function
   ``deltaLakeLocal`` verdict (a server can register the base
   integration without the local alias).

   :param connection: ClickHouse connection exposing ``execute()``.
   :param location: Bucket URL or filesystem path of the Delta table.

   :returns: The chosen :class:`DeltaReader`.

   :raises ValueError: If the location is empty, blank, unrecognized, or has no executable read path (remote without native reads).

.. py:method:: benchbox.platforms.clickhouse.workload.ClickHouseWorkloadMixin.execute_query(self, connection: Any, query: str, query_id: str, benchmark_type: str | None=None, scale_factor: float | None=None, validate_row_count: bool=True, stream_id: int | None=None) -> dict[str, Any]

   Execute query with detailed timing and profiling.

.. py:method:: benchbox.platforms.clickhouse.tuning.ClickHouseTuningMixin.get_effective_tuning_configuration(self) -> UnifiedTuningConfiguration | None

   Override to create ClickHouse-specific tuning configuration.

   ClickHouse requires primary keys even in no-tuning mode, so we create
   a configuration that reflects ClickHouse's requirements.

.. py:method:: benchbox.platforms.clickhouse.tuning.ClickHouseTuningMixin.configure_for_benchmark(self, connection: Any, benchmark_type: str) -> None

   Apply ClickHouse-specific optimizations based on benchmark type.

   Per ADR-3 (docs/development/tuning-adr-003-baseline-and-single-renderer.md)
   baseline policy: the basic settings below (memory/timeout/thread
   limits, cache control, join_use_nulls) are harness-operational, not
   optimization -- they apply in every mode so results are measured
   consistently and against standard-SQL semantics. The OLAP session
   pack (grace_hash join, spill thresholds, aggregation-in-order) is a
   curated performance profile, so it applies only on the TUNED path.
   Before this fix it fired only when tuning was DISABLED -- "notuning"
   shipped a curated OLAP profile while an explicit `--tuning tuned` run
   got none of it, exactly backwards from what the labels promise (see
   ADR-3's "notuning is not a baseline today" finding).

.. py:method:: benchbox.platforms.clickhouse.tuning.ClickHouseTuningMixin.validate_session_cache_control(self, connection: Any) -> dict[str, Any]

   Validate that session-level cache control settings were successfully applied.

   :param connection: Active ClickHouse database connection

   :returns:     - validated: bool - Whether validation passed - cache_disabled: bool - Whether cache is actually disabled - settings: dict - Actual session settings - warnings: list[str] - Any validation warnings - errors: list[str] - Any validation errors
   :rtype: dict with

   :raises ConfigurationError: If cache control validation fails and strict_validation=True

.. py:method:: benchbox.platforms.clickhouse.tuning.ClickHouseTuningMixin.supports_tuning_type(self, tuning_type) -> bool

   Check if ClickHouse supports a specific tuning type.

.. py:method:: benchbox.platforms.clickhouse.tuning.ClickHouseTuningMixin.apply_table_tunings(self, table_tuning, connection: Any) -> None

   Apply ClickHouse-specific table tunings.

   ClickHouse tuning approach:
   PARTITIONING: Handled via PARTITION BY in CREATE TABLE
   SORTING: Handled via ORDER BY in CREATE TABLE
   CLUSTERING: Achieved through ORDER BY and OPTIMIZE operations
   DISTRIBUTION: Handled via distributed engine settings

   :param table_tuning: TableTuning configuration object
   :param connection: ClickHouse connection

   :raises ValueError: If the tuning configuration is invalid for ClickHouse

.. py:method:: benchbox.platforms.clickhouse.tuning.ClickHouseTuningMixin.apply_unified_tuning(self, unified_config: UnifiedTuningConfiguration, connection: Any) -> None

   Apply unified tuning configuration to ClickHouse.

   :param unified_config: Unified tuning configuration to apply
   :param connection: ClickHouse connection

.. py:method:: benchbox.platforms.clickhouse.tuning.ClickHouseTuningMixin.apply_platform_optimizations(self, platform_config: PlatformOptimizationConfiguration, connection: Any) -> None

   Apply ClickHouse-specific platform optimizations.

   `PlatformOptimizationConfiguration` only models the Databricks/BigQuery
   style knobs (z-ordering, liquid clustering, auto-optimize, bloom
   filters, materialized views) -- none of which apply to ClickHouse.
   ClickHouse's own session settings (memory, threads, join algorithm,
   cache control) are applied separately via `configure_for_benchmark`,
   which has direct adapter attributes to read rather than a
   `platform_config` blob. This hook is therefore an intentional no-op
   for ClickHouse today.

   :param platform_config: Platform optimization configuration
   :param connection: ClickHouse connection

.. py:method:: benchbox.platforms.clickhouse.tuning.ClickHouseTuningMixin.apply_constraint_configuration(primary_key_config: PrimaryKeyConfiguration, foreign_key_config: ForeignKeyConfiguration, connection: Any) -> None

   Logs informational messages for enabled primary-key and foreign-key settings.
   This hook executes no SQL and does not use ``connection``. Table-creation
   hooks handle any platform-supported constraint DDL.

Constructor Configuration
~~~~~~~~~~~~~~~~~~~~~~~~~

Pass keyword configuration through ``ClickHouseAdapter(**config)``.
The canonical ``deployment_mode`` selects ``"local"`` (default) or ``"server"``;
``mode`` is a legacy alias.

- Server mode reads ``host="localhost"``, ``port=9000``, ``database="default"``,
  ``username="default"`` (or ``user``), ``password=""``, ``secure=False`` and
  ``compression=False``.
- Local mode reads optional ``data_path`` and ``database_path`` for filesystem
  and persistent chDB storage.
- Both modes default ``max_memory_usage`` to ``"8GB"`` and
  ``max_execution_time`` to 300 seconds. ``max_threads`` defaults to eight
  for server mode and four for local mode.

See the class contract above for mode-specific dependency requirements.

Configuration Examples
----------------------

Server Mode - Local Development
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from benchbox.platforms.clickhouse import ClickHouseAdapter

    adapter = ClickHouseAdapter(
        host="localhost",
        port=9000,
        database="benchmark"
    )

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

    adapter = ClickHouseAdapter(
        host="clickhouse.example.com",
        port=9440,
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

    adapter = ClickHouseAdapter(mode="local")

    adapter = ClickHouseAdapter(
        mode="local",
        data_path="./benchmarks/clickhouse_local.chdb"
    )

Performance Tuning
~~~~~~~~~~~~~~~~~~

.. code-block:: python

    adapter = ClickHouseAdapter(
        host="localhost",
        database="benchmark",
        max_memory_usage="64GB",
        max_execution_time=600,
        max_threads=32,
        compression=False
    )

Data Loading
------------

Bulk Loading from Files
~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from benchbox.platforms.clickhouse import ClickHouseAdapter

    adapter = ClickHouseAdapter(host="localhost", database="benchmark")
    conn = adapter.create_connection()

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

    conn.execute("""
        INSERT INTO lineitem
        FROM INFILE 'data/lineitem.tbl'
        FORMAT CSV
    """)

Loading from S3
~~~~~~~~~~~~~~~

.. code-block:: python

    conn.execute("""
        CREATE TABLE lineitem AS
        SELECT * FROM s3(
            'https://s3.amazonaws.com/bucket/lineitem/*.parquet',
            'Parquet'
        )
    """)

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

    result = conn.execute("SELECT COUNT(*) FROM lineitem")
    row_count = result[0][0]

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

    plan = conn.execute("""
        EXPLAIN
        SELECT * FROM lineitem
        WHERE l_shipdate > '1995-01-01'
    """)
    for row in plan:
        print(row[0])

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
           max_memory_usage="16GB"
       )

2. **Monitor memory usage** during execution:

   .. code-block:: python

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

       conn.execute("SET max_bytes_before_external_group_by = 10000000000")

Performance Optimization
~~~~~~~~~~~~~~~~~~~~~~~~

1. **Choose optimal table engine** and ordering key:

   Illustrative SQL fragments; supply complete table definitions before execution.

   .. code-block:: sql

       CREATE TABLE lineitem (...)
       ENGINE = MergeTree()
       ORDER BY (l_shipdate, l_orderkey)

       ORDER BY (l_shipdate, l_returnflag, l_orderkey)

2. **Use appropriate data types**:

   Prefer smaller types:

   - UInt8 instead of UInt32 for small integers
   - Date instead of DateTime for date-only fields
   - LowCardinality(String) for repeated strings

3. **Partition large tables**:

   Illustrative SQL fragments; supply complete table definitions before execution.

   .. code-block:: sql

       CREATE TABLE lineitem (...)
       ENGINE = MergeTree()
       PARTITION BY toYYYYMM(l_shipdate)
       ORDER BY (l_orderkey, l_linenumber)

Connection Management
~~~~~~~~~~~~~~~~~~~~~

1. **Reuse connections** for multiple queries:

   .. code-block:: python

       adapter = ClickHouseAdapter(host="localhost")
       conn = adapter.create_connection()

       for query_id in range(1, 23):
           result = conn.execute(queries[query_id])

       adapter.close_connection(conn)

2. **Set connection timeouts** appropriately:

   .. code-block:: python

       adapter = ClickHouseAdapter(
           host="localhost",
           max_execution_time=600
       )

Common Issues
-------------

Connection Refused
~~~~~~~~~~~~~~~~~~

**Problem**: Cannot connect to ClickHouse server

**Solutions**:

.. code-block:: bash

    ps aux | grep clickhouse-server

    sudo service clickhouse-server start

    netstat -ln | grep 9000

    clickhouse-client --host=localhost --port=9000

.. code-block:: python

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

    adapter = ClickHouseAdapter(
        host="localhost",
        max_memory_usage="32GB"
    )

    conn = adapter.create_connection()
    conn.execute("SET max_bytes_before_external_group_by = 20000000000")
    conn.execute("SET max_bytes_before_external_sort = 20000000000")

    benchmark = TPCH(scale_factor=0.1)

Local Mode Import Error
~~~~~~~~~~~~~~~~~~~~~~~

**Problem**: "chdb is not installed" error in local mode

**Solution**:

.. code-block:: bash

    uv pip install chdb

    adapter = ClickHouseAdapter(mode="server", host="localhost")

Slow Query Performance
~~~~~~~~~~~~~~~~~~~~~~

**Problem**: Queries execute slowly

**Solutions**:

.. code-block:: python

    adapter = ClickHouseAdapter(
        host="localhost",
        max_threads=16
    )

    plan = conn.execute("EXPLAIN SELECT ...")

    conn.execute("SET log_queries = 1")
    conn.execute("SET log_query_threads = 1")

    result = conn.execute("SELECT ...")

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
- :doc:`/reference/api-reference` - High-level API guide

External Resources
~~~~~~~~~~~~~~~~~~

- `ClickHouse Documentation <https://clickhouse.com/docs>`_ - Official ClickHouse docs
- `ClickHouse Performance Guide <https://clickhouse.com/docs/optimize/query-optimization>`_ - Performance tuning
- `chDB Documentation <https://github.com/chdb-io/chdb>`_ - Local mode library
- `ClickHouse Table Engines <https://clickhouse.com/docs/engines/table-engines>`_ - Storage engines
