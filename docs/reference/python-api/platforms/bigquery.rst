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

    adapter = BigQueryAdapter(
        project_id="my-project-id",
        dataset_id="benchbox_tpch",
        location="US",
        credentials_path="/path/to/service-account.json"
    )

    benchmark = TPCH(scale_factor=1.0)
    results = benchmark.run_with_platform(adapter)

The adapter connects to BigQuery and the benchmark runs on it.

Auto-Detection
~~~~~~~~~~~~~~

.. code-block:: python

    from benchbox.platforms.bigquery import BigQueryAdapter

    adapter = BigQueryAdapter.from_config({
        "benchmark": "tpch",
        "scale_factor": 1.0,
    })

The adapter auto-detects credentials from Application Default Credentials, and it detects ``project_id`` from the gcloud config.

API Reference
-------------

BigQueryAdapter Class
~~~~~~~~~~~~~~~~~~~~~

.. py:class:: benchbox.platforms.bigquery.BigQueryAdapter(**config)

   BigQuery adapter.  ``project_id`` is required; ``dataset_id`` defaults to
   ``"benchbox"``, ``location`` to ``"US"``, ``storage_prefix`` to
   ``"benchbox-data"``, ``job_priority`` to ``"INTERACTIVE"``, and result
   caching is disabled unless explicitly configured.  ``staging_root`` must be
   a GCS location when supplied.  Missing dependencies raise ``ImportError``;
   missing project configuration raises ``ConfigurationError``.

   Example::

      adapter = BigQueryAdapter(project_id="example-project", dataset_id="benchbox")

   The adapter advertises external-table support.  See :doc:`common` for shared methods.

.. py:method:: benchbox.platforms.bigquery.BigQueryAdapter.create_connection(**connection_config) -> Any

   Create optimized BigQuery client connection.

.. py:method:: benchbox.platforms.bigquery.BigQueryAdapter.create_schema(benchmark, connection: Any) -> float

   Create schema using BigQuery dataset and tables.

.. py:method:: benchbox.platforms.bigquery.BigQueryAdapter.load_data(benchmark, connection: Any, data_dir: Path) -> tuple[dict[str, int], float, dict[str, Any] | None]

   Load data using BigQuery efficient loading via Cloud Storage.

.. py:method:: benchbox.platforms.bigquery.BigQueryAdapter.create_external_tables(benchmark: Any, connection: Any, data_dir: Path) -> tuple[dict[str, int], float, dict[str, Any] | None]

   Upload external-table sources to GCS and register BigQuery external tables.

.. py:method:: benchbox.platforms.bigquery.BigQueryAdapter.execute_query(connection: Any, query: str, query_id: str, benchmark_type: str | None = None, scale_factor: float | None = None, validate_row_count: bool = True, stream_id: int | None = None) -> dict[str, Any]

   Execute query with detailed timing and cost tracking.

.. py:method:: benchbox.platforms.bigquery.BigQueryAdapter.get_query_plan(connection: Any, query: str) -> dict[str, Any] | None

   Return BigQuery's dry-run bytes and estimated on-demand cost.

   BigQuery exposes bytes processed through a dry-run job rather than an
   EXPLAIN text result. Structured execution stages remain available from
   the completed job through ``_capture_bq_plan``.

.. py:method:: benchbox.platforms.bigquery.BigQueryAdapter.get_table_row_count(connection: Any, table: str) -> int

   Get row count using BigQuery Client API.

   Overrides base implementation that uses cursor pattern.
   BigQuery Client doesn't have .cursor() method, so we use .query() instead.

   :param connection: BigQuery Client
   :param table: Table name

   :returns: Row count as integer, or 0 if unable to determine

Static member inventory
-----------------------

.. py:staticmethod:: benchbox.platforms.bigquery.BigQueryAdapter.add_cli_arguments(parser: argparse.ArgumentParser) -> None

   Add BigQuery-specific CLI arguments.

.. py:classmethod:: benchbox.platforms.bigquery.BigQueryAdapter.from_config(config: dict[str, Any])

   Create BigQuery adapter from unified configuration.

.. py:property:: benchbox.platforms.bigquery.BigQueryAdapter.platform_name

   Returns this adapter's registered platform identifier for selection, metadata, and capability lookup.

.. py:method:: benchbox.platforms.bigquery.BigQueryAdapter.get_platform_info(self, connection: Any=None) -> dict[str, Any]

   Get BigQuery platform information.

   Captures comprehensive BigQuery configuration including:
   Dataset location and region
   Slot reservation information (best effort)
   Project and billing configuration
   Dataset metadata

   BigQuery doesn't expose a version number as it's a fully managed service.
   Gracefully degrades if permissions are insufficient for metadata queries.

.. py:method:: benchbox.platforms.bigquery.BigQueryAdapter.get_normalized_result_metadata(self, *, connection: Any | None=None, platform_info: Mapping[str, Any] | None=None) -> dict[str, Any]

   Return BigQuery-specific normalized cloud/runtime metadata.

.. py:method:: benchbox.platforms.bigquery.BigQueryAdapter.get_target_dialect(self) -> str

   Return the target SQL dialect for BigQuery.

.. py:method:: benchbox.platforms.bigquery.BigQueryAdapter.preprocess_operation_sql(self, query_id: str, operation: Any) -> str | None

   Rewrite operation write SQL for BigQuery-only dialect gaps.

   Respects catalog ``bigquery`` overrides (including skip ``None``):
   rewrites the override when present, otherwise the default write SQL.
   Four rewrites, each linear and single-level by construction of the
   catalog SQL they target (verified live: the unmodified forms fail
   server-side with ``Type not found: VARCHAR`` and ``INT64`` interval
   complaints while COUNT(*) validations kept passing):

   ``CAST(x AS VARCHAR)`` -> ``CAST(x AS STRING)``
   ``INTERVAL 'N' UNIT`` -> ``INTERVAL N UNIT``
   a missing ``WHERE`` on an UPDATE/DELETE statement gains
   ``WHERE true`` (BigQuery rejects filter-less DML; constant-true
   preserves the full-table intent)
   a trailing bare ``WHEN NOT MATCHED ... THEN INSERT`` gains
   ``ROW`` (Snowflake shorthand for inserting the source row;
   BigQuery requires ``INSERT ROW``)

.. py:method:: benchbox.platforms.bigquery.BigQueryAdapter.check_server_database_exists(self, **connection_config) -> bool

   Check if dataset exists in BigQuery project.

.. py:method:: benchbox.platforms.bigquery.BigQueryAdapter.drop_database(self, **connection_config) -> None

   Drop dataset in BigQuery project.

.. py:method:: benchbox.platforms.bigquery.BigQueryAdapter.validate_external_table_requirements(self) -> None

   Validate required GCS configuration for external table mode.

.. py:method:: benchbox.platforms.bigquery.BigQueryAdapter.configure_for_benchmark(self, connection: Any, benchmark_type: str) -> None

   Apply BigQuery-specific optimizations based on benchmark type.

.. py:method:: benchbox.platforms.bigquery.BigQueryAdapter.get_query_plan_parser(self)

   Expose the BigQuery plan parser for symmetry with other adapters.

.. py:method:: benchbox.platforms.bigquery.BigQueryAdapter.close_connection(self, connection: Any) -> None

   Close BigQuery connection.

   Handles credential refresh errors gracefully during connection cleanup.
   Suppresses all credential-related errors as they are non-fatal during cleanup.

.. py:method:: benchbox.platforms.bigquery.BigQueryAdapter.generate_tuning_clause(self, table_tuning) -> str

   Generate BigQuery-specific tuning clauses for CREATE TABLE statements.

   BigQuery supports:
   PARTITION BY DATE(column), DATETIME_TRUNC(column, DAY), column (for date/integer)
   CLUSTER BY column1, column2, ... (up to 4 columns)

   :param table_tuning: The tuning configuration for the table

   :returns: SQL clause string to be appended to CREATE TABLE statement

.. py:method:: benchbox.platforms.bigquery.BigQueryAdapter.apply_table_tunings(self, table_tuning, connection: Any) -> None

   Apply tuning configurations to a BigQuery table.

   BigQuery tuning approach:
   PARTITIONING: Handled in CREATE TABLE via PARTITION BY
   CLUSTERING: Handled in CREATE TABLE via CLUSTER BY
   Additional optimization via table options

   :param table_tuning: The tuning configuration to apply
   :param connection: BigQuery client connection

   :raises ValueError: If the tuning configuration is invalid for BigQuery

.. py:method:: benchbox.platforms.bigquery.BigQueryAdapter.apply_unified_tuning(self, unified_config: UnifiedTuningConfiguration, connection: Any) -> None

   Apply unified tuning configuration to BigQuery.

.. py:method:: benchbox.platforms.bigquery.BigQueryAdapter.apply_platform_optimizations(self, platform_config: PlatformOptimizationConfiguration, connection: Any) -> None

   Apply BigQuery-specific platform optimizations.

   :param platform_config: Platform optimization configuration
   :param connection: BigQuery connection

.. py:attribute:: benchbox.platforms.bigquery.BigQueryAdapter.driver_isolation_capability

   Declares whether this adapter can run through an isolated driver runtime; the value controls runtime-resolution support.

.. py:attribute:: benchbox.platforms.bigquery.BigQueryAdapter.supports_external_tables

   Advertises whether the adapter implements external-table creation.

.. py:attribute:: benchbox.platforms.bigquery.BigQueryAdapter.plan_capture_phase_eligible

   Advertises whether benchmark plan capture is available for this adapter.

.. py:method:: benchbox.platforms.bigquery.BigQueryAdapter.apply_constraint_configuration(primary_key_config: PrimaryKeyConfiguration, foreign_key_config: ForeignKeyConfiguration, connection: Any) -> None

   Logs informational messages for enabled primary-key and foreign-key settings.
   This hook executes no SQL and does not use ``connection``. Table-creation
   hooks handle any platform-supported constraint DDL.

Constructor Configuration
~~~~~~~~~~~~~~~~~~~~~~~~~

Pass keyword configuration through ``BigQueryAdapter(**config)``.

- ``project_id`` identifies the project; ``credentials_path`` is optional.
- ``dataset_id`` defaults to ``"benchbox"`` and ``location`` to ``"US"``.
- ``storage_bucket`` is optional; ``storage_prefix`` defaults to ``"benchbox-data"``.
  A GCS ``staging_root`` overrides the bucket/prefix derived from these fields.
- ``job_priority`` defaults to ``"INTERACTIVE"``. ``query_cache`` defaults to
  ``False``; an explicit value takes precedence over ``disable_result_cache``.
- ``dry_run`` defaults to ``False``; ``maximum_bytes_billed`` is optional.
- ``clustering_fields`` defaults to a new empty list; ``partitioning_field``
  is optional. These are table-creation settings.

Configuration Examples
----------------------

Application Default Credentials
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: bash

    gcloud auth application-default login

.. code-block:: python

    adapter = BigQueryAdapter(
        project_id="my-project",
        dataset_id="benchbox_tpch"
    )

The ``gcloud`` command sets up the default credentials, so no ``credentials_path`` is needed.

Service Account Authentication
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: bash

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

The ``gcloud`` commands create a service account, grant it BigQuery permissions, and download its key.

GCS Integration for Data Loading
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    adapter = BigQueryAdapter(
        project_id="my-project",
        dataset_id="benchbox_tpch",
        storage_bucket="my-benchmark-data",
        storage_prefix="tpch/sf1"
    )

This gives efficient loading through Cloud Storage. Data is automatically uploaded to GCS and then loaded into BigQuery. This is recommended for large datasets.


Cost Control Configuration
~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    adapter = BigQueryAdapter(
        project_id="my-project",
        dataset_id="benchbox_tpch",
        job_priority="BATCH",
        query_cache=True,
        maximum_bytes_billed=10 * 1024**3
    )

This sets budget limits: ``BATCH`` priority costs less but runs slower, ``query_cache=True`` reuses cached results, and ``maximum_bytes_billed`` is a 10 GB limit per query.

Table Optimization
~~~~~~~~~~~~~~~~~~

.. code-block:: python

    adapter = BigQueryAdapter(
        project_id="my-project",
        dataset_id="benchbox_tpch",
        partitioning_field="l_shipdate",
        clustering_fields=["l_orderkey", "l_partkey"]
    )

This configures partitioning and clustering. ``partitioning_field`` partitions on a date column, and ``clustering_fields`` clusters by the listed columns.

Authentication
--------------

Application Default Credentials (Development)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: bash

    gcloud auth application-default login

    gcloud config set project my-project-id

.. code-block:: python

    adapter = BigQueryAdapter(
        project_id="my-project",
        dataset_id="benchbox"
    )

The first ``gcloud`` command logs in with your Google account, and the second sets the default project. You can omit ``project_id`` in the adapter because it is auto-detected from the gcloud config.

Service Account (Production)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: bash

    gcloud iam service-accounts create benchbox-sa

    gcloud projects add-iam-policy-binding my-project \
        --member="serviceAccount:benchbox-sa@my-project.iam.gserviceaccount.com" \
        --role="roles/bigquery.admin"

    gcloud projects add-iam-policy-binding my-project \
        --member="serviceAccount:benchbox-sa@my-project.iam.gserviceaccount.com" \
        --role="roles/storage.objectAdmin"

    gcloud iam service-accounts keys create sa-key.json \
        --iam-account=benchbox-sa@my-project.iam.gserviceaccount.com

.. code-block:: python

    adapter = BigQueryAdapter(
        project_id="my-project",
        credentials_path="/secure/path/sa-key.json"
    )

The ``gcloud`` commands create the service account with the required roles, grant BigQuery permissions, grant GCS permissions (only if you use Cloud Storage), and download the key. The Python code uses that service account key.

Environment Variables
~~~~~~~~~~~~~~~~~~~~~

.. code-block:: bash

    export GOOGLE_APPLICATION_CREDENTIALS="/path/to/key.json"
    export GOOGLE_CLOUD_PROJECT="my-project-id"

.. code-block:: python

    import os
    adapter = BigQueryAdapter(
        project_id=os.environ["GOOGLE_CLOUD_PROJECT"],
        dataset_id="benchbox"
    )

The environment variables set the credentials, and the adapter loads them automatically.

Data Loading
------------

Via Cloud Storage (Recommended)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from benchbox.platforms.bigquery import BigQueryAdapter
    from benchbox.tpch import TPCH
    from pathlib import Path

    adapter = BigQueryAdapter(
        project_id="my-project",
        dataset_id="benchbox_tpch_sf10",
        storage_bucket="benchmark-data-bucket",
        storage_prefix="tpch/sf10"
    )

    benchmark = TPCH(scale_factor=10.0)
    data_dir = Path("./tpch_data")
    benchmark.generate_data(data_dir)

    conn = adapter.create_connection()
    table_stats, load_time = adapter.load_data(benchmark, conn, data_dir)

The example configures the adapter with a GCS bucket, generates the data, and loads it. The load automatically uploads the data to GCS first.

Direct Loading (Small Datasets)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    adapter = BigQueryAdapter(
        project_id="my-project",
        dataset_id="benchbox_tpch_sf001"
    )

    conn = adapter.create_connection()
    table_stats, load_time = adapter.load_data(benchmark, conn, data_dir)

For small datasets (under 1 GB), skip GCS: no ``storage_bucket`` is specified, so the adapter loads directly from local files.

Query Execution
---------------

Basic Query Execution
~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    adapter = BigQueryAdapter(project_id="my-project", dataset_id="benchbox")
    conn = adapter.create_connection()

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

    print(f"Bytes processed: {query_job.total_bytes_processed:,}")
    print(f"Bytes billed: {query_job.total_bytes_billed:,}")
    print(f"Slot milliseconds: {query_job.slot_millis:,}")

The example executes a SQL query and then checks the query statistics.

Cost Estimation (Dry Run)
~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from google.cloud import bigquery

    adapter = BigQueryAdapter(project_id="my-project", dataset_id="benchbox")

    plan = adapter.get_query_plan(conn, query)
    print(f"Estimated bytes: {plan['bytes_processed']:,}")
    print(f"Estimated cost: ${plan['estimated_cost']:.4f}")

``get_query_plan`` estimates the query cost and returns the plan without executing the query.

Query Plans and Optimization
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    job_config = bigquery.QueryJobConfig(dry_run=True)
    query_job = conn.query(query, job_config=job_config)

    print(f"This query will process {query_job.total_bytes_processed:,} bytes")

    cost_per_tb = 6.25
    estimated_cost = (query_job.total_bytes_processed / 1024**4) * cost_per_tb
    print(f"Estimated cost: ${estimated_cost:.4f}")

The dry run returns the query execution plan without running the query. The on-demand rate varies by location; the US, EU and Asia multi-region rate is $6.25 per TiB. See ``benchbox/core/cost/pricing_data.yaml`` for all locations.

Advanced Features
-----------------

Partitioning
~~~~~~~~~~~~

.. code-block:: python

    query = """
        CREATE OR REPLACE TABLE `my-project.benchbox.orders_partitioned`
        PARTITION BY DATE(o_orderdate)
        AS SELECT * FROM `my-project.benchbox.ORDERS`
    """
    conn.query(query).result()

    query = """
        SELECT COUNT(*) FROM `my-project.benchbox.orders_partitioned`
        WHERE DATE(o_orderdate) BETWEEN '1995-01-01' AND '1995-12-31'
    """

The first query creates a partitioned table. The second query filters on the partition column, which reduces cost because it scans only the 1995 partitions.

Clustering
~~~~~~~~~~

.. code-block:: python

    query = """
        CREATE OR REPLACE TABLE `my-project.benchbox.lineitem_clustered`
        PARTITION BY DATE(l_shipdate)
        CLUSTER BY l_orderkey, l_partkey, l_suppkey
        AS SELECT * FROM `my-project.benchbox.LINEITEM`
    """
    conn.query(query).result()

    query = """
        SELECT * FROM `my-project.benchbox.lineitem_clustered`
        WHERE l_orderkey = 12345
        AND DATE(l_shipdate) = '1995-03-15'
    """

The first query creates a clustered table (up to 4 clustering columns are allowed). The second query filters on the clustered columns, so it is optimized.

Query Caching
~~~~~~~~~~~~~

.. code-block:: python

    adapter = BigQueryAdapter(
        project_id="my-project",
        dataset_id="benchbox",
        query_cache=True
    )

    query = "SELECT COUNT(*) FROM `my-project.benchbox.LINEITEM`"
    job1 = conn.query(query)
    print(f"Bytes billed (first): {job1.total_bytes_billed:,}")

    job2 = conn.query(query)
    print(f"Bytes billed (cached): {job2.total_bytes_billed:,}")

Query caching is enabled by default. The first execution processes the data. The second execution uses the cache and bills 0 bytes.

Batch vs Interactive Priority
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from google.cloud import bigquery

    job_config_interactive = bigquery.QueryJobConfig(
        priority=bigquery.QueryPriority.INTERACTIVE
    )

    job_config_batch = bigquery.QueryJobConfig(
        priority=bigquery.QueryPriority.BATCH
    )

    query = "SELECT COUNT(*) FROM `my-project.benchbox.LINEITEM`"

    job = conn.query(query, job_config=job_config_batch)
    job.result()

Interactive priority (the default) executes immediately. Batch priority queues the query and gets a 50% discount, so use it for non-time-sensitive queries. ``job.result()`` may wait in the queue.

Best Practices
--------------

Cost Optimization
~~~~~~~~~~~~~~~~~

1. **Use partitioning** to reduce data scanned:

   .. code-block:: python

       adapter = BigQueryAdapter(
           project_id="my-project",
           partitioning_field="l_shipdate"
       )

   Partition on a date column.

2. **Enable query caching**:

   .. code-block:: python

       adapter = BigQueryAdapter(
           query_cache=True
       )

   This reuses cached results.

3. **Set billing limits**:

   .. code-block:: python

       adapter = BigQueryAdapter(
           maximum_bytes_billed=10 * 1024**3
       )

   This sets a 10 GB maximum per query.

4. **Use BATCH priority** for non-urgent queries:

   .. code-block:: python

       adapter = BigQueryAdapter(
           job_priority="BATCH"
       )

   BATCH priority gets a 50% discount.

5. **Estimate costs** before execution:

   .. code-block:: python

       plan = adapter.get_query_plan(conn, query)
       if plan["estimated_cost"] > 1.0:
           print("Query too expensive, optimizing...")

   The example flags any query that is estimated to cost more than $1.

Data Loading Efficiency
~~~~~~~~~~~~~~~~~~~~~~~

1. **Use Cloud Storage** for large datasets:

   .. code-block:: python

       adapter = BigQueryAdapter(
           storage_bucket="benchmark-data"
       )

   Cloud Storage is recommended for large datasets.

2. **Compress data files**:

   .. code-block:: bash

       gzip data/*.csv

   BigQuery supports compressed files.

3. **Use Parquet format** when possible:

   .. code-block:: python

       benchmark.generate_data(data_dir, format="parquet")

   Parquet is more efficient than CSV.

Performance Optimization
~~~~~~~~~~~~~~~~~~~~~~~~

1. **Cluster frequently filtered columns**:

   .. code-block:: python

       adapter = BigQueryAdapter(
           clustering_fields=["order_key", "customer_key"]
       )

2. **Avoid SELECT \***:

   .. code-block:: sql

       SELECT * FROM lineitem WHERE l_orderkey = 1

       SELECT l_orderkey, l_quantity FROM lineitem WHERE l_orderkey = 1

   The first query is bad because it scans all columns. The second is good because it scans only the columns it needs.

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

    gcloud projects get-iam-policy my-project

    gcloud projects add-iam-policy-binding my-project \
        --member="user:your-email@example.com" \
        --role="roles/bigquery.admin"

    gcloud projects add-iam-policy-binding my-project \
        --member="user:your-email@example.com" \
        --role="roles/storage.objectAdmin"

.. code-block:: python

    from google.cloud import bigquery

    client = bigquery.Client(project="my-project")
    print(f"Authenticated as: {client._credentials.service_account_email}")

The steps are: check the required permissions, grant the BigQuery Admin role, grant the Storage permissions (only if you use GCS), and verify the credentials in code.

Dataset Not Found
~~~~~~~~~~~~~~~~~

**Problem**: "Dataset not found" error

**Solutions**:

.. code-block:: python

    client = bigquery.Client(project="my-project")
    datasets = list(client.list_datasets())
    print("Datasets:", [d.dataset_id for d in datasets])

    from google.cloud import bigquery

    dataset_id = "benchbox"
    dataset = bigquery.Dataset(f"my-project.{dataset_id}")
    dataset.location = "US"
    client.create_dataset(dataset, exists_ok=True)

First list the available datasets. Then create the dataset if it does not exist.

Quota Exceeded
~~~~~~~~~~~~~~

**Problem**: "Quota exceeded" errors

**Solutions**:

.. code-block:: python

    adapter = BigQueryAdapter(
        maximum_bytes_billed=100 * 1024**3
    )

    adapter = BigQueryAdapter(
        job_priority="BATCH"
    )

The steps are:

1. Check the current quota usage at https://console.cloud.google.com/iam-admin/quotas.
2. Set a maximum bytes billed (the example uses a 100 GB limit).
3. Use BATCH priority to reduce the quota impact.
4. Request a quota increase at the same quota page.


Slow Query Performance
~~~~~~~~~~~~~~~~~~~~~~

**Problem**: Queries are slower than expected

**Solutions**:

.. code-block:: python

    query_job = conn.query(query)
    query_job.result()

    print(f"Total slot time: {query_job.slot_millis}ms")
    print(f"Bytes processed: {query_job.total_bytes_processed:,}")

    conn.query("""
    CREATE TABLE dataset.table_partitioned
    PARTITION BY DATE(date_column)
    AS SELECT * FROM dataset.table
    """).result()

    conn.query("""
    CREATE TABLE dataset.table_clustered
    CLUSTER BY key_column1, key_column2
    AS SELECT * FROM dataset.table
    """).result()

    job_config = bigquery.QueryJobConfig(dry_run=True)
    query_job = conn.query(query, job_config=job_config)

The steps are: check the query execution details, add partitioning to reduce the data scanned, add clustering for better data organization, and check for full table scans by using the query plan to identify issues.

High Costs
~~~~~~~~~~

**Problem**: Unexpected high query costs

**Solutions**:

.. code-block:: python

    adapter = BigQueryAdapter(
        project_id="my-project",
        dry_run=True
    )

    plan = adapter.get_query_plan(conn, query)
    print(f"Will process: {plan['bytes_processed'] / 1024**3:.2f} GB")
    print(f"Estimated cost: ${plan['estimated_cost']:.4f}")

    adapter = BigQueryAdapter(
        maximum_bytes_billed=10 * 1024**3
    )

    conn.query("""
    CREATE TABLE dataset.table_optimized
    PARTITION BY DATE(date_column)
    CLUSTER BY key1, key2
    AS SELECT * FROM dataset.table_raw
    """).result()

The steps are:

1. Enable ``dry_run=True`` to preview and estimate costs without running queries.
2. Check the query costs.
3. Set a hard billing limit (the example uses 10 GB).
4. Use partitioning and clustering, which reduces the data scanned per query.

See Also
--------

Platform Documentation
~~~~~~~~~~~~~~~~~~~~~~

- :doc:`/platforms/platform-selection-guide` - Choosing BigQuery vs other platforms
- :doc:`/platforms/quick-reference` - Quick setup for all platforms
- :doc:`/platforms/comparison-matrix` - Feature comparison
- :doc:`/guides/cloud-storage` - GCS, S3, Azure Blob Storage integration

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
