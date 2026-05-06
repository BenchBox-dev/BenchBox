# Catalog `verified` Comment Sweep — 2026-05-06

Inventory of `verified <tool>` comments in
`benchbox/core/write_primitives/catalog/operations.yaml`. Each row
records the comment, tool + version at write time, the matching
`expected_value_min/max` bound, and a verdict against currently
installed tools.

Source: `grep -n "verified" benchbox/core/write_primitives/catalog/operations.yaml`.
Author runtime: BenchBox develop @ 2fd761edd, DuckDB 1.3.2, datasketches
extension 2e38607 (matches TODO 4's smoke). ClickHouse-local was not
present on this sweep host, so ClickHouse-keyed observations are
inherited from the original 2026-05-04 measurements.

| # | Op (yaml line)                                  | Tool / version stamped       | Comment claim         | YAML bound (sketch_bytes) | Re-measured? | Verdict |
|---|-------------------------------------------------|------------------------------|-----------------------|---------------------------|--------------|---------|
| 1 | sketch_query_theta_union_merge clickhouse override (line 3155) | clickhouse-local 25.4.2, SF=0.01, 2026-05-04 | uniq HLL++ default → 60003 bytes | `[16384, 131072]`         | No (no clickhouse-local on sweep host) | Stamp inherited; smoke script (w2) is the future re-measurement path. |
| 2 | sketch_query_kll_quantiles_merge clickhouse override (line 3318) | clickhouse-local 25.4.2, SF=0.01, 2026-05-04 | quantileTDigest(100) merged → 4314 bytes | `[1500, 8000]`            | No                       | Same as #1. Doc claim "~4.3KB on ClickHouse" is consistent with the bound but neither is auto-checked. |
| 3 | sketch_query_topk_combine clickhouse override (line 3449) | clickhouse-local 25.4.2, SF=0.01, 2026-05-04 | topK(8) merged state → 317 bytes | `[200, 800]`              | No                       | Stamp inherited; bound is tighter than DataSketches frequent-items size. |
| 4 | KLL k=100 storage size (line 4011-4012)         | DuckDB 1.3.2, datasketches 2e38607, SF=0.01, 2026-05-04 | KLL k=100 → 2508 bytes merged | (validation_query upstream) | DuckDB 1.3.2 still pinned today; extension hash unchanged | OK as of 2026-05-06. |
| 5 | KLL k=1000 storage size (line 4056-4057)        | DuckDB 1.3.2, datasketches 2e38607, SF=0.01, 2026-05-04 | KLL k=1000 → 21220 bytes merged | (validation_query upstream) | Same | OK as of 2026-05-06. |

(Line 3882 is a header comment, not a per-op claim.)

## Findings

- No comment is out-of-bound against today's catalog bounds.
- Tool versions stamped (clickhouse-local 25.4.2, DuckDB 1.3.2,
  datasketches 2e38607) all match the current pin or "still in
  flight" state from related TODOs (datasketches drift is tracked
  separately by `duckdb-datasketches-family-ci-smoke`).
- The doc claim "~4.3KB on ClickHouse" in
  `docs/benchmarks/write-primitives-sketch-functions.md` falls inside
  `[1500, 8000]` -- consistent today, but the consistency is not
  enforced. w3's doc-yaml consistency test closes that gap.

## Re-stamp candidates

None on this sweep. w4 is a no-op for the 2026-05-06 sweep. The next
sweep should run `scripts/sketch_storage_smoke.sh` (shipped by w2) and
update this table, re-stamping any row whose observation drifted.
