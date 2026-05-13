# Results Explorer Cost-Schema Compatibility Decision (2026-05-07)

Decision document for `results-explorer-retheme-schema-cost-regression` (w3).

## Audit finding (paraphrased from the 2026-05-07 retheme audit)

`/results/tpch/`, `/results/star_schema/`, and `/results/p/duckdb/` exposed
DuckDB binder errors because frontend queries reference
`r.normalized_cost_usd`, `r.cost_model_version`, `r.cost_status`, etc., and
the snapshot the audit ran against was missing those columns.

## Reproduction status (w1)

Reproduction against the current fixture corpus regenerated at branch
`fix/results-explorer-schema-cost-regression`:

```text
$ cd results-explorer && npm run test:e2e:fixtures
$ npx playwright test --project=chromium \
    e2e/routes/benchmark-index.spec.ts e2e/routes/platform-index.spec.ts
4 passed (3.9s)
```

The four route smoke specs (`/results/tpch/`, `/results/p/duckdb/`, the
fixture-platform row count, and the SF filter URL sync) all render real data.
The current fixture corpus produces a snapshot whose `bench.results` table
contains the full cost contract:

```text
results: 44 columns
  ... cost_usd DOUBLE
  ... normalized_cost_usd DOUBLE
  ... cost_model_version VARCHAR
  ... cost_model_source VARCHAR
  ... cost_scope VARCHAR
  ... cost_status VARCHAR  NOT NULL
  ... billing_unit VARCHAR
  ... pricing_region VARCHAR
```

The raw reproduction log is no longer retained in git; the durable schema
evidence is summarized above.

The audit was therefore captured against either an older snapshot
(pre-`benchbox/core/explorer_pipeline/duckdb_builder.py`) or a deployment
running stale `results.duckdb`. The code path that emits the binder error
(LEFT JOIN onto `bench.results r` selecting `r.normalized_cost_usd` in
`results-explorer/src/lib/duckdbQueries.ts:395`) cannot be redirected to a
table that does not exist; the only way the binder error appears is if
`bench.results` is missing the cost columns at runtime.

## Schema audit (w2)

| Field | Source SQL | Required by | Snapshot today |
|---|---|---|---|
| `cost_usd` | `r.cost_usd` | Cost displays, ranking-cohort context | Present |
| `normalized_cost_usd` | `r.normalized_cost_usd` | Cost displays (`costDisplay.ts`), Compare cost facets, `getBenchmarkRanking` | Present |
| `cost_model_version` | `r.cost_model_version` | Compare cost diff disclosure, query workbench filter | Present |
| `cost_model_source` | `r.cost_model_source` | Result detail receipt | Present |
| `cost_scope` | `r.cost_scope` | Result detail receipt | Present |
| `cost_status` | `r.cost_status` | `costDisplay.ts` discriminator, query filters | Present (NOT NULL) |
| `billing_unit` | `r.billing_unit` | Cost diff context | Present |
| `pricing_region` | `r.pricing_region` | Cost diff context | Present |
| `cloud_provider` / `cloud_region` / `instance_or_warehouse` | `r.cloud_*` | Environment facets | Present |

Every cost column referenced by `lib/duckdbQueries.ts`,
`lib/costDisplay.ts`, `lib/queryFilters.ts`, and `lib/starterQueries.ts` is
produced by `benchbox/core/explorer_pipeline/duckdb_builder.py`. The contract
between the Python builder and the TypeScript queries is internally
consistent at the time of writing.

## Decision

**Adopt option (1) + schema-readiness column guard.** Continue producing the
full cost contract from the canonical snapshot builder, and harden the
runtime so that an out-of-date snapshot fails *loudly during init* rather
than producing a `Binder Error` inside a deep page query.

Concretely:

1. The `bench.results` schema continues to include the full cost contract
   (`cost_usd`, `normalized_cost_usd`, `cost_model_version`,
   `cost_model_source`, `cost_scope`, `cost_status`, `billing_unit`,
   `pricing_region`). No frontend tolerance for missing columns is
   introduced — that would silently mask a real upstream regression and
   regress the audit's stated user impact.

2. Extend the snapshot-readiness path in `results-explorer/src/db.ts` with a
   **column-level guard**: before exposing the cached DB instance, query
   `bench.information_schema.columns` (or DuckDB's `pragma_table_info`) to
   verify that the cost contract is complete. If a column is missing,
   `getDb()` rejects with an actionable error naming the missing columns.

3. Add a unit test for the new guard so a future bundle that drops a column
   surfaces in CI rather than in production.

4. Keep `LEFT JOIN ... USING (result_id)` semantics in `getBenchmarkRanking`
   so a *row* missing in `bench.results` (e.g. orphan benchmark_rankings
   row) does not 500 — that is a different failure mode and the existing
   tolerance is correct.

### Why not the alternatives

- **Option 2 (frontend tolerance for missing columns).** Rejected because
  it would silently degrade the cost-aware ranking semantics and let the
  binder error condition recur unnoticed. The product owns the cost
  contract; the source of truth must remain the snapshot, not the page.

- **Option 3 (revert the canonical contract to `cost_usd` only).** Rejected
  because `costDisplay.ts`, `queryFilters.ts`, environment facets, and the
  starter Query Workbench prompts already depend on the normalized cost
  fields. A revert would regress the explorer's product surface.

## Impact summary

- **Published bundles.** No change. Every cost field in the contract is
  already produced by `duckdb_builder.py`. The guard only surfaces
  regressions; it does not alter what the builder writes.
- **Fixture generation.** No change. The fixture corpus was already
  exercising the full contract; the new guard verifies that and would catch
  drift in the fixture pipeline immediately.
- **Query Workbench visible columns.** Unchanged. The starter prompts
  continue to project the normalized cost columns.
- **Release gate.** Adds one e2e + one unit-test surface that flips red if a
  column disappears. The retheme release-gate TODO can therefore rely on
  the guard rather than re-asserting cost-schema integrity on every route.

## Out of scope for this TODO

- Schema migrations of historic, externally-published bundles.
- Documenting the cost contract on the public docs site.
- Re-exposing the binder error in tests as a *negative* fixture (we would
  need a regenerator that intentionally drops columns, which is out of scope
  for this remediation).
- An environment-variable escape hatch (e.g. `VITE_DISABLE_RESULTS_SCHEMA_GUARD=1`).
  Considered and deliberately not added: the audit's user impact is "users
  see clear empty states instead of raw SQL diagnostics", which the loud
  init-time error already satisfies (the column name is named in the error
  message). An escape hatch would re-enable the deep-binder-error mode the
  TODO is meant to eliminate. If a future regression argues for one, add it
  in a separate decision note rather than re-litigating in code.
