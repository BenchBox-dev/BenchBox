Read Primitives Benchmark API
==============================

.. tags:: reference, python-api, custom-benchmark

Complete Python API reference for the Read Primitives benchmark.

Overview
--------

The Read Primitives benchmark tests **109 fundamental database operations** using the TPC-H schema. It provides focused testing of specific database capabilities without business logic complexity, ideal for performance regression detection and optimization validation.

**Key Features**:

- **109 primitive operation queries** - Comprehensive database operation coverage
- **26 operation categories** - Aggregation, joins, filters, window functions, optimizer tests, and more
- **Full DataFrame support** - 149 expression-family + 149 pandas-family implementations
- **TPC-H schema** - Proven data model with familiar patterns
- **Category-based execution** - Test specific operation types
- **Performance regression detection** - Isolated operation testing
- **Optimizer sniff tests** - 13 queries testing query optimizer behavior
- **Extensible architecture** - Custom primitives support

Quick Start
-----------

.. code-block:: python

    from benchbox.read_primitives import ReadPrimitives
    from benchbox.platforms.duckdb import DuckDBAdapter

    # Create benchmark
    benchmark = ReadPrimitives(scale_factor=1.0)

    # Generate data
    benchmark.generate_data()

    # Run on platform
    adapter = DuckDBAdapter()
    results = benchmark.run_with_platform(adapter)

    print(f"Completed {results.total_queries} queries in {results.total_execution_time:.2f}s")

API Reference
-------------

ReadPrimitives Class
~~~~~~~~~~~~~~~~~~~~

.. autoclass:: benchbox.read_primitives.ReadPrimitives
   :members:
   :inherited-members:
   :show-inheritance:

Constructor
~~~~~~~~~~~

.. code-block:: python

    ReadPrimitives(
        scale_factor: float = 1.0,
        output_dir: Optional[Union[str, Path]] = None,
        verbose: bool = False,
        **kwargs
    )

Parameters:

- **scale_factor** (float): Data size multiplier. SF=1.0 generates ~6M lineitem rows (~1GB). Range: 0.01 to 10+
- **output_dir** (str|Path, optional): Directory for generated data files. Default: temporary directory
- **verbose** (bool): Enable verbose logging. Default: False
- **kwargs**: Additional options

Raises:

- **ValueError**: If scale_factor is not positive
- **TypeError**: If scale_factor is not a number

Methods
-------

generate_data(tables=None)
~~~~~~~~~~~~~~~~~~~~~~~~~~

Generate Read Primitives benchmark data (TPC-H schema).

.. code-block:: python

    # Generate all tables
    table_files = benchmark.generate_data()

    # Generate specific tables
    table_files = benchmark.generate_data(tables=["lineitem", "orders"])

    for table_name, file_path in table_files.items():
        print(f"{table_name}: {file_path}")

Parameters:

- **tables** (list[str], optional): Table names to generate. If None, generates all tables

Returns:
    dict[str, str]: Dictionary mapping table names to file paths

get_query(query_id, \\*, params=None)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Get a specific primitive query.

.. code-block:: python

    # Get simple aggregation query
    q1 = benchmark.get_query("aggregation_simple")

    # Get window function query
    q2 = benchmark.get_query("window_rank")

    # Get join query
    q3 = benchmark.get_query("join_inner")

Parameters:

- **query_id** (int|str): Query identifier (e.g., "aggregation_simple", "window_rank")
- **params** (dict, optional): Query parameters

Returns:
    str: Query SQL text

Raises:

- **ValueError**: If query_id is invalid

get_queries(dialect=None)
~~~~~~~~~~~~~~~~~~~~~~~~~

Get all primitive queries.

.. code-block:: python

    # Get all queries
    queries = benchmark.get_queries()
    print(f"Total queries: {len(queries)}")

    # Get with dialect translation
    queries_sf = benchmark.get_queries(dialect="snowflake")

Parameters:

- **dialect** (str, optional): Target SQL dialect for translation

Returns:
    dict[str, str]: Dictionary mapping query IDs to SQL text

get_queries_by_category(category)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Get queries filtered by category.

.. code-block:: python

    # Get all aggregation queries
    agg_queries = benchmark.get_queries_by_category("aggregation")

    # Get all window function queries
    window_queries = benchmark.get_queries_by_category("window")

    # Get all join queries
    join_queries = benchmark.get_queries_by_category("join")

Parameters:

- **category** (str): Category name (e.g., "aggregation", "window", "join")

Returns:
    dict[str, str]: Dictionary mapping query IDs to SQL text for the category

Raises:

- **ValueError**: If category is invalid

get_query_categories()
~~~~~~~~~~~~~~~~~~~~~~

Get list of available query categories.

.. code-block:: python

    categories = benchmark.get_query_categories()

    print("Available categories:")
    for category in categories:
        queries = benchmark.get_queries_by_category(category)
        print(f"  {category}: {len(queries)} queries")

Returns:
    list[str]: List of category names

**Available Categories**:

- **aggregation**: SUM, COUNT, AVG, MIN, MAX operations
- **window**: Window functions (ROW_NUMBER, RANK, DENSE_RANK, LAG, LEAD)
- **join**: Inner, left, right, full outer joins
- **filter**: WHERE clause filtering operations
- **groupby**: GROUP BY and HAVING operations
- **orderby**: ORDER BY and TOP-N operations
- **subquery**: Subquery and correlated subquery operations
- **union**: UNION, UNION ALL, INTERSECT, EXCEPT operations
- **cte**: Common table expressions (WITH clauses)
- **string**: String manipulation functions
- **date**: Date/time operations
- **numeric**: Numeric calculations and functions
- **analytical**: Advanced analytical operations

get_schema()
~~~~~~~~~~~~

Get Read Primitives benchmark schema (TPC-H).

.. code-block:: python

    schema = benchmark.get_schema()

    for table_name, table_def in schema.items():
        print(f"{table_name}: {len(table_def['columns'])} columns")

Returns:
    dict[str, dict]: Dictionary mapping table names to schema definitions

get_create_tables_sql(dialect="standard", tuning_config=None)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Get CREATE TABLE SQL for all tables.

.. code-block:: python

    # Standard SQL
    create_sql = benchmark.get_create_tables_sql()

    # With dialect
    create_sql_pg = benchmark.get_create_tables_sql(dialect="postgres")

    # With tuning configuration
    from benchbox.core.tuning.interface import UnifiedTuningConfiguration
    tuning = UnifiedTuningConfiguration(...)
    create_sql_tuned = benchmark.get_create_tables_sql(tuning_config=tuning)

Parameters:

- **dialect** (str): Target SQL dialect. Default: "standard"
- **tuning_config** (UnifiedTuningConfiguration, optional): Tuning settings

Returns:
    str: SQL script for creating all tables

run_benchmark(connection, queries=None, iterations=1, categories=None)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Run the complete Read Primitives benchmark.

.. code-block:: python

    from benchbox.platforms.duckdb import DuckDBAdapter

    adapter = DuckDBAdapter()
    conn = adapter.create_connection()

    # Run all queries
    results = benchmark.run_benchmark(conn)

    # Run specific queries
    results = benchmark.run_benchmark(
        conn,
        queries=["aggregation_simple", "window_rank"],
        iterations=3
    )

    # Run specific categories
    results = benchmark.run_benchmark(
        conn,
        categories=["aggregation", "window"],
        iterations=3
    )

Parameters:

- **connection** (Any): Database connection
- **queries** (list[str], optional): Query IDs to run. If None, runs all
- **iterations** (int): Number of times to run each query. Default: 1
- **categories** (list[str], optional): Categories to run. Overrides queries parameter

Returns:
    dict[str, Any]: Benchmark results with timing and status

run_category_benchmark(connection, category, iterations=1)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Run benchmark for a specific query category.

.. code-block:: python

    # Run all aggregation queries
    agg_results = benchmark.run_category_benchmark(conn, "aggregation", iterations=3)

    # Run all window function queries
    window_results = benchmark.run_category_benchmark(conn, "window", iterations=3)

    print(f"Aggregation results: {agg_results}")

Parameters:

- **connection** (Any): Database connection
- **category** (str): Category name (e.g., "aggregation", "window")
- **iterations** (int): Number of times to run each query. Default: 1

Returns:
    dict[str, Any]: Benchmark results for the category

load_data_to_database(connection, tables=None)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Load generated data into a database.

.. code-block:: python

    # Load all tables
    benchmark.load_data_to_database(conn)

    # Load specific tables
    benchmark.load_data_to_database(conn, tables=["lineitem", "orders"])

Parameters:

- **connection** (Any): Database connection
- **tables** (list[str], optional): Tables to load. If None, loads all

Raises:

- **ValueError**: If data hasn't been generated yet

execute_query(query_id, connection, params=None)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Execute a primitive query on the database.

.. code-block:: python

    # Execute single query
    result = benchmark.execute_query("aggregation_simple", conn)

    # Execute with custom parameters
    result = benchmark.execute_query(
        "aggregation_simple",
        conn,
        params={"threshold": 100}
    )

Parameters:

- **query_id** (str): Query identifier
- **connection** (Any): Database connection
- **params** (dict, optional): Query parameters

Returns:
    Any: Query results from the database

Raises:

- **ValueError**: If query_id is invalid

get_benchmark_info()
~~~~~~~~~~~~~~~~~~~~

Get information about the benchmark.

.. code-block:: python

    info = benchmark.get_benchmark_info()

    print(f"Benchmark: {info['name']}")
    print(f"Total queries: {info['total_queries']}")
    print(f"Categories: {', '.join(info['categories'])}")
    print(f"Scale factor: {info['scale_factor']}")

Returns:
    dict[str, Any]: Benchmark metadata

Usage Examples
--------------

Basic Benchmark Run
~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from benchbox.read_primitives import ReadPrimitives
    from benchbox.platforms.duckdb import DuckDBAdapter

    # Create benchmark with scale factor 0.1 (~100MB)
    benchmark = ReadPrimitives(scale_factor=0.1)

    # Generate data
    benchmark.generate_data()

    # Run on DuckDB
    adapter = DuckDBAdapter()
    results = benchmark.run_with_platform(adapter)

    # Print results
    print(f"Benchmark: {results.benchmark_name}")
    print(f"Total time: {results.total_execution_time:.2f}s")
    print(f"Queries: {results.successful_queries}/{results.total_queries}")

Category-Based Execution
~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from benchbox.read_primitives import ReadPrimitives
    from benchbox.platforms.duckdb import DuckDBAdapter

    benchmark = ReadPrimitives(scale_factor=0.1)
    benchmark.generate_data()

    adapter = DuckDBAdapter()
    conn = adapter.create_connection()

    # Load data
    adapter.create_schema(benchmark, conn)
    benchmark.load_data_to_database(conn)

    # Get all categories
    categories = benchmark.get_query_categories()

    # Run each category
    category_results = {}

    for category in categories:
        print(f"\nRunning {category} category...")
        results = benchmark.run_category_benchmark(conn, category, iterations=3)

        category_results[category] = {
            "total_time": results["total_time"],
            "avg_time": results["average_time"],
            "query_count": results["query_count"],
            "successful": results["successful_queries"]
        }

        print(f"  Total time: {results['total_time']:.2f}s")
        print(f"  Avg query time: {results['average_time']:.3f}s")
        print(f"  Successful: {results['successful_queries']}/{results['query_count']}")

    # Print category summary
    print("\n" + "="*60)
    print("Category Performance Summary")
    print("="*60)
    for category, stats in sorted(category_results.items()):
        print(f"{category:15s}: {stats['avg_time']:6.3f}s avg ({stats['query_count']} queries)")

Selective Query Execution
~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from benchbox.read_primitives import ReadPrimitives
    from benchbox.platforms.duckdb import DuckDBAdapter
    import time

    benchmark = ReadPrimitives(scale_factor=0.1)
    adapter = DuckDBAdapter()

    # Setup
    benchmark.generate_data()
    conn = adapter.create_connection()
    adapter.create_schema(benchmark, conn)
    benchmark.load_data_to_database(conn)

    # Run specific queries
    selected_queries = [
        "aggregation_simple",
        "aggregation_group",
        "window_rank",
        "join_inner",
        "filter_simple"
    ]

    print("Running selected primitive queries:")
    query_times = {}

    for query_id in selected_queries:
        query = benchmark.get_query(query_id)

        start = time.time()
        result = benchmark.execute_query(query_id, conn)
        duration = time.time() - start

        query_times[query_id] = duration
        print(f"  {query_id:25s}: {duration:.3f}s")

    # Summary
    total_time = sum(query_times.values())
    avg_time = total_time / len(query_times)
    print(f"\nTotal: {total_time:.2f}s, Average: {avg_time:.3f}s")

Performance Regression Testing
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from benchbox.read_primitives import ReadPrimitives
    from benchbox.platforms.duckdb import DuckDBAdapter
    import json

    benchmark = ReadPrimitives(scale_factor=0.1)
    adapter = DuckDBAdapter()

    # Setup
    benchmark.generate_data()
    conn = adapter.create_connection()
    adapter.create_schema(benchmark, conn)
    benchmark.load_data_to_database(conn)

    # Run baseline benchmark
    print("Running baseline benchmark...")
    baseline_results = benchmark.run_benchmark(conn, iterations=3)

    # Save baseline
    with open("baseline_results.json", "w") as f:
        json.dump(baseline_results, f, indent=2)

    # ... make changes to database configuration ...

    # Run comparison benchmark
    print("\nRunning comparison benchmark...")
    comparison_results = benchmark.run_benchmark(conn, iterations=3)

    # Compare results
    print("\nPerformance Comparison:")
    print(f"{'Query':<30s} {'Baseline':<12s} {'Current':<12s} {'Change':<10s}")
    print("-" * 70)

    for query_id in baseline_results.keys():
        if query_id in ["total_time", "average_time"]:
            continue

        baseline_time = baseline_results[query_id]["average_time"]
        current_time = comparison_results[query_id]["average_time"]
        change_pct = ((current_time - baseline_time) / baseline_time) * 100

        status = "REGRESSION" if change_pct > 10 else "OK"
        print(f"{query_id:<30s} {baseline_time:>10.3f}s  {current_time:>10.3f}s  "
              f"{change_pct:>+7.1f}% {status}")

Multi-Category Analysis
~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from benchbox.read_primitives import ReadPrimitives
    from benchbox.platforms.duckdb import DuckDBAdapter
    import pandas as pd

    benchmark = ReadPrimitives(scale_factor=0.1)
    adapter = DuckDBAdapter()

    # Setup
    benchmark.generate_data()
    conn = adapter.create_connection()
    adapter.create_schema(benchmark, conn)
    benchmark.load_data_to_database(conn)

    # Run selected categories
    categories_to_test = ["aggregation", "window", "join", "filter"]

    results_data = []

    for category in categories_to_test:
        print(f"\nTesting {category} category...")
        results = benchmark.run_category_benchmark(conn, category, iterations=3)

        results_data.append({
            "category": category,
            "total_time": results["total_time"],
            "avg_time": results["average_time"],
            "query_count": results["query_count"],
            "successful": results["successful_queries"],
            "failed": results["failed_queries"],
            "success_rate": (results["successful_queries"] / results["query_count"]) * 100
        })

    # Create DataFrame for analysis
    df = pd.DataFrame(results_data)

    print("\nCategory Analysis:")
    print(df.to_string(index=False))

    # Identify slowest categories
    df_sorted = df.sort_values("avg_time", ascending=False)
    print(f"\nSlowest categories:")
    for idx, row in df_sorted.head(3).iterrows():
        print(f"  {row['category']}: {row['avg_time']:.3f}s average")

Multi-Platform Comparison
~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from benchbox.read_primitives import ReadPrimitives
    from benchbox.platforms.duckdb import DuckDBAdapter
    from benchbox.platforms.clickhouse import ClickHouseAdapter
    import pandas as pd

    benchmark = ReadPrimitives(scale_factor=0.1, output_dir="./data/primitives")
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
        })

    df = pd.DataFrame(results_data)
    print("\nPlatform Comparison:")
    print(df)

Custom Primitive Development
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from benchbox.read_primitives import ReadPrimitives

    # Extend with custom primitives
    class CustomPrimitives(ReadPrimitives):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)

            # Add custom queries
            self._custom_queries = {
                "custom_complex_join": """
                    SELECT l.l_orderkey, o.o_custkey, c.c_name, p.p_name
                    FROM lineitem l
                    JOIN orders o ON l.l_orderkey = o.o_orderkey
                    JOIN customer c ON o.o_custkey = c.c_custkey
                    JOIN part p ON l.l_partkey = p.p_partkey
                    WHERE l.l_shipdate > '1995-01-01'
                    LIMIT 100
                """,
                "custom_window_aggregation": """
                    SELECT
                        l_orderkey,
                        l_partkey,
                        l_quantity,
                        SUM(l_quantity) OVER (PARTITION BY l_partkey) as total_qty,
                        AVG(l_quantity) OVER (PARTITION BY l_partkey) as avg_qty
                    FROM lineitem
                    WHERE l_shipdate > '1995-01-01'
                    LIMIT 1000
                """
            }

        def get_query(self, query_id, *, params=None):
            # Check custom queries first
            if query_id in self._custom_queries:
                return self._custom_queries[query_id]

            # Fall back to standard primitives
            return super().get_query(query_id, params=params)

    # Use custom primitives
    custom_bench = CustomPrimitives(scale_factor=0.1)
    custom_bench.generate_data()

    # Execute custom query
    custom_query = custom_bench.get_query("custom_complex_join")
    print(f"Custom query: {custom_query}")

DataFrame Support
-----------------

Read Primitives provides full DataFrame support for both expression-family and pandas-family platforms.

**Platform Support**:

- **Expression Family** (Polars, PySpark, DataFusion): 149 query implementations
- **Pandas Family** (Pandas, Modin, Dask, cuDF): 149 query implementations
- **Skipped queries**: Only 3 (correlated subqueries with no DataFrame equivalent)

**DataFrame Query Execution**:

.. code-block:: python

    from benchbox.core.read_primitives.dataframe_queries import (
        aggregation_distinct_expression_impl,
        aggregation_distinct_pandas_impl,
        SKIP_FOR_DATAFRAME,
    )
    from benchbox.platforms import get_dataframe_adapter

    # Expression family (Polars, PySpark, DataFusion)
    ctx = get_dataframe_adapter("polars-df", working_dir="./data").create_context()
    result = aggregation_distinct_expression_impl(ctx)

    # Pandas family (Pandas, Modin, Dask, cuDF)
    pandas_ctx = get_dataframe_adapter("pandas-df", working_dir="./data").create_context()
    result = aggregation_distinct_pandas_impl(pandas_ctx)

    # Check which queries are skipped for DataFrame
    print(f"Skipped queries: {SKIP_FOR_DATAFRAME}")

**DataFrame Query Categories**:

All 26 SQL categories have DataFrame implementations:

- aggregation, filter, groupby, orderby, window, qualify
- broadcast, exchange, shuffle, string, predicate
- array, subquery, join, limit, union, and more

**Note**: Optimizer queries test SQL optimizer behavior which applies equally to
DataFrame platforms - Spark's Catalyst optimizer optimizes DataFrame operations
just like SQL queries.

See Also
--------

- :doc:`index` - Benchmark API overview
- :doc:`tpch` - TPC-H benchmark API (same schema)
- :doc:`tpcds` - TPC-DS benchmark API
- :doc:`clickbench` - ClickBench benchmark API
- :doc:`../base` - Base benchmark interface
- :doc:`../results` - Results API
- :doc:`/benchmarks/read-primitives` - Read Primitives user guide
- :doc:`/platforms/dataframe` - DataFrame platforms overview

External Resources
~~~~~~~~~~~~~~~~~~

- `TPC-H Specification <http://www.tpc.org/tpch/>`_ - Schema specification
- `Database Testing Best Practices <https://www.vldb.org/>`_ - VLDB resources
