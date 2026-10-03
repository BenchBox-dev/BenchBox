Databricks Platform Adapter
============================

.. tags:: reference, python-api, databricks

The Databricks adapter provides cloud-native Spark SQL execution with Delta Lake optimization for analytical benchmarks.

Overview
--------

Databricks is a Data Intelligence Platform with lakehouse architecture, built on Apache Spark:

- **Lakehouse Architecture** - Combines data warehouse and data lake capabilities
- **Serverless SQL Warehouses** - On-demand compute without cluster management
- **Delta Lake** - ACID transactions and time travel support
- **Unity Catalog** - Unified governance for data and AI assets
- **Photon Engine** - Vectorized query engine for analytical workloads

Common use cases:

- Lakehouse deployments
- ML and data science workflows
- Large-scale benchmarking (multi-TB datasets)
- Multi-cloud deployments (AWS, Azure, GCP)
- Delta Lake performance evaluation

Quick Start
-----------

Basic Configuration
~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from benchbox.tpch import TPCH
    from benchbox.platforms.databricks import DatabricksAdapter

    adapter = DatabricksAdapter(
        server_hostname="dbc-12345678-abcd.cloud.databricks.com",
        http_path="/sql/1.0/warehouses/abcd1234efgh5678",
        access_token="dapi1234567890abcdef",
        catalog="main",
        schema="benchbox"
    )

    benchmark = TPCH(scale_factor=1.0)
    results = benchmark.run_with_platform(adapter)

Auto-Detection (Recommended)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from benchbox.platforms.databricks import DatabricksAdapter

    adapter = DatabricksAdapter.from_config({
        "benchmark": "tpch",
        "scale_factor": 1.0,
        "very_verbose": True
    })

API Reference
-------------

DatabricksAdapter Class
~~~~~~~~~~~~~~~~~~~~~~~

.. py:class:: benchbox.platforms.databricks.DatabricksAdapter(**config)

   Databricks SQL adapter.  It accepts connection configuration such as the
   server host, HTTP path, access token, catalog, and schema.  ``table_format``
   accepts ``"delta"`` or ``"hudi"``; Hudi table type accepts ``"cow"`` or
   ``"mor"``.  Invalid values raise ``ValueError``; missing driver dependencies
   raise ``ImportError``; incomplete required configuration raises
   ``ConfigurationError``.

   Example::

      adapter = DatabricksAdapter(server_hostname="host", http_path="/sql/path", access_token="token")

   The adapter advertises external-table support.  See :doc:`common` for the
   shared lifecycle.

.. py:method:: benchbox.platforms.databricks.DatabricksAdapter.create_connection(**connection_config) -> Any

   Create optimized Databricks SQL connection.

.. py:method:: benchbox.platforms.databricks.DatabricksAdapter.create_schema(benchmark, connection: Any) -> float

   Create schema using Databricks Delta Lake tables.

.. py:method:: benchbox.platforms.databricks.DatabricksAdapter.load_data(benchmark, connection: Any, data_dir: Path) -> tuple[dict[str, int], float, dict[str, Any] | None]

   Load data using Databricks COPY INTO from UC Volumes or cloud storage.

   This implementation avoids temporary views and uses COPY INTO for robust ingestion.

.. py:method:: benchbox.platforms.databricks.DatabricksAdapter.create_external_tables(benchmark: Any, connection: Any, data_dir: Path) -> tuple[dict[str, int], float, dict[str, Any] | None]

   Register Databricks external tables via USING PARQUET LOCATION.

.. py:method:: benchbox.platforms.databricks.DatabricksAdapter.execute_query(connection: Any, query: str, query_id: str, benchmark_type: str | None = None, scale_factor: float | None = None, validate_row_count: bool = True, stream_id: int | None = None) -> dict[str, Any]

   Execute query with detailed timing and profiling.

   Accepts either a DB-API connection or an already-open cursor: the TPC
   power harness passes a per-stream cursor through the facade, which has
   no ``cursor()`` method of its own.

.. py:method:: benchbox.platforms.databricks.DatabricksAdapter.reset_database_in_place(**connection_config) -> bool

   Truncate the schema's tables instead of dropping the schema.

   Unity Catalog keeps dropped tables recoverable for about seven days,
   and they count against the metastore table quota until then, so a
   drop-and-recreate on every reload exhausts small quotas. Schema
   creation replaces tables with ``CREATE OR REPLACE``, which does not add
   to the quota. Tables created with ``IF NOT EXISTS`` keep their
   structure and start empty. Returns False, and the caller drops the
   schema as before, when the schema is absent or any table cannot be
   truncated.

.. py:method:: benchbox.platforms.databricks.DatabricksAdapter.drop_database(**connection_config) -> None

   Drop schema in Databricks catalog.

.. py:method:: benchbox.platforms.databricks.DatabricksAdapter.analyze_table(connection: Any, table_name: str) -> None

   Run ANALYZE TABLE for better query optimization.

.. py:method:: benchbox.platforms.databricks.DatabricksAdapter.optimize_table(connection: Any, table_name: str) -> None

   Optimize Delta Lake table.

   Hudi tables skip Delta OPTIMIZE (recorded as a skipped layout
   operation): Hudi file management runs through its own
   cleaner/clustering table configurations.

.. py:method:: benchbox.platforms.databricks.DatabricksAdapter.vacuum_table(connection: Any, table_name: str, hours: int = 168) -> None

   Vacuum Delta Lake table to remove old files.

   Hudi tables skip Delta VACUUM (recorded as a skipped layout
   operation): retention runs through Hudi cleaner table
   configurations, and Delta RETAIN syntax is not valid for them.

Static member inventory
-----------------------

.. py:property:: benchbox.platforms.databricks.DatabricksAdapter.platform_name

   Returns this adapter's registered platform identifier for selection, metadata, and capability lookup.

.. py:staticmethod:: benchbox.platforms.databricks.DatabricksAdapter.add_cli_arguments(parser) -> None

   Add Databricks-specific CLI arguments.

.. py:classmethod:: benchbox.platforms.databricks.DatabricksAdapter.from_config(config: dict[str, Any])

   Create Databricks adapter from unified configuration.

.. py:method:: benchbox.platforms.databricks.DatabricksAdapter.get_platform_info(self, connection: Any=None) -> dict[str, Any]

   Get Databricks platform information.

   Captures comprehensive Databricks configuration including:
   Runtime/Spark version
   Warehouse/cluster size and configuration
   Compute tier and pricing information (best effort)
   Photon acceleration status
   Auto-scaling configuration

   Gracefully degrades if SDK is unavailable or permissions are insufficient.

.. py:method:: benchbox.platforms.databricks.DatabricksAdapter.get_normalized_result_metadata(self, *, connection: Any | None=None, platform_info: Mapping[str, Any] | None=None) -> dict[str, Any]

   Return Databricks-specific normalized workspace and warehouse metadata.

.. py:method:: benchbox.platforms.databricks.DatabricksAdapter.get_target_dialect(self) -> str

   Return the target SQL dialect for Databricks.

.. py:method:: benchbox.platforms.databricks.DatabricksAdapter.preprocess_operation_sql(self, query_id: str, operation: Any) -> str | None

   Rewrite operation write SQL for Databricks-only dialect gaps.

   Respects catalog ``databricks`` overrides (including skip ``None``):
   rewrites the override when present, otherwise the default write SQL.

   ``CAST(x AS VARCHAR)`` -> ``CAST(x AS STRING)`` (Databricks
   VARCHAR requires a length parameter; verified live with
   DATATYPE_MISSING_SIZE on batch inserts)
   ``unnest(generate_series(a, b))`` -> ``explode(sequence(a, b))``
   (Databricks has neither function; verified live with
   UNRESOLVED_ROUTINE ``unnest``)

.. py:method:: benchbox.platforms.databricks.DatabricksAdapter.check_server_database_exists(self, **connection_config) -> bool

   Check if schema exists in Databricks catalog.

.. py:method:: benchbox.platforms.databricks.DatabricksAdapter.validate_external_table_requirements(self) -> None

   Validate required staging configuration for external table mode.

.. py:method:: benchbox.platforms.databricks.DatabricksAdapter.configure_for_benchmark(self, connection: Any, benchmark_type: str) -> None

   Apply Databricks-specific configurations including cache control.

   Applies result cache control first, then any user-provided custom Spark configurations.

.. py:method:: benchbox.platforms.databricks.DatabricksAdapter.new_stream_connection(self, connection: Any, *, benchmark_type: str | None=None) -> Any

   Opens a stream-specific Databricks connection so concurrent benchmark streams do not share one cursor.

.. py:method:: benchbox.platforms.databricks.DatabricksAdapter.get_query_plan(self, connection: Any, query: str) -> str | None

   Get the Spark physical plan via ``EXPLAIN EXTENDED`` over the SQL cursor.

   Databricks runs Spark SQL, so the plan text is parsed by
   SparkQueryPlanParser. Returns ``None`` on any failure so capture degrades
   gracefully.

.. py:method:: benchbox.platforms.databricks.DatabricksAdapter.get_query_plan_parser(self)

   Return the Spark plan parser (Databricks runs Spark SQL).

.. py:method:: benchbox.platforms.databricks.DatabricksAdapter.close_connection(self, connection: Any) -> None

   Close Databricks connection.

.. py:method:: benchbox.platforms.databricks.DatabricksAdapter.generate_tuning_clause(self, table_tuning) -> str

   Generate Databricks-specific tuning clauses for CREATE TABLE statements.

   Databricks supports:
   USING DELTA (Delta Lake format) or USING HUDI (Apache Hudi)
   PARTITIONED BY (column1, column2, ...)
   CLUSTER BY (column1, column2, ...) for Delta Lake 2.0+
   Z-ORDER optimization

   CLUSTER BY / Z-ORDER are Delta-only: Hudi tables get USING HUDI,
   record-key TBLPROPERTIES, and PARTITIONED BY, with clustering omitted
   (Hudi manages file layout via its own cleaner/clustering configs).

   :param table_tuning: The tuning configuration for the table

   :returns: SQL clause string to be appended to CREATE TABLE statement

.. py:method:: benchbox.platforms.databricks.DatabricksAdapter.apply_table_tunings(self, table_tuning, connection: Any) -> None

   Apply tuning configurations to a Databricks Delta Lake table.

   Databricks tuning approach:
   PARTITIONING: Handled via PARTITIONED BY in CREATE TABLE
   CLUSTERING: Handled via CLUSTER BY in CREATE TABLE or ALTER TABLE
   DISTRIBUTION: Achieved through Z-ORDER clustering and OPTIMIZE
   Delta Lake optimization and maintenance

   :param table_tuning: The tuning configuration to apply
   :param connection: Databricks connection

   :raises ValueError: If the tuning configuration is invalid for Databricks

.. py:method:: benchbox.platforms.databricks.DatabricksAdapter.apply_unified_tuning(self, unified_config: UnifiedTuningConfiguration, connection: Any) -> None

   Apply unified tuning configuration to Databricks.

.. py:method:: benchbox.platforms.databricks.DatabricksAdapter.apply_platform_optimizations(self, platform_config: PlatformOptimizationConfiguration, connection: Any) -> None

   Apply Databricks-specific platform optimizations.

   Databricks optimizations include:
   Spark configuration tuning (adaptive query execution, join strategies)
   Delta Lake optimization settings (auto-optimize, auto-compact)
   Cluster autoscaling and resource allocation
   Unity Catalog performance settings

   :param platform_config: Platform optimization configuration
   :param connection: Databricks connection

.. py:attribute:: benchbox.platforms.databricks.DatabricksAdapter.plan_capture_phase_eligible

   Advertises whether benchmark plan capture is available for this adapter.

.. py:attribute:: benchbox.platforms.databricks.DatabricksAdapter.driver_isolation_capability

   Declares whether this adapter can run through an isolated driver runtime; the value controls runtime-resolution support.

.. py:attribute:: benchbox.platforms.databricks.DatabricksAdapter.supports_external_tables

   Advertises whether the adapter implements external-table creation.

.. py:method:: benchbox.platforms.databricks.DatabricksAdapter.apply_constraint_configuration(primary_key_config: PrimaryKeyConfiguration, foreign_key_config: ForeignKeyConfiguration, connection: Any) -> None

   Logs informational messages for enabled primary-key and foreign-key settings.
   This hook executes no SQL and does not use ``connection``. Table-creation
   hooks handle any platform-supported constraint DDL.

Constructor Configuration
~~~~~~~~~~~~~~~~~~~~~~~~~

Pass keyword configuration through ``DatabricksAdapter(**config)``.

- ``server_hostname`` (alias ``host``), ``http_path`` and ``access_token``
  (alias ``token``) identify the endpoint and credentials.
- ``catalog`` defaults to ``"main"`` and ``schema`` to ``"benchbox"``.
- ``uc_catalog``, ``uc_schema``, ``uc_volume`` and ``staging_root`` are optional
  Unity Catalog/staging settings.
- ``enable_delta_optimization``, ``delta_auto_optimize`` and
  ``delta_auto_compact`` each default to ``True``.
- ``cluster_size`` is optional requested metadata; it has no inferred size
  default and does not establish observed warehouse capacity.
- ``auto_terminate_minutes`` defaults to 30; ``create_catalog`` defaults to
  ``False``.

Configuration Examples
----------------------

Environment Variables
~~~~~~~~~~~~~~~~~~~~~

.. code-block:: bash

    export DATABRICKS_HOST="https://dbc-12345678-abcd.cloud.databricks.com"
    export DATABRICKS_TOKEN="dapi1234567890abcdef"
    export DATABRICKS_WAREHOUSE_ID="abcd1234efgh5678"

.. code-block:: python

    import os
    from benchbox.platforms.databricks import DatabricksAdapter

    adapter = DatabricksAdapter(
        server_hostname=os.environ["DATABRICKS_HOST"].replace("https://", ""),
        http_path=f"/sql/1.0/warehouses/{os.environ['DATABRICKS_WAREHOUSE_ID']}",
        access_token=os.environ["DATABRICKS_TOKEN"]
    )

Unity Catalog Configuration
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    adapter = DatabricksAdapter(
        server_hostname="workspace.cloud.databricks.com",
        http_path="/sql/1.0/warehouses/abc123",
        access_token="dapi...",
        catalog="production",
        schema="tpch_sf100",
        uc_catalog="staging",
        uc_schema="benchmark_data",
        uc_volume="tpch_staging"
    )


S3 Staging Configuration
~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    adapter = DatabricksAdapter(
        server_hostname="workspace.cloud.databricks.com",
        http_path="/sql/1.0/warehouses/abc123",
        access_token="dapi...",
        staging_root="s3://my-bucket/benchbox-staging"
    )

Delta Lake Optimization
~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    adapter = DatabricksAdapter(
        server_hostname="workspace.cloud.databricks.com",
        http_path="/sql/1.0/warehouses/large-warehouse",
        access_token="dapi...",
        enable_delta_optimization=True,
        delta_auto_optimize=True,
        delta_auto_compact=True
    )

Authentication
--------------

Personal Access Token
~~~~~~~~~~~~~~~~~~~~~

.. code-block:: bash

    export DATABRICKS_TOKEN="dapi1234567890abcdef"

Databricks CLI Configuration
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: bash

    databricks configure --token

    adapter = DatabricksAdapter.from_config({
        "benchmark": "tpch",
        "scale_factor": 1.0
    })

Service Principal (Production)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from databricks.sdk import WorkspaceClient
    from databricks.sdk.oauth import ClientCredentials

    client = WorkspaceClient(
        host="https://workspace.cloud.databricks.com",
        auth_type="oauth",
        client_id="your-client-id",
        client_secret="your-client-secret"
    )

    adapter = DatabricksAdapter(
        server_hostname=client.config.host.replace("https://", ""),
        http_path="/sql/1.0/warehouses/abc123",
        access_token=client.config.token
    )

Data Loading
------------

UC Volumes (Recommended)
~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from benchbox.platforms.databricks import DatabricksAdapter
    from benchbox.tpch import TPCH
    from pathlib import Path

    adapter = DatabricksAdapter(
        server_hostname="workspace.cloud.databricks.com",
        http_path="/sql/1.0/warehouses/abc123",
        access_token="dapi...",
        uc_catalog="staging",
        uc_schema="benchmark_data",
        uc_volume="tpch_volume"
    )

    benchmark = TPCH(scale_factor=1.0)
    data_dir = Path("./tpch_data")
    benchmark.generate_data(data_dir)


    conn = adapter.create_connection()
    table_stats, load_time = adapter.load_data(benchmark, conn, data_dir)

S3 Data Loading
~~~~~~~~~~~~~~~

.. code-block:: python

    adapter = DatabricksAdapter(
        server_hostname="workspace.cloud.databricks.com",
        http_path="/sql/1.0/warehouses/abc123",
        access_token="dapi...",
        staging_root="s3://my-bucket/benchbox-data"
    )


Delta Lake Tables
-----------------

Automatic Delta Conversion
~~~~~~~~~~~~~~~~~~~~~~~~~~~

All benchmark tables are automatically created as Delta Lake tables:

.. code-block:: python

    adapter = DatabricksAdapter(...)
    conn = adapter.create_connection()

    schema_time = adapter.create_schema(benchmark, conn)


Manual Delta Optimization
~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    adapter.optimize_table(conn, "lineitem")

    adapter.vacuum_table(conn, "lineitem", hours=168)

    cursor = conn.cursor()
    cursor.execute("""
        OPTIMIZE lineitem
        ZORDER BY (l_shipdate, l_orderkey)
    """)

Delta Lake Time Travel
~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    cursor = conn.cursor()

    cursor.execute("""
        SELECT * FROM lineitem VERSION AS OF 5
        WHERE l_shipdate = '1995-01-01'
    """)

    cursor.execute("""
        SELECT * FROM lineitem TIMESTAMP AS OF '2025-01-01 00:00:00'
        WHERE l_shipdate = '1995-01-01'
    """)

    cursor.execute("DESCRIBE HISTORY lineitem")
    history = cursor.fetchall()

Query Execution
---------------

Basic Query Execution
~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    adapter = DatabricksAdapter(...)
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

Query Plans and Optimization
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    cursor.execute("""
        EXPLAIN FORMATTED
        SELECT * FROM lineitem
        WHERE l_shipdate > '1995-01-01'
    """)
    plan = cursor.fetchall()

    cursor.execute("""
        EXPLAIN COST
        SELECT count(*) FROM lineitem
        GROUP BY l_orderkey
    """)

Advanced Features
-----------------

Spark Configuration
~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    cursor = conn.cursor()

    cursor.execute("SET spark.sql.adaptive.enabled = true")
    cursor.execute("SET spark.sql.adaptive.coalescePartitions.enabled = true")

    cursor.execute("SET spark.sql.adaptive.skewJoin.enabled = true")
    cursor.execute("SET spark.sql.join.preferSortMergeJoin = true")

Partitioning Strategy
~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    cursor.execute("""
        CREATE OR REPLACE TABLE orders
        USING DELTA
        PARTITIONED BY (order_year, order_month)
        AS SELECT
            *,
            YEAR(o_orderdate) as order_year,
            MONTH(o_orderdate) as order_month
        FROM orders_raw
    """)

Clustering and Z-ORDER
~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    cursor.execute("""
        OPTIMIZE lineitem
        ZORDER BY (l_orderkey, l_partkey, l_shipdate)
    """)

    cursor.execute("DESCRIBE HISTORY lineitem")
    history = cursor.fetchall()

Photon Engine
~~~~~~~~~~~~~

.. code-block:: python

    cursor.execute("SET spark.databricks.photon.enabled")
    result = cursor.fetchone()
    print(f"Photon enabled: {result}")

Best Practices
--------------

Warehouse Selection
~~~~~~~~~~~~~~~~~~~

1. **Choose appropriate warehouse size** for workload:

   .. code-block:: python



2. **Use Serverless SQL Warehouses** for variable workloads:

   Faster start times
   Better resource utilization
   Automatic scaling

Data Staging
~~~~~~~~~~~~

1. **Use Unity Catalog Volumes** for managed storage:

   .. code-block:: python

       adapter = DatabricksAdapter(
           uc_catalog="staging",
           uc_schema="benchmarks",
           uc_volume="tpch_data"
       )

2. **Prefer cloud storage** (S3, ADLS, GCS) for large datasets:

   .. code-block:: python

       adapter = DatabricksAdapter(
           staging_root="s3://benchmark-data/tpch"
       )

Delta Lake Optimization
~~~~~~~~~~~~~~~~~~~~~~~

1. **Enable auto-optimize** for write performance:

   .. code-block:: python

       adapter = DatabricksAdapter(
           delta_auto_optimize=True,
           delta_auto_compact=True
       )

2. **Run OPTIMIZE regularly** on active tables:

   .. code-block:: python

       adapter.optimize_table(conn, "lineitem")

       cursor.execute("OPTIMIZE lineitem ZORDER BY (l_shipdate, l_orderkey)")

3. **Vacuum old files** to reduce storage costs:

   .. code-block:: python

       adapter.vacuum_table(conn, "lineitem", hours=168)

Cost Optimization
~~~~~~~~~~~~~~~~~

1. **Auto-terminate idle warehouses**:

   .. code-block:: python

       adapter = DatabricksAdapter(
           auto_terminate_minutes=10
       )

2. **Use smallest warehouse** that meets SLA:

   .. code-block:: python

       adapter = DatabricksAdapter(
           cluster_size="Small"
       )

3. **Cache frequently accessed data**:

   .. code-block:: python

       cursor.execute("CACHE SELECT * FROM lineitem WHERE l_shipdate > '1995-01-01'")

Common Issues
-------------

Warehouse Not Available
~~~~~~~~~~~~~~~~~~~~~~~

**Problem**: "Warehouse is not available" error

**Solutions**:

.. code-block:: python

    from databricks.sdk import WorkspaceClient

    w = WorkspaceClient()
    warehouses = list(w.warehouses.list())
    for wh in warehouses:
        print(f"{wh.name}: {wh.state}")


    import time
    adapter = DatabricksAdapter(...)
    for attempt in range(5):
        try:
            conn = adapter.create_connection()
            break
        except Exception as e:
            if "not running" in str(e).lower():
                print(f"Waiting for warehouse to start... (attempt {attempt+1}/5)")
                time.sleep(30)
            else:
                raise

Authentication Failed
~~~~~~~~~~~~~~~~~~~~~

**Problem**: "Invalid access token" error

**Solutions**:

.. code-block:: bash

    databricks workspace list

    echo $DATABRICKS_TOKEN

.. code-block:: python

    import os
    token = os.getenv("DATABRICKS_TOKEN")
    if not token:
        raise ValueError("DATABRICKS_TOKEN not set")

Unity Catalog Errors
~~~~~~~~~~~~~~~~~~~~

**Problem**: "Catalog not found" or "Schema not found"

**Solutions**:

.. code-block:: python

    cursor = conn.cursor()
    cursor.execute("SHOW CATALOGS")
    catalogs = cursor.fetchall()
    print("Available catalogs:", catalogs)

    adapter = DatabricksAdapter(
        catalog="workspace",
        schema="default"
    )

    adapter = DatabricksAdapter(
        catalog="benchmarks",
        schema="tpch",
        create_catalog=True
    )

Slow Query Performance
~~~~~~~~~~~~~~~~~~~~~~

**Problem**: Queries are slower than expected

**Solutions**:

.. code-block:: python

    adapter.optimize_table(conn, "lineitem")

    cursor.execute("""
        OPTIMIZE lineitem
        ZORDER BY (l_orderkey, l_shipdate)
    """)

    cursor.execute("ANALYZE TABLE lineitem COMPUTE STATISTICS")

    cursor.execute("EXPLAIN EXTENDED SELECT ...")
    plan = cursor.fetchall()

Out of Memory Errors
~~~~~~~~~~~~~~~~~~~~

**Problem**: "Out of memory" during query execution

**Solutions**:

.. code-block:: python

    cursor.execute("""
        OPTIMIZE lineitem
        ZORDER BY (l_orderkey)
    """)

    cursor.execute("""
        CREATE OR REPLACE TABLE lineitem_partitioned
        USING DELTA
        PARTITIONED BY (l_shipdate_year, l_shipdate_month)
        AS SELECT *, YEAR(l_shipdate) as l_shipdate_year, MONTH(l_shipdate) as l_shipdate_month
        FROM lineitem
    """)

See Also
--------

Platform Documentation
~~~~~~~~~~~~~~~~~~~~~~

- :doc:`/platforms/platform-selection-guide` - Choosing Databricks vs other platforms
- :doc:`/platforms/quick-reference` - Quick setup for all platforms
- :doc:`/platforms/comparison-matrix` - Feature comparison
- :doc:`/guides/cloud-storage` - S3, ADLS, GCS integration

Benchmark Guides
~~~~~~~~~~~~~~~~

- :doc:`/benchmarks/tpc-h` - TPC-H on Databricks
- :doc:`/benchmarks/tpc-ds` - TPC-DS on Databricks
- :doc:`/benchmarks/tpc-di` - TPC-DI on Databricks

API Reference
~~~~~~~~~~~~~

- :doc:`duckdb` - DuckDB adapter
- :doc:`clickhouse` - ClickHouse adapter
- :doc:`bigquery` - BigQuery adapter for comparison
- :doc:`../base` - Base benchmark interface
- :doc:`../index` - Python API overview

External Resources
~~~~~~~~~~~~~~~~~~

- `Databricks Documentation <https://docs.databricks.com/aws/en>`_ - Official Databricks docs
- `Delta Lake Guide <https://docs.databricks.com/aws/en/delta>`_ - Delta Lake reference
- `Unity Catalog <https://docs.databricks.com/aws/en/data-governance/unity-catalog>`_ - Unity Catalog docs
- `SQL Warehouses <https://docs.databricks.com/aws/en/compute/sql-warehouse/create>`_ - Warehouse configuration
- `Photon Engine <https://docs.databricks.com/aws/en/compute/photon>`_ - Photon performance
