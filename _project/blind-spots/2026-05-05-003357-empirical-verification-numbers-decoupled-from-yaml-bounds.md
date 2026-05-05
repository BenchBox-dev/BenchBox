---
id: 2026-05-05-003357-empirical-verification-numbers-decoupled-from-yaml-bounds
date: 2026-05-05
status: open
finding_kind: framework-gap
review_context: "/code review of write-primitives-sketch-clickhouse-local-smoke (TODO completion)"
related_paths:
  - benchbox/core/write_primitives/catalog/operations.yaml
  - docs/benchmarks/write-primitives-sketch-functions.md
suggested_sweep: "audit other 'verified <tool> at SF=X' style comments in catalog yaml + matching docs prose; check whether any pair of (yaml-bound, doc-claim) can drift independently with no test"
todo_id: null
---

# Five-Axis Review Misses Durability of Empirical Verification Numbers

## Finding

The five-axis review framework (correctness / readability / architecture /
security / performance) catches code-quality issues but does not surface
the durability problem inherent to empirical verification updates:

1. **No regression alarm if observations drift.** The clickhouse-local
   smoke test captured point-in-time bytes (60003 / 4314 / 317) and
   stamped them into `operations.yaml` comments. Nothing in CI re-runs
   the smoke and re-tunes (or alerts on) drift after a ClickHouse
   upgrade. Six months from now, a routine ClickHouse bump may shift
   one of these by 30 % and the comment will silently be wrong.

2. **Doc-vs-yaml-bound skew is unguarded.** `docs/benchmarks/write-primitives-sketch-functions.md`
   now claims "~4.3KB on ClickHouse" and the matching yaml bound is
   `[1500, 8000]`. These can drift independently with zero CI signal.
   The same pattern already exists for the DuckDB numbers.

3. **Verification methodology is not codified.** The SQL script that
   captured the observations
   (`/tmp/clickhouse-smoke/storage-sizes.sql`) lived only in this
   session and is now gone. A future contributor refreshing the
   numbers has to reconstruct it from `operations.yaml`. A persisted
   script or `make` target would close the gap.

The five-axis frame would score this kind of change ≥ 4/5 across the
board because the *individual update* is correct and well-scoped — it
just doesn't ask "does the next person who needs to refresh this know
how, and will the comment be right when they get there?"

## Why this matters

BenchBox's catalog has many `verified <tool> at SF=<x>` comments
(DuckDB DataSketches, ClickHouse, chDB spikes). Each one is a small
correctness claim that can rot. Without a sweep mechanism or a doc/yaml
consistency check, the catalog accumulates plausible-looking but
unverified numbers, eroding the value of the whole methodology.

## Suggested next steps

- [ ] Sweep existing `verified <tool>` comments in
  `benchbox/core/write_primitives/catalog/operations.yaml` and check
  for date staleness or version drift.
- [ ] Consider adding a `scripts/sketch_storage_smoke.sh` (or a `make`
  target) that runs the persist+merge cycles against the bundled
  fixtures and prints observed bytes — checked-in companion to the
  yaml comments.
- [ ] Consider a doc-yaml consistency test that fails when a number in
  `docs/benchmarks/write-primitives-sketch-functions.md` falls outside
  the yaml bound for the same metric.
- [ ] Add "durability of empirical claims" as an axis or sub-axis to
  the review framework for verification-type changes.
