# Publication deployer soak and retirement

`publication-deploy.yml` is an armed, dispatch-only Pages deployer. It builds
one complete site from an exact `develop` SHA and an exact
`published-results` SHA, then deploys that immutable artifact only after its
pre-deploy checks pass. It does not run on a push. The `docs.yml` release job
shares its deployment lock and stops writing Pages after the first successful
independent live-receipt run, preventing a queued legacy artifact from
overwriting an attested deployment during the soak.

## Prerequisites

Before the first dispatch, configure the `PUBLICATION_ATTESTOR_PRIVATE_KEY`
environment secret in both `publication-attestation` and `github-pages`. The
former must allow only `develop`; the latter must continue to allow `develop`
and `release` during the bounded soak so the legacy release deploy remains
available until its retirement is approved. Disable the obsolete
`publication-preview-deploy.yml` workflow at repository level before activation;
its in-file ownership guard remains defense in depth if it is later re-enabled.
Do not configure a repository-level copy,
because unmerged branch workflow code could request it. The secret must be the
PEM Ed25519 private key
whose public half is committed at
[`publication-attestor-public-key.pem`](publication-attestor-public-key.pem).
Do not place the private key in a workflow input, artifact, commit, issue, or
receipt. A missing secret makes the live-receipt stage fail closed.

Choose exact 40-character lowercase commit SHAs for `develop_sha` and
`published_results_sha`. Generations are positive decimal CAS values: use `1`
for the first independent deployment, then increment by one. Record the current
attested live receipt ID when the run replaces an earlier generation.

For a publication that changes corpus content, first dispatch the exact inputs
with `candidate_only=true`, `expect_noop=false`, and no
`approved_manifest_digest`. Download `desired-manifest.json` from the candidate
receipt artifact, inspect its pins and measured artifact closure, and record its
`manifest_digest` and workflow run ID. Dispatch the production run with the same inputs,
`expect_noop=false`, `force_rollback=false`, and that reviewed digest as
`approved_manifest_digest`; pass the recorded run ID as
`approved_candidate_run_id`. The workflow authenticates the successful no-write
run, rechecks its pins and manifest digest, downloads its retained site, and
refuses deployment unless the site's exact byte digest matches the reviewed
manifest. It promotes those reviewed bytes without rebuilding the DuckDB file.
This is an authorized production action; this runbook does not authorize it.

For a no-op rehearsal, set `expect_noop=true` and `candidate_only=false`. That compares the candidate
database with the freeze baseline and skips the deploy job. A rehearsal is not
a live receipt and cannot count toward soak.

## Evidence for each soak run

Collect the build, deployment, and live-receipt artifacts from the same run.
The run is a successful production observation only when all are present:

- `desired-manifest.json` identifies the pinned inputs and generation.
- `assembly-receipt.json` records distinct site, docs, Explorer, and DuckDB
  digests; the retained site artifact has the same site digest.
- `deployment-receipt.json` is provider acknowledgement, not proof of live
  service.
- `live-receipt.json` follows external probes of `/`, `/docs/`, `/results/`, and
  `/results/data/results.duckdb`, has a fresh nonce and timestamp, includes the
  source SHAs, digest set, prior receipt ID where applicable, and verifies with
  `scripts/publication/reconciliation.py` against the repository public key.

Digest equivalence means that the whole-site digest and its component docs,
Explorer, and DuckDB digests from the new lane are compared with the equivalent
artifact produced by the current `docs.yml` release lane for the same pinned
inputs. Compare like with like: a deployment acknowledgement is not a digest,
and a live route hash is not a substitute for the retained artifact digest.
The required DuckDB route must also equal the assembly receipt checksum. Any
mismatch, stale receipt, signature failure, or partial route success fails the
soak run.

Run the bounded soak for the approved window and preserve each attested receipt
and comparison record. A `docs.yml` release deployment during a run changes
the observed target; mark that sample inconclusive and start a fresh comparison
for the new release generation. Do not call an artifact live before its
external probes and signature have completed.

## Rollback boundary

On a deployment or probe failure, the workflow searches retained
`publication-live-receipt-*` artifacts, verifies the newest eligible receipt
with the public key, downloads its named site artifact, recomputes its digest,
and only then permits the rollback Pages write. It never rebuilds a site from a
branch name or uses `rollback_target_sha` as bytes. If no unexpired attested
artifact exists, rollback fails closed.

## Retirement decision

The freeze closure at
[`publication-freeze-closure-2026-09-04.json`](publication-freeze-closure-2026-09-04.json)
records that G1–G5 passed but that retirement was deferred because there was no
independent production deployer. This workflow supplies the replacement; it
does not itself prove retirement.

Do not remove the `docs.yml` release Pages deploy, retire or disable
`sync-results-data-to-published.yml`, or remove `develop` from the GitHub Pages
branch policy (policy id 59059907) until the bounded soak has preserved the
digest-equivalence and attested-live evidence above and an authorized follow-up
approves the retirement change.

Corpus mirror pull requests are reconciled by the exact `results-data` path set
and content digests against the target branch. Recency, title, and a newer open
mirror PR are not grounds to close an older mirror PR.
