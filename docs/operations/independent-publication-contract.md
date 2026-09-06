# Independent publication operations contract

The governing architecture decision is
[`docs/development/adr/adr-independent-publication-authorities.md`](../development/adr/adr-independent-publication-authorities.md).
This runbook defines operator-visible states and evidence. It does not activate a new
workflow or modify the A0 freeze.

## Evidence hierarchy

| Claim | Minimum evidence |
|---|---|
| accepted | Bundle and sidecar are validator-clean and reachable from the pinned `published-results` SHA. |
| desired | Manually reviewed manifest digest pins exact `develop` and `published-results` SHAs, policy version, builder, target, and generation. |
| built | Immutable artifact digest plus provenance matches the desired manifest. |
| deployed | Provider acknowledgement names the exact artifact, target, and generation. |
| live | Fresh attested live receipt matches the manifest, artifact, target, generation, and required public probes. |
| promotion_failed | The build, deployment, or observation lane ended without a valid matching live receipt. |
| withdrawal_requested | Authorized withdrawal event is present in desired state and excluded from candidate public and ranking read models. |
| withdrawn | A matching live receipt confirms that the deployed generation suppresses the result from public presentation and ranking. |

Only an attested live receipt proves publication. Only `live` permits an operator or
document to say a publication succeeded. A `published-results` merge proves acceptance
only. A green workflow, uploaded artifact, provider deployment object, or successful
internal health check does not prove live publication.

## Promotion procedure

1. Select exact `develop` and `published-results` SHAs. The latter includes every valid
   accepted result as publication input by default.
2. Apply orthogonal presentation policy. Record visibility, trust, withdrawal, and
   ranking eligibility independently. Do not create a second curated corpus membership
   list on `develop`.
3. Prepare the canonical immutable permit containing content digest, target, generation,
   expected durable parent, and nonce.
4. Have one authorized maintainer review and approve the environment deployment with
   comment `publication-approval:<permit_sha256>`. Trust, admission, workflow, credential,
   receipt, withdrawal, and ranking-policy changes require manual review and may not auto-merge.
5. Reserve the target generation with Git compare-and-set on the `publication` metadata ref.
   A conflicting promotion stops; it does not overwrite newer desired state.
6. Verify provider feasibility gates before deployment:
   - Unique correlation: write-intent commit OID passed as `pages_build_version`.
   - Supported activation barrier: provider contract guaranteeing no late activation.
   - Stop condition: if provider correlation or finality is indeterminate, transition to
     `recovery-required` and fail closed.
7. Build immutable artifacts from the pinned inputs and record provenance and digests.
8. Deploy only the matching artifact using the pinned Pages adapter. Record provider
   acknowledgement as `deployed`, not `live`.
9. Probe required public routes from outside the deployment boundary. Issue the attested
   live receipt only when all observations match. Then and only then set the generation
   to `live`.
10. If any stage fails, record `promotion_failed`; retain the previous live generation and
    its receipt.

## Provider feasibility and fail-closed fallback

Before implementing or activating the production journal controller, two provider guarantees
must be established in an isolated test repository:
1. **Unique Write Correlation:** GitHub Pages must accept the unique write-intent commit OID as
   `pages_build_version` without aliasing to workflow SHAs, and return deployment status by that version.
2. **Supported Activation Barrier:** A documented provider contract specifying that an in-flight or
   canceled request cannot activate after compensation.

If either guarantee cannot be proven, the system fails closed: automated compensation is blocked,
and operator escalation is required. Do not use unreviewed markers or SHA-only aliases.

## Required live receipt fields

A receipt records, at minimum:

- schema version, receipt ID, target, generation, and observation timestamp;
- publication manifest digest and exact `develop` and `published-results` SHAs;
- artifact identity and digests;
- required route set and per-route status, content digest or semantic assertion, cache
  metadata where relevant, and observation origin;
- nonce and freshness window;
- attestor identity and signature; and
- the prior live receipt ID when this is a promotion or rollback.

Receipts are immutable and append-only. Partial route success, stale observations,
internal-only probes, or a signature over mismatched inputs fail closed.

## Reconciliation inputs

The `scripts/publication` canaries consume this evidence as files. They never
fabricate a state; a missing or malformed input fails closed.

- `reconciliation.py` requires `--manifest` (the desired manifest) and a
  `--receipts-dir` containing `assembly-receipt.json` (built), `deployment-receipt.json`
  (deployed), and `live-receipt.json` (the attested live receipt with the fields
  above). The four states must be distinct sources.
- `verify_independence_matrix.py` requires a `--receipts-dir` containing recorded
  lane transitions in `independence-matrix.json` or `lane-transitions.json`.
- `check_operational_receipts.py` requires a `--receipts-dir` containing
  `rollback-drill.json`, `takedown-drill.json`, `incident-drill.json`,
  `retention-policy.json` (which must cite its `source`), and either a
  `capacity-audit.json` or a `--pages-dir` to measure.

`scripts/publication/reconciliation.py` verifies every live receipt signature
against the repository public key at
`docs/operations/publication-attestor-public-key.pem`. It signs canonical JSON
(sorted keys, compact separators, UTF-8) with `signature` and
`attestor_signature` excluded. Receipts must declare
`signature_algorithm: ed25519`; missing, empty, malformed, or non-verifying
signatures fail closed. The matching private key is never stored in the
repository. Before dispatching the production deployer, a maintainer must set
the `PUBLICATION_ATTESTOR_PRIVATE_KEY` environment secret to the matching
Ed25519 PEM private key in the protected `publication-attestation` and
`github-pages` environments. There must be no repository-level copy.

## Rollback

Rollback targets the last known-good attested manifest and exact artifact. Do not rebuild
from a branch name and call the result equivalent. Reserve a new generation, deploy the
known artifact, run fresh public probes, and issue a new receipt that references the
prior known-good receipt. Until the new receipt exists, report rollback as pending or
failed, not complete.

Automatic rollback may select only the last known-good receipt and its recorded durable
parent. It must construct a self-consistent successor transaction whose desired manifest,
artifact, acknowledgement, probes, receipt, generation, and parent all describe the
restored bytes. It may not advance policy, add accepted inputs, change visibility or
ranking, or select unattested bytes.

Throughout migration and the 72-hour bounded soak, the legacy release fallback remains
independently runnable and does not require reading or executing through the new journal.
Retirement of the legacy fallback requires explicit user approval after soak completion.

## Emergency takedown

One authorized maintainer may initiate emergency takedown.

1. Record actor, reason, time, affected public IDs or archive paths, and whether the
   action is presentation withdrawal or a request for source-byte erasure.
2. For presentation withdrawal, add `withdrawal_requested` to desired state. Exclude
   affected rows from the candidate public and ranking read models, reserve a generation,
   deploy, and obtain a fresh live receipt. Keep desired state at `withdrawal_requested`
   while deployment or external probes are pending or failed. Record `withdrawn` only in
   observed live state after the matching receipt confirms suppression. Ordinary promotion
   must carry the withdrawal request or receipt-confirmed withdrawal forward.
3. During the A0 migration freeze, do not delete accepted source bytes. For a privacy or
   legal incident, record the withdrawal request immediately, suppress candidate output and
   accessible artifacts where the provider permits, and open a separately approved erasure
   plan covering Git history, workflow artifacts, caches, mirrors, and inventory
   consequences. A branch deletion is not proof of erasure.
4. Preserve non-sensitive audit evidence. Do not claim public removal until external
   probes and a live receipt confirm it.

## Authorized readmission

One authorized maintainer may reverse a mistaken or temporary withdrawal, but the policy
event alone does not restore public presentation.

1. Record actor, reason, time, affected public IDs, prior withdrawal receipt, and
   `readmission_requested` in desired state.
2. Reserve a new generation, restore the result only in the candidate public and ranking
   read models allowed by current visibility, trust, and ranking policy, then deploy and
   run fresh external probes.
3. Keep observed presentation `withdrawn` while deployment or probes are pending or failed.
   Retain the public tombstone when a public ID previously existed; a never-public private
   result continues to have no public route or tombstone. Record presentation `active` only
   after a matching live receipt confirms the restoration generation.
4. Preserve the readmission event, deployment evidence, probe observations, and receipt in
   the append-only audit record. Readmission does not erase prior withdrawal evidence.

## Retention and audit

Retain manifests, approvals, provenance, artifact digests, deployment acknowledgements,
live receipts, failures, withdrawal events, and rollback events independently of derived
indexes. The accepted archive remains recoverable under the A0 preservation floor. Any
later privacy/legal erasure exception must explicitly supersede that freeze through an
audited incident decision. Derived Explorer databases, pages, indexes, and caches are
replaceable.

The operational record must allow a reviewer to answer who approved which exact source
SHAs, what was built, what was deployed, what was observed publicly, which policy was in
force, and how rollback or takedown changed presentation.
