Benchmark APIs
==============

.. tags:: reference, python-api

Complete reference for using benchmark classes programmatically in Python.

Overview
--------

BenchBox provides Python APIs for all supported benchmarks, allowing you to:

- Instantiate benchmarks with custom scale factors
- Generate data programmatically
- Access benchmark queries with dialect translation
- Run benchmarks on any supported platform
- Customize execution parameters

All benchmark classes extend :doc:`../base` and share a common interface.
Shared generation and query methods are documented in :doc:`mixins`;
TPC-H query variants are documented in :doc:`tpchavoc`.

Available Benchmarks
--------------------

Standard Benchmarks
~~~~~~~~~~~~~~~~~~~

.. list-table::
   :header-rows: 1
   :widths: 25 50 25

   * - Benchmark
     - Description
     - Query Count
   * - :doc:`tpch`
     - TPC-H analytical queries
     - 22 queries
   * - :doc:`tpcds`
     - TPC-DS decision support queries
     - 99 queries
   * - TPC-DI
     - Data integration benchmark
     - ETL pipelines
   * - SSB
     - Star Schema Benchmark
     - 13 queries
   * - ClickBench
     - Real-world analytics
     - 43 queries
   * - :doc:`coffeeshop`
     - Coffee-shop transaction analytics
     - 11 queries

Quick Start
-----------

Basic Usage
~~~~~~~~~~~

.. code-block:: python

    from benchbox.tpch import TPCH
    from benchbox.platforms.duckdb import DuckDBAdapter

    benchmark = TPCH(scale_factor=1.0)

    data_files = benchmark.generate_data()

    queries = benchmark.get_queries()

    adapter = DuckDBAdapter()
    results = benchmark.run_with_platform(adapter)

Common Patterns
---------------

Data Generation
~~~~~~~~~~~~~~~

.. code-block:: python

    from benchbox.tpch import TPCH
    from pathlib import Path

    benchmark = TPCH(scale_factor=0.1, output_dir="./data")
    data_files = benchmark.generate_data()

    for table_name, file_path in benchmark.tables.items():
        size_mb = Path(file_path).stat().st_size / 1024 / 1024
        print(f"{table_name}: {size_mb:.2f} MB")

Query Access
~~~~~~~~~~~~

.. code-block:: python

    queries = benchmark.get_queries()
    print(f"Total queries: {len(queries)}")

    q1 = benchmark.get_query(1)
    print(q1)

    q1_bq = benchmark.get_query(1, dialect="bigquery")
    q1_sf = benchmark.get_query(1, dialect="snowflake")

Platform Execution
~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from benchbox.tpch import TPCH
    from benchbox.platforms.duckdb import DuckDBAdapter
    from benchbox.platforms.clickhouse import ClickHouseAdapter

    benchmark = TPCH(scale_factor=1.0)

    duckdb_adapter = DuckDBAdapter()
    duckdb_results = benchmark.run_with_platform(duckdb_adapter)

    clickhouse_adapter = ClickHouseAdapter(host="localhost")
    clickhouse_results = benchmark.run_with_platform(clickhouse_adapter)

    print(f"DuckDB: {duckdb_results.total_execution_time:.2f}s")
    print(f"ClickHouse: {clickhouse_results.total_execution_time:.2f}s")

Custom Scale Factors
~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    small_bench = TPCH(scale_factor=0.01)

    standard_bench = TPCH(scale_factor=1.0)

    large_bench = TPCH(scale_factor=100.0)

Result Analysis
~~~~~~~~~~~~~~~

.. code-block:: python

    from benchbox.tpch import TPCH
    from benchbox.platforms.duckdb import DuckDBAdapter

    benchmark = TPCH(scale_factor=1.0)
    adapter = DuckDBAdapter()
    results = benchmark.run_with_platform(adapter)

    print(f"Benchmark: {results.benchmark_name}")
    print(f"Platform: {results.platform}")
    print(f"Total time: {results.total_execution_time:.2f}s")
    print(f"Average query time: {results.average_query_time:.3f}s")
    print(f"Success rate: {results.successful_queries}/{results.total_queries}")

    for qr in results.query_results:
        if qr.status == "SUCCESS":
            print(f"{qr.query_id}: {qr.execution_time:.3f}s ({qr.row_count} rows)")
        else:
            print(f"{qr.query_id}: FAILED - {qr.error_message}")

    results.to_json_file("benchmark_results.json")

Advanced Usage
--------------

Query Streams
~~~~~~~~~~~~~

.. code-block:: python

    from benchbox.tpch import TPCH

    benchmark = TPCH(scale_factor=1.0)

    streams = benchmark.generate_streams(
        num_streams=5,
        rng_seed=42,
        streams_output_dir="./streams"
    )

    for stream_id in range(1, 6):
        info = benchmark.get_stream_info(stream_id)
        print(f"Stream {stream_id}: {len(info['queries'])} queries")

Custom Parameters
~~~~~~~~~~~~~~~~~

.. code-block:: python

    q1_custom = benchmark.get_query(
        query_id=1,
        seed=42,
        scale_factor=10.0
    )

Schema Access
~~~~~~~~~~~~~

.. code-block:: python

    schema = benchmark.get_schema()
    for table in schema:
        print(f"Table: {table['name']}")
        print(f"  Columns: {len(table['columns'])}")
        for col in table['columns']:
            print(f"    {col['name']}: {col['type']}")

    create_sql = benchmark.get_create_tables_sql(dialect="duckdb")
    print(create_sql)

Error Handling
~~~~~~~~~~~~~~

.. code-block:: python

    from benchbox.tpch import TPCH
    from benchbox.platforms.duckdb import DuckDBAdapter

    try:
        benchmark = TPCH(scale_factor=-1.0)
    except ValueError as e:
        print(f"Error: {e}")

    try:
        benchmark = TPCH(scale_factor=1.0)
        query = benchmark.get_query(999)
    except ValueError as e:
        print(f"Error: {e}")

    try:
        adapter = DuckDBAdapter(database_path="/invalid/path/db.duckdb")
        results = benchmark.run_with_platform(adapter)
    except Exception as e:
        print(f"Platform error: {e}")

Best Practices
--------------

Scale Factor Selection
~~~~~~~~~~~~~~~~~~~~~~

1. **Development and CI**: Use SF=0.01 to 0.1

   .. code-block:: python

       dev_benchmark = TPCH(scale_factor=0.01)

2. **Testing and validation**: Use SF=1.0

   .. code-block:: python

       test_benchmark = TPCH(scale_factor=1.0)

3. **Performance benchmarking**: Use SF=10 to 100

   .. code-block:: python

       perf_benchmark = TPCH(scale_factor=10.0)

Data Management
~~~~~~~~~~~~~~~

1. **Reuse generated data**:

   .. code-block:: python

       benchmark = TPCH(scale_factor=1.0, output_dir="./data/tpch_sf1")
       benchmark.generate_data()

       benchmark2 = TPCH(scale_factor=1.0, output_dir="./data/tpch_sf1")

2. **Clean up after testing**:

   .. code-block:: python

       import shutil
       from pathlib import Path

       data_dir = Path("./data/tpch_sf1")
       if data_dir.exists():
           shutil.rmtree(data_dir)

Result Validation
~~~~~~~~~~~~~~~~~

1. **Check row counts**:

   .. code-block:: python

       expected_rows = {
           "LINEITEM": 6001215,
           "ORDERS": 1500000,
           "CUSTOMER": 150000,
           "PART": 200000,
           "SUPPLIER": 10000,
           "PARTSUPP": 800000,
           "NATION": 25,
           "REGION": 5,
       }

       for qr in results.query_results:
           if qr.query_id in expected_rows:
               assert qr.row_count == expected_rows[qr.query_id]

2. **Verify query results**:

   .. code-block:: python

       baseline = BenchmarkResults.from_json_file("baseline.json")
       current = results

       for qr_current in current.query_results:
           qr_baseline = next(
               (qr for qr in baseline.query_results
                if qr.query_id == qr_current.query_id),
               None
           )
           if qr_baseline:
               assert qr_current.row_count == qr_baseline.row_count

See Also
--------

Conceptual Documentation
~~~~~~~~~~~~~~~~~~~~~~~~

- :doc:`/concepts/architecture` - System architecture overview
- :doc:`/concepts/workflow` - Common benchmarking workflows
- :doc:`/concepts/data-model` - Result data structures

API References
~~~~~~~~~~~~~~

- :doc:`../base` - Base benchmark interface
- :doc:`../results` - Results API
- :doc:`../index` - Python API overview

Platform Adapters
~~~~~~~~~~~~~~~~~

- :doc:`../platforms/duckdb` - DuckDB adapter
- :doc:`../platforms/clickhouse` - ClickHouse adapter
- :doc:`../platforms/databricks` - Databricks adapter
- :doc:`../platforms/bigquery` - BigQuery adapter

Benchmark Guides
~~~~~~~~~~~~~~~~

- :doc:`/benchmarks/tpc-h` - TPC-H guide
- :doc:`/benchmarks/tpc-ds` - TPC-DS guide
- :doc:`/benchmarks/clickbench` - ClickBench guide
- :doc:`/benchmarks/index` - Benchmark catalog

External Resources
~~~~~~~~~~~~~~~~~~

- `TPC Official Website <http://www.tpc.org>`_ - TPC benchmark specifications
- `TPC-H Specification <http://www.tpc.org/tpch>`_ - Official TPC-H spec
- `TPC-DS Specification <http://www.tpc.org/tpcds>`_ - Official TPC-DS spec
