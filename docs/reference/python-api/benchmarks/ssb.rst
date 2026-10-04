SSB (Star Schema Benchmark) API
================================

.. tags:: reference, python-api, ssb

Complete Python API reference for the Star Schema Benchmark (SSB).

Overview
--------

The Star Schema Benchmark (SSB) is a simplified variant of TPC-H specifically designed for testing OLAP systems and data warehouses. It transforms the normalized TPC-H schema into a denormalized star schema that better represents typical data warehouse designs.

**Key Features**:

- **Star schema design** - Single fact table with dimension tables
- **13 analytical queries** - Organized into 4 logical flights
- **Simplified query patterns** - Focus on aggregation and filtering
- **OLAP-oriented** - Tests typical data warehouse patterns
- **Parameterized queries** - Configurable selectivity
- **Performance-focused** - Stresses aggregation and scan performance
- **Scale factors from 0.01 to 100+**

Quick Start
-----------

.. code-block:: python

    from benchbox.ssb import SSB
    from benchbox.platforms.duckdb import DuckDBAdapter

    benchmark = SSB(scale_factor=1.0)

    benchmark.generate_data()

    adapter = DuckDBAdapter()
    results = benchmark.run_with_platform(adapter)

    print(f"Completed in {results.total_execution_time:.2f}s")

API Reference
-------------

.. py:module:: benchbox.ssb

SSB Class
~~~~~~~~~

.. py:class:: SSB(scale_factor: float = 1.0, output_dir: Union[str, pathlib.Path, NoneType] = None, **kwargs: Any)

   SSB benchmark implementation with 13 queries in four flights.


Constructor
~~~~~~~~~~~


Parameters:

- **scale_factor** (float): Data size multiplier. SF=1.0 generates approximately six million fact-table rows. Range: 0.01 to 100+
- **output_dir** (str|Path, optional): Directory for generated data files. Default: temporary directory
- **kwargs**: Additional options (e.g., date_range_years, partition_fact_table)

Raises:

- **ValueError**: If scale_factor is not positive
- **TypeError**: If scale_factor is not a number

Methods
-------

generate_data()
~~~~~~~~~~~~~~~

Generate Star Schema Benchmark data.

.. code-block:: python

    data_files = benchmark.generate_data()
    print(f"Generated {len(data_files)} table files")

Returns:
    List[Union[str, Path]]: Paths to generated data files (5 tables: date, customer, supplier, part, lineorder)

get_query(query_id, \\*, params=None)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Get a specific SSB query.

.. code-block:: python

    q1_1 = benchmark.get_query("Q1.1")

    q2_1 = benchmark.get_query("Q2.1", params={
        "category": "MFGR#12",
        "region": "AMERICA"
    })

    q3_1 = benchmark.get_query("Q3.1")

Parameters:

- **query_id** (str): Query ID (Q1.1 to Q4.3)
- **params** (dict, optional): Query parameters for customization

Returns:
    str: Query SQL text

Raises:

- **ValueError**: If query_id is invalid

get_queries(dialect=None)
~~~~~~~~~~~~~~~~~~~~~~~~~

Get all SSB benchmark queries.

.. code-block:: python

    queries = benchmark.get_queries()
    print(f"Total queries: {len(queries)}")

    queries_ch = benchmark.get_queries(dialect="clickhouse")

Parameters:

- **dialect** (str, optional): Target SQL dialect

Returns:
    dict[str, str]: Dictionary mapping query IDs to SQL text

get_schema() -> dict[str, dict]
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Get SSB schema information.

The facade annotation says ``list[dict]``, but the delegated implementation returns a table-name mapping.

.. code-block:: python

    schema = benchmark.get_schema()
    for table_name, table in schema.items():
        print(f"{table_name}: {len(table['columns'])} columns")

Returns:
    dict[str, dict]: Mapping of table names to their definitions (5 tables: date, customer, supplier, part, lineorder)

get_create_tables_sql(dialect="standard", tuning_config=None)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Get CREATE TABLE SQL for all SSB tables.

.. code-block:: python

    create_sql = benchmark.get_create_tables_sql()

    create_sql_ch = benchmark.get_create_tables_sql(dialect="clickhouse")

    from benchbox.core.tuning.interface import UnifiedTuningConfiguration
    tuning = UnifiedTuningConfiguration(...)
    create_sql_tuned = benchmark.get_create_tables_sql(tuning_config=tuning)

Parameters:

- **dialect** (str): Target SQL dialect. Default: "standard"
- **tuning_config** (UnifiedTuningConfiguration, optional): Tuning settings

Returns:
    str: SQL script for creating all tables

Query Flights
-------------

SSB organizes 13 queries into 4 logical flights:

Flight 1: Simple Aggregation (Q1.1 - Q1.3)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Tests basic aggregation and filtering on the fact table.

.. code-block:: python

    flight_1_queries = ["Q1.1", "Q1.2", "Q1.3"]

    for query_id in flight_1_queries:
        query = benchmark.get_query(query_id)

**Query Characteristics**:

- **Q1.1**: Year-based aggregation with discount and quantity filters
- **Q1.2**: Month-based aggregation with quantity range
- **Q1.3**: Week-based aggregation with refined quantity range

Flight 2: Customer-Supplier Analysis (Q2.1 - Q2.3)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Tests dimension table joins and drill-down analysis.

.. code-block:: python

    flight_2_queries = ["Q2.1", "Q2.2", "Q2.3"]

    for query_id in flight_2_queries:
        query = benchmark.get_query(query_id, params={
            "category": "MFGR#12",
            "region": "AMERICA"
        })

**Query Characteristics**:

- **Q2.1**: Brand category analysis with supplier region
- **Q2.2**: Brand range analysis with supplier region
- **Q2.3**: Specific brand focus with supplier region

Flight 3: Customer Behavior Analysis (Q3.1 - Q3.4)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Tests complex multi-dimension analysis with customer geography.

.. code-block:: python

    flight_3_queries = ["Q3.1", "Q3.2", "Q3.3", "Q3.4"]

    for query_id in flight_3_queries:
        query = benchmark.get_query(query_id)

**Query Characteristics**:

- **Q3.1**: Customer nation analysis
- **Q3.2**: City-level analysis
- **Q3.3**: Specific city analysis
- **Q3.4**: Regional analysis

Flight 4: Profit Analysis (Q4.1 - Q4.3)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Tests complex aggregation with profit calculations.

.. code-block:: python

    flight_4_queries = ["Q4.1", "Q4.2", "Q4.3"]

    for query_id in flight_4_queries:
        query = benchmark.get_query(query_id)

**Query Characteristics**:

- **Q4.1**: Regional profit analysis
- **Q4.2**: Nation-specific profit trends
- **Q4.3**: City-specific profit with part category

Usage Examples
--------------

Basic Benchmark Run
~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from benchbox.ssb import SSB
    from benchbox.platforms.duckdb import DuckDBAdapter

    benchmark = SSB(scale_factor=1.0)

    benchmark.generate_data()

    adapter = DuckDBAdapter()
    results = benchmark.run_with_platform(adapter)

    print(f"Benchmark: {results.benchmark_name}")
    print(f"Total time: {results.total_execution_time:.2f}s")
    print(f"Queries: {results.successful_queries}/{results.total_queries}")

Flight-Based Execution
~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from benchbox.ssb import SSB
    from benchbox.platforms.duckdb import DuckDBAdapter
    import time

    benchmark = SSB(scale_factor=1.0)
    benchmark.generate_data()

    adapter = DuckDBAdapter()
    conn = adapter.create_connection()

    adapter.create_schema(benchmark, conn)
    adapter.load_data(benchmark, conn, benchmark.output_dir)

    print("Flight 1: Simple Aggregation")
    flight_1_queries = ["Q1.1", "Q1.2", "Q1.3"]

    flight_1_times = {}
    for query_id in flight_1_queries:
        query = benchmark.get_query(query_id)

        start = time.time()
        result = adapter.execute_query(conn, query, query_id)
        duration = time.time() - start

        flight_1_times[query_id] = duration
        print(f"  {query_id}: {duration:.3f}s")

    print(f"Flight 1 total: {sum(flight_1_times.values()):.2f}s")

Parameterized Query Execution
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from benchbox.ssb import SSB

    benchmark = SSB(scale_factor=1.0)

    custom_params = {
        "year": 1993,
        "year_month": 199401,
        "week": 6,
        "discount_min": 1,
        "discount_max": 3,
        "quantity": 25,
        "quantity_min": 26,
        "quantity_max": 35,
        "category": "MFGR#12",
        "region": "AMERICA",
        "brand_min": "MFGR#2221",
        "brand_max": "MFGR#2228",
        "brand": "MFGR#2221"
    }

    q1_1 = benchmark.get_query("Q1.1", params=custom_params)
    q2_1 = benchmark.get_query("Q2.1", params=custom_params)

    print("Q1.1 with custom year:")
    print(q1_1[:200])

Complete Flight Benchmark
~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from benchbox.ssb import SSB
    from benchbox.platforms.duckdb import DuckDBAdapter
    import time

    benchmark = SSB(scale_factor=1.0)
    adapter = DuckDBAdapter()

    benchmark.generate_data()
    conn = adapter.create_connection()
    adapter.create_schema(benchmark, conn)
    adapter.load_data(benchmark, conn, benchmark.output_dir)

    flights = {
        "Flight 1": ["Q1.1", "Q1.2", "Q1.3"],
        "Flight 2": ["Q2.1", "Q2.2", "Q2.3"],
        "Flight 3": ["Q3.1", "Q3.2", "Q3.3", "Q3.4"],
        "Flight 4": ["Q4.1", "Q4.2", "Q4.3"]
    }

    all_results = {}

    for flight_name, query_ids in flights.items():
        print(f"\n{flight_name}:")
        flight_results = {}

        for query_id in query_ids:
            query = benchmark.get_query(query_id)

            start = time.time()
            result = adapter.execute_query(conn, query, query_id)
            duration = time.time() - start

            flight_results[query_id] = {
                "duration": duration,
                "status": result["status"],
                "rows": result.get("rows_returned", 0)
            }

            print(f"  {query_id}: {duration:.3f}s ({result['status']})")

        all_results[flight_name] = flight_results

    print("\n" + "="*60)
    print("SSB Benchmark Summary")
    print("="*60)
    for flight_name, flight_results in all_results.items():
        total_time = sum(r["duration"] for r in flight_results.values())
        print(f"{flight_name}: {total_time:.2f}s total")

Multi-Platform Comparison
~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from benchbox.ssb import SSB
    from benchbox.platforms.duckdb import DuckDBAdapter
    from benchbox.platforms.clickhouse import ClickHouseAdapter
    import pandas as pd

    benchmark = SSB(scale_factor=1.0, output_dir="./data/ssb_sf1")
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
    print("\nBenchmark Results:")
    print(df)

Columnar Database Optimization
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from benchbox.ssb import SSB
    from benchbox.platforms.clickhouse import ClickHouseAdapter

    benchmark = SSB(scale_factor=10.0)
    adapter = ClickHouseAdapter(host="localhost")

    benchmark.generate_data()
    conn = adapter.create_connection()

    adapter.create_schema(benchmark, conn)
    adapter.load_data(benchmark, conn, benchmark.output_dir)

    conn.execute("""
        ALTER TABLE lineorder
        ORDER BY (lo_orderdate, lo_custkey, lo_partkey);
    """)

    flight_1_queries = ["Q1.1", "Q1.2", "Q1.3"]
    for query_id in flight_1_queries:
        query = benchmark.get_query(query_id)
        result = adapter.execute_query(conn, query, query_id)
        print(f"{query_id}: {result['execution_time']:.3f}s")

Scale Factor Comparison
~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from benchbox.ssb import SSB
    from benchbox.platforms.duckdb import DuckDBAdapter
    import pandas as pd

    adapter = DuckDBAdapter()
    scale_factors = [0.1, 1.0, 10.0]
    results_data = []

    for sf in scale_factors:
        print(f"\nTesting SF={sf}...")

        benchmark = SSB(scale_factor=sf, output_dir=f"./data/ssb_sf{sf}")
        benchmark.generate_data()

        results = benchmark.run_with_platform(adapter)

        results_data.append({
            "scale_factor": sf,
            "data_size_mb": sf * 500,
            "total_time": results.total_execution_time,
            "avg_query_time": results.average_query_time,
            "queries_per_sec": results.total_queries / results.total_execution_time
        })

    df = pd.DataFrame(results_data)
    print("\nScale Factor Performance:")
    print(df)

The ``data_size_mb`` value is an approximation of 500 MB per unit of scale factor.

See Also
--------

- :doc:`index` - Benchmark API overview
- :doc:`tpch` - TPC-H benchmark API (normalized schema)
- :doc:`tpcds` - TPC-DS benchmark API
- :doc:`../base` - Base benchmark interface
- :doc:`../results` - Results API
- :doc:`/benchmarks/ssb` - SSB guide
- :doc:`/benchmarks/tpc-h` - TPC-H guide (SSB is derived from TPC-H)

External Resources
~~~~~~~~~~~~~~~~~~

- `Original SSB Paper <https://www.cs.umb.edu/~poneil/StarSchemaB.PDF>`_ - "Star Schema Benchmark" by O'Neil et al.
- `Star Schema Design <https://en.wikipedia.org/wiki/Star_schema>`_ - Star schema principles
- `OLAP Performance <https://link.springer.com/chapter/10.1007/978-3-642-10424-4_17>`_ - Data warehouse benchmarking
