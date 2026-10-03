AMPLab Big Data Benchmark API
==============================

.. tags:: reference, python-api, custom-benchmark

Complete Python API reference for the AMPLab Big Data Benchmark.

Overview
--------

The AMPLab Big Data Benchmark tests the performance of big data processing systems using realistic web analytics workloads. Developed by UC Berkeley's AMPLab, this benchmark focuses on three core patterns: scanning, joining, and analytics operations on web-scale data.

**Key Features**:

- **Web Analytics Workload**: Models internet-scale data processing
- **Three Query Types**: Scan, Join, and Analytics patterns
- **Simple Schema**: 3 tables (Rankings, UserVisits, Documents)
- **Scalable**: From 100MB (SF 0.01) to multi-TB (SF 100+)
- **Big Data Focus**: Designed for distributed processing systems

**Reference**: https://amplab.cs.berkeley.edu/benchmark/

Quick Start
-----------

.. code-block:: python

    from benchbox.amplab import AMPLab
    from benchbox.platforms.duckdb import DuckDBAdapter

    benchmark = AMPLab(scale_factor=0.1)
    benchmark.generate_data()

    adapter = DuckDBAdapter()
    results = adapter.run_benchmark(benchmark)

API Reference
-------------

.. py:module:: benchbox.amplab

AMPLab Class
~~~~~~~~~~~~

.. py:class:: AMPLab(scale_factor: float = 1.0, output_dir: Union[str, pathlib.Path, NoneType] = None, **kwargs)

   AMPLab web-analytics benchmark implementation.


   .. py:method:: generate_data() -> list[Union[str, Path]]

      Generate this benchmark's data files and return their paths. Generator errors propagate to the caller.

**Constructor**:


**Parameters**:

- **scale_factor** (float): Data size multiplier (choose a scale appropriate for the available storage)
- **output_dir** (str | Path | None): Output directory for generated data

Schema Methods
~~~~~~~~~~~~~~

**get_create_tables_sql(dialect="standard", tuning_config=None) -> str**

Get SQL to create all AMPLab tables (rankings, uservisits, documents).

**Example**:

.. code-block:: python

    schema_sql = benchmark.get_create_tables_sql(dialect="duckdb")

**get_schema() -> dict[str, dict]**

Get the table-definition mapping keyed by table name.

The facade annotation says ``list[dict]``, but the delegated implementation returns a table-name mapping.

Query Methods
~~~~~~~~~~~~~

**get_query(query_id, \*, params=None) -> str**

Get specific AMPLab query with optional parameters.

**Parameters**:

- **query_id** (int | str): Query ID (1, 1a, 2, 2a, 3, 3a, 4, or 5)
- **params** (dict | None): Query parameters

**Supported Parameters**:

- pagerank_threshold (int): Minimum page rank
- start_date (str): Start date for filtering
- end_date (str): End date for filtering
- limit_rows (int): Result limit
- search_term (str): Search keyword
- min_visits (int): Minimum visit count
- keyword1 (str): First content keyword (default: ``web``)
- keyword2 (str): Second content keyword (default: ``data``)
- min_content_length (int): Minimum content length (default: 1000)
- min_revenue (float): Minimum revenue (default: 1.0)

**Example**:

.. code-block:: python

    scan_query = benchmark.get_query("1", params={
        'pagerank_threshold': 1500
    })

    join_query = benchmark.get_query("2", params={
        'start_date': '2000-01-01',
        'end_date': '2000-01-03',
        'limit_rows': 100
    })

    analytics_query = benchmark.get_query("3", params={
        'search_term': 'google',
        'min_visits': 10
    })

**get_queries(dialect=None) -> dict[str, str]**

Get all eight AMPLab queries.

**Example**:

.. code-block:: python

    queries = benchmark.get_queries()
    print(f"Available queries: {list(queries.keys())}")

Usage Examples
--------------

Basic Benchmark Execution
~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from benchbox.amplab import AMPLab
    from benchbox.platforms.duckdb import DuckDBAdapter

    benchmark = AMPLab(scale_factor=0.1)
    data_files = benchmark.generate_data()

    adapter = DuckDBAdapter(memory_limit="4GB")
    results = adapter.run_benchmark(benchmark)

    print(f"Queries: {results.total_queries}")
    print(f"Average time: {results.average_query_time:.3f}s")

Query Type Testing
~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from benchbox.amplab import AMPLab
    from benchbox.platforms.duckdb import DuckDBAdapter
    import time

    benchmark = AMPLab(scale_factor=0.01)
    benchmark.generate_data()

    adapter = DuckDBAdapter()
    conn = adapter.create_connection()
    adapter.create_schema(benchmark, conn)
    adapter.load_data(benchmark, conn, benchmark.output_dir)

    query_types = {
        'Scan': ['1', '1a'],
        'Join': ['2', '2a'],
        'Analytics': ['3', '3a'],
        'Extended analytics': ['4', '5']
    }

    params = {
        'pagerank_threshold': 1000,
        'start_date': '2000-01-01',
        'end_date': '2000-01-03',
        'limit_rows': 100
    }

    for query_type, query_ids in query_types.items():
        print(f"\n{query_type} Queries:")
        for query_id in query_ids:
            query = benchmark.get_query(query_id, params=params)

            start = time.time()
            result = conn.execute(query).fetchall()
            elapsed = time.time() - start

            print(f"  Query {query_id}: {elapsed*1000:.1f} ms ({len(result)} rows)")

Performance Comparison
~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from benchbox.amplab import AMPLab
    from benchbox.platforms.duckdb import DuckDBAdapter
    from benchbox.core.results.timing import TimingCollector, TimingAnalyzer

    scale_factors = [0.01, 0.1, 0.5]

    for sf in scale_factors:
        print(f"\n=== Scale Factor {sf} ===")

        benchmark = AMPLab(scale_factor=sf)
        benchmark.generate_data()

        adapter = DuckDBAdapter()
        conn = adapter.create_connection()
        adapter.create_schema(benchmark, conn)
        adapter.load_data(benchmark, conn, benchmark.output_dir)

        scan_query = benchmark.get_query("1", params={'pagerank_threshold': 1000})

        start = time.time()
        result = conn.execute(scan_query).fetchall()
        elapsed = time.time() - start

        print(f"  Scan query: {elapsed*1000:.1f} ms")
        print(f"  Rows: {len(result)}")

Best Practices
--------------

1. **Use Appropriate Scale Factors**

   .. code-block:: python

       dev = AMPLab(scale_factor=0.01)

       test = AMPLab(scale_factor=0.1)

       prod = AMPLab(scale_factor=1.0)

2. **Parameterize Queries**

   .. code-block:: python

       params = {
           'pagerank_threshold': 1000,
           'start_date': '2000-01-01',
           'end_date': '2000-01-03',
           'limit_rows': 100,
           'search_term': 'google',
           'min_visits': 10
       }

       query = benchmark.get_query("2", params=params)

3. **Test Query Types Separately**

   .. code-block:: python

       scan_queries = ['1', '1a']

       join_queries = ['2', '2a']

       analytics_queries = ['3', '3a', '4', '5']

See Also
--------

- :doc:`/benchmarks/amplab` - AMPLab benchmark guide
- :doc:`clickbench` - ClickBench analytics benchmark
- :doc:`tpch` - TPC-H benchmark
- :doc:`/reference/python-api/base` - Base benchmark interface

External Resources
~~~~~~~~~~~~~~~~~~

- `AMPLab Benchmark <https://amplab.cs.berkeley.edu/benchmark/>`_ - Original specification
- `Berkeley AMPLab <https://amplab.cs.berkeley.edu/>`_ - Research lab
