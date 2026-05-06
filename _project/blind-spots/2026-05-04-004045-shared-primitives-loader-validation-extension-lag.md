---
id: 2026-05-04-004045-shared-primitives-loader-validation-extension-lag
date: 2026-05-04
status: merged-to-todo
finding_kind: framework-gap
review_context: "/code review W1 / feat/write-primitives-architecture-fixes"
related_paths:
  - benchbox/core/primitives/catalog/loader.py
  - benchbox/core/write_primitives/catalog/loader.py
  - benchbox/core/transaction_primitives/catalog/loader.py
suggested_sweep: "audit which validation_query fields the shared primitives loader passes through vs which write_primitives' local loader supports; close the gap or document the divergence"
todo_id: shared-primitives-loader-validation-parity
---

# Shared primitives catalog loader lags write_primitives validation extensions

## Finding
W1 of `write-primitives-architecture-fixes` added `platform_overrides` to
`ValidationQuery` and runtime resolution in `write_primitives/benchmark.py`. The
five-axis review framework graded the change correct in isolation. What it did
not surface: `benchbox/core/primitives/catalog/loader.py` is a *shared* operations
catalog loader (used by `transaction_primitives` via `load_operations_catalog`),
and its `_parse_validation_queries` only forwards 7 fields to
`build_validation_query`. It already lacks `expected_value_min` /
`expected_value_max` (added by PR #112/#114 inside the write_primitives-local
loader path), and now also lacks `platform_overrides`.

The asymmetry is invisible because:
- `write_primitives` has its own `load_write_primitives_catalog` that does not
  delegate to `load_operations_catalog`, so the local extensions work.
- Anyone reaching for `load_operations_catalog` (today: `transaction_primitives`)
  silently gets the older, narrower validation_query shape.

## Why this matters
The repo currently has two versions of "what fields a validation_query supports"
— one in the shared loader, one in the write_primitives-local loader — and the
gap widens every time write_primitives adds a field. A future agent extending
`transaction_primitives` to use approximate-value bounds or per-platform
validation will not get a clear failure; the field will be silently dropped
because the shared loader does not pass it through to `build_validation_query`.

The five-axis review framework grades each diff in isolation; it does not flag
"this datatype has a sibling parser that has fallen behind." That is the class
of issue this finding marks.

## Suggested next steps
- [ ] Decide: fold the write_primitives-local loader into the shared
      `load_operations_catalog`, or document the divergence and accept it.
- [ ] If folding: extend the shared `_parse_validation_queries` to forward
      `expected_value_min`, `expected_value_max`, and `platform_overrides`
      (the latter via a parser identical to the one added in this PR).
- [ ] Either way, add a CI grep / test that fails when one loader gains a
      validation_query field the other does not, so the gap stops widening
      silently.

## Triage log

- 2026-05-05: actionable (sweep). Confirmed:
  `benchbox/core/primitives/catalog/loader.py:_parse_validation_queries`
  (lines 464–500) still forwards only 7 fields
  (id/sql/expected_rows/min/max/values/check_expression). Still missing
  `expected_value_min`, `expected_value_max`, and validation-level
  `platform_overrides`. Operation-level `platform_overrides` IS present.
  Asymmetry persists. Carry forward all three next-steps.
- 2026-05-05: promoted to TODO `shared-primitives-loader-validation-parity`
