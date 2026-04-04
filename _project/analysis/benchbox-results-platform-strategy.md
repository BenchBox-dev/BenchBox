# BenchBox Results Platform Product + Architecture Strategy

**Created:** 2026-03-29
**Revised:** 2026-03-30
**Originating TODO:** `productize-result-publishing-and-artifact-sharing`

## Executive Summary

BenchBox should not treat local artifact publication, hosted result submission,
and public result analysis as one feature. They are adjacent, but they have
different product contracts, trust models, and operational requirements.

Recommended split:

1. `benchbox publish`
   Local/cloud artifact publication. Publishes canonical result bundles to
   local or cloud storage (S3, R2, etc.). Does not interact with the hosted
   results platform or public corpus.
2. `benchbox submit`
   Public corpus contribution. Packages a canonical bundle with a submission
   manifest and either prepares a PR against `results-data/` (Phase 2) or
   uploads directly to the hosted API (Phase 3).
3. `benchbox.dev/results/`
   A static-first public explorer for browsing, comparing, and analyzing
   curated public results.

### Phase 1 Status: Launched (2026-04-04)

Phase 1 is complete. The static explorer at benchbox.dev/results/ is deployed
with a seed corpus of 6 bundles across 2 cohorts (TPC-H SF 0.01, SSB SF 0.01),
each with ≥3 platforms. All launch criteria from the checklist below were met.

### Revised Launch Phases

| Phase | Goal | Write Path | Infrastructure | Priority |
| --- | --- | --- | --- | --- |
| **1: Static Explorer MVP** | Curated seed corpus + read-only explorer at `benchbox.dev/results/` | Maintainer-only: CI-generated results committed under `results-data/` in this repo | Static only: GitHub Pages, no API, no auth, no hosted services | **Ship first** |
| **2: Community Contributions** | Community-submitted results via PR-based workflow | PRs against `results-data/` in this repo with CI validation + automated ingestion | Still static: GitHub Actions validates + merges + rebuilds; extract to a dedicated data repo only if churn justifies it | **Ship when Phase 1 UX is proven** |
| **3: Hosted Platform** | Self-service submission API, org/team spaces, richer features | Hosted API + object storage + async ingest | API server, metadata DB, auth, rate limiting, moderation | **Only if demand warrants the operational burden** |

### Key Architecture Decision

**Phase 1 and Phase 2 require zero backend services.** The entire read path is
static (derived JSON manifests + DuckDB/Parquet snapshots served via GitHub
Pages). The write path is git + CI/CD inside this repository
(`results-data/` → transform → build → deploy).

A hosted API (Phase 3) is explicitly deferred. The "submit via PR" model used by
many successful open-source benchmark databases (e.g., js-framework-benchmark,
ClickBench contribution model) proves that community contributions scale well
without a custom API until volume demands one.

## Product Intent and Positioning

### Core Hypothesis

"People want to browse and compare public benchmark results across platforms."
This is the primary value proposition that Phase 1 must validate.

### Target Audience

The broader data/analytics community — not just existing BenchBox users. The
explorer is a credibility and marketing play: transparent, reproducible,
multi-benchmark results that visitors can explore and compare themselves.

### Differentiator vs ClickBench

ClickBench covers a single workload in a single format. BenchBox's explorer
differentiates on three axes:

1. **Multi-benchmark coverage** — TPC-H, TPC-DS, SSB, and future benchmarks in
   one place, not siloed sites
2. **Rich per-query detail** — execution plans, tuning configurations, validation
   status, companion files
3. **Reproducibility** — any published result can be re-run with `benchbox run`
   using the same parameters

ClickBench was considered and rejected because its format cannot capture what
BenchBox measures (items 2 and 3 above).

### Explorer as Dynamic Tool

The explorer is a **dynamic comparison tool**, not a static shootout page.
Visitors pick benchmark, scale factor, and platforms to build their own
comparisons. This is the core UX — not a curated leaderboard.

### Corpus Size and DuckDB-WASM Justification

The benchmark × platform × scale matrix is large even at launch. Phase 1 should
cover most supported benchmarks and platforms at limited scale factors. DuckDB-WASM
is justified because:

- The corpus needs to be large enough for a dynamic tool to be useful
- It will grow quickly as new platforms and benchmarks are added
- It demonstrates BenchBox's DuckDB expertise (audience alignment)

The primary corpus criterion is **depth per benchmark**: each included benchmark
must have ≥3 comparable platforms at the same scale factor. The ≥30 total bundle
count is a secondary estimate that falls out of the coverage matrix, not an
independent target. Depth is the right primary target because the core deliverable
is a comparison tool — a cohort needs multiple platforms at the same scale to be
meaningful, regardless of total bundle count.

### Visual Identity and Build Pipeline

The explorer is a standalone Vite app with its own build pipeline, but shares the
benchbox.dev visual identity (header, nav, styling). It is not embedded in the
docs or blog — it is a distinct feature of the site.

### SEO

Search engine discoverability is nice-to-have but not a launch blocker. Users
will primarily arrive through benchbox.dev directly. Pre-rendering can be added
post-launch if organic traffic becomes a goal.

### Timeline

No hard deadline or external event. Quality over speed.

### Brand Decision

**Resolved 2026-04-03**: The results explorer lives at `benchbox.dev/results/` under
the BenchBox brand. See
[`_project/analysis/brand-ownership-decision.md`](brand-ownership-decision.md) for
the full decision rationale.

**Summary**: Oxbow Research has no independent web presence, domain, or active product
identity — it was an earlier brand concept that was deliberately separated from
BenchBox in git history. The explorer's core value proposition (reproducible results,
`benchbox run` re-execution) is inseparable from BenchBox, making BenchBox placement
the coherent choice. The working default is confirmed; no changes to existing
scaffolding or CI/CD are needed.

## Phase 1 MVP Definition

### Primary Deliverable: Dynamic Comparison Tool

The core UX of Phase 1 is a **dynamic comparison tool** where visitors pick a
benchmark, scale factor, and platforms, then see a side-by-side query-level
timing breakdown. This is the feature that differentiates the explorer from a
file listing, makes users come back and share links, and validates the core
hypothesis ("people want to browse and compare public benchmark results").

All other Phase 1 deliverables (home page, browse pages, detail pages) exist to
support navigation into and out of comparisons. They are necessary but secondary.

### What Ships

| Component | Role | Description | Done When |
| --- | --- | --- | --- |
| **Compare view** | **Primary** | Dynamic comparison tool: pick benchmark/scale/platforms, see side-by-side query-level timing breakdown with cohort validation | Compare works for any compatible results in the corpus; shareable URLs |
| **Seed corpus** | Data | Result bundles with depth per benchmark (many platforms at key scale factors) rather than just breadth | Bundles exported, validated, committed under `results-data/bundles/` |
| **Static build pipeline** | Data | Transforms canonical schema-v2 bundles into navigation manifest JSON, per-result detail JSON, and DuckDB database snapshot | Pipeline runs in CI, output deployed to GitHub Pages |
| **Explorer home + browse** | Navigation | Landing page with summary cards; benchmark and platform index pages with filterable result lists and "compare" checkboxes | Users can navigate to any result and select results for comparison |
| **Result detail page** | Supporting | Stable URL per result showing metadata, query timings, validation status, and raw bundle download | Detail page works for all seed corpus results |
| **DuckDB-WASM filtering** | Interaction | Client-side filtering by benchmark, platform, scale factor, date range | Filters work over the full corpus |
| **GitHub Pages integration** | Deployment | Explorer builds and deploys alongside existing landing + docs + blog | Single `git push` to `main` deploys everything |

### What Does NOT Ship in Phase 1

- No user accounts, authentication, or authorization
- No hosted submission API or `benchbox submit` command
- No anonymous or community uploads
- No branded "leaderboard" page, but cohort views may be sorted by total duration
  or geometric mean — this is a sorted table within a validated cohort, not a
  cross-context ranking claim
- No organization accounts or private workspaces
- No moderation, trust labels, or abuse controls (not needed — corpus is maintainer-curated)

### Launch Criteria

1. Seed corpus has sufficient depth for the dynamic comparison tool to show
   meaningful cross-platform comparisons: each included benchmark has ≥3
   comparable platforms at the same scale factor
2. Compare view is the primary entry point and works end-to-end: select
   benchmark/scale/platforms → see query-level timing breakdown → share URL
3. All explorer pages render correctly with real data
4. DuckDB-WASM filtering works in Chrome, Firefox, Safari
5. GitHub Pages deployment succeeds end-to-end from CI
6. Explorer is navigable from the existing benchbox.dev site header/nav
7. Brand ownership decision is resolved and reflected in domain/hosting/identity

## Phase 2: Community Contributions (Deferred)

### Model: Submit via Pull Request

Instead of building a hosted API, Phase 2 uses a PR-based contribution model:

1. Contributor runs `benchbox submit --output ./submission/` which packages
   the canonical schema-v2 bundle with a submission manifest (contributor
   metadata, benchmark context, optional notes)
2. Contributor opens a PR against this repository touching `results-data/`
3. GitHub Actions CI validates: schema conformance, bundle integrity (hash check),
   cohort compatibility, and basic sanity checks (no absurd timings, valid platform)
4. Maintainers review and merge
5. Merge triggers rebuild of derived read models + redeploy of explorer

A dedicated `benchbox-results` repository remains an optional future extraction
if corpus size or contribution volume starts to overwhelm the main repo. It is
not a Phase 1 or early Phase 2 requirement.

### Why PR-Based Before API-Based

| Concern | PR model | API model |
| --- | --- | --- |
| Auth | GitHub identity (free) | Custom auth system (build + operate) |
| Moderation | PR review (familiar, auditable) | Custom moderation UI (build + operate) |
| Abuse prevention | PR rate = human rate | Rate limiting, quotas, captchas |
| Trust labels | Commit author = attribution | Custom trust promotion workflow |
| Operational cost | Zero (GitHub Actions) | API server + DB + storage + monitoring |
| Scalability ceiling | ~100s of submissions/month | Thousands+/month |

The PR model is sufficient until submission volume exceeds what maintainer review
can handle. That threshold is unlikely in the first year of a results platform.

### What Ships in Phase 2

- `benchbox submit` command to package and submit results to the public corpus
- Submission manifest schema (contributor, context, notes)
- CI validation workflow for the data repository
- Trust labels in explorer: "maintainer" vs "community-submitted"
- Contributor guidelines documentation

## Phase 3: Hosted Platform (Deferred)

Phase 3 is explicitly contingent on Phase 2 reaching a scale where the PR model
becomes a bottleneck. Indicators that Phase 3 is needed:

- Submission volume exceeds ~50/month sustained
- Maintainer review becomes a sustained bottleneck
- Users need private/unlisted results (not possible in a public repo)
- Organization/team features are requested by paying or strategic users

### What Would Ship in Phase 3

- Hosted submission API at `api.benchbox.dev`
- Authentication (API keys, OAuth)
- Private and unlisted visibility states
- Automated trust promotion workflow
- Rate limiting, quotas, abuse controls
- Organization/team spaces
- Richer APIs and embedded widgets

### Cost and Operational Complexity

A hosted platform requires:

| Component | Estimated Cost | Operational Burden |
| --- | --- | --- |
| API server (e.g., Fly.io, Railway) | $20-100/mo | Deployment, monitoring, on-call |
| Metadata database (Postgres) | $15-50/mo | Backups, migrations, scaling |
| Object storage (S3/R2) | $5-20/mo | Lifecycle policies, access control |
| Auth provider (Auth0/Clerk) | $0-25/mo | Token management, session handling |
| Monitoring (Sentry, metrics) | $0-30/mo | Alert triage, incident response |

**Total: $40-225/month + significant engineering time.** This is only justified
if the results platform becomes a core product with sustained community usage.

## Current BenchBox Constraints

| Constraint | Evidence | Strategy implication |
| --- | --- | --- |
| Canonical results already exist as schema-v2 bundles with companion files | `benchbox/core/results/exporter.py` | All downstream paths ingest the real exported bundle, not a second payload |
| Public site is currently static GitHub Pages assembled from landing + docs + blog | `.github/workflows/docs.yml`, `docs/conf.py` | The public explorer must be a static subsite — no server dependency |
| BenchBox already hints at a hosted service contract | `_project/specs/cli/config.md` documents `submit_to_service` and `service_url` | CLI public submission (`benchbox submit`) is a legitimate future direction, but Phase 1 does not require it |
| Existing publishing prototype is process-local | `benchbox/core/publishing/artifacts.py`, `benchbox/core/publishing/permalink.py` | The prototype is not the hosted service architecture; it is only a source of reusable concepts |

## Reference Matrix

| Reference | Strong pattern | What BenchBox should copy | What BenchBox should not copy |
| --- | --- | --- | --- |
| Geekbench | Stable public result pages, comparison flows, account-linked online result management, offline vs online distinction | Stable result detail pages, obvious compare actions, explicit separation between local results and hosted results | A closed scoring model or consumer-device-centric assumptions |
| CloudSpecs | Static browser app, GitHub Pages hosting, browser-side DuckDB-WASM analysis over a curated dataset | **Phase 1 reference architecture**: static-first explorer, DuckDB-WASM for browser-side analytics, downloadable snapshots, reproducible analysis artifacts | No-write-path assumptions for the whole product |
| OpenBenchmarking | Centralized submission ecosystem, aggregate comparison, rich result metadata, public/private policy | Cohort-aware comparison, richer metadata, trust labels, aggregate analysis | Day-1 open public firehose without curation, moderation, or clear verification state |
| ASV | Results stored as files, publish to a static website, precomputed regression views | Derived read models published as static assets, regression/change-oriented views, offline-friendly read path | Limiting the product to codebase-over-time regressions only |

## Product Boundary

BenchBox needs three explicit user contracts, but they do NOT all ship at once.

| Contract | Primary actor | Phase | Runtime boundary |
| --- | --- | --- | --- |
| Publish (local/cloud) | BenchBox user sharing files or mirroring artifacts | Independent (existing TODO) | CLI + local/cloud storage backend |
| Explore | Reader/analyst comparing public results | **Phase 1** | Static subsite on GitHub Pages |
| Submit (PR) | Community contributor adding results | **Phase 2** | `benchbox submit --output` → GitHub PR + CI validation |
| Submit (API) | Self-service submitter | **Phase 3** | `benchbox submit` → Hosted API + async ingest |

## Technology Recommendations for Phase 1

### Explorer Frontend Stack

| Choice | Recommendation | Rationale |
| --- | --- | --- |
| **Build tool** | Vite | Fast, modern, used by CloudSpecs reference. Produces optimized static bundles. |
| **Framework** | Vanilla TypeScript + Preact (or no framework) | Minimizes bundle size for a content-heavy site. Preact if component model helps; plain TS if it stays simple. |
| **Browser analytics** | DuckDB-WASM | BenchBox already has deep DuckDB expertise. Enables SQL-powered filtering, comparison, and ad-hoc analysis in the browser. Proven by CloudSpecs. |
| **Data format** | Static JSON manifests + DuckDB database file | JSON for navigation/SEO/fast page loads. DuckDB `.db` file for rich filtering and comparison. |
| **Routing** | File-based with real paths | `/results/tpch/`, `/results/duckdb/`, `/results/r/{result_id}` — not hash routing. Required for stable share URLs and SEO. |
| **Styling** | Tailwind CSS or minimal custom CSS | Consistent with modern static sites. Light enough for GitHub Pages. |

### Derived Read Model Schema

The static build pipeline transforms canonical schema-v2 bundles into:

1. **`manifest.json`** — Global navigation index:
   ```json
   {
     "results": [
       {
         "id": "tpch-duckdb-sf1-20260315",
         "benchmark": "tpch",
         "platform": "duckdb",
         "scale_factor": 1.0,
         "timestamp": "2026-03-15T10:30:00Z",
         "total_duration_ms": 1234,
         "query_count": 22,
         "queries_passed": 22,
         "source": "maintainer",
         "bundle_path": "bundles/tpch-duckdb-sf1-20260315.json"
       }
     ],
     "benchmarks": ["tpch", "tpcds", "ssb"],
     "platforms": ["duckdb", "datafusion", "clickhouse", "polars-df"],
     "generated_at": "2026-03-29T00:00:00Z"
   }
   ```

2. **Per-result detail JSON** — Full query timings + metadata for result pages:
   ```json
   {
     "id": "tpch-duckdb-sf1-20260315",
     "metadata": { "benchmark": "...", "platform": "...", "environment": "..." },
     "queries": [
       {"id": "Q1", "ms": 45.2, "rows": 4, "status": "passed"},
       {"id": "Q2", "ms": 12.1, "rows": 460, "status": "passed"}
     ],
     "summary": { "total_ms": 1234, "passed": 22, "failed": 0 },
     "bundle_download": "bundles/tpch-duckdb-sf1-20260315.json"
   }
   ```

3. **`results.duckdb`** — DuckDB database for browser-side analysis:
   - `results` table: one row per result run (flattened metadata)
   - `queries` table: one row per query execution (result_id, query_id, ms, rows, status)
   - Enables: `SELECT * FROM queries WHERE benchmark='tpch' AND platform='duckdb' ORDER BY ms`

4. **`bundles/`** — Raw canonical schema-v2 bundles for download

### Compare URL Format

Compare views use query parameters for flexibility:
- `/results/compare?ids=tpch-duckdb-sf1-20260315,tpch-datafusion-sf1-20260315`
- Cohort validation happens client-side: same benchmark + same scale factor required
- **Cohort mismatch is a hard-block, not a warning.** The compare view refuses to render incompatible comparisons (different benchmark or different scale factor). Non-blocking differences (query subset, tuning mode) produce warnings but do not prevent rendering.

### Site Integration

The explorer is built as a standalone Vite app in `results-explorer/`. The
static read-model pipeline writes build inputs to `results-explorer/public/data/`;
the Vite build emits static files to `results-explorer/dist/`; the existing
GitHub Pages workflow then copies that output into `site/results/`.

Build flow:

```
results-data/ + static build pipeline → results-explorer/public/data/
results-explorer/dist/ + [landing page] + [sphinx docs] + [blog] → /site/ → GitHub Pages
```

Navigation integration: add "Results" link to the shared site header/nav.

## Architecture by Phase

### Phase 1 Architecture (Static Only)

```
CI benchmark runs → schema-v2 bundles in results-data/
                                        ↓
                          static build pipeline → results-explorer/public/data/
                                                  ↓
                                            Vite build (dist/)
                                                  ↓
                           GitHub Pages assembly copies dist/ → site/results/
                                                  ↓
                                   GitHub Pages (benchbox.dev/results/)
                                                  ↓
                                     Vite app + DuckDB-WASM in browser
```

No API. No database. No auth. No hosted services.

### Phase 2 Architecture (PR-Based Contributions)

```
Contributor: benchbox submit --output ./submission/
                ↓
        PR touching results-data/ in this repo
                ↓
        CI validates (schema, hash, cohort, sanity)
                ↓
        Maintainer reviews + merges
                ↓
        Same static build pipeline as Phase 1
```

Still no API. Still no hosted services. GitHub is the auth + moderation layer.

### Phase 3 Architecture (Hosted — Deferred)

```
benchbox submit → api.benchbox.dev → object store + metadata DB
                                            ↓
                                    async ingest + validation
                                            ↓
                                    derived read model rebuild
                                            ↓
                                    static explorer update
```

Only build this if Phase 2 PR volume exceeds maintainer capacity.

### Storage Layers (Phase 3 Only)

| Layer | Purpose | Properties |
| --- | --- | --- |
| Object store | Immutable raw bundle + companions | Content-addressable, versioned, durable |
| Metadata store | Submission, run, visibility, trust, cohort metadata | Queryable, transactional, auditable |
| Derived public store | Static projections for public reads | Rebuildable, cacheable, CDN-friendly |

### Result Identity

Result identity is phase-dependent:

| Phase | Identity Scheme |
| --- | --- |
| Phase 1 | `{benchmark}-{platform}-sf{scale}-{date}` — human-readable, derived from bundle metadata |
| Phase 2 | Same, plus contributor attribution from PR author |
| Phase 3 | Adds `bundle_hash` (content identity), `submission_id` (API identity), `result_id` (public identity) |

## Trust, Visibility, and Ranking

Trust complexity scales with phases:

| Phase | Trust Model |
| --- | --- |
| Phase 1 | All results are maintainer-curated. A simple "Maintainer Run" label is fine, but no richer trust model is needed. |
| Phase 2 | Two labels: **maintainer** (generated by BenchBox CI) and **community** (submitted via PR). Both public. |
| Phase 3 | Full trust tiers: private, unlisted, public-self-reported, public-curated, public-verified |

Comparison and ranking should be cohort-aware. Public pages must avoid mixing
incompatible runs across materially different contexts:

- benchmark family and version
- scale factor
- execution mode
- phase set
- query subset vs full benchmark
- tuning mode
- hardware or platform family where relevant

If a cohort is too heterogeneous for a clean ranking, the explorer should fall
back to filters and pairwise comparison rather than pretend the leaderboard is
authoritative.

**No branded "leaderboard" page.** Phase 1 browse views may sort results within
a validated cohort (e.g., by total duration or geometric mean), but this is
presented as a sorted table, not a ranked competition. Cross-context ranking
claims are never shown.

## Impact on Existing Publishing TODO

`productize-result-publishing-and-artifact-sharing` remains the BenchBox-local
artifact publication track. It owns `benchbox publish` workflows for copying
canonical result bundles to local/cloud storage. It does NOT own the results
platform or explorer.

## TODO Cluster and Priority

| TODO | Phase | Priority | Rationale |
| --- | --- | --- | --- |
| `define-results-platform-product-and-launch-strategy` | Planning | High | Must complete before any implementation |
| `resolve-results-explorer-brand-ownership` | Planning | High | Must resolve before launch — implementation proceeds with BenchBox as working default |
| `build-results-explorer-subsite-on-benchbox-dev` | Phase 1 | High | Core deliverable (umbrella) |
| `implement-results-compare-view` | Phase 1 | High | **Primary deliverable** — the dynamic comparison tool is the core UX |
| `define-hosted-results-contract-and-governance-model` | Phase 2-3 prep | Medium | Not needed for Phase 1 (all curated) |
| `design-results-ingest-storage-and-derived-read-model` | Phase 3 | Medium | Phase 1 static pipeline is covered by dedicated implementation TODOs |
| `integrate-benchbox-cli-submit-and-service-auth` | Phase 2-3 | Medium | Deferred until explorer is proven; `benchbox submit` command for PR-based and hosted corpus contribution |
| `operate-results-platform-security-observability-and-abuse-controls` | Phase 3 | Low | No hosted services to operate until Phase 3 |

## External Sources

- Geekbench editions: https://www.geekbench.com/editions/
- Geekbench Browser: https://browser.geekbench.com/
- CloudSpecs site: https://cloudspecs.fyi/
- CloudSpecs repository: https://github.com/TUM-DIS/cloudspecs
- OpenBenchmarking: https://openbenchmarking.org/
- airspeed velocity: https://asv.readthedocs.io/en/latest/using.html
- js-framework-benchmark (PR-based contribution model): https://github.com/nicholasgasior/js-framework-benchmark
- ClickBench contribution model: https://github.com/ClickHouse/ClickBench
