---
id: 2026-05-04-140839-repro-harness-call-shape-coverage-gap
date: 2026-05-04
status: open
finding_kind: bug-class
review_context: "/code review during retire-sqlglot-duckdb-all-workaround / chore/retire-sqlglot-duckdb-all-workaround"
related_paths:
  - _project/sqlglot-upstream/repros/repro_all.py
  - benchbox/utils/dialect_utils.py
  - _project/sqlglot-upstream/README.md
suggested_sweep: "Audit every repro in repros/repro_all.py against the actual call shape used in benchbox/utils/dialect_utils.py and benchbox/platforms/base/dialect_translation.py. For each, confirm the read/write dialect pair the harness exercises matches the pair production code uses; widen any narrow probes."
todo_id: null
---

# Repro harness call-shape coverage gap

## Finding

`_project/sqlglot-upstream/repros/repro_all.py:34-45` (`repro_1_duckdb_all_keyword`)
exercises `sqlglot.transpile(..., read="duckdb", write="duckdb", identify=True)` and
reports PASS on `sqlglot==30.6.0`. Based on that PASS, the upstream README and the
`retire-sqlglot-duckdb-all-workaround` TODO concluded the BenchBox post-fixup
`_restore_group_order_by_all_keyword` was no longer load-bearing.

That conclusion was wrong. BenchBox's actual call site —
`dialect_utils.translate_sql_query` at the production path used by every TPC-shaped
benchmark — uses `read="postgres"` (after `netezza→postgres` normalization) and
`write="duckdb"`. On the same `sqlglot==30.6.0`, that cross-dialect call still emits
`ORDER BY "ALL"`, which DuckDB rejects without the post-fixup. The workaround stays.

The mistake was found by an ad-hoc probe during code review, not by the harness. The
harness's single-dialect probe is not a sufficient retirement gate for any post-fixup
that lives in `dialect_utils.translate_sql_query`, because that wrapper is invoked
across dialects.

## Why this matters

This is not a one-off. The same pattern can recur for any post-fixup retired against
the harness:

- `_fix_sqlite_unsupported_syntax` is gated on `tgt == "sqlite"` and is exercised in
  `repro_2` and `repro_3` with `read="postgres"` / `write="sqlite"` — that pair is
  correct, so those repros are not affected.
- `fix_postgres_date_arithmetic` is a pre-processor that is by design not exercised
  by the harness; that's an explicit "keep" decision (item #4 in the verdict table).
- Future post-fixups added to `dialect_utils.py` will inherit the same risk: a single
  `read=write=<target>` repro will report PASS while the cross-dialect path still
  fails, and a retirement TODO will be filed against false evidence.

The class is "post-fixup retirement decisions made against a repro that doesn't
match the wrapper's actual call shape." This is not strictly an upstream bug —
SQLGlot's own dialect parsers may legitimately diverge in what they emit per source
dialect — but it is a live trap for anyone writing a "retire the workaround" TODO.

## Suggested next steps

1. **Cheap fix in this branch's follow-up**: extend `repros/repro_all.py` `repro_1`
   to also probe `read="postgres", write="duckdb"` (and report PASS/FAIL for each
   call shape independently). This converts the harness from a single-dialect probe
   into a wrapper-call-shape probe, matching how BenchBox actually consumes SQLGlot.
2. **Documented convention**: update the README's "Run the harness" section to
   record that any new `repro_*` for an item that lives in
   `dialect_utils.translate_sql_query` must exercise both
   `read=<target>, write=<target>` and `read="postgres", write=<target>` to be a
   valid retirement gate.
3. **Prophylactic check**: when a future TODO claims to retire a post-fixup based
   on a harness PASS, the review should grep `dialect_utils.translate_sql_query`
   for the helper's call site and confirm the harness probe matches the wrapper's
   `read=` argument at that call.

This is a `bug-class` finding (not specific to item #1) but it does not block the
current PR — that PR captures the immediate consequence (workaround stays, docs
clarified, floor bumped). The class itself wants a separate sweep.
