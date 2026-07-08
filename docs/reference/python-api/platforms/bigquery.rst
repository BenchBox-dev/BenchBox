BigQuery Platform Adapter
==========================

.. tags:: reference, python-api, bigquery

The BigQuery adapter provides Google Cloud's serverless data warehouse execution for analytical benchmarks with built-in cost optimization.

Overview
--------

Google BigQuery is a fully managed, serverless data warehouse that provides:

- **Serverless architecture** - No infrastructure management required
- **Petabyte-scale support** - Supports large datasets
- **Pay-per-query pricing** - Usage-based cost model
- **Built-in ML** - SQL-based machine learning capabilities
- **Query optimization** - Automatic query optimization and caching

Common use cases:

- Cloud-native analytics workloads on Google Cloud
- Large-scale benchmarking (multi-TB to PB scale)
- Testing with pay-per-query pricing and budget controls
- Multi-region deployments
- Integration with Google Cloud ecosystem

Quick Start
-----------

Basic Configuration
~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from benchbox.tpch import TPCH
    from benchbox.platforms.bigquery import BigQueryAdapter

    # Connect to BigQuery
    adapter = BigQueryAdapter(
        project_id="my-project-id",
        dataset_id="benchbox_tpch",
        location="US",
        credentials_path="/path/to/service-account.json"
    )

    # Run benchmark
    benchmark = TPCH(scale_factor=1.0)
    results = benchmark.run_with_platform(adapter)

Auto-Detection
~~~~~~~~~~~~~~

.. code-block:: python

    # Auto-detect from Application Default Credentials
    from benchbox.platforms.bigquery import BigQueryAdapter

    adapter = BigQueryAdapter.from_config({
        "benchmark": "tpch",
        "scale_factor": 1.0,
        # project_id auto-detected from gcloud config
    })

API Reference
-------------

BigQueryAdapter Class
~~~~~~~~~~~~~~~~~~~~~

.. autoclass:: benchbox.platforms.bigquery.BigQueryAdapter
   :members:
   :undoc-members:
   :show-inheritance:

Constructor Parameters
~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    BigQueryAdapter(
        project_id: str,
        dataset_id: str = "benchbox",
        location: str = "US",
        credentials_path: Optional[str] = None,
        storage_bucket: Optional[str] = None,
        storage_prefix: str = "benchbox-data",
        job_priority: str = "INTERACTIVE",
        query_cache: bool = True,
        dry_run: bool = False,
        maximum_bytes_billed: Optional[int] = None,
        clustering_fields: List[str] = [],
        partitioning_field: Optional[str] = None
    )

Parameters:

**Connection (Required)**:

- **project_id** (str): Google Cloud project ID
- **dataset_id** (str): BigQuery dataset name. Default: "benchbox"
- **location** (str): Dataset location (US, EU, asia-northeast1, etc.). Default: "US"
- **credentials_path** (str, optional): Path to service account JSON key file

**Cloud Storage**:

- **storage_bucket** (str, optional): GCS bucket for efficient data loading
- **storage_prefix** (str): Prefix for uploaded data files. Default: "benchbox-data"

**Query Configuration**:

- **job_priority** (str): Query priority - "INTERACTIVE" or "BATCH". Default: "INTERACTIVE"
- **query_cache** (bool): Enable query result caching. Default: True
- **dry_run** (bool): Validate queries without execution. Default: False
- **maximum_bytes_billed** (int, optional): Maximum bytes billed per query (cost control)

**Table Optimization**:

- **clustering_fields** (List[str]): Default clustering columns for tables. Default: []
- **partitioning_field** (str, optional): Default partitioning column

Configuration Examples
----------------------

Application Default Credentials
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: bash

    # Set up default credentials
    gcloud auth application-default login

.. code-block:: python

    # No credentials_path needed
    adapter = BigQueryAdapter(
        project_id="my-project",
        dataset_id="benchbox_tpch"
    )

Service Account Authentication
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: bash

    # Create service account and download key
    gcloud iam service-accounts create benchbox-runner
    gcloud projects add-iam-policy-binding my-project \
        --member="serviceAccount:benchbox-runner@my-project.iam.gserviceaccount.com" \
        --role="roles/bigquery.admin"
    gcloud iam service-accounts keys create key.json \
        --iam-account=benchbox-runner@my-project.iam.gserviceaccount.com

.. code-block:: python

    adapter = BigQueryAdapter(
        project_id="my-project",
        dataset_id="benchbox_tpch",
        credentials_path="./key.json"
    )

GCS Integration for Data Loading
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    # Efficient loading via Cloud Storage
    adapter = BigQueryAdapter(
        project_id="my-project",
        dataset_id="benchbox_tpch",
        storage_bucket="my-benchmark-data",
        storage_prefix="tpch/sf1"
    )

    # Data is automatically uploaded to GCS then loaded to BigQuery
    # Recommended for large datasets

Cost Control Configuration
~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    # Set budget limits and use BATCH priority
    adapter = BigQueryAdapter(
        project_id="my-project",
        dataset_id="benchbox_tpch",
        job_priority="BATCH",  # Lower cost, slower
        query_cache=True,  # Reuse cached results
        maximum_bytes_billed=10 * 1024**3  # 10 GB limit per query
    )

Table Optimization
~~~~~~~~~~~~~~~~~~

.. code-block:: python

    # Configure partitioning and clustering
    adapter = BigQueryAdapter(
        project_id="my-project",
        dataset_id="benchbox_tpch",
        partitioning_field="l_shipdate",  # Partition on date column
        clustering_fields=["l_orderkey", "l_partkey"]  # Cluster by these columns
    )

Authentication
--------------

Application Default Credentials (Development)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: bash

    # Log in with your Google account
    gcloud auth application-default login

    # Set default project
    gcloud config set project my-project-id

.. code-block:: python

    # Auto-detected from gcloud config
    adapter = BigQueryAdapter(
        project_id="my-project",  # Or auto-detected
        dataset_id="benchbox"
    )

Service Account (Production)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: bash

    # Create service account with required roles
    gcloud iam service-accounts create benchbox-sa

    # Grant BigQuery permissions
    gcloud projects add-iam-policy-binding my-project \
        --member="serviceAccount:benchbox-sa@my-project.iam.gserviceaccount.com" \
        --role="roles/bigquery.admin"

    # Grant GCS permissions (if using cloud storage)
    gcloud projects add-iam-policy-binding my-project \
        --member="serviceAccount:benchbox-sa@my-project.iam.gserviceaccount.com" \
        --role="roles/storage.objectAdmin"

    # Download key
    gcloud iam service-accounts keys create sa-key.json \
        --iam-account=benchbox-sa@my-project.iam.gserviceaccount.com

.. code-block:: python

    # Use service account key
    adapter = BigQueryAdapter(
        project_id="my-project",
        credentials_path="/secure/path/sa-key.json"
    )

Environment Variables
~~~~~~~~~~~~~~~~~~~~~

.. code-block:: bash

    # Set credentials via environment variable
    export GOOGLE_APPLICATION_CREDENTIALS="/path/to/key.json"
    export GOOGLE_CLOUD_PROJECT="my-project-id"

.. code-block:: python

    # Credentials automatically loaded from environment
    import os
    adapter = BigQueryAdapter(
        project_id=os.environ["GOOGLE_CLOUD_PROJECT"],
        dataset_id="benchbox"
    )

Data Loading
------------

Via Cloud Storage (Recommended)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from benchbox.platforms.bigquery import BigQueryAdapter
    from benchbox.tpch import TPCH
    from pathlib import Path

    # Configure with GCS bucket
    adapter = BigQueryAdapter(
        project_id="my-project",
        dataset_id="benchbox_tpch_sf10",
        storage_bucket="benchmark-data-bucket",
        storage_prefix="tpch/sf10"
    )

    # Generate data
    benchmark = TPCH(scale_factor=10.0)
    data_dir = Path("./tpch_data")
    benchmark.generate_data(data_dir)

    # Load data (automatically uploads to GCS first)
    conn = adapter.create_connection()
    table_stats, load_time = adapter.load_data(benchmark, conn, data_dir)

Direct Loading (Small Datasets)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    # For small datasets (< 1GB), skip GCS
    adapter = BigQueryAdapter(
        project_id="my-project",
        dataset_id="benchbox_tpch_sf001"
        # No storage_bucket specified
    )

    # Direct loading from local files
    conn = adapter.create_connection()
    table_stats, load_time = adapter.load_data(benchmark, conn, data_dir)

Query Execution
---------------

Basic Query Execution
~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    adapter = BigQueryAdapter(project_id="my-project", dataset_id="benchbox")
    conn = adapter.create_connection()

    # Execute SQL query
    query = """
        SELECT
            l_returnflag,
            l_linestatus,
            sum(l_quantity) as sum_qty,
            count(*) as count_order
        FROM `my-project.benchbox.LINEITEM`
        WHERE l_shipdate <= '1998-09-01'
        GROUP BY l_returnflag, l_linestatus
        ORDER BY l_returnflag, l_linestatus
    """

    query_job = conn.query(query)
    results = list(query_job.result())

    # Check query statistics
    print(f"Bytes processed: {query_job.total_bytes_processed:,}")
    print(f"Bytes billed: {query_job.total_bytes_billed:,}")
    print(f"Slot milliseconds: {query_job.slot_millis:,}")

Cost Estimation (Dry Run)
~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from google.cloud import bigquery

    # Estimate query cost before execution
    adapter = BigQueryAdapter(project_id="my-project", dataset_id="benchbox")

    # Get query plan without execution
    plan = adapter.get_query_plan(conn, query)
    print(f"Estimated bytes: {plan['bytes_processed']:,}")
    print(f"Estimated cost: ${plan['estimated_cost']:.4f}")

Query Plans and Optimization
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    # Get query execution plan
    job_config = bigquery.QueryJobConfig(dry_run=True)
    query_job = conn.query(query, job_config=job_config)

    print(f"This query will process {query_job.total_bytes_processed:,} bytes")

    # Estimated cost: $5 per TB processed
    cost_per_tb = 5.0
    estimated_cost = (query_job.total_bytes_processed / 1024**4) * cost_per_tb
    print(f"Estimated cost: ${estimated_cost:.4f}")

Advanced Features
-----------------

Partitioning
~~~~~~~~~~~~

.. code-block:: python

    # Create partitioned table
    query = """
        CREATE OR REPLACE TABLE `my-project.benchbox.orders_partitioned`
        PARTITION BY DATE(o_orderdate)
        AS SELECT * FROM `my-project.benchbox.ORDERS`
    """
    conn.query(query).result()

    # Query with partition filter (reduces cost)
    query = """
        SELECT COUNT(*) FROM `my-project.benchbox.orders_partitioned`
        WHERE DATE(o_orderdate) BETWEEN '1995-01-01' AND '1995-12-31'
    """
    # Only scans data from 1995 partitions

Clustering
~~~~~~~~~~

.. code-block:: python

    # Create clustered table (up to 4 columns)
    query = """
        CREATE OR REPLACE TABLE `my-project.benchbox.lineitem_clustered`
        PARTITION BY DATE(l_shipdate)
        CLUSTER BY l_orderkey, l_partkey, l_suppkey
        AS SELECT * FROM `my-project.benchbox.LINEITEM`
    """
    conn.query(query).result()

    # Queries filtering on clustered columns are optimized
    query = """
        SELECT * FROM `my-project.benchbox.lineitem_clustered`
        WHERE l_orderkey = 12345
        AND DATE(l_shipdate) = '1995-03-15'
    """

Query Caching
~~~~~~~~~~~~~

.. code-block:: python

    # Enable caching (default)
    adapter = BigQueryAdapter(
        project_id="my-project",
        dataset_id="benchbox",
        query_cache=True
    )

    # First execution processes data
    query = "SELECT COUNT(*) FROM `my-project.benchbox.LINEITEM`"
    job1 = conn.query(query)
    print(f"Bytes billed (first): {job1.total_bytes_billed:,}")

    # Second execution uses cache (0 bytes billed)
    job2 = conn.query(query)
    print(f"Bytes billed (cached): {job2.total_bytes_billed:,}")  # 0

Batch vs Interactive Priority
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from google.cloud import bigquery

    # Interactive (default) - immediate execution
    job_config_interactive = bigquery.QueryJobConfig(
        priority=bigquery.QueryPriority.INTERACTIVE
    )

    # Batch - queued execution, 50% discount
    job_config_batch = bigquery.QueryJobConfig(
        priority=bigquery.QueryPriority.BATCH
    )

    query = "SELECT COUNT(*) FROM `my-project.benchbox.LINEITEM`"

    # Use batch for non-time-sensitive queries
    job = conn.query(query, job_config=job_config_batch)
    job.result()  # May wait in queue

Best Practices
--------------

Cost Optimization
~~~~~~~~~~~~~~~~~

1. **Use partitioning** to reduce data scanned:

   .. code-block:: python

       # Partition by date column
       adapter = BigQueryAdapter(
           project_id="my-project",
           partitioning_field="l_shipdate"
       )

2. **Enable query caching**:

   .. code-block:: python

       adapter = BigQueryAdapter(
           query_cache=True  # Reuse cached results
       )

3. **Set billing limits**:

   .. code-block:: python

       adapter = BigQueryAdapter(
           maximum_bytes_billed=10 * 1024**3  # 10 GB max
       )

4. **Use BATCH priority** for non-urgent queries:

   .. code-block:: python

       adapter = BigQueryAdapter(
           job_priority="BATCH"  # 50% discount
       )

5. **Estimate costs** before execution:

   .. code-block:: python

       plan = adapter.get_query_plan(conn, query)
       if plan["estimated_cost"] > 1.0:  # > $1
           print("Query too expensive, optimizing...")

Data Loading Efficiency
~~~~~~~~~~~~~~~~~~~~~~~

1. **Use Cloud Storage** for large datasets:

   .. code-block:: python

       adapter = BigQueryAdapter(
           storage_bucket="benchmark-data"  # Recommended for large datasets
       )

2. **Compress data files**:

   .. code-block:: bash

       # BigQuery supports compressed files
       gzip data/*.csv

3. **Use Parquet format** when possible:

   .. code-block:: python

       # Parquet is more efficient than CSV
       benchmark.generate_data(data_dir, format="parquet")

Performance Optimization
~~~~~~~~~~~~~~~~~~~~~~~~

1. **Cluster frequently filtered columns**:

   .. code-block:: python

       adapter = BigQueryAdapter(
           clustering_fields=["order_key", "customer_key"]
       )

2. **Avoid SELECT \***:

   .. code-block:: sql

       -- Bad: scans all columns
       SELECT * FROM lineitem WHERE l_orderkey = 1

       -- Good: only scans needed columns
       SELECT l_orderkey, l_quantity FROM lineitem WHERE l_orderkey = 1

3. **Use materialized views** for repeated queries:

   .. code-block:: sql

       CREATE MATERIALIZED VIEW benchbox.lineitem_summary AS
       SELECT
           l_orderkey,
           sum(l_quantity) as total_qty
       FROM benchbox.LINEITEM
       GROUP BY l_orderkey

Common Issues
-------------

Permission Denied
~~~~~~~~~~~~~~~~~

**Problem**: "Access Denied" errors

**Solutions**:

.. code-block:: bash

    # 1. Check required permissions
    gcloud projects get-iam-policy my-project

    # 2. Grant BigQuery Admin role
    gcloud projects add-iam-policy-binding my-project \
        --member="user:your-email@example.com" \
        --role="roles/bigquery.admin"

    # 3. Grant Storage permissions (if using GCS)
    gcloud projects add-iam-policy-binding my-project \
        --member="user:your-email@example.com" \
        --role="roles/storage.objectAdmin"

.. code-block:: python

    # 4. Verify credentials in code
    from google.cloud import bigquery

    client = bigquery.Client(project="my-project")
    print(f"Authenticated as: {client._credentials.service_account_email}")

Dataset Not Found
~~~~~~~~~~~~~~~~~

**Problem**: "Dataset not found" error

**Solutions**:

.. code-block:: python

    # 1. List available datasets
    client = bigquery.Client(project="my-project")
    datasets = list(client.list_datasets())
    print("Datasets:", [d.dataset_id for d in datasets])

    # 2. Create dataset if it doesn't exist
    from google.cloud import bigquery

    dataset_id = "benchbox"
    dataset = bigquery.Dataset(f"my-project.{dataset_id}")
    dataset.location = "US"
    client.create_dataset(dataset, exists_ok=True)

Quota Exceeded
~~~~~~~~~~~~~~

**Problem**: "Quota exceeded" errors

**Solutions**:

.. code-block:: python

    # 1. Check current quota usage
    # Visit: https://console.cloud.google.com/iam-admin/quotas

    # 2. Set maximum bytes billed
    adapter = BigQueryAdapter(
        maximum_bytes_billed=100 * 1024**3  # 100 GB limit
    )

    # 3. Use BATCH priority to reduce quota impact
    adapter = BigQueryAdapter(
        job_priority="BATCH"
    )

    # 4. Request quota increase
    # Visit: https://console.cloud.google.com/iam-admin/quotas

Slow Query Performance
~~~~~~~~~~~~~~~~~~~~~~

**Problem**: Queries are slower than expected

**Solutions**:

.. code-block:: python

    # 1. Check query execution details
    query_job = conn.query(query)
    query_job.result()

    print(f"Total slot time: {query_job.slot_millis}ms")
    print(f"Bytes processed: {query_job.total_bytes_processed:,}")

    # 2. Add partitioning to reduce data scanned
    CREATE TABLE dataset.table_partitioned
    PARTITION BY DATE(date_column)
    AS SELECT * FROM dataset.table

    # 3. Add clustering for better data organization
    CREATE TABLE dataset.table_clustered
    CLUSTER BY key_column1, key_column2
    AS SELECT * FROM dataset.table

    # 4. Check for full table scans
    # Use query plan to identify issues
    job_config = bigquery.QueryJobConfig(dry_run=True)
    query_job = conn.query(query, job_config=job_config)

High Costs
~~~~~~~~~~

**Problem**: Unexpected high query costs

**Solutions**:

.. code-block:: python

    # 1. Enable dry run to estimate costs
    adapter = BigQueryAdapter(
        project_id="my-project",
        dry_run=True  # Preview only
    )

    # 2. Check query costs
    plan = adapter.get_query_plan(conn, query)
    print(f"Will process: {plan['bytes_processed'] / 1024**3:.2f} GB")
    print(f"Estimated cost: ${plan['estimated_cost']:.4f}")

    # 3. Set billing limits
    adapter = BigQueryAdapter(
        maximum_bytes_billed=10 * 1024**3  # Hard limit
    )

    # 4. Use partitioning and clustering
    # Reduces data scanned per query
    CREATE TABLE dataset.table_optimized
    PARTITION BY DATE(date_column)
    CLUSTER BY key1, key2
    AS SELECT * FROM dataset.table_raw

See Also
--------

Platform Documentation
~~~~~~~~~~~~~~~~~~~~~~

- :doc:`/platforms/platform-selection-guide` - Choosing BigQuery vs other platforms
- :doc:`/platforms/quick-reference` - Quick setup for all platforms
- :doc:`/platforms/comparison-matrix` - Feature comparison
- :doc:`/cloud-storage` - GCS, S3, Azure Blob Storage integration

Benchmark Guides
~~~~~~~~~~~~~~~~

- :doc:`/benchmarks/tpc-h` - TPC-H on BigQuery
- :doc:`/benchmarks/tpc-ds` - TPC-DS on BigQuery
- :doc:`/benchmarks/clickbench` - ClickBench on BigQuery

API Reference
~~~~~~~~~~~~~

- :doc:`duckdb` - DuckDB adapter
- :doc:`clickhouse` - ClickHouse adapter
- :doc:`databricks` - Databricks adapter
- :doc:`../base` - Base benchmark interface
- :doc:`../index` - Python API overview

External Resources
~~~~~~~~~~~~~~~~~~

- `BigQuery Documentation <https://docs.cloud.google.com/bigquery/docs>`_ - Official BigQuery docs
- `BigQuery Best Practices <https://docs.cloud.google.com/bigquery/docs/best-practices-performance-overview>`_ - Performance and cost optimization
- `Partitioning Guide <https://docs.cloud.google.com/bigquery/docs/partitioned-tables>`_ - Partitioning strategies
- `Clustering Guide <https://docs.cloud.google.com/bigquery/docs/clustered-tables>`_ - Clustering best practices
- `Cost Optimization <https://docs.cloud.google.com/bigquery/docs/best-practices-costs>`_ - Reducing query costs
