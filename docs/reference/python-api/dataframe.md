<!-- markdownlint-disable MD024 -->

# DataFrame query registries

```{tags} reference, python-api
```

Constants that describe the DataFrame platforms and the DataFrame query sets that BenchBox ships. On 0.4.1 the TPC-H DataFrame query names do not import in a fresh process; see the sections below.

## `benchbox.DATAFRAME_PLATFORMS`

<span id="benchbox.DATAFRAME_PLATFORMS"></span>

A dictionary of the six DataFrame platforms BenchBox knows, keyed by platform name.

**Import:** `from benchbox import DATAFRAME_PLATFORMS` · **Extras:** none

### Contents

- **Type:** `dict` mapping `str` to `PlatformInfo`.
- **Keys (6):** `pandas`, `polars`, `dask`, `cudf`, `pyspark`, `datafusion`.
- **Values:** `benchbox.platforms.dataframe.platform_checker.PlatformInfo` objects with these attributes:

| Attribute | Meaning |
| --- | --- |
| `name` | Display name, for example `Polars`. |
| `family` | `DataFrameFamily`: `pandas` for pandas, Dask and cuDF; `expression` for Polars, PySpark and DataFusion. Read its text with `.value`. |
| `import_name` | Module name to import. |
| `version_attr` | Attribute that holds the module version. |
| `extra_name` | BenchBox extra that installs the library. An empty string for `polars`. |
| `description` | One-line description. |
| `min_version` | Minimum supported version, for example `1.0.0` for Polars. |
| `max_version` | Maximum supported version, `None` for all six. |

### Example

```python
from benchbox import DATAFRAME_PLATFORMS

print(type(DATAFRAME_PLATFORMS).__name__, len(DATAFRAME_PLATFORMS))
print(list(DATAFRAME_PLATFORMS))
info = DATAFRAME_PLATFORMS["polars"]
print(info.name, info.family.value, info.import_name, repr(info.extra_name), info.min_version)
```

Output on 0.4.1:

```text
dict 6
['pandas', 'polars', 'dask', 'cudf', 'pyspark', 'datafusion']
Polars expression polars '' 1.0.0
```

## `benchbox.TPCDS_DATAFRAME_QUERIES`

<span id="benchbox.TPCDS_DATAFRAME_QUERIES"></span>

The registry of the 99 TPC-DS queries written for DataFrame platforms.

**Import:** `from benchbox import TPCDS_DATAFRAME_QUERIES` · **Extras:** none

### Contents

- **Type:** `benchbox.core.dataframe.query.QueryRegistry`.
- **Entries:** 99 `DataFrameQuery` objects, with ids `Q1` to `Q99` as strings. The id list is sorted as text (`Q1`, `Q10`, `Q11`, ...).
- **Registry methods used here:**
  - `get_query_ids()` returns the list of ids.
  - `get(query_id)` returns the `DataFrameQuery`, or `None` for an unknown id.
  - `get_or_raise(query_id)` returns the query, or raises `KeyError` for an unknown id.
  - `get_all_queries()` returns every query.
- **Query attributes:** `query_id`, `query_name`, `description`, `categories`, and the methods `has_expression_impl()` and `has_pandas_impl()`. All 99 queries have both an expression and a pandas implementation.

### Example

```python
from benchbox import TPCDS_DATAFRAME_QUERIES

print(type(TPCDS_DATAFRAME_QUERIES).__name__)
print(len(TPCDS_DATAFRAME_QUERIES.get_query_ids()))
print(TPCDS_DATAFRAME_QUERIES.get_query_ids()[:5])
q = TPCDS_DATAFRAME_QUERIES.get("Q1")
print(q.query_id, q.query_name)
print(TPCDS_DATAFRAME_QUERIES.get("Q999"))
print(q.has_expression_impl(), q.has_pandas_impl())
```

Output on 0.4.1:

```text
QueryRegistry
99
['Q1', 'Q10', 'Q11', 'Q12', 'Q13']
Q1 Customer Returns Analysis
None
True True
```

## `benchbox.TPCH_DATAFRAME_QUERIES`

<span id="benchbox.TPCH_DATAFRAME_QUERIES"></span>

The TPC-H DataFrame query registry exported at the top level of `benchbox`.

**Import:** `from benchbox import TPCH_DATAFRAME_QUERIES` · **Extras:** none

### Known issue on 0.4.1

This name does not import in a fresh process on 0.4.1. The import fails with an `ImportError` caused by a circular import between `benchbox.core.tpch.dataframe_queries` and `benchbox.core.dataframe.benchmark_suite`. Its type, contents and behaviour are not documented here because they could not be run.

```python
from benchbox import TPCH_DATAFRAME_QUERIES
```

Output on 0.4.1 (last lines):

```text
  File ".../site-packages/benchbox/core/dataframe/benchmark_suite.py", line 62, in <module>
    from benchbox.core.tpch.dataframe_queries import get_tpch_dataframe_queries
ImportError: cannot import name 'get_tpch_dataframe_queries' from partially initialized module 'benchbox.core.tpch.dataframe_queries' (most likely due to a circular import) (.../site-packages/benchbox/core/tpch/dataframe_queries.py)
```

### Compatibility

The same name is listed under `benchbox.core.tpch.dataframe_queries.TPCH_DATAFRAME_QUERIES` below, which fails the same way.

## `benchbox.core.tpch.dataframe_queries.TPCH_DATAFRAME_QUERIES`

<span id="benchbox.core.tpch.dataframe_queries.TPCH_DATAFRAME_QUERIES"></span>

The TPC-H DataFrame query registry in its defining module.

**Import:** `from benchbox.core.tpch.dataframe_queries import TPCH_DATAFRAME_QUERIES` · **Extras:** none

### Known issue on 0.4.1

This name does not import in a fresh process on 0.4.1, because of the circular import described for `benchbox.TPCH_DATAFRAME_QUERIES`. Its type, contents and behaviour are not documented here because they could not be run.

```python
from benchbox.core.tpch.dataframe_queries import TPCH_DATAFRAME_QUERIES
```

Output on 0.4.1 (last lines):

```text
  File ".../site-packages/benchbox/core/dataframe/benchmark_suite.py", line 62, in <module>
    from benchbox.core.tpch.dataframe_queries import get_tpch_dataframe_queries
ImportError: cannot import name 'get_tpch_dataframe_queries' from partially initialized module 'benchbox.core.tpch.dataframe_queries' (most likely due to a circular import) (.../site-packages/benchbox/core/tpch/dataframe_queries.py)
```

## `benchbox.core.tpch.dataframe_queries.get_query`

<span id="benchbox.core.tpch.dataframe_queries.get_query"></span>

A function in the TPC-H DataFrame query module that returns a query.

**Import:** `from benchbox.core.tpch.dataframe_queries import get_query` · **Extras:** none

### Known issue on 0.4.1

This function does not import in a fresh process on 0.4.1, because of the same circular import. Its parameters, return value and exceptions are not documented here because they could not be run.

```python
from benchbox.core.tpch.dataframe_queries import get_query
```

Output on 0.4.1 (last lines):

```text
  File ".../site-packages/benchbox/core/dataframe/benchmark_suite.py", line 62, in <module>
    from benchbox.core.tpch.dataframe_queries import get_tpch_dataframe_queries
ImportError: cannot import name 'get_tpch_dataframe_queries' from partially initialized module 'benchbox.core.tpch.dataframe_queries' (most likely due to a circular import) (.../site-packages/benchbox/core/tpch/dataframe_queries.py)
```
