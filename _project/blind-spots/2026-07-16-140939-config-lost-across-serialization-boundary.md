---
id: 2026-07-16-140939-config-lost-across-serialization-boundary
date: 2026-07-16
status: actionable
finding_kind: bug-class
review_context: "tuning remediation batch close-out 2026-07-16 / chore/tuning-residual-cleanups"
related_paths:
  - benchbox/core/platform_config.py
  - benchbox/core/schemas.py
  - benchbox/platforms/duckdb.py
suggested_sweep: "grep from_config implementations for dropped kwargs classes beyond tuning"
todo_id: null
---

# Producer-added config fields can be silently dropped by hand-picking consumers

## Finding
`get_platform_config` (`benchbox/core/platform_config.py`) still builds the
adapter-facing dict from `DatabaseConfig.model_dump(exclude_none=False)`, which
includes allowed extras, then merges runtime keys such as `benchmark`,
`scale_factor`, and `tuning_config`. Each platform's
`PlatformAdapter.from_config(cls, config: dict)` still selects the constructor
keys it knows about. For example, `DuckDB.from_config` explicitly reads the
database path, benchmark/scale context, memory/force settings, tuning keys,
and driver metadata, while other adapters use different hand-maintained
lists.

The tuning remediation added a shared forwarding list for the known tuning
keys, but there is still no producer/consumer contract that distinguishes
intentionally ignored metadata from a semantically required new config field.
A future field added to `DatabaseConfig` or `get_platform_config` can therefore
be dropped without an error or warning when an affected adapter's
`from_config` is not updated in lockstep. The generic class remains; only the
known tuning instance was fixed.

## Why this matters
A dict-flattening boundary on the producer side and manual key extraction on
the consumer side has no schema contract for semantically required fields. The
type system cannot catch a field that one side starts producing while the
other side never reads; the only symptom is a config value quietly not taking
effect, which looks identical to "the value was never set" from the caller's
perspective. This is structurally the same class of bug as the platform-
identity display-name/canonical-key confusion from the 2026-07-12 batch, but
for config values rather than config keys.

## Suggested next steps
- [ ] Inventory all `from_config` implementations under `benchbox/platforms/**` and
      classify each producer key as consumed, intentionally ignored metadata, or
      required-but-dropped; do not treat every diagnostic/driver field as a constructor
      obligation.
- [ ] Add a contract or focused test for semantically required producer fields so a new
      field cannot be silently omitted by an adapter override. A shared helper may reduce
      drift, but it must preserve platform-specific filtering.

## Triage log

- 2026-07-18: actionable — Rechecked against origin/develop 8a7ee88e0 on 2026-07-18: producer flattening and hand-picked from_config consumers remain, while the tuning forwarding helper fixes only the known tuning instance; revised the record to retain the generic semantically-required-field gap.
