# joinorder_synthetic cross-surface divergences (staged gate)

Snapshot from `make joinorder-synthetic-cross-surface-equivalence-report`
(`python -m benchbox.core.equivalence.cross_surface --benchmark joinorder_synthetic`)
at SF=0.1 on DuckDB, SQL as the reference for its own DataFrame surface
(`expression` = Polars, `pandas`). The generator is seeded (#845), so the cell is
reproducible.

13 queries × 2 backends = 26 cells. **Current: 10 divergent, 16 passing.**

## Fixed while wiring this gate

Wiring the gate surfaced a shared DataFrame-loader bug: the production DataFrame
loader applies column *names* from `get_benchmark_schema_columns`, but that
extractor did not understand joinorder_synthetic's schema shape (columns are raw
DDL strings like `"id INTEGER PRIMARY KEY"`), so it returned **no** columns and
every table loaded **headerless** — all 26 cells errored with "unable to find
column ...". Fixed `benchbox/core/dataframe/schema_utils.py` (`column_name` /
`column_sql_type`) to parse DDL-string columns. This is a general fix (any
string-schema benchmark benefits) and dropped divergences from **26 → 10** (16
cells now pass; 791 dataframe/equivalence unit tests still pass).

## Remaining: 10 dtype-mismatch cells

The loader now applies column *names* but still **type-infers dtypes** rather than
applying the schema's column *types*, so columns whose content looks numeric (or
is null-heavy) get the wrong dtype and the query's comparisons fail:

| Symptom | Cells |
| --- | --- |
| `expected String type` (Polars) | 1a, 1b, 5a, 8a, 9a, 10a (expression) |
| `cannot compare string with numeric type` / `Invalid comparison float64 vs str` | 4a, 12a (both backends) |

### Root cause (diagnosed) and where the fix belongs

The DataFrame load path is **CSV → parquet → `read_parquet`**, not direct CSV
read. `_load_data_phase` runs the production `DataFrameDataLoader`, which converts
the generated CSVs to parquet (cache) and the adapter then calls `read_parquet`
(confirmed by instrumenting both `read_csv` and `read_parquet`: only
`read_parquet` fires for `movie_companies`). During that conversion, a declared
text column that is **all-empty/NULL or numeric-looking** (e.g.
`movie_companies.note`, all NULL at SF=0.1) is inferred as Polars `Null`/numeric
instead of `String`, so a query doing `note NOT LIKE '%...'` raises
`expected String type`.

Consequence: applying dtypes at the **CSV read layer** (`read_csv`
`schema_overrides`) does **not** work — that code never runs. A correct fix must
apply schema column types at one of:
  - the **CSV→parquet conversion** in `DataFrameDataLoader` (write parquet with the
    declared dtypes), or
  - a **post-load cast** in each family's `load_table` (cast declared-text columns
    to the string dtype after the frame is loaded, regardless of source format).

Both touch the shared loader that feeds the **enforced** SSB/CoffeeShop gates, so
the change needs a per-backend cast (Polars expression family + Pandas family) and
full regression verification of all gates. The schema column **types** are already
available via `get_benchmark_schema_columns` / `column_sql_type` (helper
`string_column_names` sketched during diagnosis). This is a bounded but
multi-backend loader task, deliberately deferred from this report rather than
rushed.

## Status

joinorder_synthetic stays in `STAGED_GATES` (report mode), **not** `GATES`, until
the 10 dtype cells are resolved. Then promote to `GATES` + a blocking `pr.yml`
step.
