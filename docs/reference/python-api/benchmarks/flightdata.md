# FlightData Benchmark API

```{tags} reference, python-api, flightdata
```

Python API reference for the FlightData benchmark.

FlightData models US domestic flight on-time performance (the Bureau of Transportation Statistics "On-Time Performance" data). It has a `flights` fact table, two small reference tables (`airlines` and `airports`) and 20 analytical queries in five categories.

Network access matters for this benchmark. `generate_data()` tries to download each month of real data from the Bureau of Transportation Statistics and generates synthetic rows for any month it cannot download. The runs on this page had no access to that site, so every example output below comes from synthetic data. Row counts and query results from a run with network access will differ.

## `benchbox.FlightData`

Creates a FlightData benchmark that provides flight data in CSV files and serves 20 queries.

**Import:** `from benchbox import FlightData` · **Extras:** none

### Parameters

| Name | Type | Default | Meaning |
| --- | --- | --- | --- |
| `scale_factor` | `float` | `1.0` | Selects how many months of data to use: `max(1, round(scale_factor * 41))`, newest first. 0.01 gives 1 month and 0.1 gives 4 months. Must be positive. Values of 1 or more must be whole numbers. |
| `output_dir` | `str`, `Path` or `None` | `None` | Directory for generated data files. When `None`, the directory is `benchmark_runs/datagen/flightdata_<sf token>` under the current directory (for example `flightdata_sf001` for 0.01), or under `$BENCHBOX_OUTPUT_DIR/datagen` when that variable is set. |
| `end_year` | `int` | `2024` | Stored and reported by `get_benchmark_info()` as `end_year`. On 0.4.1 it does not move the data window: with `end_year=2020`, scale factor 0.01 still selects December 2024 and the query dates stay `2024-12-01` to `2025-01-01`. |
| `**kwargs` | keyword arguments | none | `seed` (`int`) seeds the synthetic data; the same seed gives an identical `flights.csv` and a different seed gives a different one. `force_regenerate` (`bool`) rewrites the files; without it, files from an earlier run in `output_dir` are reused. `verbose` (`bool` or `int`) and `quiet` (`bool`) set the log level. Other keywords are stored as attributes and are not validated. |

The constructor creates no files. Data is written by `generate_data()`.

### Returns

A `FlightData` instance. It subclasses `BaseBenchmark`; see {doc}`/reference/python-api/base` for the shared interface. The property `tables` holds the table-to-path mapping; it is empty until `generate_data()` has run on this instance.

### Raises

`ValueError` when `scale_factor` is zero or negative, or is 1 or more and not a whole number.

### Example

```python
from benchbox import FlightData

benchmark = FlightData(scale_factor=0.01, output_dir="flightdata_data", seed=1)
files = benchmark.generate_data()
print(files)
stats = benchmark.get_download_stats()
print(stats["months"], stats["months_downloaded"], stats["months_synthetic"])
info = benchmark.get_benchmark_info()
print(info["num_months"], info["query_start_date"], info["query_end_date"], info["num_queries"])
```

Output on 0.4.1, without access to the Bureau of Transportation Statistics site:

```text
[PosixPath('flightdata_data/flights.csv'), PosixPath('flightdata_data/airlines.csv'), PosixPath('flightdata_data/airports.csv')]
[(2024, 12)] 0 1
1 2024-12-01 2025-01-01 20
```

### Compatibility

`benchbox.flightdata.FlightData` is the same class.

## Methods

### `generate_data()`

`generate_data() -> list[str | Path]` writes `flights.csv`, `airlines.csv` and `airports.csv` to `output_dir`, plus `_datagen_manifest.json`, and returns the file paths as a list of `Path` objects in that order. The files are comma-delimited with a header row. `benchmark.tables` maps the table names `flights`, `airlines` and `airports` to the same paths.

`airlines` has 25 rows and `airports` has 50 rows. With a `seed` of 1 the synthetic `flights.csv` for December 2024 has 566,315 rows and is 60 MB; scale factors of 1 or more select 41 or more months. At those sizes the `flights` table is written as several monthly files, and `tables["flights"]` is then a list of paths.

### `get_query(query_id, *, params=None, **kwargs)`

`get_query(query_id, *, params=None, **kwargs) -> str` returns one query as SQL text.

| Name | Type | Default | Meaning |
| --- | --- | --- | --- |
| `query_id` | `int` or `str` | required | A query key such as `"ontime-by-carrier"`, or its number `1` to `20` as an integer or string. Numbers follow the order of `get_queries()`. |
| `params` | `dict` or `None` | `None` | Values that replace the defaults. `start_date` (inclusive) and `end_date` (exclusive) are `YYYY-MM-DD` strings that default to the data window (`2024-12-01` and `2025-01-01` at scale factor 0.01). |
| `**kwargs` | keyword arguments | none | Accepted and ignored. |

Raises `ValueError` for an unknown key or a number outside 1 to 20: `Unknown query: 'nope'. Valid keys: [...]`.

### `get_queries(dialect=None)`

`get_queries(dialect=None) -> dict[str, str]` returns all 20 queries keyed by query key, rendered with the default date window. The `dialect` argument has no effect: `duckdb` and `bigquery` return the same text as no dialect.

| Category | Query keys |
| --- | --- |
| `ontime` | `ontime-by-carrier`, `delay-by-airport`, `delay-by-hour`, `best-routes`, `improvement-trend` |
| `delay` | `delay-causes`, `cascade-delays`, `weather-impact`, `recovery-time` |
| `routes` | `busiest-routes`, `route-reliability`, `distance-delay`, `hub-connectivity` |
| `temporal` | `day-of-week`, `seasonal-trends`, `holiday-impact`, `time-of-day` |
| `carriers` | `carrier-ranking`, `cancellation-rate`, `market-share` |

### `get_query_info(query_id)`

`get_query_info(query_id) -> dict` returns `id`, `name`, `description`, `category` and `key` for one query. It takes the query key only; a number such as `"1"` raises `ValueError`, as does an unknown key.

### `get_queries_by_category(category)`

`get_queries_by_category(category) -> list[str]` returns the query keys in a category from the table above, in the order shown. An unknown category returns an empty list.

### `get_benchmark_info()`

`get_benchmark_info() -> dict` returns `name`, `description`, `reference`, `version`, `scale_factor`, `end_year`, `num_months`, `query_start_date`, `query_end_date`, `num_queries`, `query_categories`, `tables` and `data_type`. `data_type` is always `"real_or_synthetic"`.

### `get_download_stats()`

`get_download_stats() -> dict` returns `source`, `scale_factor`, `num_months`, `months` (a list of `(year, month)` pairs, newest first), `months_downloaded`, `months_synthetic`, `total_flights` and `source_provenance`. The month counts and `total_flights` are 0 until `generate_data()` has run. `months_downloaded` and `months_synthetic` show how much of the data is real.

### `get_schema()`

`get_schema() -> dict` returns a mapping from table name to a definition with `description`, `columns` and `primary_key` (`flights` also has `indexes`). `columns` is a dict from column name to a dict with `type` and `description`. The keys, in order, are `flights` (28 columns), `airlines` (2) and `airports` (6).

### `get_create_tables_sql(dialect="standard", tuning_config=None)`

`get_create_tables_sql(dialect="standard", tuning_config=None) -> str` returns `CREATE TABLE IF NOT EXISTS` statements for `airlines`, `airports` and `flights`, in that order.

| Name | Type | Default | Meaning |
| --- | --- | --- | --- |
| `dialect` | `str` | `"standard"` | `standard`, `postgres` and `bigquery` return the same script. `duckdb` uses `DOUBLE` where the standard script has `DOUBLE PRECISION`. `snowflake` uses `NUMBER(p,s)` and `FLOAT` types. `clickhouse` uses ClickHouse types such as `String` and `Float64` and has no `PRIMARY KEY` clauses. An unrecognised name returns the standard script. |
| `tuning_config` | `UnifiedTuningConfiguration` or `None` | `None` | Accepted and ignored. |

The standard script has 3 `PRIMARY KEY` clauses (`code` on `airlines` and `airports`, `flight_id` on `flights`) and no foreign keys.

```python
from benchbox import FlightData

benchmark = FlightData(scale_factor=0.01)
print(list(benchmark.get_queries())[:4])
print(benchmark.get_query(1) == benchmark.get_query("ontime-by-carrier"))
print(benchmark.get_query_info("ontime-by-carrier"))
print(benchmark.get_queries_by_category("carriers"))
params = {"start_date": "2020-01-01", "end_date": "2020-02-01"}
print([line.strip() for line in benchmark.get_query("ontime-by-carrier", params=params).splitlines() if "flight_date" in line])
try:
    benchmark.get_query("nope")
except ValueError as error:
    print(str(error)[:40])
schema = benchmark.get_schema()
print({name: len(table["columns"]) for name, table in schema.items()})
print(benchmark.get_create_tables_sql().count("CREATE TABLE"))
```

Output on 0.4.1:

```text
['ontime-by-carrier', 'delay-by-airport', 'delay-by-hour', 'best-routes']
True
{'id': '1', 'name': 'On-Time Rate by Carrier', 'description': 'On-time arrival percentage by airline carrier', 'category': 'ontime', 'key': 'ontime-by-carrier'}
['carrier-ranking', 'cancellation-rate', 'market-share']
["AND f.flight_date >= '2020-01-01'", "AND f.flight_date < '2020-02-01'"]
Unknown query: 'nope'. Valid keys: ['ont
{'flights': 28, 'airlines': 2, 'airports': 6}
3
```

### Loading into DuckDB

This example loads the generated files into an in-memory DuckDB database and runs all 20 queries. It needs the `duckdb` package. The `flights` row count is left out because it depends on whether real data was downloaded.

```python
import duckdb
from benchbox import FlightData

benchmark = FlightData(scale_factor=0.01, output_dir="flightdata_data", seed=1)
benchmark.generate_data()
connection = duckdb.connect()
connection.execute(benchmark.get_create_tables_sql(dialect="duckdb"))
for table, path in benchmark.tables.items():
    connection.execute(f"COPY {table} FROM '{path}' (HEADER true)")
for table in ("airlines", "airports"):
    print(table, connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0])
for query in benchmark.get_queries().values():
    connection.execute(query).fetchall()
print(len(benchmark.get_queries()), "queries ran")
```

Output on 0.4.1:

```text
airlines 25
airports 50
20 queries ran
```

## Inherited members

`run_with_platform`, `run_benchmark`, `output_dir`, `scale_factor` and every other member come from `BaseBenchmark`. See {doc}`/reference/python-api/base` for what they do.
