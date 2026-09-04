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

All five gates passed on 2026-09-04. See [Freeze closure](#freeze-closure)
for which of these restrictions the closure carried forward, and why.

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

## Gate evidence log

### G1 archive preservation — PASS (2026-09-03)

Restore drill re-materialized the exact accepted-path union from the pinned
source and proved per-object byte identity for every path:

- Seed: `publication/ledger-seed.json`, 199 union paths with sha256 digests,
  `source_ref = origin/published-results`, pinned `source =
  b3e34585d0fc60ea5c0f858638e9cd90b0e5a70c`.
- Drill A (live union, bidirectional, `published_only = []`): materialized 199
  paths via `create_ledger_seed.py --materialize-dest`; independent verifier
  hashed both the materialized bytes and the git-object bytes at the pinned
  SHA against the seed digests: **PASS=199 FAIL=0**.
- Drill B (asymmetric case): synthetic seed regenerated from the pinned SHA
  with 1 forced `published_only` path, materialized and independently
  verified the same way: **PASS=199 FAIL=0**, including the published-only
  path restored from git objects.

Provenance caveat: the `--materialize-dest` drill tooling lands in PR #2022
(commit `beb1a4615`), not yet merged to `develop` at the time of the drill.
This G1 pass is replayable from that commit; it becomes replayable from
`develop` itself once #2022 merges. The destructive-corpus-rewrite row is
released on that basis — the drill, not the row, is what a re-verifier replays.

Residual: land the drill as a durable repo command with a committed
PASS/FAIL artifact instead of a throwaway probe.

### G2 dual publication — PASS (2026-09-04)

An independently assembled target served the required routes and matched the
production database by canonical digest for a bounded soak:

- Deploy: `Publication Preview Deploy (G2)` run 33814942530, live receipt
  `live-gen1-2026-09-04T13:11:04Z`, served at `https://benchbox.dev/preview/gen1/`.
- Soak: 12 hours of scheduled probes, every window PASS, concluded by
  `Publication Preview Soak (G2)` run 33876444641.
- Byte equality was rejected as the gate condition. The assembler stamps
  `generated_at` and float serialization drifts by one ULP between builds, so
  root neutrality is proven by canonical digest instead (PR #2031).
- Supporting fixes: build Sphinx before root assembly (#2025), mirror the
  Explorer dist from `docs.yml` (#2028), and reuse the probe deploy run when
  concluding the soak (#2035).

### G3 rollback — PASS (2026-09-04)

A timed drill restored the pinned known-good release tree to production and
probed it publicly. Receipt:
[`docs/operations/publication-rollback-receipt-2026-09-04.json`](../../docs/operations/publication-rollback-receipt-2026-09-04.json).

- Drill PR #2037 merged at 14:21:22Z; `Documentation` run 33883250472 completed
  the production deploy at 14:28:03Z; public probes at 14:32:23Z returned 200
  for `/` and `/results/`. Merge to live was 11 minutes.
- The restored database differs from the baseline only by build stamp and
  one-ULP float drift, and is canonical-digest equivalent.
- The full-site release deploy wiped the preview subtree, as designed.
- Direct pushes to `release` are ruleset-blocked, so the drill rode a PR using
  the documented `RELEASE_READINESS_OVERRIDE_SHA` hatch. Those variables were
  removed after the merge.

### G4 ownership and incident response — PASS (2026-09-04)

Record:
[`docs/operations/publication-g4-incident-response-2026-09-04.json`](../../docs/operations/publication-g4-incident-response-2026-09-04.json).

- Operator Joe Harris exercised preview deploys, soak conclusions, merges
  through required gates, and the `github-pages` deployment branch policy.
- Credentials are a least-privilege `GITHUB_TOKEN` per job, with `pages: write`
  scoped to deploy jobs, plus maintainer `gh` CLI auth for operator actions.
- Alerting is GitHub-native only. There is no dedicated paging channel, which is
  accepted for a static-site risk profile.
- Bandwidth telemetry stays `unavailable`. GitHub exposes artifact bytes and
  cache headers, not transfer totals, and it is never inferred from size.
- The rollback runbook was exercised by the G3 drill, not merely described.

### G5 final reconciliation — PASS (2026-09-04)

- `scripts/publication/check_plan_reconciliation.py --todo-prefix independent-publication-`
  exits 0 against the live tracker: 7 prior surfaces, 5 gates, 12 tracker
  priorities.
- Tracker items A0 through A9 are done with audited evidence. A10 and A11 stay
  open; see the closure section below.

## Freeze closure

All five gates passed on 2026-09-04. The decision is recorded in
[`docs/operations/publication-freeze-closure-2026-09-04.json`](../../docs/operations/publication-freeze-closure-2026-09-04.json),
which also lists the drift known at closure.

Passing the gates does not by itself lift the four blocked actions above. The
retirement surgery A10 describes was not executed, because no replacement
production deployer exists: `docs.yml` is still the only lane that deploys
`benchbox.dev`, and `publication-deploy.yml` is rehearsal-only. Removing the
release coupling now would leave production undeployable.

That scope is filed as the tracker item
`independent-production-deployer-and-retirement`. Until it completes, these
restrictions remain in force:

- `sync-results-data-to-published.yml` is not retired.
- The `docs.yml` release deploy is not removed.
- No destructive corpus rewrites happen outside that workstream.
- `develop` remains an allowed `github-pages` deploy branch. Removing it belongs
  to that workstream.

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
