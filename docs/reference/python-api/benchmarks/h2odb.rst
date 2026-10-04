H2O.ai Database Benchmark API
================================

.. tags:: reference, python-api, h2odb

Complete Python API reference for the H2O.ai Database Benchmark.

Overview
--------

The H2O.ai Database Benchmark tests analytical database performance using real-world taxi trip data patterns. Developed by H2O.ai for their database benchmarking initiative, this benchmark focuses on fundamental analytical operations common in data science and machine learning workflows: aggregations, grouping, and time-series analysis.

**Key Features**:

- **Real-World Data**: Based on NYC taxi trip data structure
- **Data Science Focus**: Tests operations common in ML pipelines
- **Single-Table Design**: Emphasizes aggregation performance
- **Time-Series Operations**: Tests temporal aggregation patterns
- **Scalable**: From 10K rows (SF 0.01) to 1B rows (SF 1000)
- **Analytics-Oriented**: Focuses on data exploration patterns

**Reference**: https://h2oai.github.io/db-benchmark/

Quick Start
-----------

.. code-block:: python

    from benchbox.h2odb import H2ODB
    from benchbox.platforms.duckdb import DuckDBAdapter

    benchmark = H2ODB(scale_factor=0.1)
    benchmark.generate_data()

    adapter = DuckDBAdapter()
    results = adapter.run_benchmark(benchmark)

API Reference
-------------

.. py:module:: benchbox.h2odb

H2ODB Class
~~~~~~~~~~~

.. py:class:: H2ODB(scale_factor: float = 1.0, output_dir: Union[str, pathlib.Path, NoneType] = None, **kwargs)

   H2O database benchmark implementation for taxi-trip analytical queries.


   .. py:method:: generate_data() -> list[Union[str, Path]]

      Generate this benchmark's data files and return their paths. Generator errors propagate to the caller.

**Constructor**:

**Parameters**:

- **scale_factor** (float): Data size multiplier (1.0 ≈ 1M rows, ~100MB)
- **output_dir** (str | Path | None): Output directory for generated data

Schema Methods
~~~~~~~~~~~~~~

**get_create_tables_sql(dialect="standard", tuning_config=None) -> str**

Get SQL to create the TRIPS table with taxi trip data schema.

**Example**:

.. code-block:: python

    schema_sql = benchmark.get_create_tables_sql(dialect="duckdb")

**get_schema() -> dict[str, dict]**

Get the table-definition mapping for the TRIPS table.

The facade annotation says ``list[dict]``, but the delegated implementation returns a table-name mapping.

Query Methods
~~~~~~~~~~~~~

**get_query(query_id, \*, params=None) -> str**

Get specific H2O.ai query with optional parameters.

**Parameters**:

- **query_id** (int | str): Query ID (Q1-Q10 or 1-10)
- **params**: Must be omitted. H2O DB queries are static; supplying parameters raises ``ValueError``.

**Example**:

.. code-block:: python

    count_query = benchmark.get_query("Q1")

    temporal_query = benchmark.get_query("Q8")

    stats_query = benchmark.get_query("Q9")

**get_queries(dialect=None) -> dict[str, str]**

Get all H2O.ai queries (10 queries total).

**Example**:

.. code-block:: python

    queries = benchmark.get_queries()
    print(f"Available queries: {list(queries.keys())}")

Query Categories
~~~~~~~~~~~~~~~~

The H2O.ai benchmark queries are organized by analytical operation type:

**Basic Aggregation Queries (Q1-Q2)**:
  - Q1: Simple COUNT(*)
  - Q2: SUM and AVG aggregations
  - **Performance focus**: Sequential scan and basic aggregation speed

**Grouping Queries (Q3-Q6)**:
  - Q3: Single-column GROUP BY
  - Q4: Multi-aggregate grouping
  - Q5: Two-column GROUP BY
  - Q6: Complex multi-column grouping
  - **Performance focus**: Hash aggregation and grouping algorithms

**Temporal Analysis Queries (Q7-Q8)**:
  - Q7: Time-based grouping (hourly analysis)
  - Q8: Complex temporal aggregation with date filtering
  - **Performance focus**: Date/time function evaluation and temporal grouping

**Advanced Analytics Queries (Q9-Q10)**:
  - Q9: Statistical analysis (STDDEV, percentiles)
  - Q10: Complex multi-metric analytics
  - **Performance focus**: Statistical function computation and sorting

Usage Examples
--------------

Basic Benchmark Execution
~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from benchbox.h2odb import H2ODB
    from benchbox.platforms.duckdb import DuckDBAdapter

    benchmark = H2ODB(scale_factor=0.1)
    data_files = benchmark.generate_data()

    adapter = DuckDBAdapter(memory_limit="4GB")
    results = adapter.run_benchmark(benchmark)

    print(f"Queries: {results.total_queries}")
    print(f"Average time: {results.average_query_time:.3f}s")

Query Group Testing
~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from benchbox.h2odb import H2ODB
    from benchbox.platforms.duckdb import DuckDBAdapter
    import time

    benchmark = H2ODB(scale_factor=0.01)
    benchmark.generate_data()

    adapter = DuckDBAdapter()
    conn = adapter.create_connection()
    adapter.create_schema(benchmark, conn)
    adapter.load_data(benchmark, conn, benchmark.output_dir)

    query_groups = {
        'Basic': ['Q1', 'Q2'],
        'Grouping': ['Q3', 'Q4', 'Q5', 'Q6'],
        'Temporal': ['Q7', 'Q8'],
        'Advanced': ['Q9', 'Q10']
    }

    for group_name, query_ids in query_groups.items():
        print(f"\n{group_name} Queries:")
        for query_id in query_ids:
            query = benchmark.get_query(query_id)

            start = time.time()
            result = conn.execute(query).fetchall()
            elapsed = time.time() - start

            print(f"  {query_id}: {elapsed*1000:.1f} ms ({len(result)} rows)")

Aggregation Performance Analysis
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from benchbox.h2odb import H2ODB
    from benchbox.platforms.duckdb import DuckDBAdapter
    import time
    from statistics import mean

    scale_factors = [0.01, 0.1, 1.0]

    for sf in scale_factors:
        print(f"\n=== Scale Factor {sf} ===")

        benchmark = H2ODB(scale_factor=sf)
        benchmark.generate_data()

        adapter = DuckDBAdapter()
        conn = adapter.create_connection()
        adapter.create_schema(benchmark, conn)
        adapter.load_data(benchmark, conn, benchmark.output_dir)

        aggregation_tests = [
            ('Q1', 'Simple count'),
            ('Q2', 'Sum and avg'),
            ('Q3', 'Single-column GROUP BY'),
            ('Q5', 'Two-column GROUP BY'),
            ('Q9', 'Statistical functions')
        ]

        for query_id, description in aggregation_tests:
            query = benchmark.get_query(query_id)

            times = []
            for _ in range(3):
                start = time.time()
                result = conn.execute(query).fetchall()
                times.append(time.time() - start)

            print(f"{query_id} ({description}): {mean(times)*1000:.1f} ms")

Data Science Workflow Integration
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from benchbox.h2odb import H2ODB
    from benchbox.platforms.duckdb import DuckDBAdapter
    import pandas as pd
    import time

    benchmark = H2ODB(scale_factor=1.0)
    benchmark.generate_data()

    trips_df = pd.read_csv(benchmark.output_dir / "trips.csv")

    print("Data Science Operations Performance:")

    start = time.time()
    trips_df['hour'] = pd.to_datetime(trips_df['pickup_datetime']).dt.hour
    trips_df['day_of_week'] = pd.to_datetime(trips_df['pickup_datetime']).dt.dayofweek
    trips_df['trip_duration'] = (
        pd.to_datetime(trips_df['dropoff_datetime']) -
        pd.to_datetime(trips_df['pickup_datetime'])
    ).dt.total_seconds()
    print(f"Feature engineering: {time.time() - start:.3f}s")

    start = time.time()
    hourly_stats = trips_df.groupby('hour').agg({
        'fare_amount': ['sum', 'mean', 'std', 'count'],
        'trip_distance': ['mean'],
        'passenger_count': ['mean']
    })
    print(f"GroupBy aggregation: {time.time() - start:.3f}s")

    start = time.time()
    vendor_stats = trips_df.groupby('vendor_id').agg({
        'fare_amount': ['count', 'sum', 'mean', 'std', 'min', 'max'],
        'tip_amount': ['mean', 'std']
    })
    print(f"Statistical analysis: {time.time() - start:.3f}s")

Best Practices
--------------

1. **Use Appropriate Scale Factors**

   Use ``0.01`` for development and testing (about 10K rows, 1 MB), ``1.0`` for the standard benchmark (about 1M rows, 100 MB), and ``10.0`` for large-scale testing (about 10M rows, 1 GB).

   .. code-block:: python

       dev = H2ODB(scale_factor=0.01)

       test = H2ODB(scale_factor=1.0)

       prod = H2ODB(scale_factor=10.0)

2. **Test Query Groups Separately**

   Test basic aggregation (``Q1``, ``Q2``), grouping (``Q3``-``Q6``), temporal analysis (``Q7``, ``Q8``), and advanced analytics (``Q9``, ``Q10``) performance separately.

   .. code-block:: python

       basic_queries = ['Q1', 'Q2']

       grouping_queries = ['Q3', 'Q4', 'Q5', 'Q6']

       temporal_queries = ['Q7', 'Q8']

       advanced_queries = ['Q9', 'Q10']

3. **Use the fixed query corpus**

   H2O DB query SQL is static. Select a query ID such as ``Q8`` or ``Q9`` without parameters.

4. **Monitor Memory for Large Grouping Operations**

   Large scale factors may require memory configuration.

   .. code-block:: python

       adapter = DuckDBAdapter(memory_limit="8GB")

5. **Use Multiple Iterations for Timing**

   .. code-block:: python

       from statistics import mean

       times = []
       for _ in range(3):
           start = time.time()
           result = conn.execute(query).fetchall()
           times.append(time.time() - start)

       avg_time = mean(times)

Common Issues
-------------

**Issue: Slow aggregation queries on large datasets**
  - **Solution**: Use columnar storage and appropriate indices
  - Consider partitioning by date for temporal queries
  - Increase memory limits for large GROUP BY operations

**Issue: Memory errors with high scale factors**
  - **Solution**: Start with smaller scale factors (0.01, 0.1)
  - Increase database memory limits
  - Use external aggregation if available

**Issue: Incorrect temporal analysis results**
  - **Solution**: Ensure proper timezone handling
  - Filter out NULL or invalid dates
  - Use appropriate date truncation functions

See Also
--------

- :doc:`/benchmarks/h2odb` - H2O.ai benchmark guide
- :doc:`clickbench` - ClickBench analytics benchmark
- :doc:`amplab` - AMPLab big data benchmark
- :doc:`/reference/python-api/base` - Base benchmark interface

External Resources
~~~~~~~~~~~~~~~~~~

- `H2O.ai DB Benchmark <https://h2oai.github.io/db-benchmark/>`_ - Original specification
- `NYC Taxi Data <https://www1.nyc.gov/site/tlc/about/tlc-trip-record-data.page>`_ - Source data format
- `Database Performance Analysis <https://duckdblabs.github.io/db-benchmark/>`_ - Performance comparisons
