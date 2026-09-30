ClickBench Benchmark API
========================

.. tags:: reference, python-api, clickbench

Complete Python API reference for the ClickBench (ClickHouse Analytics Benchmark).

Overview
--------

ClickBench is a systematic analytics benchmark designed to test analytical database performance using real-world web analytics data patterns. It uses a single flat table with ~100 columns and 43 different query patterns representative of real-world analytics workloads.

**Key Features**:

- **43 analytical queries** - Diverse performance patterns
- **Single flat table design** - Emphasizes columnar storage
- **Real-world data patterns** - Based on web analytics
- **Comprehensive column coverage** - ~100 columns, various data types
- **Performance-focused** - Precise timing comparisons
- **Cross-system compatibility** - Standard across databases
- **Scale factors from 0.001 to 10+**

Quick Start
-----------

.. code-block:: python

    from benchbox.clickbench import ClickBench
    from benchbox.platforms.duckdb import DuckDBAdapter

    # Create benchmark
    benchmark = ClickBench(scale_factor=0.01)

    # Generate data
    benchmark.generate_data()

    # Run on platform
    adapter = DuckDBAdapter()
    results = benchmark.run_with_platform(adapter)

    print(f"Completed 43 queries in {results.total_execution_time:.2f}s")

API Reference
-------------

ClickBench Class
~~~~~~~~~~~~~~~~

.. autoclass:: benchbox.clickbench.ClickBench
   :members:
   :inherited-members:
   :show-inheritance:

Constructor
~~~~~~~~~~~

.. code-block:: python

    ClickBench(
        scale_factor: float = 1.0,
        output_dir: Optional[Union[str, Path]] = None,
        **kwargs
    )

Parameters:

- **scale_factor** (float): Data size multiplier. SF=1.0 generates ~1M rows (~100MB). Range: 0.001 to 10+
- **output_dir** (str|Path, optional): Directory for generated data files. Default: temporary directory
- **kwargs**: Additional options (e.g., date_range_days, user_count, enable_compression)

Raises:

- **ValueError**: If scale_factor is not positive
- **TypeError**: If scale_factor is not a number

Methods
-------

generate_data()
~~~~~~~~~~~~~~~

Generate ClickBench web analytics data.

.. code-block:: python

    data_files = benchmark.generate_data()
    print(f"Generated {len(data_files)} data files")

Returns:
    List[Union[str, Path]]: Paths to generated data files (single hits.csv file)

get_query(query_id, \\*, params=None)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Get a specific ClickBench query.

.. code-block:: python

    # Get simple count query
    q1 = benchmark.get_query("Q1")

    # Get filtered count query
    q2 = benchmark.get_query("Q2")

    # Get string operations query
    q21 = benchmark.get_query("Q21")

    # Get complex analytics query
    q43 = benchmark.get_query("Q43")

Parameters:

- **query_id** (int|str): Query ID (Q1-Q43 or 1-43)
- **params** (dict, optional): Query parameters (rarely used in ClickBench)

Returns:
    str: Query SQL text

Raises:

- **ValueError**: If query_id is invalid

get_queries(dialect=None)
~~~~~~~~~~~~~~~~~~~~~~~~~

Get all ClickBench benchmark queries.

.. code-block:: python

    # Get all queries
    queries = benchmark.get_queries()
    print(f"Total queries: {len(queries)}")  # 43 queries

    # Get with dialect translation
    queries_sf = benchmark.get_queries(dialect="snowflake")

Parameters:

- **dialect** (str, optional): Target SQL dialect for translation

Returns:
    dict[str, str]: Dictionary mapping query IDs (Q1-Q43) to SQL text

get_query_categories()
~~~~~~~~~~~~~~~~~~~~~~

Get ClickBench queries organized by category.

.. code-block:: python

    categories = benchmark.get_query_categories()

    for category, query_ids in categories.items():
        print(f"{category}: {len(query_ids)} queries")
        print(f"  Query IDs: {query_ids}")

Returns:
    dict[str, list[str]]: Dictionary mapping category names to query ID lists

**Categories**:

- **scan**: Simple table scans (Q1, Q2, Q7)
- **aggregation**: Aggregation functions (Q3-Q6)
- **grouping**: GROUP BY queries (Q8-Q19)
- **string**: String operations (Q20-Q29)
- **complex**: Complex analytics (Q30-Q43)

get_schema()
~~~~~~~~~~~~

Get ClickBench schema information.

.. code-block:: python

    schema = benchmark.get_schema()
    for table in schema:
        print(f"{table['name']}: {len(table['columns'])} columns")

Returns:
    list[dict]: List of table definitions (single HITS table with ~100 columns)

get_create_tables_sql(dialect="standard", tuning_config=None)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Get CREATE TABLE SQL for ClickBench.

.. code-block:: python

    # Standard SQL
    create_sql = benchmark.get_create_tables_sql()

    # With dialect
    create_sql_ch = benchmark.get_create_tables_sql(dialect="clickhouse")

    # With tuning configuration
    from benchbox.core.tuning.interface import UnifiedTuningConfiguration
    tuning = UnifiedTuningConfiguration(...)
    create_sql_tuned = benchmark.get_create_tables_sql(tuning_config=tuning)

Parameters:

- **dialect** (str): Target SQL dialect. Default: "standard"
- **tuning_config** (UnifiedTuningConfiguration, optional): Tuning settings

Returns:
    str: SQL script for creating the HITS table

translate_query(query_id, dialect)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Translate a ClickBench query to a different SQL dialect.

.. code-block:: python

    # Translate query to BigQuery dialect
    q1_bq = benchmark.translate_query("Q1", "bigquery")

    # Translate to Snowflake dialect
    q10_sf = benchmark.translate_query("Q10", "snowflake")

Parameters:

- **query_id** (str): Query ID to translate (Q1-Q43)
- **dialect** (str): Target SQL dialect

Returns:
    str: Translated query string

Raises:

- **ValueError**: If query_id is invalid
- **ImportError**: If sqlglot is not installed
- **ValueError**: If dialect is not supported

Query Categories
----------------

ClickBench organizes 43 queries into 5 performance categories:

Scan Queries (Q1, Q2, Q7)
~~~~~~~~~~~~~~~~~~~~~~~~~

Tests basic table scanning and filtering performance.

.. code-block:: python

    # Scan category tests sequential scan optimization
    scan_queries = ["Q1", "Q2", "Q7"]

    for query_id in scan_queries:
        query = benchmark.get_query(query_id)
        # Execute query...

**Query Characteristics**:

- **Q1**: Simple COUNT(*) - Tests raw scan speed
- **Q2**: Filtered COUNT - Tests predicate evaluation
- **Q7**: Complex filter - Tests multiple predicates

Aggregation Queries (Q3-Q6)
~~~~~~~~~~~~~~~~~~~~~~~~~~~

Tests aggregation function performance.

.. code-block:: python

    # Aggregation category tests vectorized operations
    agg_queries = ["Q3", "Q4", "Q5", "Q6"]

    for query_id in agg_queries:
        query = benchmark.get_query(query_id)
        # Execute query...

**Query Characteristics**:

- **Q3**: Multiple aggregations (SUM, COUNT, AVG)
- **Q4**: MIN/MAX operations
- **Q5**: COUNT DISTINCT - Tests hash table efficiency
- **Q6**: Complex expressions in aggregations

Grouping Queries (Q8-Q19)
~~~~~~~~~~~~~~~~~~~~~~~~~

Tests GROUP BY and ORDER BY performance.

.. code-block:: python

    # Grouping category tests hash aggregation
    grouping_queries = ["Q8", "Q9", "Q10", "Q11", "Q12", "Q13",
                        "Q14", "Q15", "Q16", "Q17", "Q18", "Q19"]

    for query_id in grouping_queries:
        query = benchmark.get_query(query_id)
        # Execute query...

**Query Characteristics**:

- **Q8-Q10**: Basic GROUP BY with ordering
- **Q11-Q13**: COUNT DISTINCT by group
- **Q14-Q19**: Complex grouping with TOP-N

String Operations Queries (Q20-Q29)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Tests string processing and pattern matching.

.. code-block:: python

    # String operations category tests text processing
    string_queries = ["Q20", "Q21", "Q22", "Q23", "Q24",
                      "Q25", "Q26", "Q27", "Q28", "Q29"]

    for query_id in string_queries:
        query = benchmark.get_query(query_id)
        # Execute query...

**Query Characteristics**:

- **Q20-Q22**: LIKE pattern matching
- **Q23-Q25**: String functions (LENGTH, SUBSTRING)
- **Q26-Q29**: Regular expressions and complex string operations

Complex Analytics Queries (Q30-Q43)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Tests complex analytical operations.

.. code-block:: python

    # Complex category tests advanced query optimization
    complex_queries = ["Q30", "Q31", "Q32", "Q33", "Q34", "Q35",
                       "Q36", "Q37", "Q38", "Q39", "Q40", "Q41",
                       "Q42", "Q43"]

    for query_id in complex_queries:
        query = benchmark.get_query(query_id)
        # Execute query...

**Query Characteristics**:

- **Q30**: Wide aggregation (89 columns)
- **Q31-Q36**: Complex expressions and calculations
- **Q37-Q40**: Time series analysis
- **Q41-Q43**: Advanced analytics with HAVING

Usage Examples
--------------

Basic Benchmark Run
~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from benchbox.clickbench import ClickBench
    from benchbox.platforms.duckdb import DuckDBAdapter

    # Create benchmark with scale factor 0.01 (~1M rows)
    benchmark = ClickBench(scale_factor=0.01)

    # Generate data
    benchmark.generate_data()

    # Run on DuckDB
    adapter = DuckDBAdapter()
    results = benchmark.run_with_platform(adapter)

    # Print results
    print(f"Benchmark: {results.benchmark_name}")
    print(f"Total time: {results.total_execution_time:.2f}s")
    print(f"Queries: {results.successful_queries}/{results.total_queries}")
    print(f"Avg query time: {results.average_query_time:.3f}s")

Category-Based Execution
~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from benchbox.clickbench import ClickBench
    from benchbox.platforms.duckdb import DuckDBAdapter
    import time

    benchmark = ClickBench(scale_factor=0.01)
    benchmark.generate_data()

    adapter = DuckDBAdapter()
    conn = adapter.create_connection()

    # Load data
    adapter.create_schema(benchmark, conn)
    adapter.load_data(benchmark, conn, benchmark.output_dir)

    # Get query categories
    categories = benchmark.get_query_categories()

    # Run each category
    category_results = {}

    for category_name, query_ids in categories.items():
        print(f"\n{category_name.upper()} queries:")
        category_times = []

        for query_id in query_ids:
            query = benchmark.get_query(query_id)

            start = time.time()
            result = adapter.execute_query(conn, query, query_id)
            duration = time.time() - start

            category_times.append(duration)
            print(f"  {query_id}: {duration:.3f}s")

        category_results[category_name] = {
            "total_time": sum(category_times),
            "avg_time": sum(category_times) / len(category_times),
            "query_count": len(query_ids)
        }

    # Print category summary
    print("\nCategory Summary:")
    for category, stats in category_results.items():
        print(f"{category}: {stats['avg_time']:.3f}s avg ({stats['query_count']} queries)")

Performance Analysis
~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from benchbox.clickbench import ClickBench
    from benchbox.platforms.duckdb import DuckDBAdapter
    import time
    from statistics import mean, median

    benchmark = ClickBench(scale_factor=0.01)
    adapter = DuckDBAdapter()

    # Setup
    benchmark.generate_data()
    conn = adapter.create_connection()
    adapter.create_schema(benchmark, conn)
    adapter.load_data(benchmark, conn, benchmark.output_dir)

    # Run with multiple iterations
    iterations = 3
    all_results = {}

    for query_id in [f"Q{i}" for i in range(1, 44)]:
        times = []

        for iteration in range(iterations):
            query = benchmark.get_query(query_id)

            start = time.time()
            try:
                result = adapter.execute_query(conn, query, query_id)
                duration = time.time() - start
                times.append(duration)
            except Exception as e:
                print(f"{query_id} iteration {iteration}: ERROR - {e}")
                break

        if times:
            all_results[query_id] = {
                "mean": mean(times),
                "median": median(times),
                "min": min(times),
                "max": max(times),
                "times": times
            }

    # Print performance summary
    print("Performance Summary (3 iterations):")
    print(f"{'Query':<8} {'Mean':<10} {'Median':<10} {'Min':<10} {'Max':<10}")
    print("-" * 50)

    for query_id, stats in sorted(all_results.items()):
        print(f"{query_id:<8} {stats['mean']:<10.4f} {stats['median']:<10.4f} "
              f"{stats['min']:<10.4f} {stats['max']:<10.4f}")

    # Calculate geometric mean
    all_times = [stats["median"] for stats in all_results.values()]
    geomean = (1.0 / len(all_times)) * sum(all_times)
    print(f"\nGeometric mean query time: {geomean:.4f}s")

Multi-Platform Comparison
~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from benchbox.clickbench import ClickBench
    from benchbox.platforms.duckdb import DuckDBAdapter
    from benchbox.platforms.clickhouse import ClickHouseAdapter
    import pandas as pd

    benchmark = ClickBench(scale_factor=0.01, output_dir="./data/clickbench")
    benchmark.generate_data()

    platforms = {
        "DuckDB": DuckDBAdapter(),
        "ClickHouse": ClickHouseAdapter(host="localhost"),
    }

    results_data = []

    for name, adapter in platforms.items():
        print(f"\nBenchmarking {name}...")
        results = benchmark.run_with_platform(adapter)

        results_data.append({
            "platform": name,
            "total_time": results.total_execution_time,
            "avg_query_time": results.average_query_time,
            "successful": results.successful_queries,
            "failed": results.failed_queries,
            "queries_per_sec": 43 / results.total_execution_time
        })

    df = pd.DataFrame(results_data)
    print("\nBenchmark Results:")
    print(df)

Columnar Database Optimization
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from benchbox.clickbench import ClickBench
    from benchbox.platforms.clickhouse import ClickHouseAdapter

    # ClickBench is designed for columnar databases
    benchmark = ClickBench(scale_factor=1.0)
    adapter = ClickHouseAdapter(host="localhost")

    # Generate and load data
    benchmark.generate_data()
    conn = adapter.create_connection()

    # Create schema with columnar optimizations
    adapter.create_schema(benchmark, conn)
    adapter.load_data(benchmark, conn, benchmark.output_dir)

    # Add ClickHouse-specific optimizations
    conn.execute("""
        ALTER TABLE hits
        MODIFY COLUMN SearchPhrase String CODEC(ZSTD(3))
    """)

    conn.execute("""
        ALTER TABLE hits
        MODIFY COLUMN URL String CODEC(ZSTD(3))
    """)

    # Run scan queries (benefit most from columnar storage)
    scan_queries = ["Q1", "Q2", "Q7"]
    for query_id in scan_queries:
        query = benchmark.get_query(query_id)
        result = adapter.execute_query(conn, query, query_id)
        print(f"{query_id}: {result['execution_time']:.3f}s")

Query Translation Example
~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from benchbox.clickbench import ClickBench

    benchmark = ClickBench(scale_factor=0.01)

    # Original query
    q1_original = benchmark.get_query("Q1")
    print("Original (ClickHouse):")
    print(q1_original)

    # Translate to different dialects
    q1_duckdb = benchmark.translate_query("Q1", "duckdb")
    print("\nDuckDB:")
    print(q1_duckdb)

    q1_postgres = benchmark.translate_query("Q1", "postgres")
    print("\nPostgreSQL:")
    print(q1_postgres)

    q1_bigquery = benchmark.translate_query("Q1", "bigquery")
    print("\nBigQuery:")
    print(q1_bigquery)

Selective Query Execution
~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from benchbox.clickbench import ClickBench
    from benchbox.platforms.duckdb import DuckDBAdapter

    benchmark = ClickBench(scale_factor=0.01)
    adapter = DuckDBAdapter()

    # Setup
    benchmark.generate_data()
    conn = adapter.create_connection()
    adapter.create_schema(benchmark, conn)
    adapter.load_data(benchmark, conn, benchmark.output_dir)

    # Run only fast queries (scan + simple aggregation)
    fast_queries = ["Q1", "Q2", "Q3", "Q4", "Q7"]

    print("Running fast queries:")
    for query_id in fast_queries:
        query = benchmark.get_query(query_id)
        result = adapter.execute_query(conn, query, query_id)
        print(f"{query_id}: {result['execution_time']:.3f}s ({result['status']})")

    # Run only string operations queries
    string_queries = [f"Q{i}" for i in range(20, 30)]

    print("\nRunning string operations queries:")
    for query_id in string_queries:
        query = benchmark.get_query(query_id)
        result = adapter.execute_query(conn, query, query_id)
        print(f"{query_id}: {result['execution_time']:.3f}s ({result['status']})")

See Also
--------

- :doc:`index` - Benchmark API overview
- :doc:`tpch` - TPC-H benchmark API
- :doc:`tpcds` - TPC-DS benchmark API
- :doc:`ssb` - Star Schema Benchmark API
- :doc:`../base` - Base benchmark interface
- :doc:`../results` - Results API
- :doc:`/benchmarks/clickbench` - ClickBench guide
- :doc:`/benchmarks/index` - Benchmark catalog

External Resources
~~~~~~~~~~~~~~~~~~

- `ClickBench GitHub <https://github.com/ClickHouse/ClickBench>`_ - Official benchmark repository
- `ClickBench Results <https://benchmark.clickhouse.com/>`_ - Cross-database performance comparisons
- `ClickBench Methodology <https://github.com/ClickHouse/ClickBench>`_ - Detailed methodology
- `DuckDB Labs Benchmark <https://duckdblabs.github.io/db-benchmark/>`_ - Updated benchmark results
