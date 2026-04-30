# Primitives Query Catalog

```{tags} contributor, reference, custom-benchmark
```

The Read Primitives benchmark queries now live outside Python source in
`benchbox/core/read_primitives/catalog/queries.yaml`. This keeps the runtime module
small and makes it easier to audit or extend the workload.

## File layout

```yaml
version: 1
queries:
  - id: aggregation_distinct
    category: aggregation
    sql: |-
      -- Distinct count of high cardinality key on a large table
      SELECT ...
```

* `id` - unique identifier referenced by benchmarks and tests.
* `category` - lower-case grouping used for `get_queries_by_category`; omit to
default to the `id` prefix.
* `sql` - literal SQL string (keep the leading newline so comparisons remain
  stable).
* `description` (optional) - free-form text for future tooling.
* `variants` (optional) - dict mapping dialect names to platform-specific SQL.
* `skip_on` (optional) - list of dialects where this query should be skipped.
* `result_contract` (required for every active variant query) - machine-readable
  result shape and measured capability metadata.

## Platform-Specific Variants

Some queries require dialect-specific SQL due to incompatible syntax or missing features. The catalog supports two approaches:

### Query Variants

Define alternative SQL for specific platforms using the `variants` field:

```yaml
- id: json_aggregates
  category: json
  sql: |-
    -- Standard SQL version (MySQL syntax)
    SELECT
        p_brand,
        JSON_ARRAYAGG(p_name) as part_names,
        JSON_OBJECTAGG(p_partkey, p_retailprice) as part_prices,
        COUNT(*) as part_count
    FROM part
    GROUP BY p_brand
    ORDER BY p_brand
    LIMIT 100
  result_contract:
    capability: json_array_object_aggregation
    row_identity: [p_brand]
    columns:
      - p_brand
      - name: part_names
        type_class: json
      - name: part_prices
        type_class: json
      - part_count
  variants:
    duckdb: |-
      -- DuckDB uses different function names
      SELECT
          p_brand,
          JSON_GROUP_ARRAY(p_name) as part_names,
          JSON_GROUP_OBJECT(p_partkey, p_retailprice) as part_prices,
          COUNT(*) as part_count
      FROM part
      GROUP BY p_brand
      ORDER BY p_brand
      LIMIT 100
```

**When to use variants:**
- Platform uses different function names (e.g., `JSON_ARRAYAGG` vs `JSON_GROUP_ARRAY`)
- Platform requires different syntax for the same functionality
- Query needs structural changes but tests same capability (e.g., CTE to avoid nested aggregates)
- Output columns, row identity, nested shape, and measured capability remain comparable

**How it works:**
1. When `get_query(query_id, dialect="duckdb")` is called, the query manager returns the DuckDB variant if it exists
2. If no variant exists for the requested dialect, returns the base `sql` query
3. Variant SQL is authored as final target SQL; `ReadPrimitivesBenchmark.get_queries()` does not rerun it through SQLGlot

### Result Contracts

Every active platform variant must declare `result_contract`. This includes
syntax-only rewrites and scalar variants, not only high-risk nested families.
Contracts are intentionally required everywhere so future variants cannot bypass
the static comparability lint by falling outside a category allowlist.

```yaml
result_contract:
  capability: ordered_array_slice
  row_identity: [o_custkey]
  columns:
    - o_custkey
    - name: top_3_orders
      type_class: array
      order_sensitive: true
```

Contract fields:

* `capability` - the database capability the query measures. Variants that
  produce the same values by testing a different capability should be skipped.
* `row_identity` - result columns that identify a row for cross-platform
  alignment. If the query has `LIMIT`, order deterministically by this identity.
* `columns` - projected columns in exact output order. Use mappings when a
  nested type or order sensitivity matters.
* `type_class` - one of `scalar`, `json`, `array`, `struct`, or `map`.
* `order_sensitive` - set `true` when array/list order is part of the result
  semantics.

### Skipping Queries

Some queries cannot be meaningfully tested on certain platforms due to data limitations or fundamental incompatibilities. Use `skip_on` to explicitly skip:

```yaml
- id: json_extract_simple
  category: json
  sql: |-
    SELECT
        o_orderkey,
        JSON_EXTRACT(o_comment, '$.priority') as order_priority
    FROM orders
    WHERE JSON_EXTRACT(o_comment, '$.priority') IS NOT NULL
  skip_on: [duckdb]
  description: "TPC-H o_comment contains plain text, not valid JSON"
```

**When to use skip_on:**
- Data quality issues make query meaningless (e.g., JSON functions on non-JSON data)
- Platform fundamentally lacks required feature and no reasonable alternative exists
- Query would always fail due to platform limitations, not bugs
- Platform can only express a related-but-not-equivalent fallback, such as
  full-text search rewritten as `LIKE`, approximate percentile substituted for
  exact percentile, or array capability rewritten as a scalar aggregate

For a complete reference of all current skips, their root causes, and instructions on how to re-enable them, see {doc}`read-primitives-skips-reference`.

**How it works:**
1. When `get_queries(dialect="duckdb")` is called, queries with `skip_on: [duckdb]` are excluded
2. `get_query(query_id, dialect="duckdb")` raises `ValueError` if query is in skip_on list
3. Benchmark treats this as expected behavior, not a failure

### Best Practices

**Prefer variants over skip_on:**
- Only skip when no comparable alternative exists
- Most syntax differences can be handled with variants, but capability changes cannot

**Keep variants semantically equivalent:**
- Variants should test the same database capability
- Results must have comparable columns, nested shape, row identity, and ordering
- Document why variant is needed in comments
- Do not keep runnable but non-comparable fallbacks in benchmark scoring

**Dialect names:**
- Use lowercase: `duckdb`, `bigquery`, `snowflake`, `postgres`
- Must match `dialect` parameter passed to `get_queries()`
- Case-insensitive matching during query retrieval

**Validation:**
- Run static contracts: `uv run -- python -m pytest tests/unit/core/read_primitives/test_read_primitives_variant_contracts.py -q`
- Run focused runtime parity: `uv run -- python -m pytest tests/integration/validation/test_read_primitives_variant_parity.py -q`
- Run the platform query at SF=0.01 before removing a skip

### Example: Complex Variant (timeseries_trend_analysis)

```yaml
- id: timeseries_trend_analysis
  category: timeseries
  sql: |-
    -- Standard SQL with nested aggregate in REGR_SLOPE
    SELECT
        DATE_TRUNC('month', o_orderdate) as order_month,
        COUNT(*) as order_count,
        REGR_SLOPE(SUM(o_totalprice), EXTRACT(EPOCH FROM o_orderdate)) as trend
    FROM orders
    GROUP BY DATE_TRUNC('month', o_orderdate)
  variants:
    duckdb: |-
      -- DuckDB doesn't allow nested aggregates, use CTE + window function
      WITH monthly_totals AS (
        SELECT
          DATE_TRUNC('month', o_orderdate) as order_month,
          COUNT(*) as order_count,
          SUM(o_totalprice) as monthly_revenue,
          EXTRACT(EPOCH FROM DATE_TRUNC('month', o_orderdate)) as month_epoch
        FROM orders
        GROUP BY DATE_TRUNC('month', o_orderdate)
      )
      SELECT
        order_month,
        order_count,
        monthly_revenue,
        REGR_SLOPE(monthly_revenue, month_epoch) OVER () as trend
      FROM monthly_totals
      ORDER BY order_month
```

This example shows:
- Structural changes (base query → CTE with window function)
- Same capability tested (linear regression on time series data)
- Clear comment explaining why variant is needed

## Editing workflow

1. Update `queries.yaml`, keeping entries ordered and grouped by category. The
   file is packaged with the library, so every change must live under source
   control.
2. Validate the catalog locally:

   ```bash
   uv run -- python - <<'PY'
   from benchbox.core.read_primitives.queries import ReadPrimitivesQueryManager

   manager = ReadPrimitivesQueryManager()
   print(f"queries: {len(manager.get_all_queries())}")
   print(f"categories: {manager.get_query_categories()}")
   PY

   uv run -- python -m pytest tests/unit/core/read_primitives/test_catalog_loader.py
   uv run -- python -m pytest tests/unit/core/read_primitives/test_read_primitives_variant_contracts.py
   ```

   The test suite exercises catalog parsing, duplicate detection, and category
   filters. The contract suite also rejects any active variant without comparable
   result-shape metadata.
3. Run the full test suite (`uv run -- python -m pytest`) before committing.

## Adding many queries

When bulk-loading SQL from external sources, prefer authoring a small helper
script under `_project/` that outputs the YAML structure (see existing history
for examples). Temporary tooling should stay in `_project/` and be removed or
ignored once the catalog has been updated.

## Attribution and Lineage

### Query Sources

The Read Primitives catalog combines queries from multiple sources:

#### 1. Apache Impala targeted-perf (majority of queries)
- **Source**: https://github.com/apache/impala/tree/master/testdata/workloads/targeted-perf
- **License**: Apache License 2.0
- **Original format**: ~47 .test files covering database primitives
- **Categories covered**: aggregation, broadcast joins, filters, groupby, exchange, orderby, shuffle, string operations

#### 2. Optimizer Sniff Tests (13 optimizer_* queries)
- **Author**: Justin Jaffray
- **Source**: https://buttondown.com/jaffray/archive/a-sniff-test-for-some-query-optimizers/
- **Purpose**: Systematic testing of query optimizer capabilities
- **Tests covered**: subquery decorrelation, predicate pushdown, join reordering, constant folding, etc.

### Evolution

**Apache Impala targeted-perf + Optimizer Sniff Tests** → **BenchBox Read Primitives**

Changes from source materials:
1. **Format conversion**: Impala `.test` format + blog concepts → unified YAML catalog
2. **Naming standardization**: Dropped `primitive_` prefix for cleaner query IDs
3. **Query modernization**: Added SQL:2016+ features (window functions, QUALIFY, MIN_BY/MAX_BY)
4. **Category expansion**: Added JSON, full-text, statistical, OLAP categories
5. **Documentation**: Enhanced with inline comments explaining test purposes
6. **Optimizer formalization**: Converted blog post concepts into systematic 13-query test suite

### Licenses

- **Impala-derived content**: Apache License 2.0 (Apache Software Foundation)
- **Optimizer queries**: Based on publicly shared concepts (Justin Jaffray)
- **BenchBox additions**: MIT License (Copyright 2026 Joe Harris / BenchBox Project)
