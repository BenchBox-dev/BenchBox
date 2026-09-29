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

    # Create benchmark
    benchmark = TPCDI(scale_factor=1.0)

    # Generate data
    benchmark.generate_data()

    # Run on platform
    adapter = DuckDBAdapter()
    results = benchmark.run_with_platform(adapter)

    print(f"Completed in {results.total_execution_time:.2f}s")

API Reference
-------------

TPCDI Class
~~~~~~~~~~~

.. autoclass:: benchbox.tpcdi.TPCDI
   :members:
   :inherited-members:
   :show-inheritance:

Constructor
~~~~~~~~~~~

.. code-block:: python

    TPCDI(
        scale_factor: float = 1.0,
        output_dir: Optional[Union[str, Path]] = None,
        verbose: bool = False,
        **kwargs
    )

Parameters:

- **scale_factor** (float): Data size multiplier. SF=1.0 generates ~100MB of data. Range: 0.1 to 30+
- **output_dir** (str|Path, optional): Directory for generated data files. Default: temporary directory
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

    # Generate all source formats
    source_files = benchmark.generate_source_data()

    # Generate specific formats
    source_files = benchmark.generate_source_data(
        formats=["csv", "xml"],
        batch_types=["historical", "incremental"]
    )

    for format_type, files in source_files.items():
        print(f"{format_type}: {len(files)} files")

Parameters:

- **formats** (list[str], optional): Data formats to generate. Options: "csv", "xml", "fixed_width", "json"
- **batch_types** (list[str], optional): Batch types to generate. Options: "historical", "incremental", "scd"

Returns:
    dict[str, list[str]]: Dictionary mapping formats to file paths

get_query(query_id, \\*, params=None)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Get a specific TPC-DI query.

.. code-block:: python

    # Get validation query
    v1 = benchmark.get_query("V1")

    # Get analytical query
    a1 = benchmark.get_query("A1")

    # Get data quality query
    dq1 = benchmark.get_query("DQ1")

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

    # Get all queries
    queries = benchmark.get_queries()
    print(f"Total queries: {len(queries)}")

    # Get with dialect translation
    queries_bq = benchmark.get_queries(dialect="bigquery")

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

    # Standard SQL
    create_sql = benchmark.get_create_tables_sql()

    # With dialect
    create_sql_sf = benchmark.get_create_tables_sql(dialect="snowflake")

    # With tuning configuration
    from benchbox.core.tuning.interface import UnifiedTuningConfiguration
    tuning = UnifiedTuningConfiguration(...)
    create_sql_tuned = benchmark.get_create_tables_sql(tuning_config=tuning)

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

    # Run historical batch
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

    # Run complete benchmark
    results = benchmark.run_full_benchmark(conn, dialect="duckdb")

    print(f"Total duration: {results['total_duration']:.2f}s")
    print(f"ETL duration: {results['etl_duration']:.2f}s")
    print(f"Query duration: {results['query_duration']:.2f}s")
    print(f"Data quality score: {results['quality_score']:.2f}")

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

    # Run ETL and validation
    etl_result = benchmark.run_etl_benchmark(conn)
    validation_result = benchmark.run_data_validation(conn)

    # Calculate official metrics
    metrics = benchmark.calculate_official_metrics(etl_result, validation_result)

    print(f"TPC-DI Metric: {metrics['tpcdi_metric']}")
    print(f"Throughput: {metrics['throughput']:.2f} records/sec")

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

    # Create benchmark with scale factor 1 (~100MB)
    benchmark = TPCDI(scale_factor=1.0)

    # Generate source data
    source_files = benchmark.generate_source_data()

    # Setup database
    adapter = DuckDBAdapter()
    conn = adapter.create_connection()

    # Create schema
    benchmark.create_schema(conn)

    # Run ETL pipeline
    etl_result = benchmark.run_etl_pipeline(
        conn,
        batch_type="historical",
        validate_data=True
    )

    print(f"ETL completed in {etl_result['duration']:.2f}s")
    print(f"Validation status: {etl_result['validation_status']}")

Incremental Batch Processing
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from benchbox.tpcdi import TPCDI
    from benchbox.platforms.duckdb import DuckDBAdapter

    benchmark = TPCDI(scale_factor=1.0)
    adapter = DuckDBAdapter()
    conn = adapter.create_connection()

    # Initial historical load
    print("Running historical load...")
    hist_result = benchmark.run_etl_pipeline(
        conn,
        batch_type="historical",
        validate_data=True
    )

    # Process incremental batches
    for batch_id in range(1, 4):
        print(f"Processing incremental batch {batch_id}...")
        inc_result = benchmark.run_etl_pipeline(
            conn,
            batch_type="incremental",
            validate_data=True
        )
        print(f"Batch {batch_id} duration: {inc_result['duration']:.2f}s")

Data Quality Validation
~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from benchbox.tpcdi import TPCDI

    benchmark = TPCDI(scale_factor=1.0)

    # Run ETL
    etl_result = benchmark.run_etl_pipeline(conn)

    # Run comprehensive validation
    validation = benchmark.validate_etl_results(conn)

    # Check validation results
    print(f"Validation Queries:")
    for query_id in ["V1", "V2", "V3", "V4", "V5"]:
        status = validation['queries'][query_id]['status']
        print(f"  {query_id}: {status}")

    print(f"\nData Quality Checks:")
    for check_id in ["DQ1", "DQ2", "DQ3", "DQ4", "DQ5"]:
        status = validation['quality_checks'][check_id]['status']
        violations = validation['quality_checks'][check_id]['violations']
        print(f"  {check_id}: {status} ({violations} violations)")

    # Overall quality score
    print(f"\nOverall quality score: {validation['quality_score']:.2f}%")

SCD Type 2 Processing Example
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from benchbox.tpcdi import TPCDI
    from benchbox.platforms.duckdb import DuckDBAdapter

    benchmark = TPCDI(scale_factor=0.1, enable_scd=True)
    adapter = DuckDBAdapter()
    conn = adapter.create_connection()

    # Create schema with SCD support
    benchmark.create_schema(conn)

    # Load initial data
    benchmark.run_etl_pipeline(conn, batch_type="historical")

    # Query current customer records
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

    # Process SCD batch (creates new versions)
    benchmark.run_etl_pipeline(conn, batch_type="scd")

    # Query historical records
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

        # Run full benchmark
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

    # Setup
    benchmark = TPCDI(scale_factor=3.0, verbose=True)
    adapter = DuckDBAdapter()
    conn = adapter.create_connection()

    # Phase 1: Schema Creation
    print("Phase 1: Creating schema...")
    benchmark.create_schema(conn)

    # Phase 2: Historical Load
    print("Phase 2: Historical data load...")
    etl_result = benchmark.run_etl_benchmark(conn)

    # Phase 3: Data Validation
    print("Phase 3: Data quality validation...")
    validation_result = benchmark.run_data_validation(conn)

    # Phase 4: Database Optimization
    print("Phase 4: Database optimization...")
    opt_result = benchmark.optimize_database(conn)

    # Phase 5: Query Execution
    print("Phase 5: Running analytical queries...")
    query_results = {}
    for query_id in ["A1", "A2", "A3", "A4", "A5", "A6"]:
        query = benchmark.get_query(query_id)
        result = adapter.execute_query(conn, query, query_id)
        query_results[query_id] = result

    # Phase 6: Calculate Official Metrics
    print("Phase 6: Calculating official metrics...")
    official_metrics = benchmark.calculate_official_metrics(
        etl_result,
        validation_result
    )

    # Report results
    print("\n" + "="*60)
    print("TPC-DI Benchmark Results")
    print("="*60)
    print(f"Scale Factor: {benchmark.scale_factor}")
    print(f"ETL Duration: {etl_result['duration']:.2f}s")
    print(f"Data Quality Score: {validation_result['quality_score']:.2f}%")
    print(f"TPC-DI Metric: {official_metrics['tpcdi_metric']}")
    print(f"Throughput: {official_metrics['throughput']:.2f} records/sec")
    print("="*60)

See Also
--------

- :doc:`index` - Benchmark API overview
- :doc:`tpch` - TPC-H benchmark API
- :doc:`tpcds` - TPC-DS benchmark API
- :doc:`../base` - Base benchmark interface
- :doc:`../results` - Results API
- :doc:`/benchmarks/tpc-di` - TPC-DI guide

External Resources
~~~~~~~~~~~~~~~~~~

- `TPC-DI Specification <http://www.tpc.org/tpcdi/>`_ - Official TPC-DI documentation
- `TPC-DI Tools <http://www.tpc.org/tpc_documents_current_versions/current_specifications.asp>`_ - Official benchmark tools
- `Slowly Changing Dimensions <https://en.wikipedia.org/wiki/Slowly_changing_dimension>`_ - SCD patterns
