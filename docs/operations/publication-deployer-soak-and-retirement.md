# Publication deployer soak and retirement

`publication-transaction.yml` and its controller `scripts/publication/transaction_executor.py`
supply the replacement publication transaction engine for benchbox.dev. State authority is
anchored by an append-only Git journal on the `publication` metadata ref (`publication/transaction-state/state.json`),
replacing ad-hoc artifact scans and mutable GitHub Deployment queries.

Throughout the migration and bounded soak, the legacy release builder in `.github/workflows/docs.yml`
remains independently runnable and does not route through `transaction_executor.py` or require
reading the new journal.

## Operator migration from legacy dispatch

The legacy `publication-deploy.yml` workflow accepted manual decimal `generation` inputs and
arbitrary rollback references. In the canonical transaction engine:

1. **Automatic Monotonic Generations:** Operators do not specify generation numbers. The journal
   CAS reserves monotonically increasing generations atomically on the `publication` ref.
2. **Elimination of Rollback SHA:** Operators cannot roll back to arbitrary Git commit SHAs.
   Rollback transactions restore exact, previously verified durable parent transactions by
   `restore_transaction_id`.
3. **Affirmative Activation Barrier:** Automated and manual rollbacks require affirmative provider
   activation barrier evidence (`barrier_evidence`) demonstrating that in-flight or canceled provider
   requests cannot activate late.
4. **Digest-Bound Permits:** Promotion requests require an immutable permit verified and approved
   by a maintainer environment review comment (`publication-approval:<permit_sha256>`).

## Prerequisites

Before the first production dispatch:

1. **Attestor Secrets:** Configure `PUBLICATION_ATTESTOR_PRIVATE_KEY` in both
   `publication-attestation` and `github-pages` environments. The secret must match the committed
   public key at [`publication-attestor-public-key.pem`](publication-attestor-public-key.pem). Never
   place the private key in repository files or workflow inputs.
2. **Metadata Ref Protection:** Verify that the `publication` Git ref exists and has branch protection
   blocking force-pushes and deletion (`scripts/publication/check_control_plane.py`).
3. **Provider Feasibility Gates:** Prove unique write-intent commit correlation as
   `pages_build_version` and supported cancellation finality in an isolated test repository before
   enabling production writes.
4. **External Heartbeat Alert:** Configure an external availability monitor outside GitHub Actions
   to detect missed controller heartbeats within 10 minutes.
5. **Preview Deploy Disabled:** Keep `.github/workflows/publication-preview-deploy.yml` disabled in
   code and at the repository level.

## 72-Hour Bounded Production Soak

A successful production soak requires 72 continuous hours after the last controller change without
unresolved incidents, digest mismatches, or missing samples.

### Required drill matrix

The soak must execute and record evidence for:

- At least 3 acknowledged and verified candidate promotions.
- 1 independent update for each required publication lane (site, Explorer, corpus).
- 1 whole-workflow cancellation recovery where the independent watchdog (`publication-recover.yml`)
  detects the dropped worker and either finalizes or safely quarantines intent.
- 1 independently initiated rollback restoring the durable parent artifact after simulated failure.
- 1 older-release recovery drill demonstrating restoration from an attested historical release.

### Sampling and timing targets

- Sample public route availability (`/`, `/docs/`, `/results/`, `/results/data/results.duckdb`) every
  5 minutes from outside the writer.
- Detect a stale in-flight transaction within 10 minutes.
- Complete restoration after an approved barrier within 15 minutes.
- Perform full DuckDB content-stream verification hourly during soak.

Any unhandled failure, missed required sample, or unverified digest restarts the 72-hour window.

## Maintainer Exclusive Publication Window

During production trials, maintainers enforce an exclusive publication window:

1. Inventory and drain queued legacy release writers.
2. Approve only designated `publication-transaction.yml` runs.
3. Keep the legacy `docs.yml` release deploy available as an emergency fallback.
4. If the new controller fails, stop admission, drain active workers, establish provider quiescence
   through the activation barrier, and approve the legacy restore from its attested checkpoint.
   Observations from an emergency legacy restore do not advance the new journal head.

## Retirement Decision

The freeze closure at
[`publication-freeze-closure-2026-09-04.json`](publication-freeze-closure-2026-09-04.json)
deferred A10 retirement until an independent deployer passed production soak.

Only after the 72-hour bounded soak passes all required drills and receives explicit maintainer
approval may the retirement steps execute:

1. Remove the release-to-Pages deployment job in `.github/workflows/docs.yml`.
2. Retire `.github/workflows/sync-results-data-to-published.yml`.
3. Drop `develop` from the GitHub Pages branch deployment policy (leaving `release` only if required
   for emergency fallback, or removing branch policy entirely for workflow-based deploy).
4. Reconcile open corpus mirror pull requests by exact `results-data` path set and content digests
   against the target branch. Do not close older mirror PRs based on recency or title alone.
5. Close out tracking items `independent-production-deployer-and-retirement`,
   `independent-publication-a10-release-and-mirror-retirement`, and
   `independent-publication-a11-operations-canaries-and-closeout`.
