# ADR-001: Tuning Trust Model and Hash Semantics

## Status

Accepted, 2026-07-12. Decided by Joe.

## Context

The 2026-07-12 tuning-system deep review (evidence pinned to commit
`acfb8992`) surfaced two unresolved product questions blocking soundness
remediation of the tuning pipeline:

**1. Trust model.** Published tuning claims are, today, self-attested and
nothing says so:

- `tunings_applied` recorded on a benchmark result is the *requested*
  tuning configuration, not a record of what was actually applied:
  `effective_tuning_config.to_dict()` is captured directly as
  `tunings_applied_dict` (`benchbox/platforms/base/adapter.py:743-747`),
  regardless of whether individual DDL clauses or session `SET`s
  succeeded.
- `tuning_validation_status` only distinguishes `APPLIED` /
  `FAILED_TO_SAVE` / `NOT_APPLICABLE` based on whether a metadata-table
  write succeeded — it certifies that *something* was written, not that
  the requested tuning was physically realized in the database.
- No mechanism lets an evaluator verify a published tuning claim against
  the actual database state.
- `docs/reference/threat-model.md` already defines a trust-label
  vocabulary for the results platform (`maintainer-run`,
  `community-submission`, `verified` — the last one explicitly "reserved
  for future third-party attestation"). Tuning claims need an equivalent
  label without forking that vocabulary.

**2. Hash semantics.** The tuning "hash" concept is four disjoint,
inconsistent things across the codebase, and the one field meant to
carry it is never populated:

- `benchbox/core/tuning/interface.py:846-863` —
  `get_configuration_hash()`: full SHA-256 over `self.to_dict()`
  (canonical JSON, sorted keys, no truncation).
- `benchbox/core/tuning/profile_validation.py:324-333` —
  `hash_tuning_template()`: a *different* SHA-256-based hash, truncated
  to 16 hex characters, over `to_dict()` (or `repr()` as a fallback for
  non-dict-like inputs).
- The bundle's `tuning_config_hash` field: defined but never set by any
  code path — bundles ship with no populated hash at all.
- `_project/scripts/explorer_pipeline/transformer.py:187-201` —
  `_tuning_hash()`: an 8-character SHA-256 hash computed independently
  by the explorer ingest pipeline from `{"mode": ..., "detail": ...}`,
  derived from whatever ad hoc `tuning_mode`/`tuning_config` keys happen
  to be present in the ingested JSON — not derived from the canonical
  tuning object at all.

None of these four notions agree on what is hashed (requested template,
effective config, ad hoc explorer-side dict) or on truncation length,
and none of them capture the physically applied statements. This ADR
decides what the hash(es) must certify going forward.

## Decision

### 1. Trust model: self-attested, labeled; introspection is the design direction; third-party attestation stays deferred

All published tuning claims remain **self-attested**. This is labeled
explicitly in the explorer UI and in docs — evaluators must not be able
to mistake a self-attested claim for an independently verified one.
Labeling implementation itself belongs to the TODOs that touch the
explorer UI and docs surfaces; this ADR only fixes the decision, not the
UI copy.

Post-load schema-introspection receipts (querying the live database
after load to confirm the DDL/settings that were requested actually took
effect, and attaching that as a receipt alongside the bundle) are the
**design direction for future verification**. They are not implemented
by this decision and are not a blocker for the current soundness work.

Third-party attestation (an independent party re-running and certifying
a result) stays **deferred**, consistent with the `verified` trust
label already reserved but unimplemented in
`docs/reference/threat-model.md`. This decision does not fork or extend
that vocabulary; it reuses "self-attested" as the tuning-specific
instance of the same "not independently verified" concept the threat
model already anticipates.

### 2. Hash semantics: two hashes, each with a distinct, named purpose

The single ambiguous `hash` / `tuning_config_hash` field, and all
repr-based or ad hoc hashing (including the explorer's `_tuning_hash()`
derived from loosely-typed ingested JSON), are **not valid** going
forward. They are replaced by exactly two named hashes:

1. **`requested_config_hash`** — canonical SHA-256 over
   `UnifiedTuningConfiguration.to_dict()`, serialized as JSON with
   `sort_keys=True` and compact separators (`(",", ":")`), full 64-hex-
   character digest (no truncation). This is the **platform-independent
   template identity**: two runs that requested the same tuning template
   produce the same `requested_config_hash` regardless of which platform
   executed it or whether every clause actually applied.

2. **`applied_ledger_hash`** — a hash over the **applied-statement
   ledger**: the ordered record of DDL clauses, post-load statements,
   and session `SET`s that were *actually executed* against the target
   platform. (Exact failure representation and ordering guarantees are
   design decisions owned by the implementing TODO.) This is the
   **platform-specific physical identity** of the run — it changes if
   the platform renders the same requested template into different
   physical statements, or if some statements fail to apply.

Both hashes are carried on the bundle. Neither hash is optional, and
neither substitutes for the other: `requested_config_hash` answers "did
two runs ask for the same tuning," `applied_ledger_hash` answers "did
two runs physically do the same thing to the database."

The exact serialization format of the applied-statement ledger itself
(what constitutes a "statement," ordering guarantees, failure
representation) is implementation detail owned by
`tuning-applied-ledger-and-validation-status-20260712`, not this ADR.

## Consequences

Implementing TODOs must honor these decisions as fixed constraints:

- **`tuning-applied-ledger-and-validation-status-20260712`** — must
  build the applied-statement ledger this ADR assumes exists, compute
  `applied_ledger_hash` from it, and must not conflate `tunings_applied`
  (requested) with what was physically applied. `tuning_validation_status`
  must be able to express partial application, not just
  `APPLIED`/`FAILED_TO_SAVE`/`NOT_APPLICABLE`. Owns populating
  `applied_ledger_hash` onto the bundle: it depends on
  `tuning-bundle-provenance-and-config-export-20260712` (the bundle's
  `requested_config_hash` field and export scaffolding must exist
  first), so it is this TODO — not bundle-provenance — that completes
  the "both hashes carried on the bundle" requirement below.
- **`tuning-bundle-provenance-and-config-export-20260712`** — must
  populate `requested_config_hash` on the bundle (replacing the
  never-set `tuning_config_hash` field) and carry/display the
  self-attested trust label alongside it. Does **not** populate
  `applied_ledger_hash`: this TODO has no dependency on
  `tuning-applied-ledger-and-validation-status-20260712` (the applied
  statement ledger does not exist yet at this TODO's build time — the
  dependency runs the other way), so requiring it here would be
  unsatisfiable in dependency order (review finding, 2026-07-12).
- **`tuning-mode-vocabulary-and-facet-implementation-20260712`** — any
  facet or mode-derived data surfaced to evaluators must not imply
  verification beyond self-attestation, and must source hash values from
  the two canonical hashes above rather than recomputing an ad hoc hash
  (e.g., the explorer must stop deriving its own hash from ingested
  `tuning_mode`/`tuning_config` JSON and instead consume
  `requested_config_hash` / `applied_ledger_hash` directly from the
  bundle).

Any doc or UI surface that currently implies tuning claims are verified
(rather than self-attested) is out of compliance with this ADR and
should be corrected by the owning TODO.

## Rejected options

- **Single hash.** Rejected: a single hash cannot simultaneously answer
  "same requested template" and "same physical execution" — the review
  found four different single-hash notions already in conflict for
  exactly this reason. Collapsing to one hash would just relabel the
  ambiguity rather than resolve it.
- **Build introspection verification now.** Rejected for this decision
  cycle: schema-introspection receipts require new per-platform
  introspection logic and a receipt format, which is real implementation
  work with its own design surface. It is adopted as the direction for
  future verification but is explicitly out of scope for the current
  soundness remediation pass.
- **Leave tuning claims unlabeled (implicitly trusted).** Rejected:
  this is the status quo and is what the review flagged as unsound —
  evaluators currently have no signal that `tunings_applied` is a
  request, not a certified outcome.

## References

- `benchbox/platforms/base/adapter.py:743-747`
- `benchbox/core/tuning/interface.py:846-863`
- `benchbox/core/tuning/profile_validation.py:324-333`
- `_project/scripts/explorer_pipeline/transformer.py:187-201`
- `docs/reference/threat-model.md`
- `docs/development/adapter-refactor-map.md` (design-record style precedent)
- `_project/TODO/main/planning/tuning-applied-ledger-and-validation-status-20260712.yaml`
- `_project/TODO/main/planning/tuning-bundle-provenance-and-config-export-20260712.yaml`
- `_project/TODO/main/planning/tuning-mode-vocabulary-and-facet-implementation-20260712.yaml`
