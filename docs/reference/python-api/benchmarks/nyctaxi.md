# NYCTaxi Benchmark API

```{tags} reference, python-api, nyctaxi
```

Python API reference for the NYC Taxi benchmark.

NYC Taxi models trip records from the New York City Taxi and Limousine Commission (TLC). By default it has a `trips` fact table, a `taxi_zones` dimension table and 25 analytical queries on Yellow Taxi data. Green Taxi and high-volume for-hire vehicle (HVFHV, Uber and Lyft) data and 14 more queries can be added. Every statement on this page was checked against the released 0.4.1 wheel.

Network access matters for this benchmark. `generate_data()` tries to download each month of real TLC data and generates synthetic rows for any month it cannot download, logging `Download failed: ..., using synthetic data` for each. The runs on this page had no access to the TLC site, so every example output below comes from synthetic data. Row counts and query results from a run with network access will differ.

## `benchbox.NYCTaxi`

Creates an NYC Taxi benchmark that provides trip data in CSV files and serves 25 queries, or more when Green Taxi or HVFHV data is requested.

**Import:** `from benchbox import NYCTaxi` · **Extras:** none

### Parameters

| Name | Type | Default | Meaning |
| --- | --- | --- | --- |
| `scale_factor` | `float` | `1.0` | Sampling size of the trip data. Must be positive. Values of 1 or more must be whole numbers. At 0.01 the sample rate reported by `get_download_stats()` is 0.001 and the synthetic fallback writes 12,000 `trips` rows. |
| `output_dir` | `str`, `Path` or `None` | `None` | Directory for generated data files. When `None`, the directory is `benchmark_runs/datagen/nyctaxi_<sf token>` under the current directory (for example `nyctaxi_sf001` for 0.01), or under `$BENCHBOX_OUTPUT_DIR/datagen` when that variable is set. |
| `year` | `int` | `2019` | Year of trip data, from 2019 to 2025. |
| `months` | `list[int]` or `None` | `None` | Months to use, each 1 to 12. `None` means all 12. Only these months are generated: with `year=2020, months=[3, 4]`, `get_download_stats()["months"]` is `[3, 4]`. |
| `**kwargs` | keyword arguments | none | `taxi_types` is a list of `TaxiType` values (`TaxiType.YELLOW`, `TaxiType.GREEN`, `TaxiType.HVFHV`, imported from `benchbox.core.nyctaxi.schema`). `seed` (`int`) seeds the synthetic data and the random query dates. `force_regenerate` (`bool`) rewrites existing files. `verbose` (`bool` or `int`) and `quiet` (`bool`) set the log level. Other keywords are stored as attributes and are not validated. |

`taxi_types` defaults to Yellow only. Yellow data and `taxi_zones` are always generated; listing `TaxiType.GREEN` or `TaxiType.HVFHV` adds the `green_trips` and `hvfhv_trips` tables and their queries.

The constructor creates no files. Data is written by `generate_data()`.

### Returns

An `NYCTaxi` instance. It subclasses `BaseBenchmark`; see {doc}`/reference/python-api/base` for the shared interface. It also has two read-only properties: `tables`, the table-to-path mapping (empty until `generate_data()` has run on this instance), and `year`, the `year` argument.

### Raises

- `ValueError` when `scale_factor` is zero or negative, or is 1 or more and not a whole number.
- `ValueError` when `year` is outside 2019 to 2025: `year must be in 2019-2025, got 2018`.
- `ValueError` when a month is outside 1 to 12: `month must be in 1..12`.

### Example

```python
from benchbox import NYCTaxi

benchmark = NYCTaxi(scale_factor=0.01, output_dir="nyctaxi_data", seed=1)
files = benchmark.generate_data()
print(files)
stats = benchmark.get_download_stats()
print(stats["source"], stats["sample_rate"], stats["row_counts"])
print(benchmark.year, benchmark.get_benchmark_info()["num_queries"])
```

Output on 0.4.1, without access to the TLC site:

```text
[PosixPath('nyctaxi_data/taxi_zones.csv'), PosixPath('nyctaxi_data/trips.csv')]
synthetic 0.001 {'taxi_zones': 265, 'trips': 12000}
2019 25
```

### Compatibility

`benchbox.nyctaxi.NYCTaxi` is the same class.

## Methods

### `generate_data()`

`generate_data() -> list[str | Path]` writes `taxi_zones.csv` and `trips.csv` to `output_dir` (plus `green_trips.csv` and `hvfhv_trips.csv` when requested), plus `_datagen_manifest.json`. The files are comma-delimited with a header row. It returns the file paths as a list of `Path` objects, `taxi_zones` first. `benchmark.tables` maps the table names to the same paths.

`taxi_zones` has 265 rows. Files from an earlier run are reused unless `force_regenerate=True`.

### `get_query(query_id, *, params=None, **kwargs)`

`get_query(query_id, *, params=None, **kwargs) -> str` returns one query as SQL text.

| Name | Type | Default | Meaning |
| --- | --- | --- | --- |
| `query_id` | `str` | required | A query key such as `"trips-per-hour"`; see `get_queries()`. Numbers are rejected, whether `1` or `"1"`. |
| `params` | `dict` or `None` | `None` | Values that replace the generated ones. `start_date` (inclusive) and `end_date` (exclusive) are `YYYY-MM-DD` strings; `zone-detail` also takes `zone_id`. |
| `**kwargs` | keyword arguments | none | Accepted and ignored. |

Without `start_date` and `end_date`, the date window is chosen at random inside the data window, so each call can return different SQL. With a `seed`, two instances built with the same arguments return the same sequence of windows.

Raises `ValueError` for an unknown key: `Unknown query: nope. Available: [...]`.

### `get_queries(dialect=None)`

`get_queries(dialect=None) -> dict[str, str]` returns all queries keyed by query key, each with its own randomly chosen date window.

With Yellow only there are 25 keys, in this order: `trips-per-hour`, `trips-per-day`, `trips-per-month`, `trips-by-day-of-week`, `top-pickup-zones`, `top-dropoff-zones`, `top-routes`, `borough-summary`, `revenue-by-payment-type`, `fare-distribution`, `tip-analysis`, `surcharge-revenue`, `distance-distribution`, `passenger-count-analysis`, `trip-duration-analysis`, `rate-code-summary`, `airport-trips`, `vendor-comparison`, `hourly-zone-heatmap`, `weekday-weekend-comparison`, `rush-hour-analysis`, `monthly-year-over-year`, `single-day-summary`, `zone-detail`, `full-scan-count`.

Requesting `TaxiType.GREEN` adds 4 queries (29 in total), `TaxiType.HVFHV` adds 4 (29), and requesting both adds 14 (39).

| `dialect` | Result |
| --- | --- |
| `None`, `duckdb`, `postgres` | The source SQL. |
| `bigquery`, `snowflake`, `databricks`, `spark` | All queries translated with SQLGlot, with day-of-week and epoch expressions rewritten for the engine. |
| `clickhouse`, `starrocks` | The source SQL, except that `trips-by-day-of-week`, `trip-duration-analysis`, `weekday-weekend-comparison` and `rush-hour-analysis` are replaced by engine-specific versions. |
| Any other name | The source SQL. |

### `get_query_info(query_id)`

`get_query_info(query_id) -> dict` returns `id`, `name`, `description`, `category`, `sql` (the template with `{start_date}` and `{end_date}` placeholders) and `params` for one query. It takes the query key.

### `get_queries_by_category(category)`

`get_queries_by_category(category) -> list[str]` returns the query keys in a category. An unknown category returns an empty list. The Yellow categories are:

| Category | Query keys |
| --- | --- |
| `temporal` | `trips-per-hour`, `trips-per-day`, `trips-per-month`, `trips-by-day-of-week` |
| `geographic` | `top-pickup-zones`, `top-dropoff-zones`, `top-routes`, `borough-summary` |
| `financial` | `revenue-by-payment-type`, `fare-distribution`, `tip-analysis`, `surcharge-revenue` |
| `characteristics` | `distance-distribution`, `passenger-count-analysis`, `trip-duration-analysis` |
| `rates` | `rate-code-summary`, `airport-trips` |
| `vendor` | `vendor-comparison` |
| `complex` | `hourly-zone-heatmap`, `weekday-weekend-comparison`, `rush-hour-analysis`, `monthly-year-over-year` |
| `point` | `single-day-summary`, `zone-detail` |
| `baseline` | `full-scan-count` |

With Green and HVFHV data, further categories appear (for example `green-geographic`, `hvfhv-rideshare` and `cross-market`).

### `get_benchmark_info()`

`get_benchmark_info() -> dict` returns `name`, `description`, `reference`, `version`, `scale_factor`, `year`, `months`, `num_queries`, `query_categories`, `tables`, `taxi_types`, `data_type` and `dimensions`. `data_type` is `"real"` even when the data is synthetic; use `get_download_stats()["source"]` to tell them apart.

### `get_download_stats()`

`get_download_stats() -> dict` returns `source` (`"synthetic"` when no month could be downloaded), `scale_factor`, `sample_rate`, `year`, `months`, `seed`, `row_counts`, `synthetic_months` and `source_provenance`. It describes the Yellow Taxi data.

### `get_schema()`

`get_schema() -> dict` returns a mapping from table name to a definition with `description`, `columns` and `primary_key`; `trips` also has `partition_by`, `order_by` and `indexes`. The keys, in order, are `trips` (20 columns) and `taxi_zones` (4), followed by `green_trips` and `hvfhv_trips` when requested.

### `get_create_tables_sql(dialect="standard", tuning_config=None)`

`get_create_tables_sql(dialect="standard", tuning_config=None) -> str` returns the `CREATE TABLE` statements, `taxi_zones` first.

| Name | Type | Default | Meaning |
| --- | --- | --- | --- |
| `dialect` | `str` | `"standard"` | `duckdb` uses `VARCHAR` without lengths, `postgres` uses `TEXT`, and `clickhouse` uses ClickHouse types such as `Int32`. `standard` keeps `VARCHAR(64)`-style lengths. |
| `tuning_config` | `UnifiedTuningConfiguration` or `None` | `None` | Accepted and ignored. |

The Yellow-only script has 2 `PRIMARY KEY` clauses.

```python
from benchbox import NYCTaxi

benchmark = NYCTaxi(scale_factor=0.01, seed=7)
print(list(benchmark.get_queries())[:4])
params = {"start_date": "2019-03-01", "end_date": "2019-03-08"}
print(benchmark.get_query("trips-per-hour", params=params))
for query_id in (1, "nope"):
    try:
        benchmark.get_query(query_id)
    except ValueError as error:
        print(str(error)[:34])
print(benchmark.get_query_info("trips-per-hour")["category"])
print(benchmark.get_queries_by_category("geographic"))
schema = benchmark.get_schema()
print({name: len(table["columns"]) for name, table in schema.items()})
print(benchmark.get_create_tables_sql(dialect="duckdb").count("CREATE TABLE"))
```

Output on 0.4.1:

```text
['trips-per-hour', 'trips-per-day', 'trips-per-month', 'trips-by-day-of-week']
SELECT
    EXTRACT(HOUR FROM pickup_datetime) as hour,
    COUNT(*) as trip_count
FROM trips
WHERE pickup_datetime >= '2019-03-01'
  AND pickup_datetime < '2019-03-08'
GROUP BY EXTRACT(HOUR FROM pickup_datetime)
ORDER BY hour
Unknown query: 1. Available: ['tri
Unknown query: nope. Available: ['
temporal
['top-pickup-zones', 'top-dropoff-zones', 'top-routes', 'borough-summary']
{'trips': 20, 'taxi_zones': 4}
2
```

### Loading all three taxi types into DuckDB

This example adds Green Taxi and HVFHV data, loads every table into an in-memory DuckDB database and runs all 39 queries. It needs the `duckdb` package.

```python
import duckdb
from benchbox import NYCTaxi
from benchbox.core.nyctaxi.schema import TaxiType

benchmark = NYCTaxi(
    scale_factor=0.01,
    output_dir="nyctaxi_data",
    seed=1,
    taxi_types=[TaxiType.YELLOW, TaxiType.GREEN, TaxiType.HVFHV],
)
benchmark.generate_data()
print(len(benchmark.get_queries()), list(benchmark.get_schema()))
connection = duckdb.connect()
connection.execute(benchmark.get_create_tables_sql(dialect="duckdb"))
for table, path in benchmark.tables.items():
    connection.execute(f"COPY {table} FROM '{path}' (HEADER true)")
print(connection.execute("SELECT count(*) FROM taxi_zones").fetchone()[0])
for query in benchmark.get_queries(dialect="duckdb").values():
    connection.execute(query).fetchall()
print("all queries ran")
```

Output on 0.4.1:

```text
39 ['trips', 'taxi_zones', 'green_trips', 'hvfhv_trips']
265
all queries ran
```

## Inherited members

`run_with_platform`, `run_benchmark`, `output_dir`, `scale_factor` and every other member come from `BaseBenchmark`. See {doc}`/reference/python-api/base` for what they do.
