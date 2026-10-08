# MetadataPrimitives Benchmark API

```{tags} reference, python-api, metadata-primitives
```

Python API reference for the Metadata Primitives benchmark.

Metadata Primitives times a database's catalog introspection: the `INFORMATION_SCHEMA` views and the platform's catalog commands. It generates no data. It runs 62 queries in ten categories against a connection you supply, and can create wide tables, view hierarchies, complex types, large catalogs, constraints and access-control grants to see how introspection scales.

## `benchbox.MetadataPrimitives`

Creates a Metadata Primitives benchmark that runs catalog queries against a connection.

**Import:** `from benchbox import MetadataPrimitives` · **Extras:** none

### Parameters

| Name | Type | Default | Meaning |
| --- | --- | --- | --- |
| `scale_factor` | `float` | `1.0` | Has no effect on the queries or the schema. It is validated like every benchmark's: it must be positive, and values of 1 or more must be whole numbers. |
| `output_dir` | `str`, `Path` or `None` | `None` | Has no effect: nothing is written, and the directory is not created. |
| `**kwargs` | keyword arguments | none | `quiet` (`bool`) and `verbose` (`bool` or `int`) set the log level. Other keywords are stored as attributes and are not validated. |

The constructor creates no files and does not connect to a database.

### Returns

A `MetadataPrimitives` instance. It subclasses `BaseBenchmark`; see {doc}`/reference/python-api/base` for the shared interface.

### Raises

`ValueError` when `scale_factor` is zero or negative, or is 1 or more and not a whole number.

### Example

```python
import duckdb
from benchbox import MetadataPrimitives

benchmark = MetadataPrimitives()
print(benchmark.generate_data())
print(benchmark.get_table_names())
connection = duckdb.connect()
connection.execute(benchmark.get_create_tables_sql())
single = benchmark.execute_query("schema_list_tables", connection, dialect="duckdb")
print(single.query_id, single.category, single.row_count, single.success)
result = benchmark.run_benchmark(connection, dialect="duckdb", categories=["schema", "column"])
print(result.total_queries, result.successful_queries, result.failed_queries)
print(sorted(result.category_summary))
```

Output on 0.4.1 (needs the `duckdb` package):

```text
{}
['region', 'nation', 'supplier', 'part', 'partsupp', 'customer', 'orders', 'lineitem']
schema_list_tables schema 8 True
17 17 0
['column', 'schema']
```

### Compatibility

`benchbox.metadata_primitives.MetadataPrimitives` is the same class.

## Methods

### `generate_data(tables=None)`

`generate_data(tables=None) -> dict[str, str]` generates nothing and returns an empty `dict`, whatever `tables` is. There are no data files; the benchmark queries the catalog of the database it runs against.

### `get_schema()`

`get_schema() -> dict` returns a mapping from table name to a definition with `name` and `columns`. The keys, in order, are the eight TPC-H tables: `region`, `nation`, `supplier`, `part`, `partsupp`, `customer`, `orders` and `lineitem`. `get_table_names()` returns the same names as a list.

### `get_create_tables_sql(dialect="standard", tuning_config=None)`

`get_create_tables_sql(dialect="standard", tuning_config=None) -> str` returns the `CREATE TABLE` statements for the eight TPC-H tables. Create them first so that the catalog queries have tables to find.

| Name | Type | Default | Meaning |
| --- | --- | --- | --- |
| `dialect` | `str` | `"standard"` | Accepted but has no effect: `duckdb` and `clickhouse` return the same script as `standard`. |
| `tuning_config` | `UnifiedTuningConfiguration` or `None` | `None` | With `None`, the script has 8 `PRIMARY KEY` clauses and no foreign keys. With a new `UnifiedTuningConfiguration()` it has 8 `PRIMARY KEY` and 9 `FOREIGN KEY` clauses. With `primary_keys.enabled` and `foreign_keys.enabled` both false it has none. |

```python
from benchbox import MetadataPrimitives
from benchbox.core.tuning.interface import UnifiedTuningConfiguration

benchmark = MetadataPrimitives()
schema = benchmark.get_schema()
print(list(schema), list(schema["region"]))
for tuning in (None, UnifiedTuningConfiguration()):
    sql = benchmark.get_create_tables_sql(tuning_config=tuning)
    print(sql.count("PRIMARY KEY"), sql.count("FOREIGN KEY"))
```

Output on 0.4.1:

```text
['region', 'nation', 'supplier', 'part', 'partsupp', 'customer', 'orders', 'lineitem'] ['name', 'columns']
8 0
8 9
```

### `get_query(query_id, *, params=None)`

`get_query(query_id, *, params=None) -> str` returns the SQL text of one query.

| Name | Type | Default | Meaning |
| --- | --- | --- | --- |
| `query_id` | `str` | required | A query id such as `"schema_list_tables"`. Ids start with their category name. Integers are rejected. |
| `params` | `dict` or `None` | `None` | Must stay `None`: the queries are static. |

Raises `ValueError` for an unknown id (`Invalid query ID: nope. Available: ...`, with every id listed) and for any `params`, including an empty dict (`Metadata Primitives queries are static and don't accept parameters`).

### `get_queries(dialect=None)`

`get_queries(dialect=None) -> dict[str, str]` returns query id to SQL text. Without a `dialect` it returns all 62 queries. With a `dialect` it returns the dialect's variant of each query and leaves out the queries it does not support. Observed counts on 0.4.1: `postgres` 62, `snowflake` 60, `duckdb` 59, `bigquery` 53 and `sqlite` 51. A name BenchBox does not know, such as `"nosuch"`, returns all 62.

### `get_query_categories()` and `get_queries_by_category(category)`

`get_query_categories() -> list[str]` returns the ten categories, in this order: `acl`, `column`, `complex_type`, `constraint`, `large_catalog`, `query`, `schema`, `stats`, `view_hierarchy` and `wide_table`.

`get_queries_by_category(category) -> dict[str, str]` returns query id to SQL text for one category. An unknown category returns an empty dict. The counts are `acl` 11, `column` 8, `complex_type` 5, `constraint` 4, `large_catalog` 6, `query` 4, `schema` 9, `stats` 6, `view_hierarchy` 4 and `wide_table` 5.

```python
from benchbox import MetadataPrimitives

benchmark = MetadataPrimitives()
print(len(benchmark.get_queries()), len(benchmark.get_queries(dialect="sqlite")))
print(benchmark.get_query_categories())
print({name: len(benchmark.get_queries_by_category(name)) for name in benchmark.get_query_categories()})
print(benchmark.get_query("schema_list_tables"))
try:
    benchmark.get_query("nope")
except ValueError as error:
    print(str(error)[:40])
try:
    benchmark.get_query("schema_list_tables", params={})
except ValueError as error:
    print(error)
print(benchmark.get_benchmark_info()["query_count"])
```

Output on 0.4.1:

```text
62 51
['acl', 'column', 'complex_type', 'constraint', 'large_catalog', 'query', 'schema', 'stats', 'view_hierarchy', 'wide_table']
{'acl': 11, 'column': 8, 'complex_type': 5, 'constraint': 4, 'large_catalog': 6, 'query': 4, 'schema': 9, 'stats': 6, 'view_hierarchy': 4, 'wide_table': 5}
SELECT
    table_name,
    table_type,
    table_schema
FROM information_schema.tables
WHERE table_schema NOT IN ('information_schema', 'pg_catalog')
ORDER BY table_name;

Invalid query ID: nope. Available: acl_b
Metadata Primitives queries are static and don't accept parameters
62
```

### `get_benchmark_info()`

`get_benchmark_info() -> dict` returns `name`, `version`, `description`, `query_count` (62), `categories` (the ten above) and `complexity_categories`.

### `execute_query(query_id, connection, dialect=None)`

`execute_query(query_id, connection, dialect=None) -> MetadataQueryResult` runs one query and times it. `connection` is a DuckDB connection or another object whose `execute()` returns a cursor with `fetchall()`. The result has `query_id`, `category`, `execution_time_ms`, `row_count`, `success` and `error`.

A query that fails on the database, or that the `dialect` does not support, does not raise: it returns `success=False` with the message in `error`. For example, `acl_benchmark_role_grants` with `dialect="sqlite"` returns `Query 'acl_benchmark_role_grants' is not supported on dialect 'sqlite' (marked as skip_on: ...)` and `execution_time_ms=0.0`. An unknown `query_id` raises `ValueError`.

### `run_benchmark(connection, dialect=None, categories=None, query_ids=None, iterations=1)`

`run_benchmark(connection, dialect=None, categories=None, query_ids=None, iterations=1) -> MetadataBenchmarkResult` runs a set of queries and collects the timings.

| Name | Type | Default | Meaning |
| --- | --- | --- | --- |
| `connection` | connection | required | As for `execute_query()`. |
| `dialect` | `str` or `None` | `None` | Selects dialect variants, as in `get_queries()`. With neither `categories` nor `query_ids`, only the queries the dialect supports run (51 for `sqlite`, none failing). Queries you select by `categories` or `query_ids` that the dialect does not support are recorded as failures (`categories=["acl"]` with `sqlite` gives 11 queries, all failed). |
| `categories` | `list[str]` or `None` | `None` | Categories to run. `None` runs every query available for the dialect. |
| `query_ids` | `list[str]` or `None` | `None` | Query ids to run. When given, `categories` is ignored. |
| `iterations` | `int` | `1` | Times each query runs. `iterations=3` with one query gives `total_queries == 3`. |

The result has `total_queries`, `successful_queries`, `failed_queries`, `total_time_ms`, `results` (a list of `MetadataQueryResult`), `category_summary` (per category: `total_queries`, `successful`, `failed`, `total_time_ms`, `avg_time_ms`, `min_time_ms` and `max_time_ms`), `acl_mutation_results` and `acl_mutation_summary`.

**Side effect on most platforms:** when `dialect` is given and is not `duckdb`, `sqlite`, `datafusion`, `spark` or `polars`, `run_benchmark()` also creates roles and a table, grants and revokes privileges, and drops the roles after the selected queries, whatever `categories` or `query_ids` say. For example, with `dialect="postgres"` and one selected query, it runs 12 such operations (`CREATE ROLE`, `GRANT`, `REVOKE` and `DROP ROLE`, three each) and a `CREATE TABLE`, and reports them in `acl_mutation_results`. With `dialect="duckdb"` it runs only the selected query. Do not point it at a shared platform with a dialect name unless those statements are acceptable there.

### Complexity methods

The complexity methods create catalog objects to stress introspection, and remove them afterwards.

| Method | Meaning |
| --- | --- |
| `get_complexity_categories()` | Returns `['wide_table', 'view_hierarchy', 'complex_type', 'large_catalog', 'constraint', 'acl']`. |
| `setup_complexity(connection, dialect, config)` | Creates the objects that `config` describes and returns a `GeneratedMetadata` with `tables`, `views`, `schemas`, `prefix`, `config`, `roles` and `grants`. |
| `teardown_complexity(connection, dialect, generated)` | Drops everything that `setup_complexity()` created. Returns `None`. |
| `run_complexity_benchmark(connection, dialect, config, iterations=1, categories=None)` | Sets up, runs `run_benchmark()` on the categories (chosen from `config` when `categories` is `None`), and always tears down, even when the run raises. Returns a `ComplexityBenchmarkResult` with `complexity_config`, `generated_metadata`, `setup_time_ms`, `teardown_time_ms` and `benchmark_result`. |

`config` is a preset name or a `MetadataComplexityConfig` from `benchbox.core.metadata_primitives.complexity`. The preset names are `minimal`, `baseline`, `wide_tables`, `deep_views`, `complex_types`, `large_catalog`, `full`, `stress`, `acl_sparse`, `acl_moderate`, `acl_dense`, `acl_hierarchy` and `acl_full`. An unknown name raises `ValueError`: `Unknown complexity preset 'nope'. Available: ...`. Created objects are named with the prefix `benchbox_`.

On DuckDB the `wide_tables` preset created 11 tables (one with 500 columns, named `benchbox_wide_500`, and ten catalog tables) and 1 view, and `run_complexity_benchmark()` with it ran 15 queries, all successful.

```python
import duckdb
from benchbox import MetadataPrimitives

benchmark = MetadataPrimitives()
connection = duckdb.connect()
print(benchmark.get_complexity_categories())
generated = benchmark.setup_complexity(connection, "duckdb", "wide_tables")
print(len(generated.tables), len(generated.views))
print(connection.execute("SELECT count(*) FROM information_schema.tables").fetchone()[0])
benchmark.teardown_complexity(connection, "duckdb", generated)
print(connection.execute("SELECT count(*) FROM information_schema.tables").fetchone()[0])
result = benchmark.run_complexity_benchmark(connection, "duckdb", "wide_tables")
print(result.benchmark_result.total_queries, result.benchmark_result.failed_queries)
print(connection.execute("SELECT count(*) FROM information_schema.tables").fetchone()[0])
```

Output on 0.4.1:

```text
['wide_table', 'view_hierarchy', 'complex_type', 'large_catalog', 'constraint', 'acl']
11 1
12
0
15 0
0
```

## Inherited members

`run_with_platform` and every other member that this page does not describe come from `BaseBenchmark`. See {doc}`/reference/python-api/base` for what they do.
