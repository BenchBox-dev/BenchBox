Snowflake Platform Adapter
===========================

.. tags:: reference, python-api, snowflake

The Snowflake adapter provides cloud-native data warehouse execution with elastic compute and automatic optimization.

Overview
--------

Snowflake is a multi-cloud Data Cloud platform that provides:

- **Multi-cloud support** - Available on AWS, Azure, and GCP
- **Storage-compute separation** - Independent scaling of storage and compute
- **Elastic compute** - Scale warehouses up/down
- **Multi-cluster warehouses** - Concurrency scaling capabilities
- **Zero-copy cloning** - Instant data cloning for testing
- **Time Travel** - Query historical data (up to 90 days)
- **Micro-partitions** - Self-optimizing data organization

Common use cases:

- Multi-cloud analytics workloads
- Variable workload patterns (auto-suspend/resume)
- Multi-tenant benchmarking environments
- Enterprise-scale data warehousing
- Testing with per-second billing

Quick Start
-----------

Basic Configuration
~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from benchbox.tpch import TPCH
    from benchbox.platforms.snowflake import SnowflakeAdapter

    adapter = SnowflakeAdapter(
        account="xy12345.us-east-1",
        username="benchbox_user",
        password="secure_password_123",
        warehouse="COMPUTE_WH",
        database="BENCHBOX",
        schema="PUBLIC"
    )

    benchmark = TPCH(scale_factor=1.0)
    results = benchmark.run_with_platform(adapter)

    print(f"Completed in {results.total_execution_time:.2f}s")

API Reference
-------------

SnowflakeAdapter Class
~~~~~~~~~~~~~~~~~~~~~~

.. py:class:: benchbox.platforms.snowflake.SnowflakeAdapter(**config)

   Snowflake adapter.  ``warehouse`` defaults to ``"COMPUTE_WH"``,
   ``database`` to ``"BENCHBOX"``, ``schema`` to ``"PUBLIC"``,
   ``authenticator`` to ``"snowflake"``, ``warehouse_size`` to ``"MEDIUM"``,
   ``auto_suspend`` to ``300``, ``auto_resume`` to ``True``, and ``query_tag``
   to ``"BenchBox"``.  ``disable_result_cache`` and ``strict_validation``
   default to ``True``.  Optional dependencies can raise ``ImportError``;
   invalid staging or table-mode combinations raise ``ValueError``.

   Example::

      adapter = SnowflakeAdapter(account="org-account", username="user", warehouse="COMPUTE_WH")

   The adapter advertises external-table support.  See :doc:`common` for shared methods.

.. py:method:: benchbox.platforms.snowflake.SnowflakeAdapter.create_connection(**connection_config) -> Any

   Create optimized Snowflake connection.

.. py:method:: benchbox.platforms.snowflake.SnowflakeAdapter.create_schema(benchmark, connection: Any) -> float

   Create schema using Snowflake table definitions.

.. py:method:: benchbox.platforms.snowflake.SnowflakeAdapter.load_data(benchmark, connection: Any, data_dir: Path) -> tuple[dict[str, int], float, dict[str, Any] | None]

   Load data using Snowflake PUT and COPY INTO commands.

.. py:method:: benchbox.platforms.snowflake.SnowflakeAdapter.create_external_tables(benchmark: Any, connection: Any, data_dir: Path) -> tuple[dict[str, int], float, dict[str, Any] | None]

   Register external tables backed by cloud storage via a named external stage.

.. py:method:: benchbox.platforms.snowflake.SnowflakeAdapter.execute_query(connection: Any, query: str, query_id: str, benchmark_type: str | None = None, scale_factor: float | None = None, validate_row_count: bool = True, stream_id: int | None = None) -> dict[str, Any]

   Execute query with detailed timing and performance tracking.

   Accepts either a connection or an already-open cursor: the TPC power
   harness passes a per-stream cursor through the facade, which has no
   ``cursor()`` method of its own.

.. py:method:: benchbox.platforms.snowflake.SnowflakeAdapter.validate_session_cache_control(connection: Any) -> dict[str, Any]

   Validate that session-level cache control settings were successfully applied.

   :param connection: Active Snowflake database connection

   :returns:     - validated: bool - Whether validation passed - cache_disabled: bool - Whether cache is actually disabled - settings: dict - Actual session settings - warnings: list[str] - Any validation warnings - errors: list[str] - Any validation errors
   :rtype: dict with

   :raises ConfigurationError: If cache control validation fails and strict_validation=True

.. py:method:: benchbox.platforms.snowflake.SnowflakeAdapter.analyze_table(connection: Any, table_name: str) -> None

   Trigger table analysis for better query optimization.

   Raises on failure (does not swallow) so the opt-in statistics phase's
   gather_statistics() -> run_statistics_phase() caller can detect and
   record a real failure as status=FAILED.

Static member inventory
-----------------------

.. py:property:: benchbox.platforms.snowflake.SnowflakeAdapter.platform_name

   Returns this adapter's registered platform identifier for selection, metadata, and capability lookup.

.. py:staticmethod:: benchbox.platforms.snowflake.SnowflakeAdapter.add_cli_arguments(parser) -> None

   Add Snowflake-specific CLI arguments.

.. py:classmethod:: benchbox.platforms.snowflake.SnowflakeAdapter.from_config(config: dict[str, Any])

   Create Snowflake adapter from unified configuration.

.. py:method:: benchbox.platforms.snowflake.SnowflakeAdapter.get_platform_info(self, connection: Any=None) -> dict[str, Any]

   Get Snowflake platform information.

   Captures comprehensive Snowflake configuration including:
   Snowflake version
   Warehouse size and auto-suspend/resume settings
   Multi-cluster warehouse configuration
   Cloud provider and region
   Account edition (best effort)

   Gracefully degrades if permissions are insufficient for metadata queries.

.. py:method:: benchbox.platforms.snowflake.SnowflakeAdapter.get_normalized_result_metadata(self, *, connection: Any | None=None, platform_info: Mapping[str, Any] | None=None) -> dict[str, Any]

   Return Snowflake-specific normalized cloud/runtime metadata.

.. py:method:: benchbox.platforms.snowflake.SnowflakeAdapter.get_target_dialect(self) -> str

   Return the target SQL dialect for Snowflake.

.. py:method:: benchbox.platforms.snowflake.SnowflakeAdapter.check_server_database_exists(self, **connection_config) -> bool

   Check if database exists in Snowflake account.

   Also checks for existing schemas and tables, since they may exist from a
   previous run even if the database doesn't formally exist at account level.

.. py:method:: benchbox.platforms.snowflake.SnowflakeAdapter.drop_database(self, **connection_config) -> None

   Drop database in Snowflake account.

.. py:method:: benchbox.platforms.snowflake.SnowflakeAdapter.validate_external_table_requirements(self) -> None

   Validate required cloud staging configuration for external table mode.

.. py:method:: benchbox.platforms.snowflake.SnowflakeAdapter.configure_for_benchmark(self, connection: Any, benchmark_type: str) -> None

   Apply Snowflake-specific optimizations based on benchmark type.

.. py:method:: benchbox.platforms.snowflake.SnowflakeAdapter.get_query_plan(self, connection: Any, query: str) -> str | None

   Return the Snowflake plan as JSON via ``EXPLAIN USING JSON``.

   Snowflake has no plain ``EXPLAIN`` that yields a parseable tree; the
   JSON form returns a single VARIANT cell describing the operator graph.
   Accepts a connection or an already-open cursor.

.. py:method:: benchbox.platforms.snowflake.SnowflakeAdapter.get_query_plan_parser(self)

   Get Snowflake query plan parser.

.. py:method:: benchbox.platforms.snowflake.SnowflakeAdapter.get_tuning_introspector(self)

   Read ``INFORMATION_SCHEMA`` clustering keys to corroborate the ledger.

   Snowflake's tuning footprint is the clustering key, applied after load
   by ``ALTER TABLE ... CLUSTER BY``. Those statements already reach the
   applied ledger (``apply_standard_unified_tuning`` wraps the connection
   in a recording connection), so this supplies the catalog side that lets
   them be corroborated instead of classified ``unverifiable``.

.. py:method:: benchbox.platforms.snowflake.SnowflakeAdapter.close_connection(self, connection: Any) -> None

   Close Snowflake connection.

.. py:method:: benchbox.platforms.snowflake.SnowflakeAdapter.generate_tuning_clause(self, table_tuning) -> str

   Generate Snowflake-specific tuning clauses for CREATE TABLE statements.

   Snowflake supports:
   CLUSTER BY (column1, column2, ...) for clustering keys
   Micro-partitions are automatic based on ingestion order and clustering

   :param table_tuning: The tuning configuration for the table

   :returns: SQL clause string to be appended to CREATE TABLE statement

.. py:method:: benchbox.platforms.snowflake.SnowflakeAdapter.apply_table_tunings(self, table_tuning, connection: Any) -> None

   Apply tuning configurations to a Snowflake table.

   Snowflake tuning approach:
   CLUSTERING: Handled via CLUSTER BY in CREATE TABLE or ALTER TABLE
   PARTITIONING: Automatic micro-partitions with optional clustering keys
   Automatic clustering can be enabled for maintenance

   :param table_tuning: The tuning configuration to apply
   :param connection: Snowflake connection

   :raises ValueError: If the tuning configuration is invalid for Snowflake

.. py:method:: benchbox.platforms.snowflake.SnowflakeAdapter.apply_unified_tuning(self, unified_config: UnifiedTuningConfiguration, connection: Any) -> None

   Apply unified tuning configuration to Snowflake.

   :param unified_config: Unified tuning configuration to apply
   :param connection: Snowflake connection

.. py:method:: benchbox.platforms.snowflake.SnowflakeAdapter.apply_platform_optimizations(self, platform_config: PlatformOptimizationConfiguration, connection: Any) -> None

   Apply Snowflake-specific platform optimizations.

   Snowflake optimizations include:
   Warehouse scaling and multi-cluster configuration
   Query acceleration service settings
   Result set caching configuration
   Session-level optimization parameters

   :param platform_config: Platform optimization configuration
   :param connection: Snowflake connection

.. py:attribute:: benchbox.platforms.snowflake.SnowflakeAdapter.plan_capture_phase_eligible

   Advertises whether benchmark plan capture is available for this adapter.

.. py:attribute:: benchbox.platforms.snowflake.SnowflakeAdapter.driver_isolation_capability

   Declares whether this adapter can run through an isolated driver runtime; the value controls runtime-resolution support.

.. py:attribute:: benchbox.platforms.snowflake.SnowflakeAdapter.supports_external_tables

   Advertises whether the adapter implements external-table creation.

.. py:method:: benchbox.platforms.snowflake.SnowflakeAdapter.apply_constraint_configuration(primary_key_config: PrimaryKeyConfiguration, foreign_key_config: ForeignKeyConfiguration, connection: Any) -> None

   Logs informational messages for enabled primary-key and foreign-key settings.
   This hook executes no SQL and does not use ``connection``. Table-creation
   hooks handle any platform-supported constraint DDL.

Constructor Configuration
~~~~~~~~~~~~~~~~~~~~~~~~~

Pass keyword configuration through ``SnowflakeAdapter(**config)``.

- ``account``, ``username`` and ``password`` supply connection identity;
  ``role`` is optional. ``authenticator`` defaults to ``"snowflake"``;
  ``private_key_path`` and ``private_key_passphrase`` support key-pair settings.
- ``warehouse``, ``database`` and ``schema`` default to ``"COMPUTE_WH"``,
  ``"BENCHBOX"`` and ``"PUBLIC"`` respectively.
- ``warehouse_size`` defaults to ``"MEDIUM"``. ``auto_suspend`` defaults to
  300 seconds, ``auto_resume`` to ``True`` and ``multi_cluster_warehouse`` to
  ``False``.
- ``query_tag`` defaults to ``"BenchBox"`` and ``timezone`` to ``"UTC"``.
- ``file_format`` defaults to ``"CSV"`` and ``compression`` to ``"AUTO"``.

Defaulted string settings above use the default for a falsey supplied value.

Configuration Examples
----------------------

Password Authentication
~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    adapter = SnowflakeAdapter(
        account="xy12345.us-east-1",
        username="benchbox_user",
        password="secure_password_123",
        warehouse="COMPUTE_WH",
        database="BENCHBOX"
    )

Key-Pair Authentication (Recommended for Production)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The commands below generate a key pair, extract the public key, and assign the
public key to the user in Snowflake. Run the ``ALTER USER`` statement in
Snowflake, not in a shell.

.. code-block:: bash

    openssl genrsa 2048 | openssl pkcs8 -topk8 -inform PEM -out rsa_key.p8 -nocrypt

    openssl rsa -in rsa_key.p8 -pubout -out rsa_key.pub

    ALTER USER benchbox_user SET RSA_PUBLIC_KEY='MIIBIjANBgkqh...';

.. code-block:: python

    adapter = SnowflakeAdapter(
        account="xy12345.us-east-1",
        username="benchbox_user",
        password="",
        private_key_path="/path/to/rsa_key.p8",
        warehouse="COMPUTE_WH",
        database="BENCHBOX"
    )

OAuth Authentication
~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    adapter = SnowflakeAdapter(
        account="xy12345.us-east-1",
        username="benchbox_user",
        password="oauth_token_here",
        authenticator="oauth",
        warehouse="COMPUTE_WH",
        database="BENCHBOX"
    )

Warehouse Sizing
~~~~~~~~~~~~~~~~

.. code-block:: python

    adapter = SnowflakeAdapter(
        account="xy12345.us-east-1",
        username="user",
        password="password",
        warehouse="DEV_WH",
        warehouse_size="X-SMALL"
    )

    adapter = SnowflakeAdapter(
        account="xy12345.us-east-1",
        username="user",
        password="password",
        warehouse="PROD_WH",
        warehouse_size="LARGE"
    )

    adapter = SnowflakeAdapter(
        account="xy12345.us-east-1",
        username="user",
        password="password",
        warehouse="HEAVY_WH",
        warehouse_size="4X-LARGE"
    )

The three examples show a small warehouse for development, a large one for
production, and a 4X-Large one for heavy workloads. Snowflake bills X-Small at 1
credit per hour, Large at 8 credits per hour, and 4X-Large at 128 credits per
hour.

Multi-Cluster Warehouse
~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    adapter = SnowflakeAdapter(
        account="xy12345.us-east-1",
        username="user",
        password="password",
        warehouse="MULTI_CLUSTER_WH",
        warehouse_size="LARGE",
        multi_cluster_warehouse=True,
        auto_suspend=60,
        auto_resume=True
    )

Multi-cluster mode lets the warehouse scale out automatically for concurrent
workloads.

Data Loading
------------

PUT and COPY INTO (Recommended)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Snowflake uses internal stages for efficient data loading:

.. code-block:: python

    from benchbox.platforms.snowflake import SnowflakeAdapter
    from benchbox.tpch import TPCH
    from pathlib import Path

    adapter = SnowflakeAdapter(
        account="xy12345.us-east-1",
        username="user",
        password="password",
        warehouse="LOAD_WH",
        database="BENCHBOX"
    )

    benchmark = TPCH(scale_factor=1.0)
    data_dir = Path("./tpch_data")
    benchmark.generate_data(data_dir)

    conn = adapter.create_connection()
    table_stats, load_time = adapter.load_data(benchmark, conn, data_dir)

    print(f"Loaded {sum(table_stats.values()):,} rows in {load_time:.2f}s")

The data is generated locally first. ``load_data`` then uses PUT and COPY INTO
automatically: the files are uploaded to an internal stage and then bulk loaded.

External Stage (S3/GCS/Azure)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    conn = adapter.create_connection()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE OR REPLACE STAGE benchbox_stage
        URL = 's3://my-bucket/benchbox-data/'
        CREDENTIALS = (
            AWS_KEY_ID = 'AKIAIOSFODNN7EXAMPLE'
            AWS_SECRET_KEY = 'wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY'
        )
    """)

    cursor.execute("""
        COPY INTO lineitem
        FROM @benchbox_stage/lineitem.tbl
        FILE_FORMAT = (
            TYPE = 'CSV'
            FIELD_DELIMITER = '|'
            SKIP_HEADER = 0
        )
    """)

Compressed Data
~~~~~~~~~~~~~~~

.. code-block:: python

    adapter = SnowflakeAdapter(
        account="xy12345.us-east-1",
        username="user",
        password="password",
        compression="GZIP"
    )

Snowflake handles compressed files automatically, and GZIP files are
decompressed during COPY INTO. Supported compression values include GZIP,
BROTLI and ZSTD.

Query Execution
---------------

Basic Query Execution
~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    adapter = SnowflakeAdapter(account="...", username="...", password="...")
    conn = adapter.create_connection()

    cursor = conn.cursor()
    cursor.execute("""
        SELECT
            l_returnflag,
            l_linestatus,
            sum(l_quantity) as sum_qty,
            count(*) as count_order
        FROM lineitem
        WHERE l_shipdate <= '1998-09-01'
        GROUP BY l_returnflag, l_linestatus
        ORDER BY l_returnflag, l_linestatus
    """)

    results = cursor.fetchall()
    for row in results:
        print(row)

Query Statistics
~~~~~~~~~~~~~~~~

.. code-block:: python

    cursor.execute("ALTER SESSION SET QUERY_TAG = 'benchmark_q1'")
    cursor.execute(query)
    results = cursor.fetchall()

    cursor.execute("""
        SELECT
            QUERY_ID,
            QUERY_TEXT,
            TOTAL_ELAPSED_TIME,
            EXECUTION_TIME,
            COMPILATION_TIME,
            BYTES_SCANNED,
            ROWS_PRODUCED,
            CREDITS_USED_CLOUD_SERVICES,
            WAREHOUSE_SIZE
        FROM TABLE(INFORMATION_SCHEMA.QUERY_HISTORY())
        WHERE QUERY_TAG = 'benchmark_q1'
        ORDER BY START_TIME DESC
        LIMIT 1
    """)

    stats = cursor.fetchone()
    print(f"Execution time: {stats[3]}ms")
    print(f"Bytes scanned: {stats[5]:,}")
    print(f"Credits used: {stats[7]}")

The first statements execute the query under a query tag so it can be tracked.
The second query reads the query history for that tag to get performance
metrics.

Query Plans
~~~~~~~~~~~

.. code-block:: python

    cursor.execute("""
        EXPLAIN
        SELECT * FROM lineitem
        WHERE l_shipdate > '1995-01-01'
    """)

    plan = cursor.fetchall()
    for step in plan:
        print(step[0])

Advanced Features
-----------------

Clustering
~~~~~~~~~~

.. code-block:: python

    cursor.execute("""
        CREATE OR REPLACE TABLE orders_clustered (
            o_orderkey NUMBER,
            o_custkey NUMBER,
            o_orderstatus STRING,
            o_totalprice NUMBER(15,2),
            o_orderdate DATE
        )
        CLUSTER BY (o_orderdate, o_orderkey)
    """)


    cursor.execute("ALTER TABLE orders_clustered RECLUSTER")

    cursor.execute("ALTER TABLE orders_clustered RESUME RECLUSTER")

    cursor.execute("""
        SELECT SYSTEM$CLUSTERING_INFORMATION('orders_clustered')
    """)

The table declares its clustering key in ``CREATE TABLE``, and Snowflake
maintains clustering automatically. ``RECLUSTER`` reclusters manually if needed,
``RESUME RECLUSTER`` enables automatic clustering, and
``SYSTEM$CLUSTERING_INFORMATION`` reports clustering quality.

Time Travel
~~~~~~~~~~~

.. code-block:: python

    cursor.execute("""
        SELECT * FROM lineitem
        AT(OFFSET => -3600)
        WHERE l_shipdate = '1995-01-01'
    """)

    cursor.execute("""
        SELECT * FROM lineitem
        AT(TIMESTAMP => '2025-01-01 00:00:00'::TIMESTAMP)
        WHERE l_shipdate = '1995-01-01'
    """)

    cursor.execute("""
        SELECT * FROM lineitem
        BEFORE(STATEMENT => '01a12345-6789-abcd-ef01-234567890abc')
    """)

The first query reads data as of one hour ago (the offset is in seconds). The
second reads data at a specific timestamp. The third views the table as it was
before a given statement ran, which shows that statement's changes.

Zero-Copy Cloning
~~~~~~~~~~~~~~~~~

.. code-block:: python

    cursor.execute("""
        CREATE DATABASE benchbox_clone
        CLONE benchbox
    """)

    cursor.execute("""
        CREATE TABLE lineitem_clone
        CLONE lineitem
    """)

    cursor.execute("""
        CREATE TABLE lineitem_yesterday
        CLONE lineitem
        AT(OFFSET => -86400)
    """)

The database and table clones are created instantly because no data is copied.
The last clone uses an offset of -86400 seconds to capture the table as it was
24 hours ago.

Result Set Caching
~~~~~~~~~~~~~~~~~~

.. code-block:: python

    cursor.execute("ALTER SESSION SET USE_CACHED_RESULT = TRUE")

    cursor.execute("SELECT COUNT(*) FROM lineitem")
    result1 = cursor.fetchone()

    cursor.execute("SELECT COUNT(*) FROM lineitem")
    result2 = cursor.fetchone()

Result caching is enabled by default. The first execution computes the result.
The second execution returns the cached result immediately and uses no credits.

Best Practices
--------------

Warehouse Management
~~~~~~~~~~~~~~~~~~~~

1. **Right-size warehouses** for workload:

   .. code-block:: python

       adapter = SnowflakeAdapter(
           warehouse_size="MEDIUM",
           auto_suspend=300,
           auto_resume=True
       )

   Typical sizes are X-SMALL to SMALL for development, MEDIUM to LARGE for
   testing, and LARGE to 4X-LARGE for production. MEDIUM balances cost and
   performance. ``auto_suspend=300`` suspends the warehouse after 5 idle
   minutes, and ``auto_resume=True`` resumes it when a query arrives.

2. **Use separate warehouses** for different workloads:

   .. code-block:: python

       load_adapter = SnowflakeAdapter(warehouse="LOAD_WH", warehouse_size="LARGE")

       query_adapter = SnowflakeAdapter(warehouse="QUERY_WH", warehouse_size="MEDIUM")

   The first adapter is the loading warehouse. The second is the query warehouse.

3. **Enable multi-cluster** for concurrent workloads:

   .. code-block:: python

       adapter = SnowflakeAdapter(
           warehouse="CONCURRENT_WH",
           multi_cluster_warehouse=True
       )

Cost Optimization
~~~~~~~~~~~~~~~~~

1. **Suspend idle warehouses**:

   .. code-block:: python

       adapter = SnowflakeAdapter(
           auto_suspend=60,
           auto_resume=True
       )

2. **Use result caching**:

   .. code-block:: python

       cursor.execute("ALTER SESSION SET USE_CACHED_RESULT = TRUE")

   This setting is on by default and reuses results for identical queries.

3. **Start small, scale up as needed**:

   .. code-block:: python

       adapter = SnowflakeAdapter(warehouse_size="X-SMALL")

       cursor.execute(f"ALTER WAREHOUSE {warehouse} SET WAREHOUSE_SIZE = 'MEDIUM'")

   Start with the smallest warehouse, then monitor and resize if needed.

4. **Monitor credit usage**:

   .. code-block:: python

       cursor.execute("""
           SELECT
               WAREHOUSE_NAME,
               SUM(CREDITS_USED) as total_credits,
               SUM(CREDITS_USED_COMPUTE) as compute_credits,
               SUM(CREDITS_USED_CLOUD_SERVICES) as cloud_services_credits
           FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
           WHERE START_TIME >= DATEADD('day', -7, CURRENT_TIMESTAMP())
           GROUP BY WAREHOUSE_NAME
           ORDER BY total_credits DESC
       """)

   This query reports warehouse credit usage over the last seven days.

Data Organization
~~~~~~~~~~~~~~~~~

1. **Use clustering keys** for filtered columns:

   Illustrative SQL fragments; supply complete table definitions before execution.

   .. code-block:: sql

       CREATE TABLE lineitem (...)
       CLUSTER BY (l_shipdate, l_orderkey)

2. **Partition large tables** by date:

   Snowflake creates micro-partitions automatically. Date-based clustering
   uses a clause such as this illustrative fragment:

   .. code-block:: sql

       CLUSTER BY (DATE_TRUNC('month', order_date))

3. **Analyze clustering quality**:

   .. code-block:: python

       cursor.execute("""
           SELECT SYSTEM$CLUSTERING_INFORMATION('lineitem')
       """)

       if clustering_depth > 10:
           cursor.execute("ALTER TABLE lineitem RECLUSTER")

   Recluster when clustering quality degrades.

Common Issues
-------------

Warehouse Not Running
~~~~~~~~~~~~~~~~~~~~~

**Problem**: "Warehouse is suspended" error

**Solutions**: enable auto-resume so the warehouse starts automatically, resume
it manually, and check its status:

.. code-block:: python

    adapter = SnowflakeAdapter(
        auto_resume=True
    )

    cursor.execute(f"ALTER WAREHOUSE {warehouse} RESUME")

    cursor.execute(f"SHOW WAREHOUSES LIKE '{warehouse}'")
    status = cursor.fetchall()
    print(f"Warehouse state: {status[0][1]}")

Authentication Failed
~~~~~~~~~~~~~~~~~~~~~

**Problem**: "Incorrect username or password" error

**Solutions**:

1. Verify the account identifier format. Correct values look like
   ``xy12345.us-east-1`` or ``xy12345.us-east-1.aws``. A full URL such as
   ``https://xy12345.snowflakecomputing.com`` is incorrect.
2. Check that the username exists. It is case-insensitive. In the Snowflake UI,
   run ``SHOW USERS;``.
3. Use key-pair authentication for better security:

.. code-block:: python

    adapter = SnowflakeAdapter(
        account="xy12345.us-east-1",
        username="benchbox_user",
        password="",
        private_key_path="/path/to/key.p8"
    )

Insufficient Privileges
~~~~~~~~~~~~~~~~~~~~~~~

**Problem**: "Insufficient privileges" error

**Solutions**: grant the required privileges in Snowflake, then specify a role
that has them:

.. code-block:: bash

    GRANT USAGE ON WAREHOUSE COMPUTE_WH TO ROLE benchbox_role;
    GRANT USAGE ON DATABASE BENCHBOX TO ROLE benchbox_role;
    GRANT CREATE SCHEMA ON DATABASE BENCHBOX TO ROLE benchbox_role;
    GRANT USAGE ON SCHEMA BENCHBOX.PUBLIC TO ROLE benchbox_role;
    GRANT CREATE TABLE ON SCHEMA BENCHBOX.PUBLIC TO ROLE benchbox_role;

.. code-block:: python

    adapter = SnowflakeAdapter(
        account="xy12345.us-east-1",
        username="user",
        password="password",
        role="BENCHBOX_ROLE"
    )

High Costs
~~~~~~~~~~

**Problem**: Unexpected credit consumption

**Solutions**: check the query history for expensive queries, use a smaller
warehouse, enable aggressive auto-suspend (``auto_suspend=60`` is 1 minute), and
set resource monitors:

.. code-block:: python

    cursor.execute("""
        SELECT
            QUERY_TEXT,
            TOTAL_ELAPSED_TIME,
            BYTES_SCANNED,
            CREDITS_USED_CLOUD_SERVICES
        FROM TABLE(INFORMATION_SCHEMA.QUERY_HISTORY())
        WHERE START_TIME >= DATEADD('hour', -24, CURRENT_TIMESTAMP())
        ORDER BY CREDITS_USED_CLOUD_SERVICES DESC
        LIMIT 10
    """)

    adapter = SnowflakeAdapter(warehouse_size="X-SMALL")

    adapter = SnowflakeAdapter(auto_suspend=60)

    cursor.execute("""
        CREATE RESOURCE MONITOR daily_limit WITH CREDIT_QUOTA = 100
        TRIGGERS ON 75 PERCENT DO NOTIFY
                 ON 100 PERCENT DO SUSPEND
    """)

    cursor.execute(f"""
        ALTER WAREHOUSE {warehouse} SET RESOURCE_MONITOR = daily_limit
    """)

Slow Query Performance
~~~~~~~~~~~~~~~~~~~~~~

**Problem**: Queries slower than expected

**Solutions**: resize the warehouse, check clustering quality, add clustering
keys, enable automatic clustering, and check the query profile. For the profile,
open the Snowflake UI, choose Query History, click the query, and view its
profile.

.. code-block:: python

    cursor.execute(f"""
        ALTER WAREHOUSE {warehouse} SET WAREHOUSE_SIZE = 'LARGE'
    """)

    cursor.execute("""
        SELECT SYSTEM$CLUSTERING_INFORMATION('lineitem')
    """)

    cursor.execute("""
        ALTER TABLE lineitem CLUSTER BY (l_shipdate, l_orderkey)
    """)

    cursor.execute("ALTER TABLE lineitem RESUME RECLUSTER")


See Also
--------

Platform Documentation
~~~~~~~~~~~~~~~~~~~~~~

- :doc:`/platforms/platform-selection-guide` - Choosing Snowflake vs other platforms
- :doc:`/platforms/quick-reference` - Quick setup for all platforms
- :doc:`/platforms/comparison-matrix` - Feature comparison

Benchmark Guides
~~~~~~~~~~~~~~~~

- :doc:`/benchmarks/tpc-h` - TPC-H on Snowflake
- :doc:`/benchmarks/tpc-ds` - TPC-DS on Snowflake

API Reference
~~~~~~~~~~~~~

- :doc:`duckdb` - DuckDB adapter
- :doc:`clickhouse` - ClickHouse adapter
- :doc:`databricks` - Databricks adapter
- :doc:`bigquery` - BigQuery adapter
- :doc:`../base` - Base benchmark interface
- :doc:`../index` - Python API overview

External Resources
~~~~~~~~~~~~~~~~~~

- `Snowflake Documentation <https://docs.snowflake.com/en/>`_ - Official Snowflake docs
- `Warehouse Sizing <https://docs.snowflake.com/en/user-guide/warehouses-considerations>`_ - Sizing guidance
- `Clustering Keys <https://docs.snowflake.com/en/user-guide/tables-clustering-keys>`_ - Clustering best practices
- `Cost Optimization <https://docs.snowflake.com/en/user-guide/cost-understanding-overall>`_ - Cost management
- `Time Travel <https://docs.snowflake.com/en/user-guide/data-time-travel>`_ - Time Travel guide
