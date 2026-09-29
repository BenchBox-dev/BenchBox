TPC-DS Benchmark API
====================

.. tags:: reference, python-api, tpc-ds

Complete Python API reference for the TPC-DS benchmark.

Overview
--------

The TPC-DS benchmark models a retail product supplier with 99 complex decision support queries. It includes advanced SQL features like window functions, complex joins, and subqueries.

**Key Features**:

- 99 decision support queries with varying complexity
- 25 tables modeling retail operations
- Advanced SQL features (window functions, CTEs, complex joins)
- Query variants for different data distributions
- Official TPC-DS specification compliance
- Scale factors from SF=1 to 100000+

Quick Start
-----------

.. code-block:: python

    from benchbox.tpcds import TPCDS
    from benchbox.platforms.duckdb import DuckDBAdapter

    # Create benchmark
    benchmark = TPCDS(scale_factor=1.0)

    # Generate data
    benchmark.generate_data()

    # Run on platform
    adapter = DuckDBAdapter()
    results = benchmark.run_with_platform(adapter)

    print(f"Completed in {results.total_execution_time:.2f}s")

API Reference
-------------

TPCDS Class
~~~~~~~~~~~

.. autoclass:: benchbox.tpcds.TPCDS
   :members:
   :inherited-members:
   :show-inheritance:

Constructor
~~~~~~~~~~~

.. code-block:: python

    TPCDS(
        scale_factor: float = 1.0,
        output_dir: Optional[Union[str, Path]] = None,
        **kwargs
    )

Parameters:

- **scale_factor** (float): Data size multiplier. SF=1.0 generates ~1GB of data. Range: 1 to 100000+
- **output_dir** (str|Path, optional): Directory for generated data files. Default: temporary directory
- **kwargs**: Additional options (e.g., parallel=True, update_percentage=0)

Raises:

- **ValueError**: If scale_factor is not positive
- **TypeError**: If scale_factor is not a number

Methods
-------

generate_data()
~~~~~~~~~~~~~~~

Generate TPC-DS benchmark data.

.. code-block:: python

    data_files = benchmark.generate_data()
    print(f"Generated {len(data_files)} table files")

Returns:
    List[Union[str, Path]]: Paths to generated data files

get_query(query_id, \*, params=None, seed=None, scale_factor=None, dialect=None)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Get a specific TPC-DS query.

.. code-block:: python

    # Get query 1
    q1 = benchmark.get_query(1)

    # Get with dialect translation
    q1_bq = benchmark.get_query(1, dialect="bigquery")

    # Get with custom parameters
    q1_param = benchmark.get_query(1, seed=42, scale_factor=10.0)

Parameters:

- **query_id** (int): Query ID (1-99)
- **params** (dict, optional): Query parameters (legacy, mostly ignored)
- **seed** (int, optional): RNG seed for parameter generation
- **scale_factor** (float, optional): Override default scale factor
- **dialect** (str, optional): Target SQL dialect (duckdb, bigquery, snowflake, etc.)

Returns:
    str: Query SQL text

Raises:

- **ValueError**: If query_id not in range 1-99
- **TypeError**: If query_id is not an integer

get_queries(dialect=None, base_dialect=None)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Get all TPC-DS queries.

.. code-block:: python

    # Get all queries
    queries = benchmark.get_queries()
    print(f"Total queries: {len(queries)}")

    # Get with dialect translation
    queries_bq = benchmark.get_queries(dialect="bigquery")

Parameters:

- **dialect** (str, optional): Target SQL dialect
- **base_dialect** (str, optional): Source dialect for translation

Returns:
    Dict[str, str]: Dictionary mapping query IDs to SQL text

get_available_queries()
~~~~~~~~~~~~~~~~~~~~~~~

Get list of available query IDs.

.. code-block:: python

    query_ids = benchmark.get_available_queries()
    print(f"Available queries: {query_ids}")

Returns:
    List[int]: List of query IDs (1-99)

get_available_tables()
~~~~~~~~~~~~~~~~~~~~~~

Get list of available table names.

.. code-block:: python

    tables = benchmark.get_available_tables()
    print(f"Tables: {', '.join(tables)}")

Returns:
    List[str]: List of table names

get_schema()
~~~~~~~~~~~~

Get TPC-DS schema information.

.. code-block:: python

    schema = benchmark.get_schema()
    for table in schema:
        print(f"{table['name']}: {len(table['columns'])} columns")

Returns:
    List[dict]: List of table definitions with columns and types

get_create_tables_sql(dialect="standard", tuning_config=None)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Get CREATE TABLE SQL for all tables.

.. code-block:: python

    # Standard SQL
    create_sql = benchmark.get_create_tables_sql()

    # With dialect
    create_sql_bq = benchmark.get_create_tables_sql(dialect="bigquery")

    # With tuning configuration
    from benchbox.core.tuning.interface import UnifiedTuningConfiguration
    tuning = UnifiedTuningConfiguration(...)
    create_sql_tuned = benchmark.get_create_tables_sql(tuning_config=tuning)

Parameters:

- **dialect** (str): Target SQL dialect. Default: "standard"
- **tuning_config** (UnifiedTuningConfiguration, optional): Tuning settings

Returns:
    str: SQL script for creating all tables

generate_streams(num_streams=1, rng_seed=None, streams_output_dir=None)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Generate query streams for throughput testing.

.. code-block:: python

    # Generate 4 concurrent streams
    streams = benchmark.generate_streams(
        num_streams=4,
        rng_seed=42,
        streams_output_dir="./streams"
    )

    for stream_path in streams:
        print(f"Stream: {stream_path}")

Parameters:

- **num_streams** (int): Number of streams to generate. Default: 1
- **rng_seed** (int, optional): Seed for reproducible streams
- **streams_output_dir** (str|Path, optional): Output directory for stream files

Returns:
    List[Path]: Paths to generated stream files

Properties
----------

queries
~~~~~~~

Access to the query manager.

.. code-block:: python

    query_manager = benchmark.queries
    query_info = query_manager.get_query_info(1)
    print(f"Query 1: {query_info['description']}")

Returns:
    TPCDSQueryManager: Query manager instance

generator
~~~~~~~~~

Access to the data generator.

.. code-block:: python

    data_gen = benchmark.generator
    table_info = data_gen.get_table_info("store_sales")
    print(f"Store sales: {table_info}")

Returns:
    TPCDSDataGenerator: Data generator instance

Usage Examples
--------------

Basic Benchmark Run
~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from benchbox.tpcds import TPCDS
    from benchbox.platforms.duckdb import DuckDBAdapter

    # Create benchmark with scale factor 1 (~1GB)
    benchmark = TPCDS(scale_factor=1.0)

    # Generate data
    benchmark.generate_data()

    # Run on DuckDB
    adapter = DuckDBAdapter()
    results = benchmark.run_with_platform(adapter)

    # Print results
    print(f"Benchmark: {results.benchmark_name}")
    print(f"Total time: {results.total_execution_time:.2f}s")
    print(f"Queries: {results.successful_queries}/{results.total_queries}")

Query Subset Execution
~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from benchbox.tpcds import TPCDS
    from benchbox.platforms.duckdb import DuckDBAdapter

    benchmark = TPCDS(scale_factor=1.0)
    benchmark.generate_data()

    adapter = DuckDBAdapter()
    conn = adapter.create_connection()

    # Load data
    adapter.create_schema(benchmark, conn)
    adapter.load_data(benchmark, conn, benchmark.output_dir)

    # Execute reporting queries (1-10)
    for query_id in range(1, 11):
        query = benchmark.get_query(query_id)
        result = adapter.execute_query(conn, query, f"query{query_id}")
        print(f"Query {query_id}: {result['execution_time']:.3f}s")

Query Complexity Analysis
~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from benchbox.tpcds import TPCDS
    import re

    benchmark = TPCDS(scale_factor=1.0)
    queries = benchmark.get_queries()

    complexity_metrics = []

    for query_id, query_text in queries.items():
        metrics = {
            "query_id": query_id,
            "lines": len(query_text.split("\n")),
            "joins": query_text.upper().count("JOIN"),
            "subqueries": query_text.upper().count("SELECT") - 1,
            "window_functions": len(re.findall(r'\bOVER\s*\(', query_text, re.IGNORECASE)),
            "ctes": query_text.upper().count("WITH"),
        }
        complexity_metrics.append(metrics)

    # Sort by complexity
    sorted_queries = sorted(
        complexity_metrics,
        key=lambda x: (x["subqueries"], x["joins"], x["window_functions"]),
        reverse=True
    )

    print("Top 5 most complex queries:")
    for q in sorted_queries[:5]:
        print(f"Query {q['query_id']}: {q['subqueries']} subqueries, "
              f"{q['joins']} joins, {q['window_functions']} window functions")

Multi-Platform Comparison
~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from benchbox.tpcds import TPCDS
    from benchbox.platforms.duckdb import DuckDBAdapter
    from benchbox.platforms.clickhouse import ClickHouseAdapter
    import pandas as pd

    benchmark = TPCDS(scale_factor=1.0, output_dir="./data/tpcds_sf1")
    benchmark.generate_data()

    platforms = {
        "DuckDB": DuckDBAdapter(),
        "ClickHouse": ClickHouseAdapter(host="localhost"),
    }

    results_data = []

    for name, adapter in platforms.items():
        results = benchmark.run_with_platform(adapter)

        results_data.append({
            "platform": name,
            "total_time": results.total_execution_time,
            "avg_query_time": results.average_query_time,
            "successful": results.successful_queries,
            "failed": results.failed_queries,
        })

    df = pd.DataFrame(results_data)
    print(df)

Variant Testing
~~~~~~~~~~~~~~~

.. code-block:: python

    from benchbox.tpcds import TPCDS

    benchmark = TPCDS(scale_factor=1.0)

    # Generate queries with different seeds
    variants = {}
    for seed in [42, 123, 456]:
        variant_queries = {}
        for query_id in range(1, 100):
            variant_queries[query_id] = benchmark.get_query(
                query_id,
                seed=seed
            )
        variants[seed] = variant_queries

    # Compare query variants
    q1_v1 = variants[42][1]
    q1_v2 = variants[123][1]
    if q1_v1 != q1_v2:
        print("Query 1 has parametrized variants")

Stream-Based Testing
~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from benchbox.tpcds import TPCDS
    from benchbox.platforms.duckdb import DuckDBAdapter
    import concurrent.futures

    benchmark = TPCDS(scale_factor=1.0)
    benchmark.generate_data()

    # Generate 4 concurrent streams
    streams = benchmark.generate_streams(num_streams=4, rng_seed=42)

    adapter = DuckDBAdapter()

    def run_stream(stream_id):
        stream_info = benchmark.get_stream_info(stream_id)
        total_time = 0

        conn = adapter.create_connection()
        adapter.create_schema(benchmark, conn)
        adapter.load_data(benchmark, conn, benchmark.output_dir)

        for query_id in stream_info["queries"]:
            query = benchmark.get_query(query_id)
            result = adapter.execute_query(conn, query, f"q{query_id}")
            total_time += result["execution_time"]

        return {"stream_id": stream_id, "total_time": total_time}

    # Run streams in parallel
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(run_stream, i) for i in range(1, 5)]
        results = [f.result() for f in concurrent.futures.as_completed(futures)]

    for r in results:
        print(f"Stream {r['stream_id']}: {r['total_time']:.2f}s")

See Also
--------

- :doc:`index` - Benchmark API overview
- :doc:`tpch` - TPC-H benchmark API
- :doc:`../base` - Base benchmark interface
- :doc:`../results` - Results API
- :doc:`/benchmarks/tpc-ds` - TPC-DS guide
