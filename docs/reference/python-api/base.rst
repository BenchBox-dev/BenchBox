Base Benchmark API
==================

.. tags:: reference, python-api, contributor

The ``benchbox.base`` module provides the foundational abstract class that all benchmarks inherit from.

Overview
--------

Every benchmark in BenchBox extends :class:`BaseBenchmark`, which provides a standardized interface for:

- Data generation and schema setup
- Query execution and timing
- Platform adapter integration
- SQL dialect translation
- Results collection and formatting

This abstraction ensures consistent behavior across all benchmark implementations (TPC-H, TPC-DS, ClickBench, etc.).

Runtime Contract Notes
----------------------

The lifecycle runner expects loader-resolved benchmarks to provide a shared runtime contract:

- ``generate_data``
- ``get_queries`` / ``get_query``
- ``create_enhanced_benchmark_result``
- ``create_minimal_benchmark_result``
- ``validate_preflight`` / ``validate_manifest`` / ``validate_loaded_data``

Compatibility boundaries:

- Public benchmark implementations should inherit ``benchbox.base.BaseBenchmark``.
- ``benchbox.core.base_benchmark.BaseBenchmark`` remains temporarily for internal compatibility and delegates result
  construction through the same shared factory path.
- ``create_enhanced_benchmark_result()`` preserves compatibility with legacy kwargs such as
  ``table_statistics`` and ``data_loading_time`` while exporting canonical per-table load timing as
  ``table_statistics.<table>.load_time_ms`` when available.

Quick Example
-------------

.. code-block:: python

    from benchbox.tpch import TPCH
    from benchbox.platforms import DuckDBAdapter

    # Create benchmark instance
    benchmark = TPCH(scale_factor=0.01)

    # Generate data files
    data_files = benchmark.generate_data()

    # Run with platform adapter
    adapter = DuckDBAdapter()
    results = benchmark.run_with_platform(adapter)

    print(f"Completed {results.successful_queries}/{results.total_queries} queries")
    print(f"Average query time: {results.average_query_time:.3f}s")

Core Classes
------------

.. autoclass:: benchbox.base.BaseBenchmark
   :members:
   :undoc-members:
   :show-inheritance:
   :special-members: __init__

Key Methods
-----------

Data Generation
~~~~~~~~~~~~~~~

.. automethod:: benchbox.base.BaseBenchmark.generate_data
   :noindex:

   **Required override** - Each benchmark implements data generation logic.

   Returns list of paths to generated data files (Parquet, CSV, etc.).

Query Access
~~~~~~~~~~~~

.. automethod:: benchbox.base.BaseBenchmark.get_queries
   :noindex:

   **Required override** - Returns all queries for the benchmark.

   Example return value:

   .. code-block:: python

       {
           "q1": "SELECT ...",
           "q2": "SELECT ...",
           # ...
       }

.. automethod:: benchbox.base.BaseBenchmark.get_query
   :noindex:

   **Required override** - Get single query by ID with optional parameters.

   Example:

   .. code-block:: python

       query_sql = benchmark.get_query("q1", params={"date": "1998-09-02"})

Database Setup
~~~~~~~~~~~~~~

.. automethod:: benchbox.base.BaseBenchmark.setup_database
   :noindex:

   Sets up database schema and loads data. Automatically calls :meth:`generate_data` if needed.

Execution
~~~~~~~~~

.. automethod:: benchbox.base.BaseBenchmark.run_query
   :noindex:

   Execute single query and return detailed results including timing and row counts.

.. automethod:: benchbox.base.BaseBenchmark.run_benchmark
   :noindex:

   Execute complete benchmark suite with optional filtering by query IDs.

   Example:

   .. code-block:: python

       # Run all queries
       results = benchmark.run_benchmark(connection)

       # Run specific queries only
       results = benchmark.run_benchmark(
           connection,
           query_ids=["q1", "q3", "q7"]
       )

.. automethod:: benchbox.base.BaseBenchmark.run_with_platform
   :noindex:

   **Recommended entry point** - Run benchmark using platform adapter for optimized execution.

   This method delegates to the platform adapter's :meth:`run_benchmark` implementation,
   which handles:

   - Connection management
   - Data loading optimizations (bulk loading, parallel ingestion)
   - Query execution with retry logic
   - Results collection and validation

   Example:

   .. code-block:: python

       from benchbox.tpcds import TPCDS
       from benchbox.platforms import DatabricksAdapter

       benchmark = TPCDS(scale_factor=1)
       adapter = DatabricksAdapter(
           host="https://your-workspace.cloud.databricks.com",
           token="your-token",
           http_path="/sql/1.0/warehouses/abc123"
       )

       results = benchmark.run_with_platform(
           adapter,
           query_subset=["q1", "q2", "q3"]  # Optional filtering
       )

SQL Translation
~~~~~~~~~~~~~~~

.. automethod:: benchbox.base.BaseBenchmark.translate_query
   :noindex:

   Translate query to different SQL dialect using sqlglot.

   Supported dialects: postgres, mysql, sqlite, duckdb, snowflake, bigquery, redshift, clickhouse, databricks, and more.

   .. note::
      **Dialect Translation vs Platform Adapters**: BenchBox can translate queries to many SQL dialects,
      but this doesn't mean platform adapters exist for all those databases. BenchBox supports 30+ platforms
      including DuckDB, SQLite, PostgreSQL, Databricks, BigQuery, Redshift, Snowflake, Trino, Athena, and more.
      See :doc:`/platforms/index` for the full list or :doc:`/development/roadmap` for planned platforms (MySQL, etc.).

   Example:

   .. code-block:: python

       # Translate TPC-H query to Snowflake dialect (fully supported)
       snowflake_sql = benchmark.translate_query("q1", dialect="snowflake")

       # Translate to BigQuery (fully supported)
       bigquery_sql = benchmark.translate_query("q1", dialect="bigquery")

       # Translate to PostgreSQL dialect (translation only - adapter not yet available)
       postgres_sql = benchmark.translate_query("q1", dialect="postgres")

Results Creation
~~~~~~~~~~~~~~~~

.. automethod:: benchbox.base.BaseBenchmark.create_enhanced_benchmark_result
   :noindex:

   Create standardized :class:`~benchbox.core.results.models.BenchmarkResults` object with structured metadata.

   Used internally by platform adapters to ensure consistent result formatting.

Properties
----------

.. autoattribute:: benchbox.base.BaseBenchmark.benchmark_name
   :noindex:
   :annotation: str

   Human-readable benchmark name (e.g., "TPC-H", "ClickBench").

.. autoattribute:: benchbox.base.BaseBenchmark.scale_factor
   :annotation: float

   Data scale factor (1.0 = standard size, 0.01 = 1% size, 10 = 10x size).

.. autoattribute:: benchbox.base.BaseBenchmark.output_dir
   :annotation: Path

   Directory where generated data files are stored.

Utility Methods
---------------

.. automethod:: benchbox.base.BaseBenchmark.format_results
   :noindex:

   Format benchmark results dictionary into human-readable string.

.. automethod:: benchbox.base.BaseBenchmark.get_data_source_benchmark
   :noindex:

   Returns name of source benchmark if this benchmark reuses data from another.

   For example, ``Primitives`` benchmark reuses TPC-H data, so it returns ``"tpch"``.

Best Practices
--------------

1. **Always use platform adapters** - Call :meth:`run_with_platform` instead of direct :meth:`run_benchmark` for production use. Platform adapters provide optimized data loading and query execution.

2. **Handle scale factors carefully** - Scale factors ≥1 must be integers. Use 0.1, 0.01, etc. for small-scale testing.

3. **Check data generation** - Call :meth:`generate_data` explicitly if you need to inspect or manipulate data files before loading.

4. **Use query subsets for debugging** - Pass ``query_subset=["q1"]`` to test single queries during development.

5. **Use SQL translation** - Call :meth:`translate_query` to adapt queries to platform-specific dialects when needed.

See Also
--------

- :doc:`/usage/getting-started` - Getting started guide with complete examples
- :doc:`/platforms/platform-selection-guide` - Platform adapter documentation
- :doc:`/benchmarks/README` - Available benchmark implementations
- :doc:`/usage/api-reference` - High-level API overview
