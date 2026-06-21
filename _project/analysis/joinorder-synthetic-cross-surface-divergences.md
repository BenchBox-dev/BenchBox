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

Fix direction (follow-up): apply the schema column **types** when loading the
DataFrame surface (the types are now available from `column_sql_type`), so a
column declared `VARCHAR`/`TEXT` loads as string and `INTEGER` as int, instead of
relying on per-file dtype inference. This is a loader-layer fix, not per-query.

## Status

joinorder_synthetic stays in `STAGED_GATES` (report mode), **not** `GATES`, until
the 10 dtype cells are resolved. Then promote to `GATES` + a blocking `pr.yml`
step.
