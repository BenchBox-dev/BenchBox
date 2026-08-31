# ADR: `public_result_id` permanence attaches at publication

- Status: Accepted
- Date: 2026-08-05
- Supersedes the informal format and collision rules previously stated in
  `docs/reference/hosted-results-contract.md` §1.1 (and the Phase 1 line in
  `docs/development/benchbox-results-platform-strategy.md` Result Identity).
- Constrains: explorer publication pipeline
  (`_project/scripts/explorer_pipeline/`), hosted results contract,
  and any future alias/redirect surface for public result URLs.

## Context

`docs/reference/hosted-results-contract.md` documented `public_result_id` as
permanent once minted, with format:

```text
{benchmark}-{platform}-sf{scale_factor}-{date}
```

and collisions resolved by appending `-{n}`. That is not what the pipeline
mints.

What is actually minted (see
`BundleTransformer.result_id_from_bundle` in
`_project/scripts/explorer_pipeline/transformer.py`):

```text
{benchmark}-{platform}-sf{scale_factor}-{yyyymmdd}-{sha8}
```

where:

| Segment | Source |
|---|---|
| `benchmark` | published bundle `benchmark.id` |
| `platform` | published bundle `platform.name`, lowercased, spaces → `-` |
| `scale_factor` | published bundle `benchmark.scale_factor` (stringified as in Python `f"{value}"`) |
| `yyyymmdd` | first 10 chars of `run.timestamp`, hyphens stripped |
| `sha8` | first 8 hex chars of `sha256(published_bytes)` |

**Published bytes** means the anonymized, canonical-JSON bytes that land under
`bundles/{result_id}.json` — not the raw source bundle. The pipeline derives
the id only after `_public_bundle_data` / `canonical_json_bytes`
(`pipeline.py`); that order is pinned by
`tests/unit/scripts/explorer_pipeline/test_result_id_contract.py`.

Because the id is content-addressed over published bytes:

- every re-derivation of the corpus that changes published content (for
  example anonymization field-set or salt changes) rotates every id;
- identical published content re-derives the same id (idempotent republish);
- two distinct published payloads that collide on the 32-bit `sha8` prefix
  are a hard failure (`DuplicateResultIdError`), not a silent `-{n}` rename.

The current public Explorer serves result detail URLs, so the earlier pre-deploy
assumption is stale. Link permanence attached when those routes first became publicly
available to consumers. The A0 observed-site baseline is the preservation floor for the
currently served corpus; future attested live receipts provide stronger, generation-specific
proof without postponing compatibility for URLs that are already public.

The remaining operational question is which ids belong to each later receipt-backed
generation. The A0 observed baseline already protects the currently served ids. The
written format and collision contract remain authoritative, and alias or redirect
handling follows the compatibility rule below.

## Decision

### 1. Permanence attaches at publication

**A `public_result_id` is permanent for a given set of published bytes once
those bytes are part of a public Explorer corpus that consumers may link
to.** It is a content-addressed id of the published artifact, not a
stable label for an ephemeral local run, a private bundle path, or a
pre-anonymization capture.

Consequences:

- Local run ids, capture filenames, and private machine paths never become
  the public id.
- Re-deriving the same published bytes yields the same id (content
  address).
- Deliberately changing published bytes (privacy fix, schema projection, field-set drop)
  after their result route has become public is a compatibility event. It must either
  preserve ids for unchanged published bytes (the normal content-address path) or ship
  an explicit alias/redirect map for ids that change.
- Permanent does **not** mean "immune to content change." It means "the same
  published bytes always map to the same id, and once that id is live in
  the public product, links keep resolving."

### 2. Document the actual minted format (including `sha8`)

The authoritative format is:

```text
{benchmark}-{platform}-sf{scale_factor}-{yyyymmdd}-{sha8}
```

Example: `tpch-duckdb-sf1.0-20260315-a1b2c3d4`

Collision handling in the publication pipeline (Phase 1 static corpus):

| Case | Behavior |
|---|---|
| Same `result_id`, identical published digest | Skip as redundant; publish once |
| Same `result_id`, differing published digest | Fail closed with `DuplicateResultIdError` |

The older contract claim that the minting service appends `-{n}` is
**rejected** for the Phase 1 pipeline. Content addressing already
separates distinct payloads in the common case; a 32-bit prefix collision
is treated as a build error so evidence is not silently dropped or
renamed under a non-content-addressed suffix. A Phase 3 concurrent mint
service may need a different concurrency story, but it must not invent a
format that diverges from this slug without a new ADR.

`public_result_id` in the hosted contract and `result_id` in the explorer
pipeline refer to the same slug today.

### 3. Alias / redirect at the public-link boundary

No alias or redirect mechanism was required before result detail routes were publicly
available. The public Explorer now serves those routes, so operators must treat the A0
observed corpus and every later receipt-backed generation as external compatibility
surfaces.

Rationale and current posture:

1. The format mismatch lived in documentation only. Minted ids have always included
   `sha8` in code and unit tests.
2. Rotations completed before the first public Explorer deployment needed no redirect
   table because consumers could not yet link to those routes.
3. The public Explorer now serves result detail routes. The A0 observed baseline protects
   currently served ids, and later live receipts identify the exact ids in each promoted
   generation.
4. Redirect or deprecation handling is required only for affected already-public ids, not
   invented retroactively for artifacts that were never publicly served.

**Trigger now in force:** any id-changing re-derivation of bytes whose result route has
already been publicly served needs an alias/redirect or an explicit deprecation notice,
decided in a follow-up ADR or operations change. The A0 observed baseline proves the
initial protected surface; later attested receipts prove subsequent generations. Branch
or workflow state alone never proves public availability.

## Alternatives rejected

| Alternative | Why rejected |
|---|---|
| Permanence attaches at local run / commit of private capture | Private bytes and paths are not the public artifact; hashing them would fingerprint non-public content and diverge from downloadable bundles |
| Keep format without `sha8` and resolve collisions with `-{n}` | Diverges from implemented mint; sequential suffixes are not content-addressed and break deterministic re-derivation |
| Freeze ids independently of content (assign once, never recompute) | Loses verifiability ("anyone holding the published bundle can recompute the id") and forces a registry service before Phase 1 needs one |
| Ship alias/redirect tables now for pre-deploy rotations | No external links to protect; cost without benefit |

## Consequences

- `docs/reference/hosted-results-contract.md` must describe the `sha8`
  format and fail-closed / skip-identical collision rules.
- Explorer pipeline code remains the mint authority; docs follow code.
- Content-addressed permanence is preserved (must-preserve for this TODO).
- Attested live publication becomes the freeze line for external link stability;
  ops should treat post-receipt id rotations as a compatibility event.
- Strategy doc identity table remains non-authoritative relative to this
  ADR and the hosted contract (out of scope for the immediate contract fix;
  update when that doc is next edited for identity).

## Prior art

| Path | Role | Decision |
|---|---|---|
| `_project/scripts/explorer_pipeline/transformer.py` (`result_id_from_bundle`, `_sha256_prefix`) | Mint implementation | Extend docs to match; no code change |
| `_project/scripts/explorer_pipeline/pipeline.py` (id after `public_raw`, `DuplicateResultIdError`) | Publication boundary and collision policy | Keep; document |
| `tests/unit/scripts/explorer_pipeline/test_result_id_contract.py` | Pins hash-of-published-bytes | Keep |
| `tests/unit/scripts/explorer_pipeline/test_transformer.py` (`TestResultIdFromBundle`) | Pins format including 8-hex suffix | Keep |
| `docs/reference/hosted-results-contract.md` §1.1 | Public contract (was wrong) | Correct |
| `docs/development/adr/adr-published-identifier-field-set.md` | What fields enter published bytes | Orthogonal; field-set changes still rotate ids pre-deploy |

## Work units

| Unit | Outcome |
|---|---|
| w0 | This ADR |
| w1 | Contract format + collision text aligned with mint |
| w2 | Post-live id rotation requires explicit compatibility handling (this section) |
