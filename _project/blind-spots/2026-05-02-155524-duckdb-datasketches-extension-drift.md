---
id: 2026-05-02-155524-duckdb-datasketches-extension-drift
date: 2026-05-02
status: open
finding_kind: assumption
review_context: "TODO write-primitives-sketch-clickhouse-and-storage-metrics implementation attempt"
related_paths:
  - benchbox/core/write_primitives/catalog/operations.yaml
  - pyproject.toml
suggested_sweep: "Pin or vendor a known-good datasketches community-extension build (e.g. ship the .duckdb_extension binary in _binaries/), or replace `datasketch_theta` / `datasketch_frequent_items` references with HLL family substitutes that the current extension actually exports. Add a CI smoke that calls `SELECT datasketch_theta(1)` to fail fast if a future extension rebuild drops the family again."
todo_id: null
---

# DuckDB datasketches Community Extension Dropped theta + frequent-items Families

## Finding

The 4 sketch ops `sketch_insert_theta_per_partition`,
`sketch_insert_topk_per_shard`, `sketch_query_theta_union_merge`,
`sketch_query_topk_combine` reference `datasketch_theta` and
`datasketch_frequent_items` aggregates that **do not exist** in the
DuckDB community datasketches extension at the version BenchBox installs
today (commit `2e38607` for DuckDB v1.3.2).

PR #114's commit message explicitly claims smoke-verification:

> "all 3 ★ headline sketch ops still return values within their tuned
> bounds on DuckDB SF=0.01 (theta 14836.89 ∈ [14000, 16000]; ...)"

That assertion was true on 2026-05-02 morning when PR #114 merged. As of
2026-05-02 ~15:50, a fresh `INSTALL datasketches FROM community` (cache
purged, version 2e38607 re-downloaded) returns the same build and the
function family is absent: `Catalog Error: Scalar Function with name
datasketch_theta does not exist! Did you mean "datasketch_tdigest"?`.

`SELECT DISTINCT function_name FROM duckdb_functions() WHERE function_name
ILIKE 'datasketch_%'` returns the families: `cpc`, `hll`, `kll`,
`quantiles`, `req`, `tdigest`. No `theta`. No `frequent_items`.

Either the upstream extension build for v1.3.2 was rebuilt without the
theta + frequent-items families between PR #114 morning and this audit,
or the smoke verification was performed against a different DuckDB
version that BenchBox doesn't pin to.

## Why this matters

`benchbox run --platform duckdb --benchmark write_primitives --queries
sketch_query_theta_union_merge` returns FAILED on develop today, and
4/8 sketch ops fail end-to-end. This blocks the verification step of
every write_primitives sketch TODO that asserts "8/8 pass on DuckDB"
as a regression check.

Combined with the sibling blind-spot
(`2026-05-02-155448-validation-query-no-per-platform-override`), the
TODO `write-primitives-sketch-clickhouse-and-storage-metrics` is
hard-blocked: even if the ClickHouse-side overrides are added, the
DuckDB regression check cannot pass and the validation infrastructure
cannot reliably gate cross-engine ops.

CI doesn't catch this because it doesn't currently exercise the sketch
ops beyond loader unit tests. The community extensions are downloaded
on-demand from a CDN and not vendored, so an upstream re-build silently
changes BenchBox's behavior without any version bump or PR.

## Suggested next steps

- [ ] Add a fast smoke in CI that calls `SELECT datasketch_theta(1)` and
      `SELECT datasketch_frequent_items(8, 'x')` against a fresh DuckDB
      install — fails the build if either family is absent.
- [ ] Decide between vendoring the community extension binary in
      `_binaries/datasketches/` (control over version, larger artifact
      tree) vs. switching the ops to families the upstream extension
      reliably exports (`hll` substitution; closer to Redshift's
      HLL-only ceiling).
- [ ] File an upstream issue against the duckdb-community-extensions
      datasketches build asking why the theta + frequent-items families
      were dropped from the v1.3.2 build artifact, if confirmed.
- [ ] Until resolved, treat any sketch-TODO verification step that
      requires DuckDB execution of theta or topk ops as a known-fail;
      do not block PRs on that specific check.
