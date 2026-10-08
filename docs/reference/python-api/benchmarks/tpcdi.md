---
myst:
  enable_extensions:
    - attrs_block
---
<!-- markdownlint-disable MD024 -->

# TPC-DI Benchmark API

```{tags} reference, python-api, tpc-di
```

Python API reference for the TPC-DI (Data Integration) benchmark.

## Overview

The TPC-DI benchmark evaluates data integration and ETL (Extract, Transform, Load) processes in data warehousing scenarios. It models a financial services environment with customer data, trading activities, and slowly changing dimensions (SCD).

**Key Features**:

- **Data Integration focus** - Tests ETL processes, not just queries
- **Financial services domain** - 16 warehouse tables for customers, accounts, securities, companies and trades
- **Slowly Changing Dimensions** - `DimCustomer` keeps versioned rows with `IsCurrent`, `EffectiveDate` and `EndDate`
- **Data quality validation** - Validation queries and a quality score
- **Multiple data sources** - CSV, XML, fixed-width and JSON source files
- **Historical and incremental loading** - `historical`, `incremental` and `scd` batches
- **38 queries** - Validation (`V`, `VQ`), analytical (`A`, `AQ`) and ETL (`EQ`) queries

**Optional extra**: `TPCDI` needs the `tpcdi` extra (`pip install "benchbox[tpcdi]"`, which adds pandas).

## Quick Start

```python
from benchbox import TPCDI
from benchbox.platforms.duckdb import DuckDBAdapter

benchmark = TPCDI(scale_factor=1.0)

benchmark.generate_data()

adapter = DuckDBAdapter()
results = benchmark.run_with_platform(adapter)

print(f"Completed in {results.total_execution_time:.2f}s")
```

The DuckDB adapter needs the `duckdb` package. This runs the 38 TPC-DI queries against the generated warehouse tables; it does not run the ETL pipeline (see Basic ETL Pipeline).

## API Reference

### TPCDI Class

#### `benchbox.TPCDI`

<span id="benchbox.tpcdi.TPCDI"></span>

Creates a TPC-DI benchmark that generates the 16 warehouse tables, generates ETL source files in four formats, runs the ETL pipeline and serves 38 validation and analytical queries.

`TPCDI` is the public facade over the data-integration implementation. It inherits the common benchmark lifecycle and adapter integration described in {doc}`/reference/python-api/base`. Its own query, schema and ETL methods delegate to the TPC-DI implementation. `run_with_platform` returns a `BenchmarkResults` object. The connection-based `run_benchmark` and `run_full_benchmark` return TPC-DI result dictionaries. These APIs are distinct.

**Import:** `from benchbox import TPCDI` · **Extras:** `tpcdi`

##### Parameters

| Name | Type | Default | Meaning |
| --- | --- | --- | --- |
| `scale_factor` | `float` | `1.0` | Data size multiplier. Must be positive. Values of 1 or more must be whole numbers. At 0.01 the 16 tables hold 56,211 rows, including 10,000 `FactTrade` rows. |
| `output_dir` | `str`, `Path` or `None` | `None` | Directory for generated data, source files, staging and warehouse files. When `None`, the directory is `benchmark_runs/datagen/tpcdi_<sf token>` under the current directory (for example `tpcdi_sf001` for 0.01), or under `$BENCHBOX_OUTPUT_DIR/datagen` when that variable is set. |
| `**kwargs` | keyword arguments | none | See the list below. |

Keyword arguments that the constructor acts on:

- `verbose` (`bool` or `int`) and `quiet` (`bool`): log level. `verbose=True` is level 2.
- `enable_parallel` (`bool`, default `False`): parallel ETL processing.
- `max_workers` (`int` or `None`): worker count, clamped to 1 to 16. When `None`, it is 1, or `min(8, cpu_count + 2)` with `enable_parallel=True`.
- `config` (`TPCDIConfig`): a `benchbox.core.tpcdi.config.TPCDIConfig`. When given, its `scale_factor`, `output_dir`, `enable_parallel`, `max_workers` and `generation_seed` replace the arguments for the implementation (the instance's own `scale_factor` and `output_dir` attributes keep the arguments).
- `generation_seed` (`int`, default `42`): seed for the generated data; a different seed gives different `FactTrade` rows.

Any other keyword is stored as an attribute on the instance. `enable_scd`, `batch_size` and `validate_data` have no effect.

Unlike most benchmarks, the constructor creates the directories `logs`, `source`, `staging` and `warehouse` under `output_dir`. Data files are written by `generate_data()`.

##### Returns

A `TPCDI` instance. It subclasses `BaseBenchmark`; see {doc}`/reference/python-api/base` for the shared interface.

##### Raises

- `ImportError` (an `ImportErrorWithVersion`) at import time when the `tpcdi` extra is missing: `Could not import benchmark 'TPCDI'. Optional dependency extras required: tpcdi`.
- `ValueError` when `scale_factor` is zero or negative, or is 1 or more and not a whole number.
- `TypeError` when `scale_factor` is not a number.

##### Example

```python
from benchbox import TPCDI

benchmark = TPCDI(scale_factor=0.01, output_dir="tpcdi_data")
files = benchmark.generate_data()
print(len(files), len(benchmark.get_queries()))
print(sorted(benchmark.tables)[:4])
```

Output on 0.4.1:

```text
16 38
['DimAccount', 'DimBroker', 'DimCompany', 'DimCustomer']
```

##### Compatibility

`benchbox.tpcdi.TPCDI` is the same class, with the same extra. Without the extra, `from benchbox.tpcdi import TPCDI` raises `ModuleNotFoundError: No module named 'pandas'`. The result types noted under each method below are internal classes.

### Constructor

<span id="benchbox.tpcdi.TPCDI.__init__"></span>

`TPCDI(scale_factor=1.0, output_dir=None, **kwargs)`. The arguments are in the Parameters table above.

## Methods

### generate_data()

<span id="benchbox.tpcdi.TPCDI.generate_data"></span>

`generate_data() -> list[str]` writes the 16 warehouse tables as pipe-delimited `.tbl` files, without header rows, plus `_datagen_manifest.json`, and returns the file paths in table order. `benchmark.tables` maps each table name to its path. The tables are `DimCustomer`, `DimAccount`, `DimSecurity`, `DimCompany`, `FactTrade`, `DimDate`, `DimTime`, `DimBroker`, `FactCashBalances`, `FactHoldings`, `FactMarketHistory`, `FactWatches`, `Industry`, `StatusType`, `TaxRate` and `TradeType`. The wrapper method takes no arguments.

At scale factor 1 the 16 files total 160 MB, with 1,000,000 `FactTrade` rows and 50,000 `DimCustomer` rows. At scale factor 0.01: `DimCustomer` 500 rows, `DimAccount` 1,000, `DimSecurity` 100, `DimCompany` 10, `FactTrade` 10,000, `DimDate` 5,844, `DimTime` 288, `DimBroker` 100.

The generator logs progress through the `logging` module at INFO level (and configures logging on first use), so expect log lines in the console.

```python
data_files = benchmark.generate_data()
print(f"Generated {len(data_files)} table files")
```

This prints `Generated 16 table files`.

### generate_source_data(formats=None, batch_types=None)

<span id="benchbox.tpcdi.TPCDI.generate_source_data"></span>

`generate_source_data(formats=None, batch_types=None) -> dict[str, list[str]]` writes ETL source files under `<output_dir>/source/<format>/<batch type>/` and returns a mapping from format to file paths.

| Name | Type | Default | Meaning |
| --- | --- | --- | --- |
| `formats` | `list[str]` or `None` | `None` | Any of `"csv"`, `"xml"`, `"fixed_width"`, `"json"`. `None` means all four. An unknown format raises `ValueError` (`Unsupported format: bogus`). |
| `batch_types` | `list[str]` or `None` | `None` | `"historical"`, `"incremental"`, `"scd"`. `None` means all three. Other names are not rejected; they produce files named after them. |

With the defaults the result holds 6 CSV files (customers and trades per batch type) and 3 files each for XML, fixed-width and JSON (one per batch type).

```python
source_files = benchmark.generate_source_data()

source_files = benchmark.generate_source_data(
    formats=["csv", "xml"],
    batch_types=["historical", "incremental"]
)

for format_type, files in source_files.items():
    print(f"{format_type}: {len(files)} files")
```

The first call generates all source formats. The second generates only the specified formats and batch types and leaves `source_files` with `csv` (4 files) and `xml` (2 files), so the loop prints `csv: 4 files` and `xml: 2 files`.

### get_query(query_id, \*, params=None)

<span id="benchbox.tpcdi.TPCDI.get_query"></span>

`get_query(query_id, *, params=None) -> str` returns one query as SQL text.

| Name | Type | Default | Meaning |
| --- | --- | --- | --- |
| `query_id` | `str` or `int` | required | One of the 38 ids: `V1`-`V3`, `A1`-`A5`, `VQ1`-`VQ12`, `AQ1`-`AQ10`, `EQ1`-`EQ8`. Integers 1 to 12 and their digit strings select `VQ1` to `VQ12`; 13 to 22 select `AQ1` to `AQ10`. |
| `params` | `dict` or `None` | `None` | Accepted but ignored. |

Raises `ValueError` for an unknown id (`Invalid query ID: DQ1. Available: A1, A2, ...`). There are no `DQ` queries. The wrapper has no `dialect` argument; use `get_queries(dialect=...)` for translated text.

```python
v1 = benchmark.get_query("V1")

a1 = benchmark.get_query("A1")

vq1 = benchmark.get_query(1)
```

The examples get a validation query, an analytical query and a data quality query, in that order. `get_query(1)` returns the same query as `get_query("VQ1")`.

### get_queries(dialect=None)

<span id="benchbox.tpcdi.TPCDI.get_queries"></span>

`get_queries(dialect=None) -> dict[str, str]` returns all 38 queries keyed by id, in the order `V1`-`V3`, `A1`-`A5`, `VQ1`-`VQ12`, `AQ1`-`AQ10`, `EQ1`-`EQ8`. With a `dialect`, each query is translated with SQLGlot, which quotes identifiers (`SELECT ... AS "validation_name"` for DuckDB).

```python
queries = benchmark.get_queries()
print(f"Total queries: {len(queries)}")

queries_bq = benchmark.get_queries(dialect="bigquery")
```

The first call gets all queries and prints `Total queries: 38`. The second gets them with dialect translation.

### get_schema()

<span id="benchbox.tpcdi.TPCDI.get_schema"></span>

`get_schema(dialect="standard") -> dict` returns a mapping from table name to a definition with `name` and `columns`, for the 16 tables (for example `DimCustomer` has 33 columns, `FactTrade` 21). The annotation of the base method says `list[dict]`, but the value is a dict.

```python
schema = benchmark.get_schema()
for name in ("DimCustomer", "FactTrade"):
    print(f"{schema[name]['name']}: {len(schema[name]['columns'])} columns")
```

This prints `DimCustomer: 33 columns` and `FactTrade: 21 columns`.

### get_create_tables_sql(dialect="standard", tuning_config=None)

<span id="benchbox.tpcdi.TPCDI.get_create_tables_sql"></span>

`get_create_tables_sql(dialect="standard", tuning_config=None) -> str` returns the `CREATE TABLE` statements for the 16 tables.

| Name | Type | Default | Meaning |
| --- | --- | --- | --- |
| `dialect` | `str` | `"standard"` | Accepted but has no effect: `standard`, `duckdb` and `postgres` return the same script. |
| `tuning_config` | `UnifiedTuningConfiguration` or `None` | `None` | With `None`, no constraints are emitted. A new `UnifiedTuningConfiguration()` adds 12 `PRIMARY KEY` clauses and no foreign keys. |

```python
from benchbox.core.tuning.interface import UnifiedTuningConfiguration

create_sql = benchmark.get_create_tables_sql()
create_sql_pk = benchmark.get_create_tables_sql(tuning_config=UnifiedTuningConfiguration())
print(create_sql.count("PRIMARY KEY"), create_sql_pk.count("PRIMARY KEY"))
```

The first call returns the script without constraints. The second adds primary keys through a tuning configuration. This prints `0 12`.

## ETL Methods

The ETL methods take an open database connection, such as the one from `DuckDBAdapter().create_connection()`.

### run_etl_pipeline(connection, batch_type="historical", validate_data=True)

<span id="benchbox.tpcdi.TPCDI.run_etl_pipeline"></span>

`run_etl_pipeline(connection, batch_type="historical", validate_data=True) -> dict` generates source files for the batch, transforms them and loads the result into the warehouse tables. It creates the tables itself if they are missing.

| Name | Type | Default | Meaning |
| --- | --- | --- | --- |
| `connection` | database connection | required | Connection to the target warehouse. |
| `batch_type` | `str` | `"historical"` | `"historical"`, `"incremental"` or `"scd"`. Any other value raises `KeyError`. |
| `validate_data` | `bool` | `True` | Run the validation queries after loading. |

The result dict has `batch_type`, `start_time`, `end_time`, `total_duration` (seconds), `success`, `parallel_enabled`, `metrics`, `simple_stats`, `phases` and, when `validate_data` is true, `validation_results`. `phases` has `extract` (`duration`, `files_generated`, `source_files`), `transform` (`duration`, `records_processed`, `transformations_applied`, `parallel_enabled`), `load` (`duration`, `records_loaded`, `tables_updated`) and, with validation, `validation` (`duration`, `queries_executed`, `data_quality_score`).

At scale factor 0.01 the `historical` batch loads 10 `DimCustomer` rows, `incremental` loads 1 and `scd` loads 0. At 0.1 the `scd` batch loaded 5 new `DimCustomer` versions.

```python
from benchbox.platforms.duckdb import DuckDBAdapter

adapter = DuckDBAdapter()
conn = adapter.create_connection()

etl_result = benchmark.run_etl_pipeline(
    conn,
    batch_type="historical",
    validate_data=True
)

print(f"ETL duration: {etl_result['total_duration']:.2f}s")
print(f"Records loaded: {etl_result['phases']['load']['records_loaded']:,}")
```

### validate_etl_results(connection)

<span id="benchbox.tpcdi.TPCDI.validate_etl_results"></span>

`validate_etl_results(connection) -> dict` runs the validation queries `V1`-`V3` and `VQ1`-`VQ12` and the data quality checks against the warehouse tables.

It works right after `create_schema`, and after any ETL run. The result dict has `validation_queries` (query id to `{"success", "row_count", "result"}`), `data_quality_issues` (list), `data_quality_score` (percent, 100.0 is clean), `completeness_checks` (per table), `consistency_checks` (`orphaned_trades`, `duplicate_customers`, `invalid_date_sequences`) and `accuracy_checks` (`negative_trade_prices`, `invalid_customer_tiers`, and an `error` entry when a check could not run).

```python
validation_result = benchmark.validate_etl_results(conn)

print(f"Quality score: {validation_result['data_quality_score']}")
print(f"Issues: {len(validation_result['data_quality_issues'])}")
print(f"Orphaned trades: {validation_result['consistency_checks']['orphaned_trades']}")
```

### get_etl_status()

<span id="benchbox.tpcdi.TPCDI.get_etl_status"></span>

`get_etl_status() -> dict` reports the processing state of this benchmark instance. Keys: `etl_mode_enabled` (`True`), `source_directory`, `staging_directory`, `warehouse_directory`, `simple_stats` (`batches_processed`, `total_processing_time`, `error_count`, `batch_status`), `supported_formats` (`csv`, `xml`, `fixed_width`, `json`) and `batch_types` (`historical`, `incremental`, `scd`). `batch_status` maps each batch type to `{"status": "pending"}` or `{"status": "completed"}`.

```python
status = benchmark.get_etl_status()

print(f"Batches processed: {status['simple_stats']['batches_processed']}")
print(f"Historical: {status['simple_stats']['batch_status']['historical']['status']}")
```

## Benchmark Methods

### run_full_benchmark(connection, dialect="duckdb")

<span id="benchbox.tpcdi.TPCDI.run_full_benchmark"></span>

`run_full_benchmark(connection, dialect="duckdb") -> dict` runs every phase: schema creation, the historical and incremental ETL loads, data quality validation and metric calculation. It prints a results report to standard output.

| Name | Type | Default | Meaning |
| --- | --- | --- | --- |
| `connection` | database connection | required | Connection to the target warehouse. |
| `dialect` | `str` | `"duckdb"` | SQL dialect used for the schema DDL. |

The result dict has `success`, `metrics` (`benchmark_info`, `primary_metrics`, `execution_stats`, `quality_metrics`), `etl_result`, `validation_result`, `report` and `execution_time_seconds`. `metrics["primary_metrics"]` holds `etl_throughput` (records per second), `data_quality_score` (0 to 1) and `overall_performance`.

```python
from benchbox.platforms.duckdb import DuckDBAdapter

adapter = DuckDBAdapter()
conn = adapter.create_connection()

results = benchmark.run_full_benchmark(conn, dialect="duckdb")

primary = results["metrics"]["primary_metrics"]
print(f"Total duration: {results['execution_time_seconds']:.2f}s")
print(f"ETL throughput: {primary['etl_throughput']:.0f} records/s")
print(f"Data quality score: {primary['data_quality_score']:.2f}")
```

### create_schema(connection, dialect="duckdb")

<span id="benchbox.tpcdi.TPCDI.create_schema"></span>

`create_schema(connection, dialect="duckdb") -> None` creates the 16 warehouse tables on `connection` and prints `Created TPC-DI schema for duckdb`. It can be called again on the same connection.

```python
benchmark.create_schema(conn)
```

### run_etl_benchmark(connection, dialect="duckdb")

<span id="benchbox.tpcdi.TPCDI.run_etl_benchmark"></span>

`run_etl_benchmark(connection, dialect="duckdb")` runs the historical load and two incremental loads and returns an `ETLResult` object (not a dict). Its attributes are `historical_load` (an `ETLPhaseResult` with `phase_name`, `total_records_processed`, `total_execution_time`, `success`), `incremental_loads` (a list of phase results), `start_time`, `end_time`, `total_execution_time`, `total_records_processed` and `success`. At scale factor 0.01 it processes 105 records.

```python
etl_results = benchmark.run_etl_benchmark(conn, dialect="duckdb")
print(etl_results.success, etl_results.total_records_processed)
```

### run_data_validation(connection)

<span id="benchbox.tpcdi.TPCDI.run_data_validation"></span>

`run_data_validation(connection)` runs the data quality validations and returns a `DataQualityResult` object (not a dict) with `validations` (a list), `total_validations` (16), `passed_validations`, `failed_validations`, `quality_score` (0 to 1), `error_count`, `warning_count` and `categories` (`primary_key`, `foreign_key`, `business_logic`, `completeness`, `scd_type2`). It prints `Running data quality validation...`. It needs the validator that `run_etl_benchmark` or `run_full_benchmark` creates; after `create_schema` alone, or after `run_etl_pipeline`, it raises `ValueError: Validator not initialized. Call run_full_benchmark or initialize manually.`

```python
benchmark.run_etl_benchmark(conn)
validation_results = benchmark.run_data_validation(conn)
print(validation_results.passed_validations, "/", validation_results.total_validations)
```

### calculate_official_metrics(etl_result, validation_result)

<span id="benchbox.tpcdi.TPCDI.calculate_official_metrics"></span>

`calculate_official_metrics(etl_result, validation_result)` takes the `ETLResult` from `run_etl_benchmark` and the `DataQualityResult` from `run_data_validation` and returns a `BenchmarkMetrics` object. Attributes include `etl_throughput` (records per second), `data_quality_score` (0 to 1), `overall_performance`, `total_records_processed`, `historical_load_time`, `incremental_load_time`, `validations_passed`, `validations_total`, `tpc_di_compliant`, `scale_factor` and `benchmark_date`.

```python
etl_result = benchmark.run_etl_benchmark(conn)
validation_result = benchmark.run_data_validation(conn)

metrics = benchmark.calculate_official_metrics(etl_result, validation_result)

print(f"ETL throughput: {metrics.etl_throughput:.2f} records/sec")
print(f"TPC-DI compliant: {metrics.tpc_di_compliant}")
```

Run the ETL benchmark and the validation first, then calculate the official metrics from their results. Calculating metrics does not by itself certify an official TPC-DI run.

### optimize_database(connection)

<span id="benchbox.tpcdi.TPCDI.optimize_database"></span>

`optimize_database(connection) -> dict` creates 23 indexes on the dimension and fact tables and prints `Optimizing database for TPC-DI performance...`. Like `run_data_validation`, it needs a prior `run_etl_benchmark` or `run_full_benchmark`; otherwise it raises `ValueError: Data loader not initialized`. The result has `indexes_created` (index name to `True`/`False`), `tables_optimized` (table name to `True`/`False`, for seven tables) and `optimization_successful`.

```python
benchmark.run_etl_benchmark(conn)
optimization_result = benchmark.optimize_database(conn)

print(f"Indexes created: {sum(optimization_result['indexes_created'].values())}")
print(f"Successful: {optimization_result['optimization_successful']}")
```

### load_data_to_database(connection, tables=None)

<span id="benchbox.tpcdi.TPCDI.load_data_to_database"></span>

`load_data_to_database(connection, tables=None) -> None` inserts the files from `generate_data()` into existing tables, row by row. Create the tables first with `create_schema()`. `tables` is an optional list of table names; `None` loads all 16.

Raises `ValueError` (`No data generated. Call generate_data() first.`) before `generate_data()` has run, and the database's constraint error when a table already holds the rows. It is slow: at scale factor 0.01 (56,211 rows) it took about 47 seconds. Platform adapters use `load_data` instead.

### run_benchmark(connection, queries=None, iterations=1)

<span id="benchbox.tpcdi.TPCDI.run_benchmark"></span>

`run_benchmark(connection, queries=None, iterations=1) -> dict` runs the 38 queries (or the ids in `queries`) `iterations` times each against the loaded tables, and returns a dict with `benchmark` (`"TPC-DI"`), `scale_factor`, `iterations`, `total_queries`, `query_statistics` and `queries`. Each `queries` entry has `iterations` (a list of per-run results), `avg_time`, `min_time`, `max_time`, `sql_text` and `rows_returned`. This replaces the base class method of the same name, with a different signature.

```python
results = benchmark.run_benchmark(conn, queries=["V1", "A1"], iterations=2)
print(results["total_queries"], round(results["queries"]["V1"]["avg_time"], 4))
```

### execute_query(query_id, connection, params=None)

<span id="benchbox.tpcdi.TPCDI.execute_query"></span>

`execute_query(query_id, connection, params=None)` runs one query (ids as in `get_query`) and returns the rows from `fetchall()`, a list of tuples.

```python
rows = benchmark.execute_query("V1", conn)
print(rows)
```

## Properties

### etl_mode

<span id="benchbox.tpcdi.TPCDI.etl_mode"></span>

`etl_mode` is always `True`.

```python
if benchmark.etl_mode:
    print("ETL mode enabled")
```

### validator

<span id="benchbox.tpcdi.TPCDI.validator"></span>

`validator` is `None` until a method that uses a connection (such as `run_etl_pipeline` or `run_data_validation`) has run, then the internal validator object (a `TPCDIValidator`). Its methods are not part of the contract. Use `validate_etl_results()` or `run_data_validation()`.

### schema_manager

<span id="benchbox.tpcdi.TPCDI.schema_manager"></span>

`schema_manager` returns the internal schema manager (a `TPCDISchemaManager`). Its methods are not part of the contract. Use `get_schema()`.

### metrics_calculator

<span id="benchbox.tpcdi.TPCDI.metrics_calculator"></span>

`metrics_calculator` returns the internal metrics calculator (a `TPCDIMetrics`). Its methods are not part of the contract. Use `calculate_official_metrics()`.

### Inherited members

Every other member comes from `BaseBenchmark`. See {doc}`/reference/python-api/base` for what they do. The ids on this page for the inherited members are kept in the table.

| Group | Member | Kind | Notes |
| --- | --- | --- | --- |
| Run and results | <span id="benchbox.tpcdi.TPCDI.cleanup"></span>`cleanup` | method | |
| Run and results | <span id="benchbox.tpcdi.TPCDI.create_enhanced_benchmark_result"></span>`create_enhanced_benchmark_result` | method | |
| Run and results | <span id="benchbox.tpcdi.TPCDI.create_minimal_benchmark_result"></span>`create_minimal_benchmark_result` | method | |
| Run and results | <span id="benchbox.tpcdi.TPCDI.format_results"></span>`format_results` | method | |
| Run and results | <span id="benchbox.tpcdi.TPCDI.run_query"></span>`run_query` | method | |
| Run and results | <span id="benchbox.tpcdi.TPCDI.run_with_platform"></span>`run_with_platform` | method | |
| Run and results | <span id="benchbox.tpcdi.TPCDI.setup_database"></span>`setup_database` | method | |
| Run and results | <span id="benchbox.tpcdi.TPCDI.translate_query"></span>`translate_query` | method | |
| Validation | <span id="benchbox.tpcdi.TPCDI.validate_loaded_data"></span>`validate_loaded_data` | method | |
| Validation | <span id="benchbox.tpcdi.TPCDI.validate_manifest"></span>`validate_manifest` | method | |
| Validation | <span id="benchbox.tpcdi.TPCDI.validate_preflight"></span>`validate_preflight` | method | |
| Verbosity and logging | <span id="benchbox.tpcdi.TPCDI.apply_verbosity"></span>`apply_verbosity` | method | |
| Verbosity and logging | <span id="benchbox.tpcdi.TPCDI.log_debug_info"></span>`log_debug_info` | method | |
| Verbosity and logging | <span id="benchbox.tpcdi.TPCDI.log_error_with_debug_info"></span>`log_error_with_debug_info` | method | |
| Verbosity and logging | <span id="benchbox.tpcdi.TPCDI.log_notice"></span>`log_notice` | method | |
| Verbosity and logging | <span id="benchbox.tpcdi.TPCDI.log_operation_complete"></span>`log_operation_complete` | method | |
| Verbosity and logging | <span id="benchbox.tpcdi.TPCDI.log_operation_start"></span>`log_operation_start` | method | |
| Verbosity and logging | <span id="benchbox.tpcdi.TPCDI.log_verbose"></span>`log_verbose` | method | |
| Verbosity and logging | <span id="benchbox.tpcdi.TPCDI.log_version_warning"></span>`log_version_warning` | method | |
| Verbosity and logging | <span id="benchbox.tpcdi.TPCDI.log_very_verbose"></span>`log_very_verbose` | method | |
| Verbosity and logging | <span id="benchbox.tpcdi.TPCDI.logger"></span>`logger` | property | |
| Verbosity and logging | <span id="benchbox.tpcdi.TPCDI.quiet"></span>`quiet` | class attribute | |
| Verbosity and logging | <span id="benchbox.tpcdi.TPCDI.verbose"></span>`verbose` | class attribute | |
| Verbosity and logging | <span id="benchbox.tpcdi.TPCDI.verbose_enabled"></span>`verbose_enabled` | class attribute | |
| Verbosity and logging | <span id="benchbox.tpcdi.TPCDI.verbose_level"></span>`verbose_level` | class attribute | |
| Verbosity and logging | <span id="benchbox.tpcdi.TPCDI.verbosity_settings"></span>`verbosity_settings` | property | |
| Verbosity and logging | <span id="benchbox.tpcdi.TPCDI.very_verbose"></span>`very_verbose` | class attribute | |
| Data and configuration | <span id="benchbox.tpcdi.TPCDI.api_surface"></span>`api_surface` | class attribute | |
| Data and configuration | <span id="benchbox.tpcdi.TPCDI.benchmark_name"></span>`benchmark_name` | property | |
| Data and configuration | <span id="benchbox.tpcdi.TPCDI.csv_delimiter"></span>`csv_delimiter` | property | `None`. |
| Data and configuration | <span id="benchbox.tpcdi.TPCDI.csv_null_marker"></span>`csv_null_marker` | property | `None`. |
| Data and configuration | <span id="benchbox.tpcdi.TPCDI.DATA_SOURCE_BENCHMARK"></span>`DATA_SOURCE_BENCHMARK` | class attribute | `None`: TPC-DI generates its own data. |
| Data and configuration | <span id="benchbox.tpcdi.TPCDI.get_csv_loading_config"></span>`get_csv_loading_config` | method | `None`. |
| Data and configuration | <span id="benchbox.tpcdi.TPCDI.get_data_source_benchmark"></span>`get_data_source_benchmark` | method | |
| Data and configuration | <span id="benchbox.tpcdi.TPCDI.output_dir"></span>`output_dir` | property | The resolved directory from the constructor argument (or from `config`). |
| Data and configuration | <span id="benchbox.tpcdi.TPCDI.run_with_platform_api_surface"></span>`run_with_platform_api_surface` | class attribute | |
| Data and configuration | <span id="benchbox.tpcdi.TPCDI.scale_factor"></span>`scale_factor` | instance attribute | The constructor argument. |
| Data and configuration | <span id="benchbox.tpcdi.TPCDI.SKIP_DATA_LOADING"></span>`SKIP_DATA_LOADING` | class attribute | Defined on `BaseBenchmark` from 0.4.2, default `False`. Set it to `True` for a benchmark that needs schema objects but no data files. |
| Data and configuration | <span id="benchbox.tpcdi.TPCDI.tables"></span>`tables` | property | Empty until `generate_data()` has run, then the table-to-path mapping. |

## Usage Examples

### Basic ETL Pipeline

```python
from benchbox import TPCDI
from benchbox.platforms.duckdb import DuckDBAdapter

benchmark = TPCDI(scale_factor=0.1)

source_files = benchmark.generate_source_data()

adapter = DuckDBAdapter()
conn = adapter.create_connection()

benchmark.create_schema(conn)

etl_result = benchmark.run_etl_pipeline(
    conn,
    batch_type="historical",
    validate_data=True
)

print(f"ETL completed in {etl_result['total_duration']:.2f}s")
print(f"Data quality score: {etl_result['validation_results']['data_quality_score']}")
```

This example creates a benchmark with scale factor 0.1, generates the source data, sets up the database and creates the schema, and then runs the ETL pipeline.

### Incremental Batch Processing

```python
from benchbox import TPCDI
from benchbox.platforms.duckdb import DuckDBAdapter

benchmark = TPCDI(scale_factor=0.1)
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
    print(f"Batch {batch_id} duration: {inc_result['total_duration']:.2f}s")
```

The example runs the historical load first and then processes three incremental batches.

### Data Quality Validation

```python
from benchbox import TPCDI
from benchbox.platforms.duckdb import DuckDBAdapter

benchmark = TPCDI(scale_factor=0.1)
conn = DuckDBAdapter().create_connection()

etl_result = benchmark.run_etl_pipeline(conn)

validation = benchmark.validate_etl_results(conn)

print("Validation Queries:")
for query_id in ["V1", "V2", "V3", "VQ1", "VQ2"]:
    print(f"  {query_id}: success={validation['validation_queries'][query_id]['success']}")

print("\nConsistency Checks:")
for check, violations in validation["consistency_checks"].items():
    print(f"  {check}: {violations} violations")

print(f"\nOverall quality score: {validation['data_quality_score']:.2f}%")
```

The example runs ETL, then runs comprehensive validation, checks the validation results and reports the overall quality score.

### SCD Type 2 Processing Example

The example creates the schema with slowly changing dimension (SCD) support and loads the initial data. It queries the current customer records, processes an SCD batch (which creates new versions of changed records) and then queries the historical records.

```python
from benchbox import TPCDI
from benchbox.platforms.duckdb import DuckDBAdapter

benchmark = TPCDI(scale_factor=0.1)
adapter = DuckDBAdapter()
conn = adapter.create_connection()

benchmark.create_schema(conn)

benchmark.run_etl_pipeline(conn, batch_type="historical", validate_data=False)

current_customers = conn.execute("""
    SELECT CustomerID, LastName, FirstName, IsCurrent, EffectiveDate
    FROM DimCustomer
    WHERE IsCurrent
    ORDER BY CustomerID
    LIMIT 3
""").fetchall()

print("Current customers:")
for customer in current_customers:
    print(f"  {customer}")

benchmark.run_etl_pipeline(conn, batch_type="scd", validate_data=False)

historical_customers = conn.execute("""
    SELECT CustomerID, LastName, FirstName, IsCurrent,
           EffectiveDate, EndDate
    FROM DimCustomer
    WHERE CustomerID = 100000000
    ORDER BY EffectiveDate
""").fetchall()

print("\nCustomer history (CustomerID=100000000):")
for record in historical_customers:
    print(f"  {record}")
```

Output on 0.4.1:

```text
Current customers:
  (100000000, 'LastName0', 'FirstName0', True, datetime.date(1999, 1, 1))
  (100000001, 'LastName1', 'FirstName1', True, datetime.date(1999, 1, 1))
  (100000002, 'LastName2', 'FirstName2', True, datetime.date(1999, 1, 1))

Customer history (CustomerID=100000000):
  (100000000, 'LastName0', 'FirstName0', False, datetime.date(1999, 1, 1), datetime.date(1999, 1, 1))
  (100000000, 'LastName0', 'FirstName0', True, datetime.date(1999, 1, 2), datetime.date(9999, 12, 31))
```

### Multi-Platform Comparison

Run the full benchmark on several adapters and compare the metrics. This example uses two DuckDB configurations; add other adapters to the dictionary the same way.

```python
from benchbox import TPCDI
from benchbox.platforms.duckdb import DuckDBAdapter
import pandas as pd

benchmark = TPCDI(scale_factor=0.1, output_dir="./data/tpcdi_sf01")

platforms = {
    "DuckDB 1GB": DuckDBAdapter(memory_limit="1GB"),
    "DuckDB 4GB": DuckDBAdapter(memory_limit="4GB"),
}

results_data = []

for name, adapter in platforms.items():
    print(f"\nBenchmarking {name}...")
    conn = adapter.create_connection()

    result = benchmark.run_full_benchmark(conn)

    results_data.append({
        "platform": name,
        "etl_seconds": result["etl_result"]["total_execution_time"],
        "total_seconds": result["execution_time_seconds"],
        "etl_throughput": result["metrics"]["primary_metrics"]["etl_throughput"],
        "quality_score": result["metrics"]["primary_metrics"]["data_quality_score"],
    })

df = pd.DataFrame(results_data)
print("\nBenchmark Results:")
print(df)
```

### Complete Official Benchmark

```python
from benchbox import TPCDI
from benchbox.platforms.duckdb import DuckDBAdapter

benchmark = TPCDI(scale_factor=0.1)
adapter = DuckDBAdapter()
conn = adapter.create_connection()

print("Phase 1: Creating schema...")
benchmark.create_schema(conn)

print("Phase 2: ETL loads...")
etl_result = benchmark.run_etl_benchmark(conn)

print("Phase 3: Data quality validation...")
validation_result = benchmark.run_data_validation(conn)

print("Phase 4: Database optimization...")
opt_result = benchmark.optimize_database(conn)

print("Phase 5: Running analytical queries...")
query_results = {}
for query_id in ["A1", "A2", "A3", "A4", "A5"]:
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
print(f"Data Quality Score: {validation_result.quality_score * 100:.2f}%")
print(f"ETL Throughput: {official_metrics.etl_throughput:.2f} records/sec")
print(f"TPC-DI Compliant: {official_metrics.tpc_di_compliant}")
print("="*60)
```

The example runs six phases in order: schema creation, ETL loads (historical and incremental), data quality validation, database optimization, analytical queries and official metrics. It then prints the report.

## Returned ETL, validation, and metric records

These methods return mutable dataclasses. Use attribute access; they are not dictionaries. Required fields have no constructor default. Each list or dictionary factory creates a separate container for each instance.

### `benchbox.core.tpcdi.etl.ETLBatchResult`

<span id="benchbox.core.tpcdi.etl.ETLBatchResult"></span>

One ETL batch outcome. `batch_date` is the assigned business date. `execution_time` is in seconds; record fields are counts. `validation_results` contains the batch-specific validation payload.

| Field | Type | Default |
| --- | --- | --- |
| `batch_id` | `int` | required |
| `batch_date` | `date` | required |
| `start_time` | `datetime` | required |
| `end_time` | `datetime` | required |
| `execution_time` | `float` | `0.0` |
| `records_processed` | `int` | `0` |
| `records_inserted` | `int` | `0` |
| `records_updated` | `int` | `0` |
| `records_deleted` | `int` | `0` |
| `success` | `bool` | `False` |
| `error_message` | `str \| None` | `None` |
| `validation_results` | `dict[str, Any]` | new empty dict |

### `benchbox.core.tpcdi.etl.ETLPhaseResult`

<span id="benchbox.core.tpcdi.etl.ETLPhaseResult"></span>

An ETL phase and its batches. `total_execution_time` is in seconds; `total_records_processed` counts records across the phase.

| Field | Type | Default |
| --- | --- | --- |
| `phase_name` | `str` | required |
| `batches` | `list[ETLBatchResult]` | new empty list |
| `start_time` | `datetime \| None` | `None` |
| `end_time` | `datetime \| None` | `None` |
| `total_execution_time` | `float` | `0.0` |
| `total_records_processed` | `int` | `0` |
| `success` | `bool` | `False` |

### `benchbox.core.tpcdi.etl.ETLPhaseResult.add_batch_result(batch: ETLBatchResult) -> None`

<span id="benchbox.core.tpcdi.etl.ETLPhaseResult.add_batch_result"></span>

Append the batch and add its processed-record count. A failed batch sets `success` to False; a successful batch does not set it to True. This method does not update timestamps or elapsed time.

### `benchbox.core.tpcdi.etl.ETLResult`

<span id="benchbox.core.tpcdi.etl.ETLResult"></span>

Overall result returned by `run_etl_benchmark`. The historical phase is optional; `incremental_loads` contains subsequent phases. `total_execution_time` is in seconds.

| Field | Type | Default |
| --- | --- | --- |
| `historical_load` | `ETLPhaseResult \| None` | `None` |
| `incremental_loads` | `list[ETLPhaseResult]` | new empty list |
| `start_time` | `datetime \| None` | `None` |
| `end_time` | `datetime \| None` | `None` |
| `total_execution_time` | `float` | `0.0` |
| `total_records_processed` | `int` | `0` |
| `success` | `bool` | `False` |

### `benchbox.core.tpcdi.validation.ValidationResult`

<span id="benchbox.core.tpcdi.validation.ValidationResult"></span>

One rule outcome. `sql` retains the original validation rule query; execution may use its dialect translation. `violations` is the first returned scalar, or -1 on an empty result or execution failure. `expected` is the comparison value. Execution failures set `passed` to False and retain exception text in `error`. `category` groups outcomes, and `severity` determines error and warning counts.

| Field | Type | Default |
| --- | --- | --- |
| `name` | `str` | required |
| `description` | `str` | required |
| `sql` | `str` | required |
| `violations` | `Union[int, float, str]` | `0` |
| `expected` | `Union[int, float, str]` | `0` |
| `passed` | `bool` | `False` |
| `status` | `str` | `'pending'` |
| `error` | `Optional[str]` | `None` |
| `category` | `str` | `'integrity'` |
| `severity` | `str` | `'error'` |

### `benchbox.core.tpcdi.validation.DataQualityResult`

<span id="benchbox.core.tpcdi.validation.DataQualityResult"></span>

Result returned by `run_data_validation`. `quality_score` is the passing-validation fraction, or 0 when no validations ran. It is not a percentage. `error_count` and `warning_count` count failed validations with the corresponding severity. Each `categories` value contains `total`, `passed`, and `failed` counts.

| Field | Type | Default |
| --- | --- | --- |
| `validations` | `list[ValidationResult]` | new empty list |
| `total_validations` | `int` | `0` |
| `passed_validations` | `int` | `0` |
| `failed_validations` | `int` | `0` |
| `quality_score` | `float` | `0.0` |
| `error_count` | `int` | `0` |
| `warning_count` | `int` | `0` |
| `categories` | `dict[str, dict[str, int]]` | new empty dict |

### `benchbox.core.tpcdi.metrics.BenchmarkMetrics`

<span id="benchbox.core.tpcdi.metrics.BenchmarkMetrics"></span>

Result returned by `calculate_official_metrics`. Time fields use seconds. `etl_throughput` is records per second across successful ETL phases, or 0 when their summed time is nonpositive. `data_quality_score` is the passing-validation fraction; `data_integrity_score` receives the same value. The composite `overall_performance` is `sqrt(min(etl_throughput / 1000, 1) * data_quality_score) * 1000`, or 0 when either input is nonpositive.

The calculator leaves `total_records_loaded`, `validation_time`, `dimension_load_time`, `fact_load_time`, `index_creation_time`, and `scd_processing_time` at their defaults. `tpc_di_compliant` reports internal checks; it does not establish official TPC certification. `benchmark_date` is a fresh local datetime at construction.

| Field | Type | Default |
| --- | --- | --- |
| `etl_throughput` | `float` | `0.0` |
| `data_quality_score` | `float` | `0.0` |
| `overall_performance` | `float` | `0.0` |
| `total_execution_time` | `float` | `0.0` |
| `total_records_processed` | `int` | `0` |
| `total_records_loaded` | `int` | `0` |
| `historical_load_time` | `float` | `0.0` |
| `historical_load_records` | `int` | `0` |
| `incremental_load_time` | `float` | `0.0` |
| `incremental_load_records` | `int` | `0` |
| `validation_time` | `float` | `0.0` |
| `validations_passed` | `int` | `0` |
| `validations_total` | `int` | `0` |
| `data_integrity_score` | `float` | `0.0` |
| `dimension_load_time` | `float` | `0.0` |
| `fact_load_time` | `float` | `0.0` |
| `index_creation_time` | `float` | `0.0` |
| `scd_processing_time` | `float` | `0.0` |
| `tpc_di_compliant` | `bool` | `False` |
| `scale_factor` | `float` | `1.0` |
| `benchmark_date` | `datetime` | `datetime.now()` |

## Core Implementation Classes

`TPCDI` wraps the classes in this section. Use them directly to configure the benchmark with a `TPCDIConfig` or to call methods that `TPCDI` does not forward. Both classes need the `tpcdi` extra.

### `benchbox.core.tpcdi.config.TPCDIConfig`

<span id="benchbox.core.tpcdi.config.TPCDIConfig"></span>

Holds the TPC-DI settings for scale, output directory, parallelism, chunk size, seed and validation. It is a dataclass that corrects out-of-range values when it is created.

**Import:** `from benchbox.core.tpcdi.config import TPCDIConfig` · **Extras:** `tpcdi`

{#tpcdi-config-parameters}

#### Parameters

| Name | Type | Default | Meaning |
| --- | --- | --- | --- |
| `scale_factor` | `float` | `1.0` | Data size multiplier. A value of 0 or less is replaced by `1.0` without an error. |
| `output_dir` | `Path` or `None` | `None` | Output root. A string is converted to a `Path`. `None` gives `benchmark_runs/datagen/tpcdi_<sf token>` under the current directory (for example `tpcdi_sf001`), or under `$BENCHBOX_OUTPUT_DIR/datagen` when that variable is set. |
| `enable_parallel` | `bool` | `False` | Turns on parallel processing. |
| `max_workers` | `int` or `None` | `None` | Worker count, clamped to 1 to 16. `None` gives 1, or `min(8, cpu_count + 2)` with `enable_parallel=True`. |
| `chunk_size` | `int` | `10000` | Rows per processing chunk, clamped to 1000 to 50000. |
| `generation_seed` | `int` | `42` | Seed for the generated data; a different seed gives different `FactTrade` rows. |
| `enable_validation` | `bool` | `True` | Turns on data validation. |
| `strict_validation` | `bool` | `False` | Strict validation mode. |
| `optimize_memory` | `bool` | `True` | Turns on memory-saving processing. |
| `log_level` | `str` | `"INFO"` | `DEBUG`, `INFO`, `WARNING`, `ERROR` or `CRITICAL`, in any case. Creating a config calls `logging.basicConfig` with this level; an unknown name uses `INFO` there and stays unchanged on the attribute. |

{#tpcdi-config-returns}

#### Returns

A `TPCDIConfig`. Creating one makes no directories.

| Member | Returns |
| --- | --- |
| `source_dir`, `staging_dir`, `warehouse_dir` (properties) | `Path`: `source`, `staging` and `warehouse` under `output_dir`. |
| `create_directories()` | `None`. Creates `output_dir` with `source`, `staging`, `warehouse` and `logs` inside it. |
| `get_performance_profile()` | `str`: `single_threaded` without `enable_parallel`; otherwise `light` for 1 to 2 workers, `standard` up to 4, `heavy` up to 8 and `maximum` above. |
| `adjust_for_scale_factor()` | `None`. Raises `chunk_size` and `max_workers` for scale factors of 5 or more, and lowers them for 0.1 or less. |
| `get_streaming_config()`, `get_validation_config()`, `get_etl_config()`, `get_batch_config()`, `get_memory_settings()` | `dict` of the settings that each part of the pipeline reads, derived from the fields. |
| `to_dict()` | `dict` of the settings, with `output_dir` as a string and an added `performance_profile`. It leaves out `generation_seed`. |
| `from_dict(config_dict)` (class method) | A `TPCDIConfig` from a dict. Unknown keys are ignored, including `generation_seed` and `performance_profile`. |
| `for_development()` (class method) | Scale factor 0.1, one worker, `chunk_size` 1000, `optimize_memory` off, `log_level` `DEBUG`. |
| `for_production(scale_factor=1.0)` (class method) | `chunk_size` 15000 and `strict_validation` on, adjusted by `adjust_for_scale_factor()`. |
| `for_performance_testing(scale_factor=1.0)` (class method) | `max_workers` set to the CPU count (parallel stays off), `chunk_size` 25000, `enable_validation` off, `log_level` `WARNING`. |

{#tpcdi-config-raises}

#### Raises

Nothing it raises itself for numeric values, which are corrected. A value of the wrong type, such as a string `scale_factor`, raises `TypeError`.

{#tpcdi-config-example}

#### Example

```python
from pathlib import Path

from benchbox.core.tpcdi.config import TPCDIConfig

config = TPCDIConfig(scale_factor=0.01, output_dir=Path("tpcdi_out"), max_workers=99, chunk_size=10)
print(config.max_workers, config.chunk_size, config.get_performance_profile())
print(config.source_dir, config.staging_dir, config.warehouse_dir)
print(TPCDIConfig(scale_factor=-5, output_dir="tpcdi_out").scale_factor)
print(TPCDIConfig.from_dict(config.to_dict()) == config)
print(Path("tpcdi_out").exists())
config.create_directories()
print(sorted(path.name for path in Path("tpcdi_out").iterdir()))
```

Output on 0.4.1:

```text
16 1000 single_threaded
tpcdi_out/source tpcdi_out/staging tpcdi_out/warehouse
1.0
True
False
['logs', 'source', 'staging', 'warehouse']
```

### `benchbox.core.tpcdi.benchmark.TPCDIBenchmark`

<span id="benchbox.core.tpcdi.benchmark.TPCDIBenchmark"></span>

The TPC-DI benchmark implementation: it generates the 16 warehouse tables, serves the 38 queries and the schema, and runs the ETL pipeline. `benchbox.TPCDI` delegates to it.

**Import:** `from benchbox.core.tpcdi.benchmark import TPCDIBenchmark` · **Extras:** `tpcdi`

{#tpcdi-benchmark-parameters}

#### Parameters

| Name | Type | Default | Meaning |
| --- | --- | --- | --- |
| `scale_factor` | `float` | `1.0` | Data size multiplier. Must be positive; values of 1 or more must be whole numbers. |
| `output_dir` | `str`, `Path` or `None` | `None` | Output root; `None` uses the default of `TPCDIConfig`. |
| `enable_parallel` | `bool` | `False` | Turns on parallel processing. |
| `max_workers` | `int` or `None` | `None` | Worker count, as for `TPCDIConfig`. |
| `config` | `TPCDIConfig` or `None` | `None` | A configuration. When given, its `scale_factor`, `output_dir`, `enable_parallel` and `max_workers` are used and the same-named arguments are ignored. |
| `**kwargs` | keyword arguments | none | `quiet` and `verbose` set the log level; `generation_seed` sets the seed when no `config` is given. |

{#tpcdi-benchmark-returns}

#### Returns

A `TPCDIBenchmark`. It subclasses `BaseBenchmark`; see {doc}`/reference/python-api/base`. The constructor creates `logs`, `source`, `staging` and `warehouse` under `output_dir`; data files are written by `generate_data()`. Its attributes include `scale_factor`, `output_dir`, `config`, `tables` (table name to file path after `generate_data`), `schema_manager`, `metrics_calculator` and `data_generator`.

Methods that differ from the `TPCDI` wrapper:

| Method | Returns |
| --- | --- |
| `generate_data(tables=None, output_format="csv", seed=None)` | `list[str]` of the written file paths, for all 16 tables or the named ones. `seed` overrides the configured seed for that call only. `output_format` accepts only `"csv"`; the files are pipe-delimited `.tbl` files. |
| `get_query(query_id, params=None, dialect=None)` | The SQL text of one query. A number maps to a query id: 1 to 12 give `VQ1` to `VQ12` and 13 or more give `AQ1`, `AQ2` and so on. `dialect` translates the SQL; `None` or `"standard"` returns it as stored. |
| `get_queries(dialect=None)` | `dict[str, str]` of all 38 queries. |
| `get_schema(dialect="standard")` | `dict` that maps each of the 16 table names to a dict with `name` and `columns`. |
| `get_create_tables_sql(dialect="standard", tuning_config=None)` | `str` of `CREATE TABLE IF NOT EXISTS` statements for the 16 tables. |

The ETL, validation and metrics methods have the same names and meanings as on `TPCDI` (see Methods above). `TPCDIBenchmark` also has `run_validation_queries`, `run_analytical_queries`, `run_etl_validation_queries`, `run_queries_by_category`, `run_enhanced_etl_pipeline`, `get_enhanced_etl_status`, `translate_query_text`, `get_all_queries`, `get_query_execution_plan` and `get_platform_skip_queries`, which `TPCDI` does not forward.

{#tpcdi-benchmark-raises}

#### Raises

- `ValueError` when `scale_factor` is zero or negative, or is 1 or more and not whole.
- `TypeError` when `scale_factor` is not a number.
- `generate_data`: `ValueError` for an `output_format` other than `"csv"` (`Unsupported output format: parquet`) and for unknown table names (`Invalid table names: {...}`).
- `get_query`: `ValueError` for an unknown query id (`Invalid query ID: ZZ9. Available: ...`).

{#tpcdi-benchmark-example}

#### Example

```python
from benchbox.core.tpcdi.benchmark import TPCDIBenchmark
from benchbox.core.tpcdi.config import TPCDIConfig

config = TPCDIConfig(scale_factor=0.01, output_dir="tpcdi_core", generation_seed=7)
benchmark = TPCDIBenchmark(scale_factor=5, output_dir="ignored_dir", config=config)
print(benchmark.scale_factor, benchmark.output_dir, benchmark.config is config)

files = benchmark.generate_data(tables=["DimBroker", "StatusType"])
print(files)

queries = benchmark.get_queries()
print(len(queries), len(benchmark.get_schema()))

for call in (lambda: benchmark.generate_data(output_format="parquet"), lambda: benchmark.generate_data(tables=["Nope"])):
    try:
        call()
    except ValueError as exc:
        print(exc)
```

Output on 0.4.1 (the generator also logs progress to the console):

```text
0.01 tpcdi_core True
['tpcdi_core/DimBroker.tbl', 'tpcdi_core/StatusType.tbl']
38 16
Unsupported output format: parquet
Invalid table names: {'Nope'}
```

{#tpcdi-benchmark-compatibility}

#### Compatibility

`benchbox.TPCDI` creates a `TPCDIBenchmark` for each instance and forwards its methods to it. Unlike `TPCDI`, `TPCDIBenchmark` takes its `scale_factor` and `output_dir` attributes from `config` when one is given.

## See Also

- {doc}`index` - Benchmark API overview
- {doc}`tpch` - TPC-H benchmark API
- {doc}`tpcds` - TPC-DS benchmark API
- {doc}`../base` - Base benchmark interface
- {doc}`../results` - Results API
- {doc}`/benchmarks/tpc-di` - TPC-DI guide
- {doc}`/guides/tpc/tpc-di-deployment-guide` - Deployment guide
- {doc}`/guides/tpc/tpc-di-etl-guide` - ETL implementation guide

### External Resources

- [TPC-DI Specification](http://www.tpc.org/tpcdi/) - Official TPC-DI documentation
- [TPC-DI Tools](http://www.tpc.org/tpc_documents_current_versions/current_specifications.asp) - Official benchmark tools
- [Slowly Changing Dimensions](https://en.wikipedia.org/wiki/Slowly_changing_dimension) - SCD patterns
