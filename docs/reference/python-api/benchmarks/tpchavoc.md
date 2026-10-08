# TPC-Havoc API

```{tags} reference, python-api, tpch
```

<!-- markdownlint-disable MD024 -->

Python API reference for the TPC-Havoc benchmark.

## Overview

TPC-Havoc uses the TPC-H data and the 22 TPC-H queries, and adds 10 rewritten variants of each query (220 in all). A variant asks the same question with different SQL constructs, such as a CTE, a derived table, a window function or a `FILTER` clause, so it exercises other parts of a query optimizer. Run the variants on a platform adapter or your own connection and compare their timings.

## `benchbox.TPCHavoc`

<span id="benchbox.tpchavoc.TPCHavoc"></span>

Creates a TPC-Havoc benchmark that generates TPC-H data and serves the base queries and their variants.

**Import:** `from benchbox import TPCHavoc` · **Extras:** none

### Parameters

| Name | Type | Default | Meaning |
| --- | --- | --- | --- |
| `scale_factor` | `float` | `1.0` | Data size multiplier. Must be positive. Values of 1 or more must be whole numbers. |
| `output_dir` | `str`, `Path` or `None` | `None` | Directory for generated data files. When `None`, the directory is `benchmark_runs/datagen/tpchavoc_<sf token>` under the current directory (for example `tpchavoc_sf001` for 0.01), or under `$BENCHBOX_OUTPUT_DIR/datagen` when that variable is set. |
| `**kwargs` | keyword arguments | none | `verbose` (`bool` or `int`) and `quiet` (`bool`) set the log level. Other keywords are forwarded to the underlying TPC-H benchmark. |

The constructor creates no files. Data is written by `generate_data()`.

### Returns

A `TPCHavoc` instance. It subclasses `BaseBenchmark`; see {doc}`/reference/python-api/base` for the shared interface.

### Raises

- `ValueError` when `scale_factor` is zero or negative (`scale_factor must be positive, got 0`), or is 1 or more and not a whole number.
- `TypeError` when `scale_factor` is not a number.

### Example

```python
from benchbox import TPCHavoc

benchmark = TPCHavoc(scale_factor=0.01, output_dir="havoc_data")
print(benchmark.get_implemented_queries()[:3], len(benchmark.get_queries()))
print(benchmark.get_variant_description(1, 3))
variants = benchmark.get_all_variants(6)
print(sorted(variants))
print(benchmark.get_query_variant(6, 2) == benchmark.get_query("6_v2"))
```

Output on 0.4.1:

```text
[1, 2, 3] 220
Multiple FROM clauses: Use explicit join syntax with same table
[1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
True
```

### Compatibility

`benchbox.tpchavoc.TPCHavoc` is the same class.

## Constructor

<span id="benchbox.tpchavoc.TPCHavoc.__init__"></span>

`TPCHavoc(scale_factor=1.0, output_dir=None, **kwargs)`. The arguments are in the Parameters table above.

## Query methods

Query ids run from 1 to 22 and variant ids from 1 to 10. Variant SQL is generated with TPC-H's default parameter values. The `params` argument of `get_query_variant()` replaces `{key}` tokens in the variant SQL, and the only token in use is `{q11_fraction}`, which defaults to a value derived from the scale factor. Other names, such as `date` or `discount`, do not change the text.

### get_query_variant(query_id, variant_id, params=None)

<span id="benchbox.tpchavoc.TPCHavoc.get_query_variant"></span>

`get_query_variant(query_id, variant_id, params=None) -> str` returns one variant as SQL text.

| Name | Type | Default | Meaning |
| --- | --- | --- | --- |
| `query_id` | `int` | required | 1 to 22. |
| `variant_id` | `int` | required | 1 to 10. |
| `params` | `dict` or `None` | `None` | Parameter overrides; see the note above. |

Raises `ValueError` for an id out of range (`Variant ID must be 1-10, got 11`, `Query ID must be 1-22, got 23`) and `TypeError` when an id is not an `int`.

### get_all_variants(query_id)

<span id="benchbox.tpchavoc.TPCHavoc.get_all_variants"></span>

`get_all_variants(query_id) -> dict[int, str]` returns the 10 variants of one query, keyed 1 to 10. Raises `ValueError` outside 1 to 22 and `TypeError` for a non-`int`.

### get_variant_description(query_id, variant_id)

<span id="benchbox.tpchavoc.TPCHavoc.get_variant_description"></span>

`get_variant_description(query_id, variant_id) -> str` returns a short label for a variant, for example `Scalar subqueries: Use scalar subqueries for conditional aggregation` for query 6, variant 1. The same ids are checked as in `get_query_variant()`.

### get_all_variants_info(query_id)

<span id="benchbox.tpchavoc.TPCHavoc.get_all_variants_info"></span>

`get_all_variants_info(query_id) -> dict[int, dict]` returns, for each variant id, a dict with `description` and `variant_id`.

### get_implemented_queries()

<span id="benchbox.tpchavoc.TPCHavoc.get_implemented_queries"></span>

`get_implemented_queries() -> list[int]` returns the query ids that have variants: all of 1 to 22.

### get_query(query_id, \*, params=None, seed=None, scale_factor=None, dialect=None, \*\*kwargs)

<span id="benchbox.tpchavoc.TPCHavoc.get_query"></span>

`get_query(query_id, *, params=None, seed=None, scale_factor=None, dialect=None, **kwargs) -> str` returns either a base TPC-H query or a variant.

| Name | Type | Default | Meaning |
| --- | --- | --- | --- |
| `query_id` | `int` or `str` | required | An `int` from 1 to 22 returns the base TPC-H query. A string such as `"6_v2"` returns query 6, variant 2; it has to contain `_v`. |
| `seed` | `int` or `None` | `None` | Seed for the generated parameter values of a base query. Different seeds give different parameters. A variant is the same for every seed. |
| `scale_factor` | `float` or `None` | `None` | Scale factor for parameter calculation. Must be positive. |

Raises `ValueError` for an integer outside 1 to 22, a string without `_v` (`String query ID must be in format 'Q_VID' (e.g., '1_v1'), got 1`) or an unknown variant (`Invalid variant query ID format: 1_v99`), and `TypeError` for other types. `params` and `dialect` are accepted but have no effect here: `get_query(1, dialect="bigquery")` returns the same text as `get_query(1)`. Use `get_queries(dialect=...)` for translation.

### get_queries(dialect=None)

<span id="benchbox.tpchavoc.TPCHavoc.get_queries"></span>

`get_queries(dialect=None) -> dict[str, str]` returns all 220 variants, keyed `"1_v1"` to `"22_v10"`. It does not return the base queries, so `get_queries()["1"]` raises `KeyError`. With a `dialect`, each query is translated with SQLGlot: for `bigquery` identifiers are quoted with backticks.

## Data and schema methods

### generate_data()

<span id="benchbox.tpchavoc.TPCHavoc.generate_data"></span>

`generate_data() -> list` writes the eight TPC-H tables as pipe-delimited `.tbl` files, plus `_datagen_manifest.json`, to `output_dir` and returns the file paths. At scale factor 0.01, `lineitem` holds 60,175 rows. `benchmark.tables` is a `dict` of table name to path and is empty until `generate_data()` has run.

### get_schema()

<span id="benchbox.tpchavoc.TPCHavoc.get_schema"></span>

`get_schema() -> dict` returns the TPC-H schema, a mapping from table name to definition: `region`, `nation`, `supplier`, `part`, `partsupp`, `customer`, `orders`, `lineitem`.

### get_create_tables_sql(dialect="standard", tuning_config=None)

<span id="benchbox.tpchavoc.TPCHavoc.get_create_tables_sql"></span>

`get_create_tables_sql(dialect="standard", tuning_config=None) -> str` returns the TPC-H `CREATE TABLE` script.

### get_benchmark_info()

<span id="benchbox.tpchavoc.TPCHavoc.get_benchmark_info"></span>

`get_benchmark_info() -> dict` returns `benchmark_name`, `base_benchmark` (`"TPC-H"`), `scale_factor`, `implemented_queries`, `total_queries_with_variants` (22), `variants_per_query` (10), `total_query_variants` (220), `variants_info`, `validation_tolerance` and `description`.

### export_variant_queries(output_dir=None, format="sql")

<span id="benchbox.tpchavoc.TPCHavoc.export_variant_queries"></span>

`export_variant_queries(output_dir=None, format="sql") -> dict[str, Path]` writes every variant to its own file and returns a mapping from `"Q1.1"` to the file path.

| Name | Type | Default | Meaning |
| --- | --- | --- | --- |
| `output_dir` | `str`, `Path` or `None` | `None` | Target directory, created when missing. `None` uses `queries` under the benchmark's `output_dir`. |
| `format` | `str` | `"sql"` | `"sql"` or `"json"`. |

`"sql"` writes 220 files named `q<query>_variant_<variant>.sql`, each starting with two comment lines (`-- TPC-Havoc Query 1 Variant 1` and the description). `"json"` is accepted but writes nothing and returns `{}`. Any other format raises `ValueError` (`Unsupported export format: csv`).

## Running queries

Run the queries through a platform adapter, as for TPC-H, or execute the variant SQL on your own connection. On DuckDB at scale factor 0.01, the base query 6 and all ten of its variants return the same single value.

`TPCHavoc` also defines `load_data_to_database(connection_string, ...)`, `run_query(query_id, connection_string, ...)` and `run_benchmark(connection_string, ...)`. On 0.4.1 all three fail: `load_data_to_database` raises `AttributeError: 'TPCHavocBenchmark' object has no attribute 'load_data_to_database'`, and `run_query` and `run_benchmark` raise `TypeError` (`BaseBenchmark.run_query() got an unexpected keyword argument 'connection_string'`, and the same message for `BaseBenchmark.run_benchmark()`). Use an adapter instead:

```python
from benchbox import TPCHavoc
from benchbox.platforms.duckdb import DuckDBAdapter

benchmark = TPCHavoc(scale_factor=0.01, output_dir="havoc_data")
benchmark.generate_data()
adapter = DuckDBAdapter(database=":memory:")
conn = adapter.create_connection()
adapter.create_schema(benchmark, conn)
adapter.load_data(benchmark, conn, benchmark.output_dir)
base = conn.execute(benchmark.get_query(6)).fetchall()
same = [conn.execute(benchmark.get_query_variant(6, v)).fetchall() == base for v in range(1, 11)]
print(all(same))
```

Output on 0.4.1, after the adapter's progress lines:

```text
True
```

## Inherited members

Every other member comes from `BaseBenchmark`: platform runs (`run_with_platform`), validation, logging, `output_dir`, `scale_factor` and the loading configuration. See {doc}`/reference/python-api/base`.
