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

There is no deployed public Explorer that has advertised the documented
(wrong) format. Corpus rotations such as #1537 changed ids in git and CI
artifacts only. External bookmarks of `/results/r/{public_result_id}` do not
yet exist as a product surface.

The open questions that remain are when permanence freezes relative to
corpus motion, whether the written contract must match the mint, and whether
an alias/redirect table is required before first public deploy.

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
- Deliberately changing published bytes (privacy fix, schema projection,
  field-set drop) is allowed to change ids **until the first public deploy
  that treats Explorer URLs as a consumer contract**. After that deploy,
  any further rotation must either preserve ids for unchanged published
  bytes (the normal content-address path) or ship an explicit
  alias/redirect map for ids that change.
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

### 3. Alias / redirect before first public deploy: not needed

**No alias or redirect mechanism is required before the first public
Explorer deploy.**

Rationale:

1. The format mismatch lived in documentation only. Minted ids have always
   included `sha8` in code and unit tests.
2. No public product surface has served `/results/r/{id}` under either the
   wrong or the right format as a stable external contract.
3. Prior corpus-wide id rotations (#1537 and related privacy work) therefore
   had zero external link breakage cost.
4. Building redirect tables now would invent infrastructure for a consumer
   that does not exist yet.

**Trigger for revisiting:** the first release that publishes Explorer result
detail URLs as a documented, linkable public surface. After that point,
any id-changing re-derivation of already-public published bytes needs an
alias/redirect (or an explicit deprecation notice), decided in a follow-up
ADR or ops runbook change — not assumed free.

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
- First public deploy becomes the freeze line for external link stability;
  ops should treat post-deploy id rotations as a compatibility event.
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
| w2 | Alias/redirect = not needed until first public deploy (this section) |
