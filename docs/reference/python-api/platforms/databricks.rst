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

    # Connect to Databricks SQL Warehouse
    adapter = DatabricksAdapter(
        server_hostname="dbc-12345678-abcd.cloud.databricks.com",
        http_path="/sql/1.0/warehouses/abcd1234efgh5678",
        access_token="dapi1234567890abcdef",
        catalog="main",
        schema="benchbox"
    )

    # Run benchmark
    benchmark = TPCH(scale_factor=1.0)
    results = benchmark.run_with_platform(adapter)

Auto-Detection (Recommended)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    # Auto-detect from Databricks SDK configuration
    # Uses ~/.databrickscfg or environment variables
    from benchbox.platforms.databricks import DatabricksAdapter

    adapter = DatabricksAdapter.from_config({
        "benchmark": "tpch",
        "scale_factor": 1.0,
        "very_verbose": True  # Shows auto-detection details
    })

API Reference
-------------

DatabricksAdapter Class
~~~~~~~~~~~~~~~~~~~~~~~

.. autoclass:: benchbox.platforms.databricks.DatabricksAdapter
   :members:
   :undoc-members:
   :show-inheritance:

Constructor Parameters
~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    DatabricksAdapter(
        server_hostname: str,
        http_path: str,
        access_token: str,
        catalog: str = "main",
        schema: str = "benchbox",
        uc_catalog: Optional[str] = None,
        uc_schema: Optional[str] = None,
        uc_volume: Optional[str] = None,
        staging_root: Optional[str] = None,
        enable_delta_optimization: bool = True,
        delta_auto_optimize: bool = True,
        delta_auto_compact: bool = True,
        cluster_size: str = "Medium",
        auto_terminate_minutes: int = 30,
        create_catalog: bool = False
    )

Parameters:

**Connection (Required)**:

- **server_hostname** (str): Databricks workspace hostname (without ``https://``)
- **http_path** (str): SQL Warehouse HTTP path (e.g., /sql/1.0/warehouses/{warehouse_id})
- **access_token** (str): Personal access token for authentication

**Unity Catalog**:

- **catalog** (str): Catalog name for benchmark tables. Default: "main"
- **schema** (str): Schema name for benchmark tables. Default: "benchbox"
- **uc_catalog** (str, optional): Unity Catalog for staging volumes
- **uc_schema** (str, optional): Schema within UC catalog for volumes
- **uc_volume** (str, optional): Volume name for data staging

**Data Staging**:

- **staging_root** (str, optional): Explicit staging location (dbfs:/Volumes/... or s3://...)

**Delta Lake Optimization**:

- **enable_delta_optimization** (bool): Enable Delta Lake optimizations. Default: True
- **delta_auto_optimize** (bool): Enable auto-optimize on writes. Default: True
- **delta_auto_compact** (bool): Enable auto-compaction. Default: True

**Cluster Settings**:

- **cluster_size** (str): SQL Warehouse size hint. Default: "Medium"
- **auto_terminate_minutes** (int): Auto-termination timeout. Default: 30

**Schema Management**:

- **create_catalog** (bool): Create catalog if it doesn't exist. Default: False

Configuration Examples
----------------------

Environment Variables
~~~~~~~~~~~~~~~~~~~~~

.. code-block:: bash

    # Set Databricks credentials
    export DATABRICKS_HOST="https://dbc-12345678-abcd.cloud.databricks.com"
    export DATABRICKS_TOKEN="dapi1234567890abcdef"
    export DATABRICKS_WAREHOUSE_ID="abcd1234efgh5678"

.. code-block:: python

    import os
    from benchbox.platforms.databricks import DatabricksAdapter

    # Use environment variables
    adapter = DatabricksAdapter(
        server_hostname=os.environ["DATABRICKS_HOST"].replace("https://", ""),
        http_path=f"/sql/1.0/warehouses/{os.environ['DATABRICKS_WAREHOUSE_ID']}",
        access_token=os.environ["DATABRICKS_TOKEN"]
    )

Unity Catalog Configuration
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    # With Unity Catalog volumes for staging
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

    # Data will be staged to: dbfs:/Volumes/staging/benchmark_data/tpch_staging/

S3 Staging Configuration
~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    # Use S3 for data staging
    adapter = DatabricksAdapter(
        server_hostname="workspace.cloud.databricks.com",
        http_path="/sql/1.0/warehouses/abc123",
        access_token="dapi...",
        staging_root="s3://my-bucket/benchbox-staging"
    )

Delta Lake Optimization
~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    # High-performance Delta Lake configuration
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

    # Generate token in Databricks UI:
    # User Settings → Developer → Access Tokens → Generate New Token

    # Use in environment
    export DATABRICKS_TOKEN="dapi1234567890abcdef"

Databricks CLI Configuration
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: bash

    # Configure Databricks CLI
    databricks configure --token
    # Enter workspace URL and token

    # Then use auto-detection
    adapter = DatabricksAdapter.from_config({
        "benchmark": "tpch",
        "scale_factor": 1.0
    })

Service Principal (Production)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    # For production deployments
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

    # Configure adapter with UC Volume
    adapter = DatabricksAdapter(
        server_hostname="workspace.cloud.databricks.com",
        http_path="/sql/1.0/warehouses/abc123",
        access_token="dapi...",
        uc_catalog="staging",
        uc_schema="benchmark_data",
        uc_volume="tpch_volume"
    )

    # Generate data locally
    benchmark = TPCH(scale_factor=1.0)
    data_dir = Path("./tpch_data")
    benchmark.generate_data(data_dir)

    # Upload to UC Volume (manual step)
    # databricks fs cp -r ./tpch_data/ dbfs:/Volumes/staging/benchmark_data/tpch_volume/

    # Load data using COPY INTO
    conn = adapter.create_connection()
    table_stats, load_time = adapter.load_data(benchmark, conn, data_dir)

S3 Data Loading
~~~~~~~~~~~~~~~

.. code-block:: python

    # Load directly from S3
    adapter = DatabricksAdapter(
        server_hostname="workspace.cloud.databricks.com",
        http_path="/sql/1.0/warehouses/abc123",
        access_token="dapi...",
        staging_root="s3://my-bucket/benchbox-data"
    )

    # Data is loaded via COPY INTO from S3
    # Ensure IAM role or instance profile has S3 read permissions

Delta Lake Tables
-----------------

Automatic Delta Conversion
~~~~~~~~~~~~~~~~~~~~~~~~~~~

All benchmark tables are automatically created as Delta Lake tables:

.. code-block:: python

    adapter = DatabricksAdapter(...)
    conn = adapter.create_connection()

    # Creates Delta Lake tables automatically
    schema_time = adapter.create_schema(benchmark, conn)

    # Tables created with:
    # - USING DELTA format
    # - Auto-optimize enabled
    # - Auto-compact enabled

Manual Delta Optimization
~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    # Optimize specific table
    adapter.optimize_table(conn, "lineitem")

    # Vacuum old files (removes files older than retention period)
    adapter.vacuum_table(conn, "lineitem", hours=168)  # 7 days

    # Z-ORDER clustering for query performance
    cursor = conn.cursor()
    cursor.execute("""
        OPTIMIZE lineitem
        ZORDER BY (l_shipdate, l_orderkey)
    """)

Delta Lake Time Travel
~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    # Query historical data
    cursor = conn.cursor()

    # Query by version
    cursor.execute("""
        SELECT * FROM lineitem VERSION AS OF 5
        WHERE l_shipdate = '1995-01-01'
    """)

    # Query by timestamp
    cursor.execute("""
        SELECT * FROM lineitem TIMESTAMP AS OF '2025-01-01 00:00:00'
        WHERE l_shipdate = '1995-01-01'
    """)

    # View table history
    cursor.execute("DESCRIBE HISTORY lineitem")
    history = cursor.fetchall()

Query Execution
---------------

Basic Query Execution
~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    adapter = DatabricksAdapter(...)
    conn = adapter.create_connection()

    # Execute SQL query
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

    # View query plan
    cursor.execute("""
        EXPLAIN FORMATTED
        SELECT * FROM lineitem
        WHERE l_shipdate > '1995-01-01'
    """)
    plan = cursor.fetchall()

    # View query costs
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

    # Configure Spark settings for performance
    cursor = conn.cursor()

    # Adaptive Query Execution
    cursor.execute("SET spark.sql.adaptive.enabled = true")
    cursor.execute("SET spark.sql.adaptive.coalescePartitions.enabled = true")

    # Join optimization
    cursor.execute("SET spark.sql.adaptive.skewJoin.enabled = true")
    cursor.execute("SET spark.sql.join.preferSortMergeJoin = true")

Partitioning Strategy
~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    # Create partitioned Delta table
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

    # Z-ORDER clustering for co-location
    cursor.execute("""
        OPTIMIZE lineitem
        ZORDER BY (l_orderkey, l_partkey, l_shipdate)
    """)

    # Check optimization metrics
    cursor.execute("DESCRIBE HISTORY lineitem")
    history = cursor.fetchall()

Photon Engine
~~~~~~~~~~~~~

.. code-block:: python

    # Photon is enabled automatically on compatible warehouses
    # Check if Photon is active
    cursor.execute("SET spark.databricks.photon.enabled")
    result = cursor.fetchone()
    print(f"Photon enabled: {result}")

Best Practices
--------------

Warehouse Selection
~~~~~~~~~~~~~~~~~~~

1. **Choose appropriate warehouse size** for workload:

   .. code-block:: python

       # Small: 1-10GB data, development
       # Medium: 10-100GB data, testing
       # Large: 100GB-1TB data, production
       # X-Large/2X-Large: 1TB+ data, heavy workloads

2. **Use Serverless SQL Warehouses** for variable workloads:

   - Faster start times
   - Better resource utilization
   - Automatic scaling

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

       # After bulk loads
       adapter.optimize_table(conn, "lineitem")

       # With Z-ORDER for query patterns
       cursor.execute("OPTIMIZE lineitem ZORDER BY (l_shipdate, l_orderkey)")

3. **Vacuum old files** to reduce storage costs:

   .. code-block:: python

       # Keep 7 days of history
       adapter.vacuum_table(conn, "lineitem", hours=168)

Cost Optimization
~~~~~~~~~~~~~~~~~

1. **Auto-terminate idle warehouses**:

   .. code-block:: python

       adapter = DatabricksAdapter(
           auto_terminate_minutes=10  # Terminate after 10 min idle
       )

2. **Use smallest warehouse** that meets SLA:

   .. code-block:: python

       # Start small, scale up if needed
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

    # 1. Check warehouse status
    from databricks.sdk import WorkspaceClient

    w = WorkspaceClient()
    warehouses = list(w.warehouses.list())
    for wh in warehouses:
        print(f"{wh.name}: {wh.state}")

    # 2. Start warehouse manually
    # Or use serverless warehouses (auto-start)

    # 3. Wait for auto-start (may take 1-2 minutes)
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

    # 1. Verify token hasn't expired
    databricks workspace list  # Test token

    # 2. Generate new token
    # Databricks UI → User Settings → Access Tokens

    # 3. Check environment variables
    echo $DATABRICKS_TOKEN

.. code-block:: python

    # 4. Verify token in code
    import os
    token = os.getenv("DATABRICKS_TOKEN")
    if not token:
        raise ValueError("DATABRICKS_TOKEN not set")

Unity Catalog Errors
~~~~~~~~~~~~~~~~~~~~

**Problem**: "Catalog not found" or "Schema not found"

**Solutions**:

.. code-block:: python

    # 1. Check catalog permissions
    cursor = conn.cursor()
    cursor.execute("SHOW CATALOGS")
    catalogs = cursor.fetchall()
    print("Available catalogs:", catalogs)

    # 2. Use workspace catalog (always available)
    adapter = DatabricksAdapter(
        catalog="workspace",  # Or "hive_metastore"
        schema="default"
    )

    # 3. Create catalog if authorized
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

    # 1. Enable Photon (if not already enabled)
    # Use Photon-enabled warehouse

    # 2. Optimize Delta tables
    adapter.optimize_table(conn, "lineitem")

    # 3. Add Z-ORDER clustering
    cursor.execute("""
        OPTIMIZE lineitem
        ZORDER BY (l_orderkey, l_shipdate)
    """)

    # 4. Update table statistics
    cursor.execute("ANALYZE TABLE lineitem COMPUTE STATISTICS")

    # 5. Check query plan
    cursor.execute("EXPLAIN EXTENDED SELECT ...")
    plan = cursor.fetchall()
    # Look for FullScan - may need better clustering

Out of Memory Errors
~~~~~~~~~~~~~~~~~~~~

**Problem**: "Out of memory" during query execution

**Solutions**:

.. code-block:: python

    # 1. Use larger warehouse
    # Switch from Medium to Large or X-Large

    # 2. Optimize data layout
    cursor.execute("""
        OPTIMIZE lineitem
        ZORDER BY (l_orderkey)
    """)

    # 3. Reduce data scan with partitioning
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
- :doc:`/cloud-storage` - S3, ADLS, GCS integration

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
