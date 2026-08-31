# Independent publication A0 baseline and migration freeze

**Status:** Accepted, temporary migration freeze
**Date:** 2026-08-31
**Tracker:** `independent-publication-a0-baseline-and-freeze`
**Incident owner:** BenchBox maintainers

## Decision

The evidence-fresh machine-readable baseline is
[`docs/operations/publication-baseline-2026-08-31.json`](../../docs/operations/publication-baseline-2026-08-31.json).
Until every named gate below passes, the following actions are blocked:

1. destructive rewrites or count-normalization of either accepted corpus tree;
2. retirement of the `develop` to `published-results` mirror path;
3. removal or disabling of the release-driven GitHub Pages deployment; and
4. deletion of any accepted bundle or published-only path.

The preservation floor is the exact set union of bundle paths captured from
`origin/develop` and `origin/published-results`, not any expected file count.
Every member of that union must remain recoverable with its original bytes.
Production remains enabled while replacement and rollback evidence are built.

## Desired, built, deployed, and observed state

These states are deliberately separate:

- **Desired:** an independently operated publication path with immutable accepted
  archives, rebuildable read models, and a tested rollback.
- **Built:** `.github/workflows/docs.yml` assembles the site and explorer database
  from the curated `release` tree.
- **Deployed:** the baseline pins the successful release workflow run, Pages
  deployment ID, artifact digests and sizes, environment policy, and release SHA.
- **Observed:** live HTTPS probes pin the public database byte count, SHA-256,
  ETag, Last-Modified value, and cache policy. GitHub exposes no Pages transfer
  totals, so bandwidth is explicitly `unavailable`, never inferred from size.

## Named migration gates

| Gate | Pass evidence | Freeze released |
| --- | --- | --- |
| G1 archive preservation | Exact accepted-path union exported with per-object digest and restore drill | Destructive corpus rewrite only |
| G2 dual publication | Independent target serves byte/digest-equivalent database and required static routes for a bounded soak | Mirror retirement only |
| G3 rollback | Timed rollback restores the pinned known-good release deployment and live probes | Release deploy removal only |
| G4 ownership and incident response | Named operator, credentials, alerts, bandwidth telemetry, and rollback runbook exercised | Production cutover |
| G5 final reconciliation | Prior art, future-state indexes, tracker priorities, and readiness evidence are current and reviewed | Freeze closure |

No count threshold can satisfy G1. No successful build without a deployed live
probe can satisfy G2 or G3.

## Prior-decision reconciliation

- `_project/analysis/ingest-architecture-design.md`: **extended**. Immutable raw
  bundles and rebuildable read models remain the future-state authority, while
  the accepted `published-results` archive is now an explicit migration input.
- `docs/development/adr/adr-published-results-slim-corpus-branch.md`: **extended**.
  The complete accepted archive remains authoritative and published-only paths
  are preservation obligations, not missing backports.
- `docs/development/benchbox-results-platform-strategy.md`: **extended**. The
  static-first explorer remains the read contract during migration.
- `docs/operations/release-guide.md`: **reused** for release SHA, workflow run,
  deployment, and rollback evidence conventions.
- `docs/operations/repo-admin-settings.md`: **extended** by the captured Pages
  environment and branch-rule state.
- `docs/reference/threat-model.md`: **extended**. Public artifacts remain derived;
  accepted raw bundles remain immutable source assets.
- `docs/design/future-state/index.md`: **reconciled**. Its extraction proposals do
  not authorize publication extraction or relax these gates.

## Tracker sequence and readiness

A0-A11 are live tracker items and must proceed in this dependency-aware order:

1. `independent-publication-a0-baseline-and-freeze`
2. `independent-publication-a1-authority-and-threat-contract`
3. `independent-publication-a2-corpus-trust-isolation`
4. `independent-publication-a3-control-plane-and-artifact-contract`
5. `independent-publication-a4-hermetic-build-and-shadow-assembly`
6. `independent-publication-a5-noop-deploy-and-automatic-rollback`
7. `independent-publication-a6-site-and-api-docs-lane`
8. `independent-publication-a7-explorer-application-lane`
9. `independent-publication-a8-published-results-gate-and-shadow-promotion`
10. `independent-publication-a9-corpus-production-cutover`
11. `independent-publication-a10-release-and-mirror-retirement`
12. `independent-publication-a11-operations-canaries-and-closeout`

A later TODO is not ready merely because it exists. Its predecessor's named gate
must have fresh evidence, and A10 may not retire legacy surfaces until G1-G5 pass.

## Rollback floor

The current production rollback is to re-run Documentation for the pinned
known-good release SHA or revert `release` through its protected squash-PR flow.
The deployed artifact is expired in Actions, so the release tree and deterministic
build inputs are the durable rollback source. This limitation is a required input
to G1 and G3, not permission to remove the current deploy.
