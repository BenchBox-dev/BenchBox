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

### 3. Realized ledger: the `.applied.json` companion and vocabulary

The applied-statement ledger (`benchbox.core.tuning.applied_ledger`) is
produced **by the execution path** — each tuning-relevant statement is
recorded as it runs against a transparent recording proxy over the
tuning/session connection — and is never reconstructed from the
requested config. It is exported as an additive `.applied.json` companion
alongside the existing `.tuning.json` (which is unchanged and still
carries the *requested* config + `requested_config_hash`).

`.applied.json` shape (the ledger's `to_payload(status=...)`):

```json
{
  "status": "applied_unverified",
  "applied_ledger_hash": "<sha256 | null>",
  "statements": [
    {"statement": "CREATE INDEX IF NOT EXISTS ...", "phase": "ddl",
     "status": "executed", "mechanism": null, "table": null}
  ],
  "dropped": [
    {"intent": "partitioning:LINEITEM", "reason": "handled at load time"}
  ]
}
```

- **`applied_ledger_hash`** — `sha256` over the ordered list of
  *executed* statement records, serialized as canonical JSON
  (`sort_keys=True`, compact separators). List order is preserved (only
  each record's keys are sorted), so statement chronology is part of the
  identity. `null` when nothing executed (no physical layout to
  identify). Mirrored onto the bundle's `platform.tuning` summary and the
  `.tuning.json` companion next to `requested_config_hash`.
- **`phase`** ∈ {`ddl`, `post_load`, `session`}; statement `status` ∈
  {`executed`, `failed`}. `dropped` records requested intents that never
  rendered to a statement (capability-filtered / load-time-only).

`tuning_validation_status` vocabulary (execution-derived, all-lowercase),
replacing the old metadata-write proxy where `APPLIED` meant only "a
metadata INSERT succeeded":

| status | meaning |
| --- | --- |
| `not_applicable` | tuning disabled, or no effective configuration |
| `noop` | tuning requested but the execution path ran no statement |
| `applied_unverified` | ≥1 statement executed; self-attested, not yet introspection-corroborated. A session-only ledger retains this status. |
| `applied_verified` | executed **and** corroborated by a post-load introspection receipt; every physical statement must corroborate, with no failed ddl/post_load statement or dropped intent. Only the receipt path emits it; never the ledger alone. |
| `failed` | ≥1 ddl/post_load statement was attempted and all such statements failed, even if a session statement executed; or the apply path raised |
| `not_validated` | dataclass default, pre-run (before any derivation) |

Metadata-persistence outcome is **no longer** a tuning status: the old
`FAILED_TO_SAVE` is downgraded to the separate boolean
`tuning_metadata_saved` note, fully decoupled from the tuning status.

Legacy back-compat readers map old uppercase statuses via
`LEGACY_STATUS_MAP`: `NOT_APPLICABLE→not_applicable`,
`APPLIED→applied_unverified`, `FAILED_TO_SAVE→applied_unverified` (both
old values meant "a statement executed" under the new model), and
`NOT_VALIDATED→not_validated`.

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

## Addendum (2026-07-23): drift-validation bundle routing

`tuning-drift-validation-bundle-routing-20260722` asked where the rerun
**drift-validation** result belongs in the published bundle. When a run
reuses an existing database, `TuningValidator` compares the database's
persisted tuning metadata against the expected
`UnifiedTuningConfiguration` (`platforms/base/tuning_config.py`
`_validate_database_tunings` → `MetadataValidationResult`). That result
was previously computed and then dropped — only the first three error
strings survived, as validation messages; the structured drift
(`drifted_sections`, `configuration_mismatches`, `missing_tables` /
`extra_tables`) never reached the bundle.

**Decision:** the drift-validation result rides in the existing
`.applied.json` companion (ADR §3) as an additive `drift_check` section —
**not** a new sibling file. This reuses the established companion (the
same file that already carries the applied-statement ledger and the
introspection receipt), matches the `MetadataValidationResult` docstring's
own anticipation of an "applied-ledger drift_check companion", and keeps
one place to look for "what actually happened to the database this run".

`drift_check` shape (`MetadataValidationResult.to_payload()`): `is_valid`
plus, when non-empty, `errors`, `warnings`, `missing_tables`,
`extra_tables`, `configuration_mismatches`, and `drifted_sections`. It is
**descriptive only** and is never a source of `applied_verified` — that
status remains reserved for post-load introspection corroboration.

Scope and honesty constraints:

- **Reused databases only.** A fresh database just persisted its metadata,
  so nothing could have drifted; `drift_check` is emitted only when
  `database_was_reused` and the run is tuned.
- **Empty-ledger carry.** A reused DB re-applies no tuning DDL, so its
  applied-statement ledger is empty. The companion is still written when a
  `drift_check` is present (the "nothing captured → no companion" prune in
  `build_applied_ledger_payload` is relaxed to keep a drift-only companion).
- **Anonymized exports.** `drift_check` free text (`errors` can embed an
  exception's path/DSN; `warnings` / `configuration_mismatches` /
  `missing_tables` / `extra_tables` can embed catalog/table identifiers) is
  dropped under the same policy as the statement/receipt text, leaving the
  structural `is_valid` + `drifted_sections` and a `drift_redacted` marker.

## Addendum (2026-08-01): introspection and fail-closed gating landed

The original Decision section recorded post-load introspection as a future
direction. It has since landed in `benchbox.core.tuning.introspection` and
`PlatformAdapter._corroborate_applied_ledger`; this addendum updates current
state without rewriting that historical decision.

`applied_verified` now requires at least one gate-relevant physical intent,
every such intent corroborated against structured catalog facts, and no failed
ddl/post_load statement or dropped tuning intent. Failures receive blocking
`unverifiable` receipt entries, while dropped intents are copied into the
receipt. The summary key is `gate_relevant_total` because it counts all verdicts
that participate in the decision, including fail-closed `unverifiable`; the
former `verifiable_total` name had no production consumer and was misleading.

The applied-ledger hash continues to preserve statement chronology: JSON object
keys are sorted for canonical serialization, but the executed-statement list is
never reordered. Post-load layout operations that do not pass through the
recording connection are folded into that list at their actual execution phase
before session statements, via
`PlatformAdapter._fold_layout_operations_into_ledger`.

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
