---
id: 2026-07-16-140939-config-lost-across-serialization-boundary
date: 2026-07-16
status: open
finding_kind: bug-class
review_context: "tuning remediation batch close-out 2026-07-16 / chore/tuning-residual-cleanups"
related_paths:
  - benchbox/core/platform_config.py
  - benchbox/core/schemas.py
  - benchbox/platforms/duckdb.py
suggested_sweep: "grep from_config implementations for dropped kwargs classes beyond tuning"
todo_id: null
---

# Config silently lost across a serialization boundary between producer and consumer

## Finding
`get_platform_config` (`benchbox/core/platform_config.py`) builds the adapter-facing
config dict by calling `DatabaseConfig.model_dump(exclude_none=False)` and merging in a
handful of extra keys (`benchmark`, `scale_factor`, `tuning_config`). Each platform's
`PlatformAdapter.from_config(cls, config: dict)` then hand-picks the keys it knows about
out of that flattened dict (as seen in `benchbox/platforms/duckdb.py from_config`, which
explicitly reads `config.get("tuning_config")`, `config["benchmark"]`,
`config["scale_factor"]`, etc.). Nothing enforces that every `from_config` override reads
every kwarg the producer put in -- across the ~48 platform adapters, a kwarg added by the
producer side that a given adapter's `from_config` doesn't explicitly extract is dropped
silently: no error, no warning, just absent from the constructed adapter. This is the same
shape of bug independently proven in #1176 w0 for the tuning-kwarg case, but the
model_dump-then-hand-pick pattern is generic -- any future field added to `DatabaseConfig`
or to `get_platform_config`'s merged dict has the same failure mode for any adapter whose
`from_config` wasn't updated in lockstep.

## Why this matters
A serialization/deserialization boundary (dict flattening on the producer side, manual
key extraction on the consumer side) has no schema contract between the two ends. The
type system cannot catch a field that one side stops producing or the other side never
started reading -- the only symptom is a config value quietly not taking effect, which
looks identical to "the value was never set" from the caller's perspective. This is
structurally the same class of bug as the platform-identity display-name/canonical-key
confusion from the 2026-07-12 batch (differently shaped keys silently failing to connect
producer to consumer), but for config *values* rather than config *keys*.

## Suggested next steps
- [ ] Grep all `from_config` implementations under `benchbox/platforms/**` for the set of
      keys each one reads out of its `config` dict argument; diff against the full set of
      keys `get_platform_config` can produce (including `DatabaseConfig` extra/optional
      fields) to find adapters silently dropping producer-supplied config.
      (suggested_sweep, verbatim: "grep from_config implementations for dropped kwargs
      classes beyond tuning")
- [ ] Consider a shared `from_config` base helper (or a post-construction assertion) that
      surfaces unconsumed keys instead of letting `from_config` overrides silently ignore
      them.
