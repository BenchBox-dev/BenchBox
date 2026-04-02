# BenchBox Results Platform — Threat Model

**Created:** 2026-04-01
**Phase scope:** Phase 3 (Hosted API at `api.benchbox.dev`)
**Input:** `benchbox-results-platform-strategy.md`, `operate-results-platform-security-observability-and-abuse-controls.yaml`

Phase 1 (static explorer) and Phase 2 (PR-based contributions) have no hosted
services. This threat model applies exclusively to Phase 3.

---

## w1 — Asset Inventory

| Asset | Classification | Where Stored | External Exposure | Custodian |
|---|---|---|---|---|
| Raw canonical bundles (schema-v2 JSON + companions) | Sensitive — content-addressed, immutable after commit | Object store (S3/R2), `bundles/` prefix | Download link on result detail page; not browsable | Ingest service (write), CDN (read) |
| Durable submission metadata (submission_id, bundle_hash, visibility state, trust labels) | Sensitive — controls public visibility | Metadata DB (Postgres) | Indirect — reflected in public read models only | API server |
| Public read models (manifest.json, detail JSONs, results.duckdb) | Public | Derived store → GitHub Pages / CDN | Fully public | CI pipeline (write), CDN (read) |
| Service API keys / user tokens | Secret | Metadata DB (hashed) + `~/.benchbox/credentials.yaml` (client) | Never — server stores hash only | Auth service |
| Actor identity records (actor_id, contact, trust tier) | Private | Metadata DB | Not exposed publicly; used internally for attribution and moderation | API server |
| Explorer static site (benchbox.dev/results/) | Public | GitHub Pages | Fully public — read-only | GitHub Actions CI |
| CI pipeline credentials (GitHub Actions secrets) | Secret | GitHub repository secrets | No direct exposure | Maintainers |
| Admin CLI credentials | Secret | Operator environment | No direct exposure | Maintainers |

**External interfaces:**

| Interface | Protocol | Direction | Phase |
|---|---|---|---|
| Submission API (`POST /submissions`) | HTTPS | Inbound | Phase 3 |
| Explorer static pages (`benchbox.dev/results/`) | HTTPS | Outbound | Phase 1+ |
| Admin CLI (`benchbox admin ...`) | Local process | Operator-only | Phase 3 |
| CI pipeline (GitHub Actions) | GitHub API | Internal | Phase 1+ |

---

## w2 — STRIDE Threat Analysis

### Submission Layer (Phase 3 API)

| STRIDE | Threat | Likelihood | Impact | Risk | Proposed Mitigation |
|---|---|---|---|---|---|
| **Spoofing** | Impersonating a trusted submitter to inject results under their identity | Med | High | Med-High | Bind API tokens to actor_id at issue time; server re-validates token → actor_id on every request; no client-supplied actor_id accepted |
| **Tampering** | Modifying bundle contents after the hash is computed client-side but before storage commits | Med | High | Med-High | Re-compute bundle_hash server-side immediately on receipt; reject if it does not match the client-declared hash; store only the server-verified hash |
| **Repudiation** | Submitter denying they submitted a result now indexed as public | Low | Med | Low-Med | Append-only audit log records (submission_id, actor_id, timestamp, bundle_hash, action=`submitted`) at ingest time; log is immutable after write |
| **Information Disclosure** | API leaking private or unlisted bundle metadata to unauthenticated callers | Med | High | Med-High | Default-deny: all metadata queries require authentication unless the result's visibility is `public`; enforce at API layer, not UI layer |
| **Denial of Service** | Flooding the submission endpoint with large bundles to exhaust storage and compute | High | Med | High | Per-actor rate limiting (burst + daily cap); hard bundle size cap (50 MB); async ingest with queue depth limit; reject before writing to storage |
| **Elevation of Privilege** | Low-trust actor promoting their own result to `public-curated` status without maintainer approval | Low | High | Med | Trust labels are server-controlled; actors have no API endpoint to self-promote; promotion is an admin-only action requiring explicit maintainer token scope |

### Storage Layer

| STRIDE | Threat | Likelihood | Impact | Risk | Proposed Mitigation |
|---|---|---|---|---|---|
| **Spoofing** | Replacing a stored bundle with a different one under the same content-addressable key | Low | High | Med | Object store versioning enabled; keys are SHA-256 content hashes; any write to an existing key triggers an alert; re-verify hash on every read before serving |
| **Tampering** | Direct write to the storage bucket bypassing the ingest API | Low | High | Med | Bucket policy: only the ingest service IAM role may write; all other principals are read-only or denied; bucket-level CloudTrail / audit logging enabled |
| **Repudiation** | No audit log means no way to prove who changed a result's visibility state | Med | Med | Med | Every visibility or trust-label state change is recorded in the audit log with actor_id and reason_code; logs are append-only and stored outside the metadata DB |
| **Information Disclosure** | Misconfigured bucket ACLs make private bundles world-readable | Med | High | High | Private and unlisted bundles stored under an ACL-restricted prefix; public bundles served via CDN from a separate public prefix; ACL misconfiguration alerts on policy drift |
| **Denial of Service** | Storage exhaustion from uncapped uploads across many actors | Med | Med | Med | Per-actor storage quota (500 MB); service-level quota enforced before writing to the object store; lifecycle policy auto-expires rejected bundles after 30 days |
| **Elevation of Privilege** | CI pipeline credentials with overly broad object store permissions allowing arbitrary writes | Low | High | Med | CI role is read-only for raw bundles; write access restricted to ingest service role; role separation enforced by IAM; credentials rotated on each deploy |

### Explorer Layer (Phase 1+)

| STRIDE | Threat | Likelihood | Impact | Risk | Proposed Mitigation |
|---|---|---|---|---|---|
| **Spoofing** | Serving a modified read model from a compromised CDN edge node | Low | High | Med | Subresource Integrity (SRI) hashes on all derived data files; explorer app verifies manifest checksum on load; CDN cache-poisoning alerts |
| **Tampering** | PR-injecting a malformed manifest.json that breaks all compare views for all users | Low | High | Med | CI schema validation rejects malformed manifest before merge; read-only GitHub Pages (no direct push); branch protection on `main` prevents force-push |
| **Repudiation** | No access logs for static pages, making abuse attribution impossible after the fact | Med | Low | Low | GitHub Pages access logs are not available; rely on CDN-level logging (Cloudflare or equivalent) if custom domain is used; static-only scope limits blast radius |
| **Information Disclosure** | DuckDB snapshot (`results.duckdb`) contains fields that should be redacted before public release | Med | High | High | Build pipeline explicitly projects only public fields into `results.duckdb`; no private, unlisted, or actor contact fields are included; CI test asserts schema shape |
| **Denial of Service** | GitHub Pages rate limiting under a traffic spike rendering the explorer unavailable | Med | Med | Med | Custom domain with Cloudflare CDN as a caching layer in front of GitHub Pages; static assets are fully cacheable; no server to overload |
| **Elevation of Privilege** | GitHub Actions workflow with write access to `main` inadvertently triggered by a PR from a fork | Low | High | Med | Fork PRs run in a restricted environment with no write secrets; `pull_request_target` events explicitly avoided; `main` protected with required reviews |

---

## w3 — Top-10 Mitigations (Ranked by Risk Score)

| Rank | Threat | Layer | Risk Score | Mitigation | Assigns To |
|---|---|---|---|---|---|
| 1 | Private bundles world-readable due to ACL misconfiguration | Storage | High | Separate public/private prefixes; ACL drift alerts | Phase 3 launch gate — storage design |
| 2 | DuckDB snapshot contains fields that should be redacted | Explorer | High | Build pipeline projection; CI schema assertion | Phase 3 launch gate — ingest/read model design |
| 3 | Flooding submission API with large bundles (DoS) | Submission | High | Rate limiting, bundle size cap, async queue depth limit | `integrate-benchbox-cli-submit-and-service-auth` |
| 4 | API leaking private metadata to unauthenticated callers | Submission | Med-High | Default-deny auth enforcement at API layer | Phase 3 launch gate — auth design (w4) |
| 5 | Impersonating a trusted submitter | Submission | Med-High | Token bound to actor_id; server re-validates; no client-supplied identity | Phase 3 launch gate — auth design (w4) |
| 6 | Bundle tampered after hash computed client-side | Submission | Med-High | Server-side hash re-verification on receipt | Phase 3 launch gate — ingest design |
| 7 | Direct write to storage bucket bypassing ingest API | Storage | Med | Bucket policy: ingest service role only; CloudTrail logging | Phase 3 launch gate — storage design |
| 8 | No audit log for visibility state changes | Storage | Med | Append-only audit log (actor_id, action, timestamp); stored outside metadata DB | w6 (moderation + audit log) |
| 9 | CI pipeline credentials with overly broad storage permissions | Storage | Med | Read-only CI role; write access restricted to ingest service; IAM role separation | Phase 3 launch gate — storage design |
| 10 | Malformed manifest.json injected via PR | Explorer | Med | CI schema validation before merge; branch protection | Phase 1 CI hardening |
