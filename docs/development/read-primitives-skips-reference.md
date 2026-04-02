# Read Primitives: Platform Skip Reference

```{tags} contributor, reference, platform-compatibility
```

This document is the authoritative reference for every `skip_on` entry in
`benchbox/core/read_primitives/catalog/queries.yaml`. For each skipped query it
explains **why** the skip exists and **where to look** to determine whether the
skip can be removed.

There are currently **26 skipped query/platform pairs** across 6 platforms.
They fall into three root-cause classes:

1. **Missing function**: the SQL function is simply absent from the platform's
   catalog and no semantics-preserving rewrite exists.
2. **Missing type**: the platform lacks a native data type (array, struct, map)
   required by the query.
3. **Data quality**: the TPC-H column used by the query (`o_comment`,
   `c_comment`) contains plain text, not the structured data the query expects.

---

## Quick-reference table

| Query ID | Skipped on | Root cause | Category |
|----------|-----------|------------|----------|
| `asof_join_basic` | bigquery, databricks, redshift | Missing syntax | timeseries |
| `array_agg_distinct` | redshift | Missing type | array |
| `array_agg_simple` | redshift | Missing type | array |
| `array_distinct` | bigquery, redshift | Missing function | array |
| `array_min_max` | bigquery | Missing function | array |
| `array_of_struct` | redshift | Missing type | struct |
| `array_slice` | redshift | Missing type | array |
| `array_sort` | bigquery, redshift | Missing function | array |
| `array_unnest` | redshift | Missing type | array |
| `json_aggregates` | datafusion, redshift | Missing function | json |
| `json_extract_nested` | datafusion, redshift | Missing function | json |
| `json_extract_simple` | duckdb, datafusion, redshift | Data quality | json |
| `list_filter` | bigquery, redshift | Missing function | lambda |
| `list_reduce` | bigquery, redshift | Missing function | lambda |
| `list_transform` | bigquery, redshift | Missing function | lambda |
| `map_access` | bigquery, redshift | Missing type | map |
| `map_construction` | bigquery, redshift | Missing type | map |
| `map_keys_values` | bigquery, redshift | Missing type | map |
| `pivot_basic` | clickhouse | Incompatible syntax | pivot |
| `statistical_correlation` | redshift | Missing function | statistical |
| `struct_access` | redshift | Missing type | struct |
| `struct_construction` | redshift | Missing type | struct |
| `timeseries_trend_analysis` | redshift | Missing function | timeseries |
| `unpivot_basic` | clickhouse | Incompatible syntax | pivot |
| `window_moving_frame` | redshift | Semantic gap | window |
| `window_running_sum` | redshift | Semantic gap | window |

---

## Amazon Redshift (23 queries skipped)

Redshift has the largest skip set because it predates many modern SQL extensions
and has diverged significantly from PostgreSQL in the area of complex types.

### Statistical functions: `statistical_correlation`, `timeseries_trend_analysis`

**Why skipped**: `CORR`, `COVAR_POP`, `COVAR_SAMP`, `REGR_SLOPE`,
`REGR_INTERCEPT`, and `REGR_R2` are all explicitly listed on AWS's
[Unsupported PostgreSQL functions](https://docs.aws.amazon.com/redshift/latest/dg/c_unsupported-postgresql-functions.html)
page. The functions do not exist in Redshift's catalog in any form, neither as
aggregate functions nor as window functions. Casting arguments to `FLOAT8` does
not help; the 42883 error (`undefined_function`) fires because there is no
overload registered for any type combination. AWS's own
[amazon-redshift-utils](https://github.com/awslabs/amazon-redshift-utils/blob/master/src/StoredProcedures/sp_correlation.sql)
repo implements `sp_correlation` as a stored procedure using manual arithmetic,
confirming native support is absent.

**Re-enable when**:
- `CORR` and `REGR_SLOPE` disappear from the unsupported-functions list, **and**
- Both appear on the [Aggregate Functions](https://docs.aws.amazon.com/redshift/latest/dg/c_Aggregate_Functions.html) page.

**Check**: `https://docs.aws.amazon.com/redshift/latest/dg/c_unsupported-postgresql-functions.html`

---

### Window frame semantics: `window_moving_frame`, `window_running_sum`

**Why skipped**: Both queries depend on default window-frame semantics that
Redshift cannot reproduce:

- `window_moving_frame` uses `RANGE BETWEEN INTERVAL '30' DAY PRECEDING AND
  CURRENT ROW`. Redshift does not support date/interval-valued offsets in RANGE
  frames; the only available rewrite (`ROWS BETWEEN 30 PRECEDING`) changes
  semantics on sparse or duplicate dates.
- `window_running_sum` uses `SUM(o_totalprice) OVER (ORDER BY o_orderdate)`
  without an explicit frame clause. Standard SQL defaults this to `RANGE
  BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW`, which includes peer rows
  (rows with the same `o_orderdate`). Redshift interprets this as `ROWS
  BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW`, silently producing different
  results when multiple rows share a date. A rewrite with an explicit ROWS
  frame would be syntactically valid but semantically wrong for this test.

**Re-enable when**: Redshift release notes confirm support for
`RANGE BETWEEN <interval> PRECEDING` frames with date/timestamp columns. The
Redshift documentation page to watch is
[Window function syntax summary](https://docs.aws.amazon.com/redshift/latest/dg/r_Window_function_synopsis.html),
specifically the `frame_clause` section describing `RANGE` offset types.

---

### Array operations: 8 queries

`array_agg_simple`, `array_agg_distinct`, `array_unnest`, `array_slice`,
`array_sort`, `array_distinct`, `array_of_struct`

**Why skipped**: Redshift does not have a native array type. `ARRAY_AGG`,
`UNNEST`, `ARRAY_SLICE`, `ARRAY_SORT`, and `ARRAY_DISTINCT` all require an
array column as input or produce one as output. There is no semantics-preserving
rewrite that avoids materialising an array.

Note: `array_min_max` is **not** skipped on Redshift; it has a Redshift variant
that rewrites the query as a plain `MIN`/`MAX` aggregate, which is semantically
equivalent for that specific test. The variant was viable because the query's
intent is to find the extremes of a value set, not to manipulate an array object.

**Re-enable when**: AWS adds native array type support to Redshift. Monitor:
- [What's new in Amazon Redshift](https://aws.amazon.com/about-aws/whats-new/database/?whats-new-content.sort-by=item.additionalFields.postDateTime&whats-new-content.sort-order=desc&awsf.whats-new-product=product%23amazon-redshift)
- [Redshift SQL commands reference](https://docs.aws.amazon.com/redshift/latest/dg/r_ARRAY.html)
  (currently 404; if this URL resolves, native arrays have shipped)

---

### Struct operations: `struct_construction`, `struct_access`

**Why skipped**: Redshift has no `STRUCT(...)` constructor and does not support
accessing struct fields via dot notation. The base queries and the `array_of_struct`
query all depend on inline struct construction.

**Re-enable when**: `STRUCT(...)` syntax appears in the
[Redshift SQL reference](https://docs.aws.amazon.com/redshift/latest/dg/r_CREATE_TABLE_NEW.html).

---

### Map operations: `map_construction`, `map_access`, `map_keys_values`

**Why skipped**: Redshift has no native MAP type. `MAP_FROM_ENTRIES`,
`MAP_KEYS`, `MAP_VALUES`, and subscript access (`map['key']`) are all
unavailable. There is no equivalent rewrite that preserves the map-as-value
semantics these queries test.

**Re-enable when**: A native MAP or HSTORE type appears in Redshift's type
catalog and `MAP_FROM_ENTRIES` is listed in the SQL function reference.

---

### Higher-order (lambda) functions: `list_transform`, `list_filter`, `list_reduce`

**Why skipped**: Redshift does not support `TRANSFORM(arr, x -> ...)`,
`FILTER(arr, x -> ...)`, or `REDUCE(arr, init, (acc, x) -> ...)`. These are
higher-order array functions that require both a native array type and lambda
syntax, neither of which Redshift supports.

**Re-enable when**: Lambda expressions appear in the Redshift SQL reference.
This is a superset of array support, so array support is a prerequisite.

---

### JSON functions: `json_extract_simple`, `json_extract_nested`, `json_aggregates`

**Why skipped**: Two independent reasons apply:

1. **Data quality** (applies to all three, including the DuckDB skip): TPC-H
   `o_comment` and `c_comment` columns contain free-form text, not valid JSON.
   `JSON_EXTRACT` on plain text returns NULL or raises an error depending on the
   platform. This skip is permanent for `json_extract_simple` regardless of
   platform JSON function support.

2. **Missing functions**: Redshift lacks `JSON_ARRAYAGG` and `JSON_OBJECTAGG`
   entirely (`json_aggregates`). Redshift's `JSON_EXTRACT_PATH_TEXT` function
   has a different signature from standard `JSON_EXTRACT` and cannot be used as
   a drop-in replacement for complex path expressions (`json_extract_nested`).

**Re-enable `json_aggregates`/`json_extract_nested` when**: `JSON_ARRAYAGG` and
`JSON_OBJECTAGG` appear in the
[Redshift JSON functions reference](https://docs.aws.amazon.com/redshift/latest/dg/json-functions.html).

**`json_extract_simple` cannot be re-enabled** on any platform without replacing
the TPC-H `o_comment` column with actual JSON data. The skip reflects a data
constraint, not a platform constraint.

---

### ASOF JOIN: `asof_join_basic`

**Why skipped**: Redshift does not support `ASOF JOIN` syntax. No rewrite of
an ASOF JOIN as a correlated subquery or lateral join produces identical
semantics efficiently enough to be meaningful as a benchmark primitive.

**Re-enable when**: `ASOF JOIN` appears in the
[Redshift JOIN syntax reference](https://docs.aws.amazon.com/redshift/latest/dg/r_FROM_clause30.html).

---

## Google BigQuery (10 queries skipped)

### Array functions: `array_min_max`, `array_sort`, `array_distinct`

**Why skipped**: BigQuery does not have `ARRAY_MIN`, `ARRAY_MAX`, `ARRAY_SORT`,
or `ARRAY_DISTINCT` as scalar array functions. BigQuery's array manipulation
model relies on `UNNEST` + re-aggregation, which changes query structure rather
than being a drop-in dialect fix.

**Re-enable when**: These functions appear in the
[BigQuery Standard SQL array functions reference](https://cloud.google.com/bigquery/docs/reference/standard-sql/array_functions).

---

### Map operations: `map_construction`, `map_access`, `map_keys_values`

**Why skipped**: BigQuery has no native MAP type. It uses `ARRAY<STRUCT<key,
value>>` patterns instead. The queries test map-as-first-class-value semantics
(`MAP_FROM_ENTRIES`, subscript access, `MAP_KEYS`/`MAP_VALUES`) which BigQuery
cannot express equivalently.

**Re-enable when**: A native MAP type or `MAP_FROM_ENTRIES` function appears
in the [BigQuery data types reference](https://cloud.google.com/bigquery/docs/reference/standard-sql/data-types).

---

### Higher-order (lambda) functions: `list_transform`, `list_filter`, `list_reduce`

**Why skipped**: BigQuery does not support `TRANSFORM(arr, x -> ...)`,
`FILTER(arr, x -> ...)`, or `REDUCE(arr, init, (acc, x) -> ...)`.

**Re-enable when**: Lambda/higher-order array functions appear in the
[BigQuery array functions reference](https://cloud.google.com/bigquery/docs/reference/standard-sql/array_functions).

---

### ASOF JOIN: `asof_join_basic`

**Why skipped**: BigQuery does not support `ASOF JOIN` syntax.

**Re-enable when**: `ASOF JOIN` appears in the
[BigQuery JOIN reference](https://cloud.google.com/bigquery/docs/reference/standard-sql/query-syntax#join_types).

---

## Apache DataFusion (3 queries skipped)

### JSON functions: `json_extract_simple`, `json_extract_nested`, `json_aggregates`

**Why skipped**:

- `json_extract_simple`: Data quality (TPC-H `o_comment` is not JSON). Permanent.
- `json_extract_nested`: DataFusion's `JSON_EXTRACT` does not support complex
  path expressions with array index notation (`$.preferences[0]`, `$.history.last_order.date`).
- `json_aggregates`: DataFusion lacks `JSON_ARRAYAGG` and `JSON_OBJECTAGG`
  aggregate functions.

**Re-enable `json_extract_nested` when**: DataFusion's `json_get` / `JSON_EXTRACT`
gains support for nested array-index paths. Track:
[datafusion/issues](https://github.com/apache/datafusion/issues), search
`json_extract array index`.

**Re-enable `json_aggregates` when**: `JSON_ARRAYAGG` and `JSON_OBJECTAGG` appear
in [DataFusion's function catalog](https://datafusion.apache.org/user-guide/sql/aggregate_functions.html).

**`json_extract_simple` cannot be re-enabled** (data quality constraint, see above).

---

## DuckDB (1 query skipped)

### `json_extract_simple`

**Why skipped**: Data quality only. TPC-H `o_comment` contains plain text.
`JSON_EXTRACT('not json', '$.priority')` returns NULL in DuckDB rather than
raising an error, but the query produces no meaningful rows, not a useful
benchmark primitive.

**Re-enable**: Cannot be re-enabled without replacing TPC-H `o_comment` data
with valid JSON. DuckDB fully supports `JSON_EXTRACT` and complex paths.

---

## ClickHouse (2 queries skipped)

### `pivot_basic`, `unpivot_basic`

**Why skipped**: ClickHouse does not implement standard SQL `PIVOT`/`UNPIVOT`
clause syntax. ClickHouse provides `ARRAY JOIN` and conditional aggregation
(`sumIf`, etc.) as alternatives, but these require a fundamentally different
query structure that tests different capabilities than `PIVOT`/`UNPIVOT`.

**Re-enable when**: Standard `PIVOT`/`UNPIVOT` clause syntax appears in the
[ClickHouse SELECT reference](https://clickhouse.com/docs/en/sql-reference/statements/select).

---

## Databricks (1 query skipped)

### `asof_join_basic`

**Why skipped**: Databricks SQL does not support `ASOF JOIN` syntax as of the
time this skip was added. Spark's `MERGE ASOF` exists in PySpark but is not
available as a SQL clause.

**Re-enable when**: `ASOF JOIN` appears in the
[Databricks SQL reference](https://docs.databricks.com/sql/language-manual/sql-ref-syntax-qry-select-join.html).

---

## Validation workflow

Three assets work together to validate whether a skip is still needed and
whether removing it is safe. Understanding how they relate prevents both
false confidence (unit test passes but live run fails) and unnecessary work
(live run attempted before the catalog change is consistent).

```
Reference doc          queries.yaml          Unit test             Live run
─────────────          ────────────          ─────────             ────────
Check URL         →    Remove skip_on    →   pytest passes    →    benchbox run passes
condition met           (+ variant if         skip set matches      query returns rows,
                         needed)              catalog reality       no SQL errors
```

**Reference doc** (`docs/development/read-primitives-skips-reference.md`, this
file) is the starting point. Each skip has an authoritative URL and a concrete
condition. Check the URL first; do not attempt to remove a skip speculatively.

**Unit test** (`tests/unit/core/read_primitives/test_benchmark_variants.py`)
is the fast inner check. It asserts the exact expected skip set for each
platform without requiring a live database connection. Run it after every
change to `queries.yaml`:

```bash
uv run -- python -m pytest tests/unit/core/read_primitives/test_benchmark_variants.py -q
```

A passing unit test means the catalog and the test expectations are internally
consistent. It does **not** mean the SQL executes correctly on the platform.

**Live benchmark run** is the ground-truth check. Run it after the unit test
passes:

```bash
benchbox run --platform <platform> --benchmark read_primitives --queries <query_id> --scale 0.01
```

A passing live run (non-empty result set, no SQL errors) is the definitive
confirmation that the skip can be removed.

If the live run fails after the unit test passes, the skip goes back in.
Update both `queries.yaml` and this reference doc with what was tried and why
it still fails, so the next maintainer has a complete picture.

---

## How to re-enable a skip

1. Verify the platform now supports the feature using the authoritative URL
   listed for that skip above.

2. Remove the platform from the `skip_on` list in `queries.yaml`. If the
   platform was the *only* entry in `skip_on`, remove the `skip_on` field
   entirely.

3. If the base SQL works unchanged, no variant is needed. If the platform
   requires different syntax, add a `variants:` entry (see
   {doc}`read-primitives-catalog` for format).

4. Run the unit test to confirm the skip set is consistent:

   ```bash
   uv run -- python -m pytest tests/unit/core/read_primitives/test_benchmark_variants.py -q
   ```

5. Run the live benchmark against the platform:

   ```bash
   benchbox run --platform <platform> --benchmark read_primitives --queries <query_id> --scale 0.01
   ```

6. Confirm the query passes and produces a non-empty result set.

7. Update the regression test in
   `tests/unit/core/read_primitives/test_benchmark_variants.py` to reflect
   the new expected skip set (or remove the assertion if the platform no
   longer skips that query).

8. Commit with a `fix(read_primitives):` prefix and reference the platform's
   release notes or documentation URL as evidence.
