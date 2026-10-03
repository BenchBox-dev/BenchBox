Amazon Redshift Platform Adapter
==================================

.. tags:: reference, python-api, cloud-platform

The Redshift adapter provides AWS-native data warehouse execution with S3 integration and columnar storage optimization.

Overview
--------

Amazon Redshift is a fully managed petabyte-scale data warehouse service that provides:

- **Columnar storage** - Optimized for analytical queries
- **Massively parallel processing** - Distributed query execution
- **S3 integration** - COPY command for bulk loading
- **Automatic backups** - Point-in-time recovery capabilities
- **Concurrency scaling** - Automatic scaling for concurrent workloads
- **Redshift Spectrum** - Query data directly in S3

Common use cases:

- AWS-native analytics workloads
- Large-scale data warehousing (TB to PB scale)
- Integration with AWS ecosystem
- Reserved or serverless deployment options
- Federated queries across data lake and warehouse

Quick Start
-----------

Basic Configuration
~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from benchbox.tpch import TPCH
    from benchbox.platforms.redshift import RedshiftAdapter

    adapter = RedshiftAdapter(
        host="my-cluster.123456.us-east-1.redshift.amazonaws.com",
        port=5439,
        database="dev",
        username="admin",
        password="SecurePassword123"
    )

    benchmark = TPCH(scale_factor=1.0)
    results = benchmark.run_with_platform(adapter)

With S3 Data Loading
~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    adapter = RedshiftAdapter(
        host="my-cluster.123456.us-east-1.redshift.amazonaws.com",
        username="admin",
        password="SecurePassword123",
        database="benchbox",
        s3_bucket="my-redshift-data",
        s3_prefix="benchbox/staging",
        iam_role="arn:aws:iam::123456789:role/RedshiftCopyRole"
    )

API Reference
-------------

RedshiftAdapter Class
~~~~~~~~~~~~~~~~~~~~~

.. py:class:: benchbox.platforms.redshift.RedshiftAdapter(**config)

   Redshift adapter with cursor-based query-result validation.  Its connection
   and staging settings are validated by the adapter and driver; unsupported
   external-table or credential configuration can raise ``ValueError``, while
   unavailable dependencies can raise ``ImportError``.

   Example::

      adapter = RedshiftAdapter(host="cluster.example", database="benchbox", user="user")

   The adapter advertises external-table support.  See :doc:`common` for the
   shared lifecycle.

.. py:method:: benchbox.platforms.redshift.RedshiftAdapter.create_connection(**connection_config) -> Any

   Create optimized Redshift connection.

.. py:method:: benchbox.platforms.redshift.RedshiftAdapter.create_schema(benchmark, connection: Any) -> float

   Create schema using Redshift-optimized table definitions.

.. py:method:: benchbox.platforms.redshift.RedshiftAdapter.create_external_tables(benchmark: Any, connection: Any, data_dir: Path) -> tuple[dict[str, int], float, dict[str, Any] | None]

   Upload external-table sources to S3 and register Redshift Spectrum tables.

.. py:method:: benchbox.platforms.redshift.RedshiftAdapter.load_data(benchmark, connection: Any, data_dir: Path) -> tuple[dict[str, int], float, dict[str, Any] | None]

   Load data using Redshift COPY command with S3 integration.

.. py:method:: benchbox.platforms.redshift.RedshiftAdapter.execute_query(connection: Any, query: str, query_id: str, benchmark_type: str | None = None, scale_factor: float | None = None, validate_row_count: bool = True, stream_id: int | None = None) -> dict[str, Any]

   Execute via the core cursor primitive, then attach Redshift plan fields.

   Enumerated deltas vs ``CursorValidationQueryExecutionMixin`` (all hooks):
   query tags: none; statistics: ``_get_query_statistics`` / ``pg_last_query_id``;
   plan capture: post-execute ``_merge_plan_capture_into_result``;
   rollback: none; result digest: none; cursor ownership: mixin-owned;
   query rewrite: base adapter; job APIs: none.

.. py:method:: benchbox.platforms.redshift.RedshiftAdapter.validate_session_cache_control(connection: Any) -> dict[str, Any]

   Validate that session-level cache control settings were successfully applied.

   :param connection: Active Redshift database connection

   :returns:     - validated: bool - Whether validation passed - cache_disabled: bool - Whether cache is actually disabled - settings: dict - Actual session settings - warnings: list[str] - Any validation warnings - errors: list[str] - Any validation errors
   :rtype: dict with

   :raises ConfigurationError: If cache control validation fails and strict_validation=True

.. py:method:: benchbox.platforms.redshift.RedshiftAdapter.gather_statistics(connection: Any, table_names: list[str]) -> tuple[str, int]

   Statistics-phase hook: with auto_analyze, stats were already built during load.

   The S3 load path runs ANALYZE right after each table's COPY when
   auto_analyze is enabled (the default), so the statistics phase reports
   that attribution instead of double-building. With auto_analyze
   disabled, fall back to the explicit per-table ANALYZE default.

.. py:method:: benchbox.platforms.redshift.RedshiftAdapter.vacuum_table(connection: Any, table_name: str) -> None

   Run VACUUM on table for space reclamation.

.. py:method:: benchbox.platforms.redshift.RedshiftAdapter.get_query_plan(connection: Any, query: str) -> str | None

   Get query execution plan for analysis.

Static member inventory
-----------------------

.. py:property:: benchbox.platforms.redshift.RedshiftAdapter.platform_name

   Returns this adapter's registered platform identifier for selection, metadata, and capability lookup.

.. py:staticmethod:: benchbox.platforms.redshift.RedshiftAdapter.add_cli_arguments(parser) -> None

   Add Redshift-specific CLI arguments.

.. py:classmethod:: benchbox.platforms.redshift.RedshiftAdapter.from_config(config: dict[str, Any])

   Create Redshift adapter from unified configuration.

.. py:method:: benchbox.platforms.redshift.RedshiftAdapter.get_platform_info(self, connection: Any=None) -> dict[str, Any]

   Get Redshift platform information.

   Captures comprehensive Redshift configuration including:
   Deployment type (serverless vs provisioned)
   Capacity configuration (RPUs for serverless, node type/count for provisioned)
   Redshift version
   WLM (Workload Management) configuration
   AWS region
   Encryption and security settings

   Uses fallback chain: AWS API → SQL queries → hostname parsing
   Gracefully degrades if permissions are insufficient or AWS credentials unavailable.

.. py:method:: benchbox.platforms.redshift.RedshiftAdapter.get_normalized_result_metadata(self, *, connection: Any | None=None, platform_info: Mapping[str, Any] | None=None) -> dict[str, Any]

   Return Redshift-specific normalized cloud/runtime metadata.

.. py:method:: benchbox.platforms.redshift.RedshiftAdapter.get_target_dialect(self) -> str

   Return the target SQL dialect for Redshift.

.. py:method:: benchbox.platforms.redshift.RedshiftAdapter.check_server_database_exists(self, **connection_config) -> bool

   Check if database exists in Redshift cluster.

   Connects to admin database to query pg_database for the target database.

.. py:method:: benchbox.platforms.redshift.RedshiftAdapter.drop_database(self, **connection_config) -> None

   Drop database in Redshift cluster.

   Connects to admin database to drop the target database.

   .. rubric:: Notes

   DROP DATABASE must run with autocommit enabled.
   Redshift doesn't support IF EXISTS for DROP DATABASE, so we check first.
   If DROP DATABASE fails with SQLSTATE 55006 (database still has active
   connections), the method terminates backends again and retries on a
   fresh connection. redshift_connector v2.1.x enters an aborted
   transaction state after a failed DDL even with autocommit=True,
   causing any subsequent DDL on the same connection to fail with
   error 25001. Opening a new connection guarantees clean driver state.

.. py:method:: benchbox.platforms.redshift.RedshiftAdapter.validate_external_table_requirements(self) -> None

   Validate prerequisites for Redshift external table mode.

.. py:method:: benchbox.platforms.redshift.RedshiftAdapter.configure_for_benchmark(self, connection: Any, benchmark_type: str) -> None

   Apply Redshift-specific optimizations based on benchmark type.

.. py:method:: benchbox.platforms.redshift.RedshiftAdapter.analyze_table(self, connection: Any, table_name: str) -> None

   Run ANALYZE on table for query optimization.

   Raises on failure (does not swallow) so the opt-in statistics phase's
   gather_statistics() -> run_statistics_phase() caller can detect and
   record a real failure as status=FAILED. Not reached when auto_analyze
   is enabled - gather_statistics() overrides to report "auto-on-load"
   before this method is ever called.

.. py:method:: benchbox.platforms.redshift.RedshiftAdapter.get_query_plan_parser(self)

   Get Redshift query plan parser.

.. py:method:: benchbox.platforms.redshift.RedshiftAdapter.close_connection(self, connection: Any) -> None

   Close Redshift connection.

.. py:method:: benchbox.platforms.redshift.RedshiftAdapter.generate_tuning_clause(self, table_tuning) -> str

   Generate Redshift-specific tuning clauses for CREATE TABLE statements.

   Redshift supports:
   DISTSTYLE (EVEN | KEY | ALL) DISTKEY (column)
   SORTKEY (column1, column2, ...) or INTERLEAVED SORTKEY (column1, column2, ...)

   :param table_tuning: The tuning configuration for the table

   :returns: SQL clause string to be appended to CREATE TABLE statement

.. py:method:: benchbox.platforms.redshift.RedshiftAdapter.apply_table_tunings(self, table_tuning, connection: Any) -> None

   Apply tuning configurations to a Redshift table.

   Redshift tuning approach:
   DISTRIBUTION: Handled via DISTSTYLE/DISTKEY in CREATE TABLE
   SORTING: Handled via SORTKEY in CREATE TABLE
   Post-creation optimizations via ANALYZE and VACUUM

   :param table_tuning: The tuning configuration to apply
   :param connection: Redshift connection

   :raises ValueError: If the tuning configuration is invalid for Redshift

.. py:method:: benchbox.platforms.redshift.RedshiftAdapter.apply_unified_tuning(self, unified_config: UnifiedTuningConfiguration, connection: Any) -> None

   Apply unified tuning configuration to Redshift.

   :param unified_config: Unified tuning configuration to apply
   :param connection: Redshift connection

.. py:method:: benchbox.platforms.redshift.RedshiftAdapter.apply_platform_optimizations(self, platform_config: PlatformOptimizationConfiguration, connection: Any) -> None

   Apply Redshift-specific platform optimizations.

   Redshift optimizations include:
   Workload Management (WLM) queue configuration
   Query group settings for resource allocation
   Compression encoding optimization
   Statistics collection and maintenance

   :param platform_config: Platform optimization configuration
   :param connection: Redshift connection

.. py:attribute:: benchbox.platforms.redshift.RedshiftAdapter.driver_isolation_capability

   Declares whether this adapter can run through an isolated driver runtime; the value controls runtime-resolution support.

.. py:attribute:: benchbox.platforms.redshift.RedshiftAdapter.supports_external_tables

   Advertises whether the adapter implements external-table creation.

.. py:attribute:: benchbox.platforms.redshift.RedshiftAdapter.plan_capture_phase_eligible

   Advertises whether benchmark plan capture is available for this adapter.

.. py:method:: benchbox.platforms.redshift.RedshiftAdapter.apply_constraint_configuration(primary_key_config: PrimaryKeyConfiguration, foreign_key_config: ForeignKeyConfiguration, connection: Any) -> None

   Logs informational messages for enabled primary-key and foreign-key settings.
   This hook executes no SQL and does not use ``connection``. Table-creation
   hooks handle any platform-supported constraint DDL.

.. py:method:: benchbox.core.benchmark_mixins.CursorValidationQueryExecutionMixin.execute_query(self, connection: Any, query: str, query_id: str, benchmark_type: str | None=None, scale_factor: float | None=None, validate_row_count: bool=True, stream_id: int | None=None) -> dict[str, Any]

   Execute query via DBAPI cursor with optional row-count validation.

Constructor Configuration
~~~~~~~~~~~~~~~~~~~~~~~~~

Pass keyword configuration through ``RedshiftAdapter(**config)``.

- ``host``, ``username`` and ``password`` supply connection identity;
  ``cluster_identifier`` is optional. ``port`` defaults to 5439 and
  ``database`` to ``"dev"``.
- ``s3_bucket`` and ``iam_role`` are optional loading settings; ``s3_prefix``
  defaults to ``"benchbox-data"``. An S3 ``staging_root`` overrides the derived
  bucket/prefix.
- ``aws_access_key_id`` and ``aws_secret_access_key`` are optional credentials;
  ``aws_region`` defaults to ``"us-east-1"``.
- ``wlm_query_slot_count`` defaults to one.
- ``compupdate`` defaults to ``"PRESET"`` and accepts ``"PRESET"``, ``"ON"``
  or ``"OFF"`` after uppercasing; other values raise ``ValueError``.
- ``auto_vacuum`` and ``auto_analyze`` default to ``True``.

Configuration Examples
----------------------

IAM Role Authentication (Recommended)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: bash

    aws iam create-role --role-name RedshiftCopyRole \
        --assume-role-policy-document '{
            "Version": "2012-10-17",
            "Statement": [{
                "Effect": "Allow",
                "Principal": {"Service": "redshift.amazonaws.com"},
                "Action": "sts:AssumeRole"
            }]
        }'

    aws iam attach-role-policy --role-name RedshiftCopyRole \
        --policy-arn arn:aws:iam::aws:policy/AmazonS3ReadOnlyAccess

    Amazon Redshift modify-cluster-iam-roles \
        --cluster-identifier my-cluster \
        --add-iam-roles arn:aws:iam::123456789:role/RedshiftCopyRole

.. code-block:: python

    adapter = RedshiftAdapter(
        host="my-cluster.123456.us-east-1.redshift.amazonaws.com",
        username="admin",
        password="password",
        s3_bucket="my-data-bucket",
        iam_role="arn:aws:iam::123456789:role/RedshiftCopyRole"
    )

Access Key Authentication
~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    adapter = RedshiftAdapter(
        host="my-cluster.123456.us-east-1.redshift.amazonaws.com",
        username="admin",
        password="password",
        s3_bucket="my-data-bucket",
        aws_access_key_id="AKIAIOSFODNN7EXAMPLE",
        aws_secret_access_key="wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
        aws_region="us-east-1"
    )

Workload Management (WLM)
~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    adapter = RedshiftAdapter(
        host="my-cluster.123456.us-east-1.redshift.amazonaws.com",
        username="admin",
        password="password",
        wlm_query_slot_count=3
    )

Data Loading
------------

Via S3 COPY (Recommended)
~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from benchbox.platforms.redshift import RedshiftAdapter
    from benchbox.tpch import TPCH
    from pathlib import Path

    adapter = RedshiftAdapter(
        host="my-cluster.123456.us-east-1.redshift.amazonaws.com",
        username="admin",
        password="password",
        database="benchbox",
        s3_bucket="my-redshift-staging",
        s3_prefix="benchbox/tpch",
        iam_role="arn:aws:iam::123456789:role/RedshiftCopyRole"
    )

    benchmark = TPCH(scale_factor=1.0)
    data_dir = Path("./tpch_data")
    benchmark.generate_data(data_dir)

    conn = adapter.create_connection()
    table_stats, load_time = adapter.load_data(benchmark, conn, data_dir)

    print(f"Loaded {sum(table_stats.values()):,} rows in {load_time:.2f}s")

Direct Loading (Small Datasets)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    adapter = RedshiftAdapter(
        host="my-cluster.123456.us-east-1.redshift.amazonaws.com",
        username="admin",
        password="password"
    )

Advanced Features
-----------------

Distribution Keys
~~~~~~~~~~~~~~~~~

.. code-block:: python

    cursor.execute("""
        CREATE TABLE orders (
            o_orderkey BIGINT,
            o_custkey BIGINT,
            o_orderstatus CHAR(1),
            o_totalprice DECIMAL(15,2),
            o_orderdate DATE
        )
        DISTSTYLE KEY
        DISTKEY (o_custkey)
        SORTKEY (o_orderdate)
    """)

Sort Keys
~~~~~~~~~

Illustrative SQL fragments; supply complete table definitions before execution.

.. code-block:: sql

    CREATE TABLE lineitem (...)
    SORTKEY (l_shipdate, l_orderkey)

    CREATE TABLE lineitem (...)
    INTERLEAVED SORTKEY (l_shipdate, l_orderkey, l_partkey)

Compression
~~~~~~~~~~~

.. code-block:: python

    adapter = RedshiftAdapter(
        host="my-cluster...",
        compression_encoding="AUTO"
    )

    cursor.execute("""
        SELECT
            "column",
            type,
            encoding
        FROM pg_table_def
        WHERE tablename = 'lineitem'
    """)

Vacuum and Analyze
~~~~~~~~~~~~~~~~~~

.. code-block:: python

    adapter.vacuum_table(conn, "lineitem")
    adapter.analyze_table(conn, "lineitem")

    adapter = RedshiftAdapter(
        auto_vacuum=True,
        auto_analyze=True
    )

Best Practices
--------------

Distribution Strategy
~~~~~~~~~~~~~~~~~~~~~

1. **Choose appropriate DISTSTYLE**:

   .. code-block:: sql

       CREATE TABLE region (...) DISTSTYLE EVEN

       CREATE TABLE orders (...) DISTSTYLE KEY DISTKEY (o_custkey)

       CREATE TABLE nation (...) DISTSTYLE ALL

Sort Keys
~~~~~~~~~

1. **Use compound sort keys** for range/equality filters:

   .. code-block:: sql

       SORTKEY (l_shipdate, l_orderkey)

2. **Use interleaved for multiple filter combinations**:

   .. code-block:: sql

       INTERLEAVED SORTKEY (l_shipdate, l_orderkey, l_partkey)

Data Loading
~~~~~~~~~~~~

1. **Use COPY from S3** for best performance
2. **Load compressed files** (GZIP recommended)
3. **Use manifest files** for multiple files
4. **Run ANALYZE after loading**

Cost Optimization
~~~~~~~~~~~~~~~~~

1. **Use reserved instances** for predictable workloads
2. **Pause clusters** when not in use
3. **Use concurrency scaling** for burst workloads
4. **Monitor query performance** with system tables

Common Issues
-------------

Connection Timeout
~~~~~~~~~~~~~~~~~~

**Problem**: Cannot connect to cluster

**Solutions**:

.. code-block:: bash

    Amazon Redshift describe-clusters --cluster-identifier my-cluster

    psql -h my-cluster.123456.us-east-1.redshift.amazonaws.com \
         -U admin -d dev -p 5439

S3 COPY Errors
~~~~~~~~~~~~~~

**Problem**: COPY command fails

**Solutions**:

.. code-block:: python

    cursor.execute("""
        SELECT * FROM stl_load_errors
        ORDER BY starttime DESC
        LIMIT 10
    """)

Slow Query Performance
~~~~~~~~~~~~~~~~~~~~~~

**Problem**: Queries slower than expected

**Solutions**:

.. code-block:: python

    plan = adapter.get_query_plan(conn, query)

    cursor.execute("""
        SELECT
            TRIM(t.name) AS table,
            TRIM(c.name) AS column,
            c.distkey
        FROM stv_tbl_perm t
        JOIN pg_attribute a ON a.attrelid = t.id
        JOIN pg_class c ON c.oid = t.id
        WHERE c.distkey = TRUE
    """)

    cursor.execute("""
        SELECT * FROM svv_table_info
        WHERE "table" = 'lineitem'
    """)

    adapter.vacuum_table(conn, "lineitem")
    adapter.analyze_table(conn, "lineitem")

See Also
--------

Platform Documentation
~~~~~~~~~~~~~~~~~~~~~~

- :doc:`/platforms/platform-selection-guide` - Choosing Redshift vs other platforms
- :doc:`/platforms/quick-reference` - Quick setup for all platforms
- :doc:`/platforms/comparison-matrix` - Feature comparison

API Reference
~~~~~~~~~~~~~

- :doc:`snowflake` - Snowflake adapter
- :doc:`databricks` - Databricks adapter
- :doc:`bigquery` - BigQuery adapter
- :doc:`../base` - Base benchmark interface
- :doc:`../index` - Python API overview

External Resources
~~~~~~~~~~~~~~~~~~

- `Redshift Documentation <https://docs.aws.amazon.com/redshift/>`_ - Official Redshift docs
- `Best Practices <https://docs.aws.amazon.com/redshift/latest/dg/best-practices.html>`_ - Performance optimization
- `Distribution Styles <https://docs.aws.amazon.com/redshift/latest/dg/c_choosing_dist_sort.html>`_ - Distribution guidance
- `COPY Command <https://docs.aws.amazon.com/redshift/latest/dg/r_COPY.html>`_ - Data loading reference
