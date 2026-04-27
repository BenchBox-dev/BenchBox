# Phase 3 Ingest, Storage, and Derived Read-Model Architecture

This document defines the hosted-platform architecture for BenchBox
results: how a result enters the system, where it lives, what is
derived from it, and how the public explorer reads from it. It is
**not a Phase 1 or Phase 2 blocker** — Phase 1 (static, maintainer-
curated) and Phase 2 (PR-mediated) ship without any of this. This
document exists so that *when* the [Phase 3 promotion metrics][metrics]
fire, implementation has an unambiguous starting point.

[metrics]: ./phase-3-promotion-metrics.md
[strategy]: ../../docs/development/benchbox-results-platform-strategy.md

## Goals and non-goals

**Goals:**

- Separate the **mutable write path** (submitter authority, idempotent
  ingest, retries, deduplication) from the **read path** (public
  explorer, immutable, cacheable, rebuildable).
- Keep raw schema-v2 bundles immutable. They are the source of truth.
- Make every public artifact regeneratable from raw bundles plus
  durable metadata. No hidden state.
- Stay static-first on the read side: the explorer must remain a SPA
  that can run from CDN-cached assets without server roundtrips.

**Non-goals:**

- Real-time results streaming. Submissions are async-batched.
- A general analytics warehouse. We serve fixed read models, not
  ad-hoc SQL.
- Dual-write to multiple backends. One object store, one metadata DB.

## Reference architecture matrix

Three published reference points the architecture leans on. The "do" /
"don't" cells distill what's reusable for BenchBox specifically.

| Platform           | Bundle format       | Storage tier       | Idempotency model              | Public read surface       | Do                         | Don't                            |
|--------------------|---------------------|--------------------|--------------------------------|---------------------------|----------------------------|----------------------------------|
| **Geekbench**      | Proprietary `.gb*` blob; ID assigned server-side | Server-managed; private object store | New uploads always create new IDs; "claim" links the result to a user account | Stable per-result HTML pages with embedded chart data | Stable result pages, account-linked online management | Closed scoring model |
| **OpenBenchmarking** | XML profile + numeric runs | Centralized site storage | Submitter chooses an ID; collisions reject; ETag-based revalidation | Aggregated comparison views, machine-faceted browsing | Cohort-aware comparison, rich metadata, public/private policy | Day-1 open public firehose without curation |
| **CloudSpecs**     | Static-pipeline only (no submission API) | Git-tracked artifacts in a repo | N/A (no upload path) | Static SPA reading a bundled DuckDB snapshot | **Phase 1 reference**: static-first explorer with DuckDB-WASM | No-write-path assumptions for the whole product |

Lessons:

- Geekbench separates **submission identity** (transient upload event)
  from **result identity** (the public-permalink ID assigned at
  acceptance). BenchBox should do the same.
- OpenBenchmarking proves cohort-aware comparison and rich metadata
  scale to a meaningful corpus, but its day-1 public firehose is a
  cautionary tale — moderation and trust labeling are not optional.
- CloudSpecs is the **read-side template**: static SPA + DuckDB-WASM.
  We extend it with a write path, not a server-rendered explorer.

## submission API surface (write path)

Three endpoints. Authenticated. Returns 5xx for transient errors,
4xx for client errors, 2xx only on durable acceptance into the
ingest queue.

| Method | Path                            | Purpose                                             |
|--------|---------------------------------|-----------------------------------------------------|
| POST   | `/v1/submissions`               | Upload a schema-v2 bundle (multipart: bundle.json + optional companions) |
| GET    | `/v1/submissions/{submission_id}` | Poll status: `received` → `validating` → `accepted` / `rejected` |
| GET    | `/v1/submissions/{submission_id}/result` | Once accepted, returns the public `result_id` and permalink |

**Idempotency rules:**

- Each submission carries a client-supplied **`Idempotency-Key`** header
  (UUID). Re-submission with the same key returns the original
  `submission_id` regardless of body content. Server-side timeout: 24h.
- Within a single submission, the server computes the **content hash**
  (`bundle_hash`) of the canonical bundle. If a previous **accepted**
  submission has the same `bundle_hash`, the new submission is
  short-circuited to the existing `result_id`. The submitter sees a
  successful 200 with `duplicate: true`. This is what makes "submit
  again because the network blipped" safe.
- The Idempotency-Key handles "client retry of the same upload"; the
  bundle_hash handles "different submitter sends an identical
  bundle." Both paths converge on the existing public result.

**Bundle upload contract:**

- Multipart form: `bundle` (required, schema-v2 JSON), `plans` (optional
  `.plans.json`), `tuning` (optional `.tuning.json`),
  `submission_manifest` (required, signed envelope with submitter
  identity + content hashes).
- Maximum bundle size: enforce client-side at 10 MB (server checks
  the 50 MB hard cap defined in
  [`docs/reference/threat-model.md`][threat] under the submission-layer
  DoS mitigation). Larger bundles indicate a benchmark misuse; reject
  with a clear error pointing at scale-factor guidance.

[threat]: ../../docs/reference/threat-model.md
- The service **does not** repackage the bundle. Bytes-as-received are
  what land in storage. Hash check on receipt; mismatch rejects the
  submission with the offending file path.

## Raw bundle storage model

**Where:** S3-compatible object storage (R2 default, S3 fallback).
Buckets:

- `benchbox-bundles-raw-prod`: immutable raw bundles. Never overwritten.
- `benchbox-bundles-raw-quarantine`: bundles that failed validation;
  retained 30d for debugging then expired.
- `benchbox-derived-prod`: rebuildable read models (manifests, snapshot,
  projections). Treated as ephemeral cache.

**Object key scheme** — three-tier so renames don't break permalinks:

```
benchbox-bundles-raw-prod/
  {bundle_hash[0:2]}/{bundle_hash}/
    bundle.json
    plans.json (optional)
    tuning.json (optional)
    submission-manifest.json
```

Notes:

- Keys are **content-addressed** by SHA-256 of the canonical bundle. A
  rename of a benchmark or platform does not change the storage key.
- The two-character prefix is for object-store sharding only; many
  S3-compatible stores list keys lexicographically per prefix.
- Companions live alongside the bundle so a single key prefix
  retrieves the full submission.
- Submission identity (`submission_id`, an opaque UUID) and result
  identity (`result_id`, the public-permalink slug) are tracked in
  the metadata DB, **not** in the object key. They have different
  lifecycles (rebuilds, takedowns, re-attribution).

**Retention tiers:**

- Raw accepted bundles: indefinite. Storage cost is bounded by
  contributor submission rate; the metrics doc's volume threshold
  ($50/mo sustained) at 5 MB average = 3 GB/year, ~$0.06/mo at R2 list
  prices.
- Quarantined (failed validation) bundles: 30 days. Long enough for
  debugging; short enough to avoid hoarding obvious junk.
- Derived read models: rebuildable, so retention is "as long as
  rebuild infra exists". Bucket lifecycle: nothing pinned.

**Integrity properties:**

- Every accepted bundle has its SHA-256 stored in the metadata DB
  alongside the storage key. The validator script
  (`scripts/validate_submission.py`) computes the hash on receipt and
  rejects mismatches before the object is committed to the
  `*-raw-prod` bucket.
- Cross-region replication: out of scope for Phase 3. R2 is multi-AZ
  by default; that's adequate for the launch corpus.

## Durable metadata schema

PostgreSQL — managed (Fly.io Postgres or Supabase free tier at
launch). Tables below are the public-facing slice; full DDL is a
follow-up implementation deliverable.

```
actor                              -- one row per submitter (human or bot)
  actor_id          uuid pk
  display_name      text not null
  primary_identity  text not null  -- e.g., 'github:joeharris76'
  trust_tier        text not null check (trust_tier in
                                          ('community-self-reported',
                                           'community-curated',
                                           'maintainer-verified'))
  created_at        timestamptz not null

submission                         -- one row per accepted upload event
  submission_id     uuid pk
  actor_id          uuid not null references actor
  idempotency_key   uuid not null
  bundle_hash       bytea not null
  storage_key       text not null  -- the raw-prod object key prefix
  state             text not null check (state in
                                         ('received','validating',
                                          'accepted','rejected'))
  validation_error  text
  received_at       timestamptz not null
  finalized_at      timestamptz
  unique (idempotency_key)

result                             -- one row per accepted bundle (deduped by hash)
  result_id         text pk        -- public slug, e.g.,
                                   --   'tpch-duckdb-sf001-2026q2-7a2b'
  bundle_hash       bytea not null unique
  benchmark_id      text not null  -- 'tpch','tpcds','ssb',...
  scale_factor      numeric(10,4) not null
  platform_name     text not null  -- 'duckdb','clickhouse-cloud',...
  platform_version  text
  primary_actor_id  uuid not null references actor
  visibility        text not null check (visibility in
                                          ('public','unlisted','private'))
  trust_label       text not null  -- denormalized from actor at accept time
  geomean_ms        numeric
  power_score       numeric
  total_duration_s  numeric
  created_at        timestamptz not null

cohort_membership                  -- many-to-many: result <-> cohort
  result_id         text references result
  cohort_id         text references cohort
  primary key (result_id, cohort_id)

cohort                             -- saved comparison sets
  cohort_id         text pk
  benchmark_id      text not null
  scale_factor      numeric(10,4) not null
  description       text
  curated_by        uuid references actor
  created_at        timestamptz not null
```

**Why this shape:**

- Three identities — `submission_id` (event), `bundle_hash` (content),
  `result_id` (public) — never collapse. Attempting to use one for two
  purposes is the leading anti-pattern called out in the TODO.
- `result.visibility` is enforced at the **API layer** (the read
  endpoints filter on it) and at the **storage layer** (private
  bundles never enter the public derived read models). UI badges
  alone are insufficient; per the must_preserve from #9.
- `trust_label` is denormalized onto each result so a later actor
  trust-tier change does not silently rewrite history. Promotion to a
  higher trust tier creates new derived snapshots; it does not mutate
  prior labels.

## Derived public read models

Built by an async worker after `submission.state -> accepted`. All
outputs are **rebuildable from `raw-prod` + the metadata DB** at any
time. None of these are source of truth.

| Artifact                                      | Format    | Audience                       | Rebuild trigger                                    |
|-----------------------------------------------|-----------|--------------------------------|----------------------------------------------------|
| `manifests/results.json`                      | JSON      | Explorer index page            | Any new accepted result                            |
| `manifests/cohorts/{cohort_id}.json`          | JSON      | Explorer cohort/compare pages  | Membership change in the cohort                    |
| `details/{result_id}.json`                    | JSON      | Explorer result-detail page    | Per-result, on-accept; immutable thereafter        |
| `snapshot/results.duckdb`                     | DuckDB    | Browser-side analytics (DuckDB-WASM) | Daily rebuild; on-demand for cohort changes  |
| `meta_leaderboard.json`                       | JSON      | Home page leaderboard          | Any new accepted result                            |

**DuckDB vs Parquet tradeoff** — settled in favor of DuckDB
specifically for this workload:

- DuckDB-WASM already attaches `results.duckdb` and queries it
  directly from the explorer (`results-explorer/src/db.ts`). Parquet
  alone would force a second runtime in the browser and lose the
  ability to do JOINs across cohort tables in a single query.
- A single ~10MB DuckDB snapshot replaces what would be ~7 separate
  Parquet files plus a query layer. Net bandwidth lower at the seed-
  corpus size.
- The RG-2 byte-budget gate (cold load ≤10% of snapshot) is currently
  blocked on duckdb-wasm upstream (see TODO `enable-duckdb-wasm-http-
  range-reads-for-registered-urls`). Once unblocked, DuckDB wins on
  bandwidth too: a single result-detail page reads ~1% of the
  snapshot via range-reads, vs. fetching a per-page Parquet file.

**Incremental update strategy:**

- `details/{result_id}.json` is per-result and never rewritten.
- `manifests/*.json` and `meta_leaderboard.json` are small (<1MB).
  Full rebuild is cheaper than diff-update plumbing.
- `snapshot/results.duckdb` is built incrementally **only when**
  rebuild time crosses 60 seconds. Below that, full rebuild from
  metadata is simpler and verifiably correct. The threshold is a
  build-time observation, not a Phase-3 launch concern.

## Deployment topology

Three deployment surfaces, mapped to concrete services:

| Surface                  | Purpose                                  | Default service       | Lifetime           |
|--------------------------|------------------------------------------|-----------------------|--------------------|
| **API service**          | Authenticated submission endpoints       | Fly.io shared 1x      | Long-lived         |
| **Async ingest worker**  | Validates, hashes, persists, kicks rebuild | Fly.io worker (low CPU) | Triggered          |
| **Object storage**       | Raw bundles + derived read models        | Cloudflare R2         | Persistent         |
| **Metadata database**    | PostgreSQL                               | Fly.io Postgres or Supabase | Persistent  |
| **Static explorer**      | SPA, served from CDN                     | GitHub Pages (existing) | Persistent       |

**Cost model at launch volume** (50 PRs/mo when promotion fires):

| Component         | Cost (low-volume launch) | Notes                                       |
|-------------------|--------------------------|---------------------------------------------|
| API service       | $5–20/mo (shared 1x)     | Single small instance; not autoscaled       |
| Worker            | $0–5/mo                  | Triggered runs only; idle most of the time  |
| Object storage (R2) | <$1/mo                 | 10 MB/result × 50/mo = 500 MB/mo growth     |
| Postgres          | $15/mo (smallest paid)   | Free tier acceptable for first 6 months     |
| Auth provider     | $0                       | API keys self-managed; OAuth deferred        |
| Monitoring        | $0                       | Fly metrics + Sentry free tier               |

**Total: $20–40/mo**, comfortably below the strategy doc's
$40–225/mo upper-bound estimate. The headroom is intentional — the
"would Phase 3 be worth it" question is sharper if we don't blow the
budget on day one.

## Backfill, rebuild, retention, and failure recovery

**Rebuild triggers:**

| Trigger                              | Action                                         |
|--------------------------------------|------------------------------------------------|
| `submission.state -> accepted`       | Rebuild `manifests/results.json`, `meta_leaderboard.json`, `details/{result_id}.json`. Rebuild `snapshot/results.duckdb` no more often than once per hour (debounce). |
| Cohort membership change             | Rebuild affected `manifests/cohorts/{cohort_id}.json` only. |
| Result visibility change (public ↔ unlisted) | Full read-model rebuild. Visibility changes are rare; correctness > speed. |
| Trust-tier promotion                 | Full read-model rebuild with new `trust_label`. |
| Manual `make rebuild-derived`        | Used for schema migrations and bug recovery. Idempotent. |

**Backfill** — replaying ingest from raw bundles:

- The metadata DB is the source of identity; `raw-prod` is the source
  of content. Backfill walks `raw-prod`, re-validates each bundle,
  and rebuilds the metadata + derived models. This is **how
  rollback works**: the platform survives metadata loss as long as
  `raw-prod` is intact.
- Backfill must be re-runnable safely. The ingest pipeline is
  idempotent on `bundle_hash`, so a backfill cannot create duplicate
  results.

**Retention** — already documented in the storage section.
Quarantine bucket has a 30-day lifecycle policy; `raw-prod` has none.

**Failure-recovery procedures:**

| Failure class                               | Detection                                      | Recovery                                                                              |
|---------------------------------------------|------------------------------------------------|---------------------------------------------------------------------------------------|
| Corrupted derived read model                | Smoke test fails (`scripts/verify-derived.py`) | `make rebuild-derived` from raw + metadata. No raw bundle is touched.                 |
| Failed submission stuck in `validating`     | TTL of 1h on the validating state              | Worker promotes to `rejected` with a `timeout` error; submitter retries. Idempotency key prevents duplicates. |
| Schema-v2 → v3 migration                    | Migration runs in a controlled rebuild         | New worker version reads v2, writes v3. Old derived read models retired only after the new ones pass smoke tests. |
| Metadata DB lost                            | Backups restored or backfill from `raw-prod`   | Backfill from `raw-prod` + the most recent backup. RPO target: 24h. RTO: 4h.          |
| Object storage outage                       | API returns 503 to new submissions             | The validator stops accepting; idempotency keys cached so submitters can retry safely. |
| Trust-promotion error (wrong actor labeled) | Audit log review                               | Manual `result.trust_label` rewrite + full rebuild. Auditable in the Postgres history table. |

## Migration path from Phase 2

Phase 2 is the PR-mediated `published-results` branch. Phase 3 reuses
its raw bundles unchanged: the same schema-v2 JSON files that live in
`results-data/bundles/` today are valid raw bundles for Phase 3
ingest. The migration is a one-time backfill, not a rewrite:

1. Walk `results-data/bundles/` on `published-results`.
2. For each primary bundle, compute `bundle_hash`, copy to
   `raw-prod`, insert a `submission` row with
   `actor_id = "phase-2-import"` and `state = "accepted"`.
3. Generate `result_id` slugs using the existing inventory's
   conventions to preserve any in-the-wild URLs.
4. Build derived read models from the populated metadata.
5. Cut over the explorer to read from the hosted derived models.
6. Leave Phase 2 PRs working in parallel for a soak window — both
   paths produce valid raw bundles, neither is privileged.

The `published-results` branch does not get retired. It remains the
source of truth for maintainer-curated submissions and the audit
trail for Phase 2's first year. Phase 3 is additive.

## What's intentionally not in this design

- **Realtime websockets.** Submissions are async; the CLI polls.
- **Search.** "What benchmarks has DuckDB run?" is a UI affordance,
  not an architectural primitive. The metadata schema supports it;
  the read model doesn't surface a search index.
- **Versioned APIs beyond v1.** v1 is the only contract until
  reasoned otherwise.
- **Multi-tenant org spaces.** Tracked separately under the
  Phase 3 promotion metric M6. If org-space demand crosses the
  threshold, scope adds; until then, single-tenant.

## Open questions for review

| # | Question                                                                                          | Default if no review answer                                |
|---|---------------------------------------------------------------------------------------------------|------------------------------------------------------------|
| 1 | Is OAuth (GitHub) required at launch, or are personal API keys acceptable for a private beta?      | Personal API keys at launch; OAuth in M6 promotion         |
| 2 | Should `result_id` slugs be human-readable (`tpch-duckdb-sf001-2026q2-7a2b`) or opaque?            | Human-readable; opaque suffixes only on collision          |
| 3 | Does the explorer pin a specific `snapshot/results.duckdb` revision, or always read latest?        | Always read latest; cache-bust on rebuild                  |
| 4 | Should private/unlisted results be eligible for cohort comparisons against public ones?            | No; visibility filtering happens before cohort assembly    |
| 5 | What's the path for retracting a published result? (Trust drop is one mechanism; outright takedown is another.) | Trust-drop only at launch; takedown via admin path in M3 of the moderation runbook |

These defaults are wired into the design above. Reviewer overrides
become acceptance criteria for the implementation TODOs.

## Implementation TODOs unblocked by this design

- `integrate-benchbox-cli-submit-and-service-auth` — uses the
  submission API surface defined here.
- `operate-results-platform-security-observability-and-abuse-controls`
  — uses the deployment topology and metadata schema defined here.
- (Future) `implement-phase-3-ingest-worker` — owns the async
  worker pipeline.
- (Future) `implement-phase-3-derived-read-model-builder` — owns
  the read-model rebuild logic.
- (Future) `migrate-phase-2-bundles-to-phase-3` — runs the one-time
  backfill from `published-results`.

These TODOs are not active. They become active when the Phase 3
[promotion metrics][metrics] fire.
