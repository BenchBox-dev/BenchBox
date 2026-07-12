---
id: 2026-07-12-164408-display-name-used-as-platform-key
date: 2026-07-12
status: open
finding_kind: assumption
review_context: "tuning-system deep review / claude/tuning-system-review-7mzapy"
related_paths:
  - benchbox/core/tuning/interface.py
  - benchbox/platforms/base/adapter.py
  - benchbox/core/tuning/metadata.py
suggested_sweep: "grep for `platform_name` passed into any dict lookup or .lower() comparison; contrast with database_config.type"
todo_id: null
---

# Human display names are silently assumed to be canonical platform keys

## Finding
`adapter.py` passes `self.platform_name` (a display string like "ClickHouse (Local)" or
"StarRocks") into `validate_for_platform`, which lowercases it and looks it up in a map keyed
by canonical types ("clickhouse"). The lookup can never match for multi-word display names, so
validation semantics flip from "check compatibility" to "reject everything". The same
display-name value is also persisted into the tuning metadata table (`metadata.py` `platform=`)
while other layers key on `database_config.type`. Two identity vocabularies exist for platforms
and code moves between them without conversion.

## Why this matters
Any map, registry, or persisted record keyed by "platform" is only correct if every producer and
consumer agrees on which of the two identities is in play. Because both are strings, the type
system cannot catch a mix-up, and the failure mode is a silent empty lookup rather than an error.

## Suggested next steps
- [ ] Sweep all `platform_name` uses that feed comparisons, dict lookups, or persistence and classify display-key vs canonical-key.
- [ ] Consider a `PlatformKey` newtype or a `canonical_platform_type` property on adapters so the two identities cannot be confused.
