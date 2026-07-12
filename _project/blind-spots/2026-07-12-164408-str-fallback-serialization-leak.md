---
id: 2026-07-12-164408-str-fallback-serialization-leak
date: 2026-07-12
status: open
finding_kind: framework-gap
review_context: "tuning-system deep review / claude/tuning-system-review-7mzapy"
related_paths:
  - benchbox/core/results/platform_options.py
  - benchbox/platforms/base/runtime_metadata.py
suggested_sweep: "grep for `return str(value)` / `default=str` fallbacks on any path that ends in a published bundle or companion file"
todo_id: null
---

# str() serialization fallbacks silently publish Python reprs into bundles

## Finding
`_sanitize_option_value` falls back to `str(value)` for any non-JSON-able object, and
`sanitize_platform_options` (used for `platform.raw_config`) does not filter internal option
keys. Result: `UnifiedTuningConfiguration` objects are published as 900-char Python `repr()`
strings in bundles — 468 of 528 seed-corpus bundles carry one — and downstream consumers (the
explorer's tuning hash) end up hashing repr text. `hash_tuning_template` has the same
`default=str` escape hatch.

## Why this matters
A str() fallback converts "we forgot to define serialization for this type" from a loud error
into a permanent, machine-unreadable artifact in published data. Anything that reaches an
exported file should either serialize canonically or fail capture visibly.

## Suggested next steps
- [ ] Audit exported-payload paths for str()/repr fallbacks; replace with explicit to_dict or drop-with-warning.
- [ ] Decide whether internal option keys should be excluded from raw_config the way _iter_public_options already excludes them elsewhere.
