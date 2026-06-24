# read_primitives cross-surface divergences (staged gate)

Snapshot from `make read-primitives-cross-surface-equivalence-report`
(`python -m benchbox.core.equivalence.cross_surface --benchmark read_primitives`)
at **SF=0.05** on DuckDB (~300k lineitem rows). The trusted reference is the
**DuckDB-dialect** SQL surface (`benchmark.get_queries(dialect="duckdb")` —
authored catalog variants verbatim + translation), compared against both
DataFrame backends (`expression` = Polars, `pandas`). The TPC-H dbgen base makes
the cell reproducible for a given scale.

Unlike ssb/h2odb (DuckDB-native canonical SQL), read_primitives ships a rich
per-dialect catalog-variant system: its *canonical* SQL uses portable forms
(`TRANSFORM`, `STRUCT(...)`, `APPROX_*`) DuckDB rejects verbatim, so the gate must
run the DuckDB variant, not the raw canonical.

## Scope

- DataFrame registry: **152** queries, a strict subset of the 157 SQL ids (the 5
  SQL-only ids are the documented `get_skip_for_dataframe` set).
- **4 excluded**: `fulltext_boolean_search`, `fulltext_phrase_search`,
  `fulltext_simple_search`, `json_extract_simple` — DuckDB cannot transpile FTS /
  these JSON forms, so `get_queries(dialect="duckdb")` drops them. No DuckDB
  reference exists, so there is nothing to compare (same discipline as a
  missing-backend skip), not a muted divergence.
- **Gateable: 148 queries × 2 backends = 296 cells.**

## Snapshot: 127 divergent cells, 6 vacuous queries (as wired)

| Bucket | Cells | Nature |
| --- | --- | --- |
| `column_count` | 43 | DataFrame projects a different column set than the SQL/contract |
| `row_count` | 30 | DataFrame cardinality differs (filter/limit/grouping/dedup) |
| `order_by_tie` | 22 | Result ordering / tie-group differs at the boundary |
| `value_mismatch` | 21 | Approximate (HLL/T-Digest), Decimal-vs-float dtype, or float precision |
| `dataframe_impl_error` | 7 | DataFrame impl raises (real bugs) |
| `reference_sql_failed` | 4 | The 4 excluded ids (KeyError) — removed by the exclusion above |

Vacuous (0 reference rows at SF=0.05): `array_agg_simple`,
`filter_bigint_selective`, `filter_decimal_in_list_selective`,
`filter_decimal_selective`, `filter_string_like`, `json_extract_nested`.

## Arbiter: the catalog `result_contract`

Each catalog query carries a `result_contract` (`columns`, `row_identity`). This
is the objective arbiter of the intended result shape — not "SQL wins by fiat".
Spot-checked:

- `statistical_correlation`: contract = 6 columns (incl. `price_qty_slope`,
  `price_qty_intercept`, `regression_r_squared`); SQL = 6 ✓; **DataFrame = 3 ✗**
  (the REGR_* columns were dropped — Polars/pandas lack native `REGR_*`). → fix
  the DataFrame impl.
- `array_contains`: contract = `[ps_suppkey, has_part_100]` (2); SQL = 2 ✓;
  **DataFrame = 3 ✗** (leaks the intermediate `parts` array). → fix the DataFrame
  impl.

In the column_count cases checked, the SQL surface matches the contract and the
DataFrame surface is the one that drifted. The burn-down therefore conforms the
DataFrame surface to the contract/SQL; where the SQL itself disagrees with the
contract, fix the SQL.

## Burn-down plan (multi-PR, tracked to GATES promotion)

1. **column_count (43 cells)** — two patterns: array/list/map queries leaking an
   intermediate column (drop it); filter/optimizer/stat queries missing projected
   columns (add them, e.g. `SELECT *` shapes and the stat REGR_* set).
2. **row_count (30 cells)** — conform DataFrame filter/limit/grouping/dedup to the
   contract (e.g. `limit` LIMIT 100 not 1000; `window_row_number` dedup).
3. **order_by_tie (22 cells)** — add deterministic secondary sort keys on both
   surfaces (the h2odb Q10 precedent), or extend `tie_aware` only where a trailing
   LIMIT can truncate a tie.
4. **dataframe_impl_error (7 cells)** — fix real impl bugs (`to_period`,
   Polars-map parse, pandas missing-column KeyError, `datetime64[M]` dtype).
5. **value_mismatch (21 cells)** — classify genuinely approximate cells
   (`APPROX_COUNT_DISTINCT` HLL, `APPROX_QUANTILE` T-Digest) and Decimal-vs-float
   dtype residues with written rationale (the h2odb Q9 precedent); fix real
   float-precision/logic divergences.
6. **vacuous (6)** — make discriminating via scale/parameter tuning, or classify
   with rationale.
7. **Promote** `read_primitives` from `STAGED_GATES` → `GATES`, add the blocking
   CI step, refresh the oracle-coverage-map, and add the fast-lane + unit tests.

Until clean, `read_primitives` stays in `STAGED_GATES` (report mode, non-blocking)
so the oracle-coverage-map does not prematurely mark it "guarded".
