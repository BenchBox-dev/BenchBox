# Read Primitives: Platform Skip Reference

```{tags} contributor, reference, platform-compatibility
```

This document is the authoritative reference for every `skip_on` entry in
`benchbox/core/read_primitives/catalog/queries.yaml`. For each skipped query it
explains **why** the skip exists and **where to look** to determine whether the
skip can be removed.

As of 2026-04-29, there are **77 skipped query/target-dialect pairs** across 7
target dialects. Deployment aliases inherit their adapter target dialects: for
example, MotherDuck uses the DuckDB dialect skips, while ClickHouse local,
server, and cloud deployments use the ClickHouse dialect skips.
They fall into four root-cause classes:

1. **Missing function**: the SQL function is simply absent from the platform's
   catalog and no semantics-preserving rewrite exists.
2. **Missing type**: the platform lacks a native data type (array, struct, map)
   required by the query.
3. **Data quality**: the TPC-H column used by the query (`o_comment`,
   `c_comment`) contains plain text, not the structured data the query expects.
4. **Semantic gap**: a runnable fallback exists, but it would measure a related
   capability rather than the query's declared `result_contract.capability`.

---

## Quick-reference table

| Query ID | Skipped on | Root cause | Category |
|----------|-----------|------------|----------|
| `any_value_simple` | datafusion | Semantic gap | aggregation |
| `any_value_with_filter` | datafusion | Semantic gap | aggregation |
| `asof_join_basic` | bigquery, datafusion, databricks, redshift | Missing syntax | timeseries |
| `array_agg_distinct` | redshift | Missing type | array |
| `array_agg_simple` | redshift | Missing type | array |
| `array_contains` | datafusion, redshift | Semantic gap / missing type | array |
| `array_distinct` | bigquery, datafusion, redshift | Missing function / semantic gap | array |
| `array_length` | datafusion, redshift | Semantic gap / missing type | array |
| `array_min_max` | bigquery, datafusion, redshift | Missing function / semantic gap | array |
| `array_of_struct` | redshift | Missing type | struct |
| `array_slice` | redshift | Missing type | array |
| `array_sort` | bigquery, redshift | Missing function | array |
| `array_unnest` | redshift | Missing type | array |
| `fulltext_boolean_search` | bigquery, clickhouse, datafusion, databricks, duckdb, redshift, snowflake | Semantic gap | fulltext |
| `fulltext_phrase_search` | bigquery, clickhouse, datafusion, databricks, duckdb, redshift, snowflake | Semantic gap | fulltext |
| `fulltext_simple_search` | bigquery, clickhouse, datafusion, databricks, duckdb, redshift, snowflake | Semantic gap | fulltext |
| `intrinsic_appx_median` | clickhouse | Semantic gap | intrinsic |
| `json_aggregates` | datafusion, redshift | Missing function | json |
| `json_extract_nested` | datafusion, redshift | Missing function | json |
| `json_extract_simple` | duckdb, datafusion, redshift | Data quality | json |
| `list_filter` | bigquery, datafusion, redshift | Missing function / semantic gap | lambda |
| `list_reduce` | bigquery, datafusion, redshift | Missing function / semantic gap | lambda |
| `list_transform` | bigquery, datafusion, redshift | Missing function / semantic gap | lambda |
| `map_access` | bigquery, redshift | Missing type | map |
| `map_construction` | bigquery, redshift | Missing type | map |
| `map_keys_values` | bigquery, redshift | Missing type | map |
| `pivot_basic` | clickhouse | Incompatible syntax | pivot |
| `statistical_correlation` | redshift | Missing function | statistical |
| `statistical_percentiles` | clickhouse | Semantic gap | statistical |
| `struct_access` | redshift | Missing type | struct |
| `struct_construction` | redshift | Missing type | struct |
| `timeseries_trend_analysis` | redshift | Missing function | timeseries |
| `unpivot_basic` | clickhouse | Incompatible syntax | pivot |
| `window_moving_frame` | clickhouse, redshift | Semantic gap | window |
| `window_running_sum` | redshift | Semantic gap | window |

---

## Amazon Redshift (29 queries skipped)

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

### Array operations: 9 queries

`array_agg_simple`, `array_agg_distinct`, `array_unnest`, `array_contains`,
`array_length`, `array_slice`, `array_min_max`, `array_sort`, `array_distinct`

**Why skipped**: Redshift does not have a native array type. `ARRAY_AGG`,
`ARRAY_CONTAINS`, `CARDINALITY`, `UNNEST`, `ARRAY_SLICE`, `ARRAY_MIN`,
`ARRAY_MAX`, `ARRAY_SORT`, and `ARRAY_DISTINCT` all require an array column as
input or produce one as output. Redshift scalar rewrites such as `COUNT(*)`,
`MIN`/`MAX`, or `CASE WHEN` can produce the same values for the current data,
but they do not test the array capability declared in the query contract.

**Re-enable when**: AWS adds native array type support to Redshift. Monitor:
- [What's new in Amazon Redshift](https://aws.amazon.com/about-aws/whats-new/database/?whats-new-content.sort-by=item.additionalFields.postDateTime&whats-new-content.sort-order=desc&awsf.whats-new-product=product%23amazon-redshift)
- [Redshift SQL commands reference](https://docs.aws.amazon.com/redshift/latest/dg/r_ARRAY.html)
  (currently 404; if this URL resolves, native arrays have shipped)

---

### Struct operations: `struct_construction`, `struct_access`, `array_of_struct`

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

### Full-text search: `fulltext_simple_search`, `fulltext_boolean_search`, `fulltext_phrase_search`

**Why skipped**: Redshift can express coarse `LIKE` filters, but those do not
preserve MySQL full-text tokenization, boolean operators, phrase matching, or
relevance scores. Keeping the old `LIKE` variants would make Redshift look
comparable while measuring a different capability.

**Re-enable when**: Redshift exposes comparable full-text search syntax and the
variant passes contract validation plus a live Redshift run for the declared
result contract.

---

### ASOF JOIN: `asof_join_basic`

**Why skipped**: Redshift does not support `ASOF JOIN` syntax. No rewrite of
an ASOF JOIN as a correlated subquery or lateral join produces identical
semantics efficiently enough to be meaningful as a benchmark primitive.

**Re-enable when**: `ASOF JOIN` appears in the
[Redshift JOIN syntax reference](https://docs.aws.amazon.com/redshift/latest/dg/r_FROM_clause30.html).

---

## Google BigQuery (13 queries skipped)

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

### Full-text search: `fulltext_simple_search`, `fulltext_boolean_search`, `fulltext_phrase_search`

**Why skipped**: The base SQL uses MySQL `MATCH(...) AGAINST (...)`. BigQuery
has `SEARCH` and text analyzers, but the syntax and scoring behavior are not a
drop-in equivalent for MySQL natural-language, boolean, and phrase modes.

**Re-enable when**: A BigQuery variant is written that preserves tokenization,
boolean operators, phrase matching, and relevance-score semantics for the
declared full-text capability.

---

## Apache DataFusion (16 queries skipped)

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

### Full-text search: `fulltext_simple_search`, `fulltext_boolean_search`, `fulltext_phrase_search`

**Why skipped**: DataFusion does not implement MySQL-style
`MATCH(...) AGAINST (...)` full-text search. A `LIKE` rewrite runs, but it does
not preserve ranking, boolean search operators, phrase matching, tokenization,
or indexing behavior, so it would violate the full-text result contract.

**Re-enable when**: DataFusion exposes full-text search syntax with comparable
boolean and phrase semantics.

---

### Array and lambda semantic gaps

`array_contains`, `array_length`, `array_min_max`, `array_distinct`,
`list_transform`, `list_filter`, `list_reduce`

**Why skipped**: DataFusion can express some value-equivalent rewrites using
plain aggregates, `UNNEST`, or re-aggregation. Those rewrites do not exercise
the same nested-array or higher-order lambda capability as the base query. The
catalog keeps DataFusion's MAP variants because they use DataFusion MAP
functions and pass the DuckDB-reference runtime parity test.

**Re-enable when**: DataFusion supports the corresponding array and
higher-order functions directly, or a variant can be written that exercises the
same declared capability and passes
`tests/integration/validation/test_read_primitives_variant_parity.py`.

---

### Arbitrary-value aggregate: `any_value_simple`, `any_value_with_filter`

**Why skipped**: Rewriting `ANY_VALUE` to `MIN` makes the query deterministic
but changes the capability from arbitrary representative aggregate to ordered
minimum aggregate.

**Re-enable when**: DataFusion supports `ANY_VALUE` or an equivalent arbitrary
aggregate.

---

### ASOF JOIN: `asof_join_basic`

**Why skipped**: The prior DataFusion variant used Snowflake-style
`MATCH_CONDITION`, which is not a portable DataFusion syntax and could not be
statically parsed for contract validation. No verified DataFusion SQL variant is
currently retained.

**Re-enable when**: DataFusion documents a SQL `ASOF JOIN` form that can express
the query exactly and passes the DuckDB-reference parity test.

---

## DuckDB (4 queries skipped)

### `json_extract_simple`

**Why skipped**: Data quality only. TPC-H `o_comment` contains plain text.
`JSON_EXTRACT('not json', '$.priority')` returns NULL in DuckDB rather than
raising an error, but the query produces no meaningful rows, not a useful
benchmark primitive.

**Re-enable**: Cannot be re-enabled without replacing TPC-H `o_comment` data
with valid JSON. DuckDB fully supports `JSON_EXTRACT` and complex paths.

---

### Full-text search: `fulltext_simple_search`, `fulltext_boolean_search`, `fulltext_phrase_search`

**Why skipped**: DuckDB does not implement MySQL-style
`MATCH(...) AGAINST (...)` full-text semantics. `LIKE` rewrites were removed
because they produce a different shape for scored queries and a different
matching capability for every full-text query.

**Re-enable when**: DuckDB exposes comparable full-text search syntax, including
score/rank output for boolean and phrase queries.

---

## ClickHouse (8 queries skipped)

### `pivot_basic`, `unpivot_basic`

**Why skipped**: ClickHouse does not implement standard SQL `PIVOT`/`UNPIVOT`
clause syntax. ClickHouse provides `ARRAY JOIN` and conditional aggregation
(`sumIf`, etc.) as alternatives, but these require a fundamentally different
query structure that tests different capabilities than `PIVOT`/`UNPIVOT`.

**Re-enable when**: Standard `PIVOT`/`UNPIVOT` clause syntax appears in the
[ClickHouse SELECT reference](https://clickhouse.com/docs/en/sql-reference/statements/select).

---

### Full-text search: `fulltext_simple_search`, `fulltext_boolean_search`, `fulltext_phrase_search`

**Why skipped**: ClickHouse string predicates can approximate parts of the
filtering behavior, but they do not preserve MySQL full-text tokenization,
boolean operators, phrase matching, or relevance scores.

**Re-enable when**: ClickHouse exposes comparable full-text search semantics for
these three query families.

---

### Percentile semantics: `intrinsic_appx_median`, `statistical_percentiles`

**Why skipped**: ClickHouse `quantile` functions are approximate by default.
The base queries declare exact continuous percentile/median capabilities.
Running approximate percentiles against exact percentile queries would produce a
misleading benchmark signal even when the query executes successfully.

**Re-enable when**: A ClickHouse variant uses exact percentile functions with
matching interpolation semantics and passes the runtime parity test.

---

### Window frame semantics: `window_moving_frame`

**Why skipped**: The old ClickHouse variant replaced a date `RANGE` frame with a
row-count `ROWS` frame. That changes results whenever order dates are sparse or
duplicate.

**Re-enable when**: ClickHouse supports the original interval-valued `RANGE`
frame, or a variant preserves the exact frame semantics.

---

## Databricks (4 queries skipped)

### `asof_join_basic`

**Why skipped**: Databricks SQL does not support `ASOF JOIN` syntax as of the
time this skip was added. Spark's `MERGE ASOF` exists in PySpark but is not
available as a SQL clause.

**Re-enable when**: `ASOF JOIN` appears in the
[Databricks SQL reference](https://docs.databricks.com/sql/language-manual/sql-ref-syntax-qry-select-join.html).

---

### Full-text search: `fulltext_simple_search`, `fulltext_boolean_search`, `fulltext_phrase_search`

**Why skipped**: The base SQL uses MySQL `MATCH(...) AGAINST (...)`, which
Databricks SQL does not support. `LIKE`, `contains`, or Spark text functions do
not preserve MySQL full-text ranking, boolean operators, phrase matching, or
index-backed search semantics.

**Re-enable when**: Databricks SQL exposes comparable full-text search syntax or
a verified variant can preserve the declared full-text result contract.

---

## Snowflake (3 queries skipped)

### Full-text search: `fulltext_simple_search`, `fulltext_boolean_search`, `fulltext_phrase_search`

**Why skipped**: The base SQL uses MySQL `MATCH(...) AGAINST (...)`. Snowflake
has text search functions, but they do not provide a direct equivalent for the
MySQL natural-language, boolean, and phrase modes used by these primitives.

**Re-enable when**: A Snowflake variant preserves the declared full-text
capability, including boolean operators, phrase semantics, and relevance-score
shape for scored queries.

---

## Validation workflow

Five assets work together to validate whether a skip is still needed and
whether removing it is safe. Understanding how they relate prevents both
false confidence (unit test passes but live run fails) and unnecessary work
(live run attempted before the catalog change is consistent).

```
Reference doc      queries.yaml      Static/unit tests      Runtime parity      Platform run
─────────────      ────────────      ────────────────       ──────────────      ────────────
Check URL     →    Remove skip  →    contracts pass    →    DuckDB ref    →    benchbox run
condition met       (+ variant)       skip set matches       matches local      passes
                                      catalog reality        variant
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
uv run -- python -m pytest tests/unit/core/read_primitives/test_read_primitives_variant_contracts.py -q
```

A passing unit test means the catalog and the test expectations are internally
consistent and every active variant has a declared comparable shape.
It does **not** mean the SQL executes correctly on the platform.

**Runtime parity test**
(`tests/integration/validation/test_read_primitives_variant_parity.py`) is the
credential-free check for local engines. It runs DuckDB SF=0.01 as the
reference, then compares retained DataFusion and ClickHouse-local variants under
the declared result contracts:

```bash
uv run -- python -m pytest tests/integration/validation/test_read_primitives_variant_parity.py -q
```

Optional engines may skip when their packages are unavailable. If an installed
engine diverges, keep or restore `skip_on` until the variant is truly comparable.

**Live benchmark run** is the ground-truth check. Run it after the unit test
and runtime parity test pass:

```bash
uv run -- benchbox run --platform <platform> --benchmark read_primitives --queries <query_id> --scale 0.01
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
   uv run -- python -m pytest tests/unit/core/read_primitives/test_read_primitives_variant_contracts.py -q
   uv run -- python -m pytest tests/integration/validation/test_read_primitives_variant_parity.py -q
   ```

5. Run the live benchmark against the platform:

   ```bash
   uv run -- benchbox run --platform <platform> --benchmark read_primitives --queries <query_id> --scale 0.01
   ```

6. Confirm the query passes and produces a non-empty result set.

7. Update the regression test in
   `tests/unit/core/read_primitives/test_benchmark_variants.py` to reflect
   the new expected skip set (or remove the assertion if the platform no
   longer skips that query).

8. Commit with a `fix(read_primitives):` prefix and reference the platform's
   release notes or documentation URL as evidence.
