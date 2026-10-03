TPC-H Benchmark API
===================

.. tags:: reference, python-api, tpc-h

Complete Python API reference for the TPC-H benchmark.

Overview
--------

The TPC-H benchmark simulates a decision support system with 22 analytical queries. It models a wholesale supplier with parts, suppliers, customers, and orders.

**Key Features**:

- 22 analytical queries covering complex business scenarios
- 8 tables with realistic relationships
- Parametrized queries for randomization
- Official TPC-H specification compliance
- Multiple scale factors (SF=0.01 to 30000+)

Quick Start
-----------

.. code-block:: python

    from benchbox.tpch import TPCH
    from benchbox.platforms.duckdb import DuckDBAdapter

    benchmark = TPCH(scale_factor=1.0)

    benchmark.generate_data()

    adapter = DuckDBAdapter()
    results = benchmark.run_with_platform(adapter)

    print(f"Completed in {results.total_execution_time:.2f}s")

API Reference
-------------

TPCH Class
~~~~~~~~~~

.. py:module:: benchbox.tpch
.. py:class:: TPCH(scale_factor: float = 1.0, output_dir: Optional[Union[str, Path]] = None, **kwargs)

   TPC-H facade over the implementation in ``benchbox.core.tpch``. The
   constructor rejects non-numeric or non-positive scale factors. Query and
   data sizes are source-driven; this page does not promise a fixed byte size.

   .. py:method:: generate_data() -> list[Union[str, Path]]

      Generate the configured TPC-H tables and return their file paths.

   .. py:method:: get_queries(dialect: Optional[str] = None, base_dialect: Optional[str] = None) -> dict[str, str]

      Return the query mapping, optionally translated from ``base_dialect`` to
      ``dialect``.

   .. py:method:: get_query(query_id: int, *, params: Optional[dict[str, Any]] = None, seed: Optional[int] = None, scale_factor: Optional[float] = None, dialect: Optional[str] = None, base_dialect: Optional[str] = None, **kwargs) -> str

      Return one query. ``query_id`` must be an integer from 1 through 22;
      invalid types and ranges raise ``TypeError`` or ``ValueError``.

   .. py:method:: get_schema() -> list[dict]

      Return the facade's schema value. The delegated implementation currently
      returns a lower-case table-name mapping; consumers should inspect the
      runtime value rather than rely on the facade annotation.

   .. py:method:: get_create_tables_sql(dialect: str = "standard", tuning_config=None) -> str

      Return CREATE TABLE SQL for the requested dialect and tuning options.

   .. py:method:: generate_streams(num_streams: int = 1, rng_seed: Optional[int] = None, streams_output_dir: Optional[Union[str, Path]] = None) -> list[Path]

      Generate query-stream files using the supplied stream count, seed, and
      output directory.

   .. py:method:: get_stream_info(stream_id: int) -> dict[str, Any]

      Return metadata for the requested generated stream.

   .. py:method:: get_all_streams_info() -> list[dict[str, Any]]

      Return metadata for one stream or all generated streams.

   .. py:attribute:: tables

      Mapping of table names to generated data paths.

   .. py:method:: run_official_benchmark(connection_factory, config=None)

      Run the official TPC-H benchmark through the supplied connection factory and configuration, returning the implementation result.

   .. py:method:: run_power_test(connection_factory, config=None)

      Run the TPC-H power test through the supplied connection factory and configuration, returning the implementation result.

   .. py:method:: run_maintenance_test(connection_factory, config=None)

      Run the TPC-H maintenance test through the supplied connection factory and configuration, returning the implementation result.

Constructor
~~~~~~~~~~~

Parameters:

- **scale_factor** (float): Data size multiplier. SF=1.0 generates ~1GB of data. Range: 0.01 to 30000+
- **output_dir** (str|Path, optional): Directory for generated data files. Default: temporary directory
- **kwargs**: Additional options (e.g., parallel=True for parallel generation)

Raises:

- **ValueError**: If scale_factor is not positive
- **TypeError**: If scale_factor is not a number

Methods
-------

generate_data()
~~~~~~~~~~~~~~~

Generate TPC-H benchmark data.

.. code-block:: python

    data_files = benchmark.generate_data()
    print(f"Generated {len(data_files)} table files")

Returns:
    List[Union[str, Path]]: Paths to generated data files

get_query(query_id, \*, params=None, seed=None, scale_factor=None, dialect=None)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Get a specific TPC-H query.

.. code-block:: python

    q1 = benchmark.get_query(1)

    q1_bq = benchmark.get_query(1, dialect="bigquery")

    q1_param = benchmark.get_query(1, seed=42, scale_factor=10.0)

Parameters:

- **query_id** (int): Query ID (1-22)
- **params** (dict, optional): Query parameters (legacy, mostly ignored)
- **seed** (int, optional): RNG seed for parameter generation
- **scale_factor** (float, optional): Override default scale factor
- **dialect** (str, optional): Target SQL dialect (duckdb, bigquery, snowflake, etc.)

Returns:
    str: Query SQL text

Raises:

- **ValueError**: If query_id not in range 1-22
- **TypeError**: If query_id is not an integer

get_queries(dialect=None, base_dialect=None)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Get all TPC-H queries.

.. code-block:: python

    queries = benchmark.get_queries()
    print(f"Total queries: {len(queries)}")

    queries_bq = benchmark.get_queries(dialect="bigquery")

Parameters:

- **dialect** (str, optional): Target SQL dialect
- **base_dialect** (str, optional): Source dialect for translation

Returns:
    Dict[str, str]: Dictionary mapping query IDs to SQL text

get_schema()
~~~~~~~~~~~~

Get TPC-H schema information.

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

    create_sql = benchmark.get_create_tables_sql()

    create_sql_bq = benchmark.get_create_tables_sql(dialect="bigquery")

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

    streams = benchmark.generate_streams(
        num_streams=5,
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

tables
~~~~~~

Mapping of table names to generated data file paths.

.. code-block:: python

    for table_name, file_path in benchmark.tables.items():
        size_mb = Path(file_path).stat().st_size / 1024 / 1024
        print(f"{table_name}: {size_mb:.2f} MB at {file_path}")

Returns:
    Dict[str, Path]: Dictionary mapping table names to file paths

Usage Examples
--------------

Basic Benchmark Run
~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from benchbox.tpch import TPCH
    from benchbox.platforms.duckdb import DuckDBAdapter

    benchmark = TPCH(scale_factor=1.0)

    benchmark.generate_data()

    adapter = DuckDBAdapter()
    results = benchmark.run_with_platform(adapter)

    print(f"Benchmark: {results.benchmark_name}")
    print(f"Total time: {results.total_execution_time:.2f}s")
    print(f"Queries: {results.successful_queries}/{results.total_queries}")

Multi-Platform Comparison
~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from benchbox.tpch import TPCH
    from benchbox.platforms.duckdb import DuckDBAdapter
    from benchbox.platforms.clickhouse import ClickHouseAdapter

    benchmark = TPCH(scale_factor=1.0, output_dir="./data/tpch_sf1")
    benchmark.generate_data()

    platforms = {
        "DuckDB": DuckDBAdapter(),
        "ClickHouse": ClickHouseAdapter(host="localhost"),
    }

    for name, adapter in platforms.items():
        results = benchmark.run_with_platform(adapter)
        print(f"{name}: {results.total_execution_time:.2f}s")

Specific Query Execution
~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from benchbox.tpch import TPCH
    from benchbox.platforms.duckdb import DuckDBAdapter

    benchmark = TPCH(scale_factor=0.1)
    benchmark.generate_data()

    adapter = DuckDBAdapter()
    conn = adapter.create_connection()

    adapter.create_schema(benchmark, conn)
    adapter.load_data(benchmark, conn, benchmark.output_dir)

    for query_id in [1, 3, 6, 10]:
        query = benchmark.get_query(query_id)
        result = adapter.execute_query(conn, query, f"q{query_id}")
        print(f"Q{query_id}: {result['execution_time']:.3f}s")

Scale Factor Comparison
~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    import pandas as pd
    from benchbox.tpch import TPCH
    from benchbox.platforms.duckdb import DuckDBAdapter

    scale_factors = [0.01, 0.1, 1.0]
    results_data = []

    adapter = DuckDBAdapter()

    for sf in scale_factors:
        benchmark = TPCH(scale_factor=sf)
        benchmark.generate_data()

        results = benchmark.run_with_platform(adapter)

        results_data.append({
            "scale_factor": sf,
            "data_size_gb": sf * 1.0,
            "total_time": results.total_execution_time,
            "avg_query_time": results.average_query_time,
        })

    df = pd.DataFrame(results_data)
    print(df)

Official Benchmark Tests
~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from benchbox.tpch import TPCH

    benchmark = TPCH(scale_factor=1.0)

    power_results = benchmark.run_power_test(connection_factory)

    throughput_results = benchmark.run_throughput_test(connection_factory)

    maintenance_results = benchmark.run_maintenance_test(connection_factory)

See Also
--------

- :doc:`index` - Benchmark API overview
- :doc:`tpcds` - TPC-DS benchmark API
- :doc:`../base` - Base benchmark interface
- :doc:`../results` - Results API
- :doc:`/benchmarks/tpc-h` - TPC-H guide
- :doc:`/guides/tpc/tpc-h-official-guide` - Official benchmark guide
