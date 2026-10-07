# Data Vault Benchmark API

```{tags} reference, python-api, datavault
```

Python API reference for the Data Vault benchmark.

Data Vault turns the eight TPC-H tables into 21 Data Vault 2.0 tables (7 hubs, 6 links and 8 satellites) and serves 22 TPC-H-derived queries written for that model.

## `benchbox.DataVault`

Creates a Data Vault benchmark that generates TPC-H source data, transforms it into 21 pipe-delimited `.tbl` files, and serves the 22 adapted queries.

**Import:** `from benchbox import DataVault` · **Extras:** none

### Parameters

| Name | Type | Default | Meaning |
| --- | --- | --- | --- |
| `scale_factor` | `float` | `1.0` | Scale factor of the TPC-H source data. Must be a positive number. Values of 1 or more must be whole numbers. |
| `output_dir` | `str`, `Path` or `None` | `None` | Directory for the Data Vault files. When `None`, the directory is `benchmark_runs/datagen/datavault_<sf token>` under the current directory (for example `datavault_sf001` for 0.01), or under `$BENCHBOX_OUTPUT_DIR/datagen` when that variable is set. The TPC-H source files go to a sibling directory named `tpch_<sf token>` (for example `tpch_sf001`). |
| `**kwargs` | keyword arguments | none | `hash_algorithm` is `"md5"` (default) or `"sha256"` and sets the hash used for the hash-key columns. `record_source` (default `"TPCH"`) is the value written to the `record_source` column. `verbose` (`bool` or `int`) and `quiet` (`bool`) set the log level. Other keywords are stored as attributes and are not validated. |

The constructor creates no files. Data is written by `generate_data()`.

### Returns

A `DataVault` instance. It subclasses `BaseBenchmark`; see {doc}`/reference/python-api/base` for the shared interface.

It also has three read-only properties:

| Property | Value |
| --- | --- |
| `tables` | The table-to-path mapping. Empty until `generate_data()` has run on this instance. |
| `table_count` | `21`. |
| `query_count` | `22`. |

### Raises

- `TypeError` when `scale_factor` is not a number.
- `ValueError` when `scale_factor` is zero or negative, or is 1 or more and not a whole number.
- `ValueError` when `hash_algorithm` is not `"md5"` or `"sha256"`: `Unsupported hash algorithm: 'sha1'. Supported algorithms: ('md5', 'sha256').`

### Example

```python
import os
from benchbox import DataVault

benchmark = DataVault(scale_factor=0.01, output_dir="datavault_data/datavault_sf001")
files = benchmark.generate_data()
print(len(files), list(files)[:3])
print(files["hub_region"])
print(benchmark.table_count, benchmark.query_count)
print(sorted(os.listdir("datavault_data")))
```

Output on 0.4.1:

```text
21 ['hub_region', 'hub_nation', 'hub_customer']
datavault_data/datavault_sf001/hub_region.tbl
21 22
['datavault_sf001', 'tpch_sf001']
```

### Compatibility

`benchbox.datavault.DataVault` is the same class.

## Methods

### `generate_data()`

`generate_data() -> dict[str, Any]` generates the TPC-H source data, then writes one pipe-delimited `.tbl` file per Data Vault table plus `_datagen_manifest.json` to `output_dir`. It returns a `dict` that maps each of the 21 table names to its file path. The keys are in loading order: 7 hubs, 6 links, then 8 satellites. `benchmark.tables` holds the same mapping afterwards.

At scale factor 0.01 the run took about 9 seconds and wrote 46 MB for the Data Vault and TPC-H directories together.

### `get_query(query_id, *, params=None, **kwargs)`

`get_query(query_id, *, params=None, **kwargs) -> str` returns one query as SQL text, adapted from the TPC-H query with the same number.

| Name | Type | Default | Meaning |
| --- | --- | --- | --- |
| `query_id` | `int` | required | `1` to `22`. |
| `params` | `dict` or `None` | `None` | Accepted for interface compatibility. It has no effect: the query text is the same with and without it. |
| `**kwargs` | keyword arguments | none | Accepted and ignored. |

Raises `ValueError` for an integer outside 1 to 22 (`Query ID must be 1-22, got 0`) and `TypeError` for a non-integer (`query_id must be an integer, got str`). A string such as `"1"` is rejected.

### `get_queries()`

`get_queries() -> dict[str, str]` returns all 22 queries, keyed by the integers `1` to `22` (the annotation says `str` keys). It takes no `dialect` argument.

### `get_schema()`

`get_schema() -> dict[str, Any]` returns a mapping from table name to a table object. The keys, in order, are the 7 hubs, 6 links and 8 satellites. Each value has `name`, `table_type` (`"hub"`, `"link"` or `"sat"`), `columns`, and the methods `get_create_table_sql()`, `get_primary_key()` and `get_foreign_keys()`.

### `get_create_tables_sql(dialect="standard", tuning_config=None)`

`get_create_tables_sql(dialect="standard", tuning_config=None) -> str` returns the `CREATE TABLE` statements for all 21 tables.

| Name | Type | Default | Meaning |
| --- | --- | --- | --- |
| `dialect` | `str` | `"standard"` | `standard` and `duckdb` return the same script. `clickhouse` returns the statements with ClickHouse types such as `Nullable(String)`, one line per table. |
| `tuning_config` | `UnifiedTuningConfiguration` or `None` | `None` | With `None`, or with a new `UnifiedTuningConfiguration()`, the script has 21 `PRIMARY KEY` clauses and 22 `FOREIGN KEY` clauses. With `primary_keys.enabled` and `foreign_keys.enabled` both false it has none. |

### `get_table_loading_order(available_tables=None)`

`get_table_loading_order(available_tables=None) -> list[str]` returns table names in an order that loads every hub before the links and satellites that refer to it: hubs, then links, then satellites.

With `None` it returns all 21 names. With a list, it returns only the names from that list that are Data Vault tables, in loading order; unknown names are dropped.

```python
from benchbox import DataVault

benchmark = DataVault(scale_factor=0.01)
print(benchmark.get_query(6))
print(len(benchmark.get_queries()))
for query_id in (0, "1"):
    try:
        benchmark.get_query(query_id)
    except (TypeError, ValueError) as error:
        print(type(error).__name__, error)
print(benchmark.get_table_loading_order(["sat_region", "link_nation_region", "hub_region"]))
schema = benchmark.get_schema()
print(len(schema), schema["hub_region"].table_type)
sql = benchmark.get_create_tables_sql()
print(sql.count("CREATE TABLE"), sql.count("PRIMARY KEY"), sql.count("FOREIGN KEY"))
```

Output on 0.4.1:

```text
SELECT
    SUM(sl.l_extendedprice * sl.l_discount) AS revenue
FROM link_lineitem ll
JOIN sat_lineitem sl ON ll.hk_lineitem_link = sl.hk_lineitem_link AND sl.load_end_dts IS NULL
WHERE sl.l_shipdate >= DATE '1994-01-01'
  AND sl.l_shipdate < DATE '1994-01-01' + INTERVAL '1' YEAR
  AND sl.l_discount BETWEEN 0.06 - 0.01 AND 0.06 + 0.01
  AND sl.l_quantity < 24
22
ValueError Query ID must be 1-22, got 0
TypeError query_id must be an integer, got str
['hub_region', 'link_nation_region', 'sat_region']
21 hub
21 21 22
```

### Loading into DuckDB

This example loads the generated files into an in-memory DuckDB database and runs query 6. It needs the `duckdb` package. The files are pipe-delimited with no header row.

```python
import duckdb
from benchbox import DataVault

benchmark = DataVault(scale_factor=0.01, output_dir="datavault_data/datavault_sf001")
files = benchmark.generate_data()
connection = duckdb.connect()
connection.execute(benchmark.get_create_tables_sql())
for table in benchmark.get_table_loading_order(list(files)):
    connection.execute(f"COPY {table} FROM '{files[table]}' (DELIMITER '|', HEADER false)")
print(connection.execute("SELECT count(*) FROM hub_lineitem").fetchone()[0])
print(connection.execute(benchmark.get_query(6)).fetchall())
```

Output on 0.4.1:

```text
60175
[(Decimal('1193053.2253'),)]
```

## Inherited members

`run_with_platform`, `run_benchmark`, `output_dir`, `scale_factor` and every other member come from `BaseBenchmark`. See {doc}`/reference/python-api/base` for what they do.
