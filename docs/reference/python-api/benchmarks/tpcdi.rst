TPC-DI Benchmark API
====================

.. tags:: reference, python-api, tpc-di

Complete Python API reference for the TPC-DI (Data Integration) benchmark.

Overview
--------

The TPC-DI benchmark evaluates data integration and ETL (Extract, Transform, Load) processes in data warehousing scenarios. It models a financial services environment with customer data, trading activities, and complex transformation logic including slowly changing dimensions (SCD).

**Key Features**:

- **Data Integration focus** - Tests ETL processes, not just queries
- **Financial services domain** - Trading, customer, and company data
- **Slowly Changing Dimensions** - SCD Type 1 and Type 2 implementations
- **Data quality validation** - Systematic validation queries
- **Multiple data sources** - CSV, XML, fixed-width formats
- **Historical and incremental loading** - Full loads and updates
- **Complex transformations** - Business rules and data cleansing
- **Audit and lineage tracking** - Data governance capabilities

Quick Start
-----------

.. code-block:: python

    from benchbox.tpcdi import TPCDI
    from benchbox.platforms.duckdb import DuckDBAdapter

    benchmark = TPCDI(scale_factor=1.0)

    benchmark.generate_data()

    adapter = DuckDBAdapter()
    results = benchmark.run_with_platform(adapter)

    print(f"Completed in {results.total_execution_time:.2f}s")

API Reference
-------------

TPCDI Class
~~~~~~~~~~~

.. py:class:: benchbox.tpcdi.TPCDI(scale_factor: float=1.0, output_dir: Optional[Union[str, Path]]=None, **kwargs)

   Public TPC-DI facade over the data-integration implementation. Inherits the
   common benchmark lifecycle and adapter integration described in :doc:`../base`.
   Its own query, schema and ETL methods delegate to the TPC-DI implementation.
   The result of run_with_platform is a BenchmarkResults object; connection-based
   run_benchmark and run_full_benchmark return their TPC-DI result dictionaries.
   These APIs are distinct.

   :param scale_factor: Dataset scale factor; actual file size depends on generated tables and options.
   :param output_dir: Generated-data location; omitted output uses the configured TPC-DI datagen directory.
   :param kwargs: Implementation options, including verbose, parallel/configuration and generation options.

   Calculating metrics does not by itself certify an official TPC-DI run.

.. py:method:: benchbox.tpcdi.TPCDI.generate_data() -> list[Union[str, Path]]

   Generate TPC-DI benchmark data.

   :returns: A list of paths to the generated data files


.. py:method:: benchbox.tpcdi.TPCDI.get_queries(dialect: Optional[str]=None) -> dict[str, str]

   Get all TPC-DI benchmark queries.

   :param dialect: Target SQL dialect for query translation. If None, returns original queries.

   :returns: A dictionary mapping query IDs to query strings


.. py:method:: benchbox.tpcdi.TPCDI.get_query(query_id: Union[int, str], *, params: Optional[dict[str, Any]]=None) -> str

   Get a specific TPC-DI benchmark query.

   :param query_id: The ID of the query to retrieve
   :param params: Optional parameters to customize the query

   :returns: The query string

   :raises ValueError: If the query_id is invalid


   params is keyword-only on this facade. Numeric IDs up to 12 map to VQ IDs;
   higher numeric IDs map to AQ IDs after subtracting 12. Named IDs also include
   the legacy V/A queries and extended VQ/AQ/EQ query families.


.. py:method:: benchbox.tpcdi.TPCDI.get_schema(dialect: str='standard') -> dict[str, dict[str, Any]]

   Get the TPC-DI schema.

   :param dialect: Target SQL dialect

   :returns: A dictionary mapping table names to table definitions


.. py:method:: benchbox.tpcdi.TPCDI.get_create_tables_sql(dialect: str='standard', tuning_config=None) -> str

   Get SQL to create all TPC-DI tables.

   :param dialect: SQL dialect to use
   :param tuning_config: Unified tuning configuration for constraint settings

   :returns: SQL script for creating all tables


.. py:method:: benchbox.tpcdi.TPCDI.generate_source_data(formats: Optional[list[str]]=None, batch_types: Optional[list[str]]=None) -> dict[str, list[str]]

   Generate source data in various formats for ETL processing.

   :param formats: List of data formats to generate (csv, xml, fixed_width, json)
   :param batch_types: List of batch types to generate (historical, incremental, scd)

   :returns: Dictionary mapping formats to lists of generated file paths


   Omitted formats selects csv, xml, fixed_width and json; omitted batch_types
   selects historical, incremental and scd. Unsupported formats raise ValueError.


.. py:method:: benchbox.tpcdi.TPCDI.run_etl_pipeline(connection: Any, batch_type: str='historical', validate_data: bool=True) -> dict[str, Any]

   Run the complete ETL pipeline for TPC-DI.

   :param connection: Database connection for target warehouse
   :param batch_type: Type of batch to process (historical, incremental, scd)
   :param validate_data: Whether to run data validation after ETL

   :returns: Dictionary containing ETL execution results and metrics


.. py:method:: benchbox.tpcdi.TPCDI.validate_etl_results(connection: Any) -> dict[str, Any]

   Validate ETL results using data quality checks.

   :param connection: Database connection to validate against

   :returns: Dictionary containing validation results and data quality metrics


.. py:method:: benchbox.tpcdi.TPCDI.get_etl_status() -> dict[str, Any]

   Get current ETL processing status and metrics.

   :returns: Dictionary containing ETL status, metrics, and batch information


   Keys include etl_mode_enabled, source_directory, staging_directory,
   warehouse_directory, simple_stats, supported_formats and batch_types.


.. py:property:: benchbox.tpcdi.TPCDI.etl_mode
   :type: bool

   Check if ETL mode is enabled.

   :returns: Always True as TPC-DI is now a pure ETL benchmark


.. py:method:: benchbox.tpcdi.TPCDI.load_data_to_database(connection: Any, tables: Optional[list[str]]=None) -> None

   Load generated data into a database.

   :param connection: Database connection
   :param tables: Optional list of tables to load. If None, loads all.

   :raises ValueError: If data hasn't been generated yet


.. py:method:: benchbox.tpcdi.TPCDI.run_benchmark(connection: Any, queries: Optional[list[str]]=None, iterations: int=1) -> dict[str, Any]

   Run the complete TPC-DI benchmark.

   :param connection: Database connection to use
   :param queries: Optional list of query IDs to run. If None, runs all.
   :param iterations: Number of times to run each query

   :returns: Dictionary containing benchmark results


.. py:method:: benchbox.tpcdi.TPCDI.execute_query(query_id: Union[int, str], connection: Any, params: Optional[dict[str, Any]]=None) -> Any

   Execute a TPC-DI query on the given database connection.

   :param query_id: Query identifier (e.g., "V1", "V2", "A1", etc.)
   :param connection: Database connection to use for execution
   :param params: Optional parameters to use in the query

   :returns: Query results from the database

   :raises ValueError: If the query_id is not valid


.. py:method:: benchbox.tpcdi.TPCDI.create_schema(connection: Any, dialect: str='duckdb') -> None

   Create TPC-DI schema using the schema manager.

   :param connection: Database connection
   :param dialect: Target SQL dialect


.. py:method:: benchbox.tpcdi.TPCDI.run_full_benchmark(connection: Any, dialect: str='duckdb') -> dict[str, Any]

   Run the complete TPC-DI benchmark with all phases. On success, the returned
   dictionary contains ``success``, ``metrics``, ``etl_result``,
   ``validation_result``, ``report`` and ``execution_time_seconds``. Failures return
   ``success=False``, ``error`` and ``execution_time_seconds``. The nested results
   are serialized dictionaries; execution time is in seconds.

   This is the main entry point for running a complete TPC-DI benchmark
   including schema creation, data loading, ETL processing, validation,
   and metrics calculation.

   :param connection: Database connection
   :param dialect: SQL dialect for the target database

   :returns: Complete benchmark results with all metrics


.. py:method:: benchbox.tpcdi.TPCDI.run_etl_benchmark(connection: Any, dialect: str='duckdb') -> Any

   Run the ETL benchmark pipeline.

   :param connection: Database connection
   :param dialect: SQL dialect

   :returns: ETL execution results


   The current implementation returns benchbox.core.tpcdi.etl.ETLResult;
   the public facade retains its Any return annotation.


.. py:method:: benchbox.tpcdi.TPCDI.run_data_validation(connection: Any) -> Any

   Run data quality validation.

   :param connection: Database connection

   :returns: Data quality validation results


   The current implementation returns benchbox.core.tpcdi.validation.DataQualityResult.

   :raises ValueError: The validator has not been initialized.


.. py:method:: benchbox.tpcdi.TPCDI.calculate_official_metrics(etl_result: Any, validation_result: Any) -> Any

   Calculate official TPC-DI metrics.

   :param etl_result: ETL execution results
   :param validation_result: Data validation results

   :returns: Official TPC-DI benchmark metrics


   The current implementation consumes ETLResult and DataQualityResult and
   returns benchbox.core.tpcdi.metrics.BenchmarkMetrics.


.. py:method:: benchbox.tpcdi.TPCDI.optimize_database(connection: Any) -> dict[str, Any]

   Optimize database performance for TPC-DI queries.

   :param connection: Database connection

   :returns: Optimization results


.. py:property:: benchbox.tpcdi.TPCDI.validator
   :type: Any

   Get the TPC-DI validator instance.

   :returns: TPCDIValidator instance


   May be None before the implementation initializes validation for a connection.


.. py:property:: benchbox.tpcdi.TPCDI.schema_manager
   :type: Any

   Get the TPC-DI schema manager instance.

   :returns: TPCDISchemaManager instance


.. py:property:: benchbox.tpcdi.TPCDI.metrics_calculator
   :type: Any

   Get the TPC-DI metrics calculator instance.

   :returns: TPCDIMetrics instance



Constructor
~~~~~~~~~~~

The constructor accepts ``verbose`` through ``**kwargs``; it defaults to
``False`` and controls implementation logging.

Parameters:

- **scale_factor** (float): Data size multiplier. Actual file size depends on generated tables and options.
- **output_dir** (str|Path, optional): Directory for generated data files. Default: configured TPC-DI datagen directory
- **verbose** (bool): Enable verbose logging. Default: False
- **kwargs**: Additional options (e.g., batch_size, enable_scd, validate_data)

Raises:

- **ValueError**: If scale_factor is not positive
- **TypeError**: If scale_factor is not a number

Methods
-------

generate_data()
~~~~~~~~~~~~~~~

Generate TPC-DI data warehouse tables.

.. code-block:: python

    data_files = benchmark.generate_data()
    print(f"Generated {len(data_files)} table files")

Returns:
    List[Union[str, Path]]: Paths to generated data files

generate_source_data(formats=None, batch_types=None)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Generate source data files in various formats for ETL processing.

.. code-block:: python

    source_files = benchmark.generate_source_data()

    source_files = benchmark.generate_source_data(
        formats=["csv", "xml"],
        batch_types=["historical", "incremental"]
    )

    for format_type, files in source_files.items():
        print(f"{format_type}: {len(files)} files")

The first call generates all source formats. The second generates only the specified formats and batch types.

Parameters:

- **formats** (list[str], optional): Data formats to generate. Options: "csv", "xml", "fixed_width", "json"
- **batch_types** (list[str], optional): Batch types to generate. Options: "historical", "incremental", "scd"

Returns:
    dict[str, list[str]]: Dictionary mapping formats to file paths

get_query(query_id, \\*, params=None)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Get a specific TPC-DI query.

.. code-block:: python

    v1 = benchmark.get_query("V1")

    a1 = benchmark.get_query("A1")

    dq1 = benchmark.get_query("VQ1")

The examples get a validation query, an analytical query and a data quality query, in that order.

Parameters:

- **query_id** (int|str): Query ID (e.g., "V1", "A1", "DQ1")
- **params** (dict, optional): Query parameters

Returns:
    str: Query SQL text

Raises:

- **ValueError**: If query_id is invalid

get_queries(dialect=None)
~~~~~~~~~~~~~~~~~~~~~~~~~

Get all TPC-DI benchmark queries.

.. code-block:: python

    queries = benchmark.get_queries()
    print(f"Total queries: {len(queries)}")

    queries_bq = benchmark.get_queries(dialect="bigquery")

The first call gets all queries. The second gets them with dialect translation.

Parameters:

- **dialect** (str, optional): Target SQL dialect

Returns:
    dict[str, str]: Dictionary mapping query IDs to SQL text

get_schema()
~~~~~~~~~~~~

Get TPC-DI schema information.

.. code-block:: python

    schema = benchmark.get_schema()
    for table in schema:
        print(f"{table['name']}: {len(table['columns'])} columns")

Returns:
    list[dict]: List of table definitions with columns and types

get_create_tables_sql(dialect="standard", tuning_config=None)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Get CREATE TABLE SQL for all TPC-DI tables.

.. code-block:: python

    create_sql = benchmark.get_create_tables_sql()

    create_sql_sf = benchmark.get_create_tables_sql(dialect="snowflake")

    from benchbox.core.tuning.interface import UnifiedTuningConfiguration
    tuning = UnifiedTuningConfiguration(...)
    create_sql_tuned = benchmark.get_create_tables_sql(tuning_config=tuning)

The three calls return standard SQL, SQL for a specific dialect, and SQL with a tuning configuration.

Parameters:

- **dialect** (str): Target SQL dialect. Default: "standard"
- **tuning_config** (UnifiedTuningConfiguration, optional): Tuning settings

Returns:
    str: SQL script for creating all tables

ETL Methods
-----------

run_etl_pipeline(connection, batch_type="historical", validate_data=True)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Run the complete ETL pipeline for TPC-DI.

.. code-block:: python

    from benchbox.platforms.duckdb import DuckDBAdapter

    adapter = DuckDBAdapter()
    conn = adapter.create_connection()

    etl_result = benchmark.run_etl_pipeline(
        conn,
        batch_type="historical",
        validate_data=True
    )

    print(f"ETL duration: {etl_result['duration']:.2f}s")
    print(f"Records loaded: {etl_result['records_loaded']:,}")

Parameters:

- **connection** (Any): Database connection for target warehouse
- **batch_type** (str): Type of batch. Options: "historical", "incremental", "scd". Default: "historical"
- **validate_data** (bool): Run data validation after ETL. Default: True

Returns:
    dict[str, Any]: ETL execution results and metrics

validate_etl_results(connection)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Validate ETL results using data quality checks.

.. code-block:: python

    validation_result = benchmark.validate_etl_results(conn)

    print(f"Validation status: {validation_result['status']}")
    print(f"Passed checks: {validation_result['passed_checks']}")
    print(f"Failed checks: {validation_result['failed_checks']}")

Parameters:

- **connection** (Any): Database connection to validate against

Returns:
    dict[str, Any]: Validation results and data quality metrics

get_etl_status()
~~~~~~~~~~~~~~~~

Get current ETL processing status and metrics.

.. code-block:: python

    status = benchmark.get_etl_status()

    print(f"Current batch: {status['batch_id']}")
    print(f"Tables loaded: {status['tables_loaded']}")
    print(f"Total records: {status['total_records']:,}")

Returns:
    dict[str, Any]: ETL status, metrics, and batch information

Benchmark Methods
-----------------

run_full_benchmark(connection, dialect="duckdb")
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Run the complete TPC-DI benchmark with all phases.

.. code-block:: python

    from benchbox.platforms.duckdb import DuckDBAdapter

    adapter = DuckDBAdapter()
    conn = adapter.create_connection()

    results = benchmark.run_full_benchmark(conn, dialect="duckdb")

    print(f"Total duration: {results['execution_time_seconds']:.2f}s")
    if results["success"]:
        print(results["metrics"])
    else:
        print(results["error"])

Parameters:

- **connection** (Any): Database connection
- **dialect** (str): SQL dialect for the target database. Default: "duckdb"

Returns:
    dict[str, Any]: Complete benchmark results with all metrics

create_schema(connection, dialect="duckdb")
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Create TPC-DI schema using the schema manager.

.. code-block:: python

    adapter.create_schema(benchmark, conn)

Parameters:

- **connection** (Any): Database connection
- **dialect** (str): Target SQL dialect. Default: "duckdb"

run_etl_benchmark(connection, dialect="duckdb")
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Run the ETL benchmark pipeline.

.. code-block:: python

    etl_results = benchmark.run_etl_benchmark(conn, dialect="duckdb")

Parameters:

- **connection** (Any): Database connection
- **dialect** (str): SQL dialect. Default: "duckdb"

Returns:
    Any: ETL execution results

run_data_validation(connection)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Run data quality validation.

.. code-block:: python

    validation_results = benchmark.run_data_validation(conn)

Parameters:

- **connection** (Any): Database connection

Returns:
    Any: Data quality validation results

calculate_official_metrics(etl_result, validation_result)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Calculate official TPC-DI metrics.

.. code-block:: python

    etl_result = benchmark.run_etl_benchmark(conn)
    validation_result = benchmark.run_data_validation(conn)

    metrics = benchmark.calculate_official_metrics(etl_result, validation_result)

    print(f"Composite Performance Score: {metrics.overall_performance:.2f}")
    print(f"Throughput: {metrics.etl_throughput:.2f} records/sec")

Run the ETL benchmark and the validation first, then calculate the official metrics from their results.

Parameters:

- **etl_result** (Any): ETL execution results
- **validation_result** (Any): Data validation results

Returns:
    Any: Official TPC-DI benchmark metrics

optimize_database(connection)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Optimize database performance for TPC-DI queries.

.. code-block:: python

    optimization_result = benchmark.optimize_database(conn)

    print(f"Indexes created: {optimization_result['indexes_created']}")
    print(f"Statistics updated: {optimization_result['stats_updated']}")

Parameters:

- **connection** (Any): Database connection

Returns:
    dict[str, Any]: Optimization results

Properties
----------

etl_mode
~~~~~~~~

Check if ETL mode is enabled.

.. code-block:: python

    if benchmark.etl_mode:
        print("ETL mode enabled")

Returns:
    bool: Always True (TPC-DI is an ETL benchmark)

validator
~~~~~~~~~

Access to the TPC-DI validator instance.

.. code-block:: python

    validator = benchmark.validator
    validation_result = validator.run_all_validations(conn)

Returns:
    TPCDIValidator: Validator instance for data quality checks

schema_manager
~~~~~~~~~~~~~~

Access to the TPC-DI schema manager instance.

.. code-block:: python

    schema_mgr = benchmark.schema_manager
    schema_info = schema_mgr.get_table_info("DimCustomer")

Returns:
    TPCDISchemaManager: Schema manager instance

metrics_calculator
~~~~~~~~~~~~~~~~~~

Access to the TPC-DI metrics calculator instance.

.. code-block:: python

    metrics_calc = benchmark.metrics_calculator
    official_metrics = metrics_calc.calculate_metrics(etl_result)

Returns:
    TPCDIMetrics: Metrics calculator instance

Usage Examples
--------------

Basic ETL Pipeline
~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from benchbox.tpcdi import TPCDI
    from benchbox.platforms.duckdb import DuckDBAdapter

    benchmark = TPCDI(scale_factor=1.0)

    source_files = benchmark.generate_source_data()

    adapter = DuckDBAdapter()
    conn = adapter.create_connection()

    benchmark.create_schema(conn)

    etl_result = benchmark.run_etl_pipeline(
        conn,
        batch_type="historical",
        validate_data=True
    )

    print(f"ETL completed in {etl_result['duration']:.2f}s")
    print(f"Validation status: {etl_result['validation_status']}")

This example creates a benchmark with scale factor 1 (about 100MB), generates the source data, sets up the database and creates the schema, and then runs the ETL pipeline.

Incremental Batch Processing
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from benchbox.tpcdi import TPCDI
    from benchbox.platforms.duckdb import DuckDBAdapter

    benchmark = TPCDI(scale_factor=1.0)
    adapter = DuckDBAdapter()
    conn = adapter.create_connection()

    print("Running historical load...")
    hist_result = benchmark.run_etl_pipeline(
        conn,
        batch_type="historical",
        validate_data=True
    )

    for batch_id in range(1, 4):
        print(f"Processing incremental batch {batch_id}...")
        inc_result = benchmark.run_etl_pipeline(
            conn,
            batch_type="incremental",
            validate_data=True
        )
        print(f"Batch {batch_id} duration: {inc_result['duration']:.2f}s")

The example runs the historical load first and then processes three incremental batches.

Data Quality Validation
~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from benchbox.tpcdi import TPCDI

    benchmark = TPCDI(scale_factor=1.0)

    etl_result = benchmark.run_etl_pipeline(conn)

    validation = benchmark.validate_etl_results(conn)

    print(f"Validation Queries:")
    for query_id in ["V1", "V2", "V3", "V4", "V5"]:
        status = validation['queries'][query_id]['status']
        print(f"  {query_id}: {status}")

    print(f"\nData Quality Checks:")
    for check_id in ["DQ1", "DQ2", "DQ3", "DQ4", "DQ5"]:
        status = validation['quality_checks'][check_id]['status']
        violations = validation['quality_checks'][check_id]['violations']
        print(f"  {check_id}: {status} ({violations} violations)")

    print(f"\nOverall quality score: {validation['quality_score']:.2f}%")

The example runs ETL, then runs comprehensive validation, checks the validation results and reports the overall quality score.

SCD Type 2 Processing Example
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from benchbox.tpcdi import TPCDI
    from benchbox.platforms.duckdb import DuckDBAdapter

    benchmark = TPCDI(scale_factor=0.1, enable_scd=True)
    adapter = DuckDBAdapter()
    conn = adapter.create_connection()

    benchmark.create_schema(conn)

    benchmark.run_etl_pipeline(conn, batch_type="historical")

    current_customers = conn.execute("""
        SELECT CustomerID, LastName, FirstName, IsCurrent, EffectiveDate
        FROM DimCustomer
        WHERE IsCurrent = 1
        ORDER BY CustomerID
        LIMIT 5
    """).fetchall()

    print("Current customers:")
    for customer in current_customers:
        print(f"  {customer}")

    benchmark.run_etl_pipeline(conn, batch_type="scd")

    historical_customers = conn.execute("""
        SELECT CustomerID, LastName, FirstName, IsCurrent,
               EffectiveDate, EndDate
        FROM DimCustomer
        WHERE CustomerID = 1000
        ORDER BY EffectiveDate
    """).fetchall()

    print("\nCustomer history (CustomerID=1000):")
    for record in historical_customers:
        print(f"  {record}")

The example creates the schema with slowly changing dimension (SCD) support and loads the initial data. It queries the current customer records, processes an SCD batch (which creates new versions of changed records) and then queries the historical records.

Multi-Platform Comparison
~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from benchbox.tpcdi import TPCDI
    from benchbox.platforms.duckdb import DuckDBAdapter
    from benchbox.platforms.clickhouse import ClickHouseAdapter
    import pandas as pd

    benchmark = TPCDI(scale_factor=1.0, output_dir="./data/tpcdi_sf1")

    platforms = {
        "DuckDB": DuckDBAdapter(),
        "ClickHouse": ClickHouseAdapter(host="localhost"),
    }

    results_data = []

    for name, adapter in platforms.items():
        print(f"\nBenchmarking {name}...")
        conn = adapter.create_connection()

        result = benchmark.run_full_benchmark(conn)

        results_data.append({
            "platform": name,
            "etl_duration": result['etl_duration'],
            "query_duration": result['query_duration'],
            "total_duration": result['total_duration'],
            "quality_score": result['quality_score'],
            "validation_passed": result['validation_passed'],
        })

    df = pd.DataFrame(results_data)
    print("\nBenchmark Results:")
    print(df)

Complete Official Benchmark
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from benchbox.tpcdi import TPCDI
    from benchbox.platforms.duckdb import DuckDBAdapter

    benchmark = TPCDI(scale_factor=3.0, verbose=True)
    adapter = DuckDBAdapter()
    conn = adapter.create_connection()

    print("Phase 1: Creating schema...")
    benchmark.create_schema(conn)

    print("Phase 2: Historical data load...")
    etl_result = benchmark.run_etl_benchmark(conn)

    print("Phase 3: Data quality validation...")
    validation_result = benchmark.run_data_validation(conn)

    print("Phase 4: Database optimization...")
    opt_result = benchmark.optimize_database(conn)

    print("Phase 5: Running analytical queries...")
    query_results = {}
    for query_id in ["A1", "A2", "A3", "A4", "A5", "A6"]:
        query = benchmark.get_query(query_id)
        result = adapter.execute_query(conn, query, query_id)
        query_results[query_id] = result

    print("Phase 6: Calculating official metrics...")
    official_metrics = benchmark.calculate_official_metrics(
        etl_result,
        validation_result
    )

    print("\n" + "="*60)
    print("TPC-DI Benchmark Results")
    print("="*60)
    print(f"Scale Factor: {benchmark.scale_factor}")
    print(f"ETL Duration: {etl_result.total_execution_time:.2f}s")
    print(f"Data Quality Score: {validation_result.quality_score:.2%}")
    print(f"Composite Performance Score: {official_metrics.overall_performance:.2f}")
    print(f"Throughput: {official_metrics.etl_throughput:.2f} records/sec")
    print("="*60)

Returned ETL, validation, and metric records
--------------------------------------------------

These methods return mutable dataclasses. Use attribute access; they are not
dictionaries. Required fields have no constructor default. Each list or
dictionary factory creates a separate container for each instance.

.. py:class:: benchbox.core.tpcdi.etl.ETLBatchResult

   One ETL batch outcome. ``batch_date`` is the assigned business date.
   ``execution_time`` is in seconds; record fields are counts.
   ``validation_results`` contains the batch-specific validation payload.

   .. list-table:: Fields
      :header-rows: 1
      :widths: 34 43 23

      * - Field
        - Type
        - Default
      * - ``batch_id``
        - ``int``
        - ``Required``
      * - ``batch_date``
        - ``date``
        - ``Required``
      * - ``start_time``
        - ``datetime``
        - ``Required``
      * - ``end_time``
        - ``datetime``
        - ``Required``
      * - ``execution_time``
        - ``float``
        - ``0.0``
      * - ``records_processed``
        - ``int``
        - ``0``
      * - ``records_inserted``
        - ``int``
        - ``0``
      * - ``records_updated``
        - ``int``
        - ``0``
      * - ``records_deleted``
        - ``int``
        - ``0``
      * - ``success``
        - ``bool``
        - ``False``
      * - ``error_message``
        - ``str | None``
        - ``None``
      * - ``validation_results``
        - ``dict[str, Any]``
        - ``Fresh dict``

.. py:class:: benchbox.core.tpcdi.etl.ETLPhaseResult

   An ETL phase and its batches. ``total_execution_time`` is in seconds;
   ``total_records_processed`` counts records across the phase.

   .. list-table:: Fields
      :header-rows: 1
      :widths: 34 43 23

      * - Field
        - Type
        - Default
      * - ``phase_name``
        - ``str``
        - ``Required``
      * - ``batches``
        - ``list[ETLBatchResult]``
        - ``Fresh list``
      * - ``start_time``
        - ``datetime | None``
        - ``None``
      * - ``end_time``
        - ``datetime | None``
        - ``None``
      * - ``total_execution_time``
        - ``float``
        - ``0.0``
      * - ``total_records_processed``
        - ``int``
        - ``0``
      * - ``success``
        - ``bool``
        - ``False``

.. py:method:: benchbox.core.tpcdi.etl.ETLPhaseResult.add_batch_result(batch: ETLBatchResult) -> None

   Append the batch and add its processed-record count. A failed batch sets
   ``success`` to False; a successful batch does not set it to True.
   This method does not update timestamps or elapsed time.

.. py:class:: benchbox.core.tpcdi.etl.ETLResult

   Overall result returned by ``run_etl_benchmark``. The historical phase is
   optional; ``incremental_loads`` contains subsequent phases.
   ``total_execution_time`` is in seconds.

   .. list-table:: Fields
      :header-rows: 1
      :widths: 34 43 23

      * - Field
        - Type
        - Default
      * - ``historical_load``
        - ``ETLPhaseResult | None``
        - ``None``
      * - ``incremental_loads``
        - ``list[ETLPhaseResult]``
        - ``Fresh list``
      * - ``start_time``
        - ``datetime | None``
        - ``None``
      * - ``end_time``
        - ``datetime | None``
        - ``None``
      * - ``total_execution_time``
        - ``float``
        - ``0.0``
      * - ``total_records_processed``
        - ``int``
        - ``0``
      * - ``success``
        - ``bool``
        - ``False``

.. py:class:: benchbox.core.tpcdi.validation.ValidationResult

   One rule outcome. ``sql`` retains the original validation rule query;
   execution may use its dialect translation. ``violations`` is the first
   returned scalar, or -1 on an empty result or execution failure.
   ``expected`` is the comparison value. Execution failures set ``passed``
   to False and retain exception text in ``error``. ``category`` groups
   outcomes, and ``severity`` determines error and warning counts.

   .. list-table:: Fields
      :header-rows: 1
      :widths: 34 43 23

      * - Field
        - Type
        - Default
      * - ``name``
        - ``str``
        - ``Required``
      * - ``description``
        - ``str``
        - ``Required``
      * - ``sql``
        - ``str``
        - ``Required``
      * - ``violations``
        - ``Union[int, float, str]``
        - ``0``
      * - ``expected``
        - ``Union[int, float, str]``
        - ``0``
      * - ``passed``
        - ``bool``
        - ``False``
      * - ``status``
        - ``str``
        - ``'pending'``
      * - ``error``
        - ``Optional[str]``
        - ``None``
      * - ``category``
        - ``str``
        - ``'integrity'``
      * - ``severity``
        - ``str``
        - ``'error'``

.. py:class:: benchbox.core.tpcdi.validation.DataQualityResult

   Result returned by ``run_data_validation``. ``quality_score`` is the
   passing-validation fraction, or 0 when no validations ran. It is not a
   percentage. ``error_count`` and ``warning_count`` count failed validations
   with the corresponding severity. Each ``categories`` value contains
   ``total``, ``passed``, and ``failed`` counts.

   .. list-table:: Fields
      :header-rows: 1
      :widths: 34 43 23

      * - Field
        - Type
        - Default
      * - ``validations``
        - ``list[ValidationResult]``
        - ``Fresh list``
      * - ``total_validations``
        - ``int``
        - ``0``
      * - ``passed_validations``
        - ``int``
        - ``0``
      * - ``failed_validations``
        - ``int``
        - ``0``
      * - ``quality_score``
        - ``float``
        - ``0.0``
      * - ``error_count``
        - ``int``
        - ``0``
      * - ``warning_count``
        - ``int``
        - ``0``
      * - ``categories``
        - ``dict[str, dict[str, int]]``
        - ``Fresh dict``

.. py:class:: benchbox.core.tpcdi.metrics.BenchmarkMetrics

   Result returned by ``calculate_official_metrics``. Time fields use seconds.
   ``etl_throughput`` is records per second across successful ETL phases, or
   0 when their summed time is nonpositive. ``data_quality_score`` is the
   passing-validation fraction; ``data_integrity_score`` receives the same
   value. The composite ``overall_performance`` is
   ``sqrt(min(etl_throughput / 1000, 1) * data_quality_score) * 1000``, or 0
   when either input is nonpositive.

   The calculator leaves ``total_records_loaded``, ``validation_time``,
   ``dimension_load_time``, ``fact_load_time``, ``index_creation_time``, and
   ``scd_processing_time`` at their defaults. ``tpc_di_compliant`` reports
   internal checks; it does not establish official TPC certification.
   ``benchmark_date`` is a fresh local datetime at construction.

   .. list-table:: Fields
      :header-rows: 1
      :widths: 34 43 23

      * - Field
        - Type
        - Default
      * - ``etl_throughput``
        - ``float``
        - ``0.0``
      * - ``data_quality_score``
        - ``float``
        - ``0.0``
      * - ``overall_performance``
        - ``float``
        - ``0.0``
      * - ``total_execution_time``
        - ``float``
        - ``0.0``
      * - ``total_records_processed``
        - ``int``
        - ``0``
      * - ``total_records_loaded``
        - ``int``
        - ``0``
      * - ``historical_load_time``
        - ``float``
        - ``0.0``
      * - ``historical_load_records``
        - ``int``
        - ``0``
      * - ``incremental_load_time``
        - ``float``
        - ``0.0``
      * - ``incremental_load_records``
        - ``int``
        - ``0``
      * - ``validation_time``
        - ``float``
        - ``0.0``
      * - ``validations_passed``
        - ``int``
        - ``0``
      * - ``validations_total``
        - ``int``
        - ``0``
      * - ``data_integrity_score``
        - ``float``
        - ``0.0``
      * - ``dimension_load_time``
        - ``float``
        - ``0.0``
      * - ``fact_load_time``
        - ``float``
        - ``0.0``
      * - ``index_creation_time``
        - ``float``
        - ``0.0``
      * - ``scd_processing_time``
        - ``float``
        - ``0.0``
      * - ``tpc_di_compliant``
        - ``bool``
        - ``False``
      * - ``scale_factor``
        - ``float``
        - ``1.0``
      * - ``benchmark_date``
        - ``datetime``
        - ``datetime.now()``


See Also
--------

- :doc:`index` - Benchmark API overview
- :doc:`tpch` - TPC-H benchmark API
- :doc:`tpcds` - TPC-DS benchmark API
- :doc:`../base` - Base benchmark interface
- :doc:`../results` - Results API
- :doc:`/benchmarks/tpc-di` - TPC-DI guide
- :doc:`/guides/tpc/tpc-di-deployment-guide` - Deployment guide
- :doc:`/guides/tpc/tpc-di-etl-guide` - ETL implementation guide

External Resources
~~~~~~~~~~~~~~~~~~

- `TPC-DI Specification <http://www.tpc.org/tpcdi/>`_ - Official TPC-DI documentation
- `TPC-DI Tools <http://www.tpc.org/tpc_documents_current_versions/current_specifications.asp>`_ - Official benchmark tools
- `Slowly Changing Dimensions <https://en.wikipedia.org/wiki/Slowly_changing_dimension>`_ - SCD patterns
