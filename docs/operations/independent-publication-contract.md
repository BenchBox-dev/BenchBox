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
3. Have one authorized maintainer review and approve the manifest. Trust, admission,
   workflow, credential, receipt, withdrawal, and ranking-policy changes require manual
   review and may not auto-merge.
4. Reserve the target generation with compare-and-set. A conflicting promotion stops;
   it does not overwrite newer desired state.
5. Build immutable artifacts from the pinned inputs and record provenance and digests.
6. Deploy only the matching artifact. Record provider acknowledgement as `deployed`, not
   `live`.
7. Probe required public routes from outside the deployment boundary. Issue the attested
   live receipt only when all observations match. Then and only then set the generation
   to `live`.
8. If any stage fails, record `promotion_failed`; retain the previous live generation and
   its receipt.

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

## Rollback

Rollback targets the last known-good attested manifest and exact artifact. Do not rebuild
from a branch name and call the result equivalent. Reserve a new generation, deploy the
known artifact, run fresh public probes, and issue a new receipt that references the
prior known-good receipt. Until the new receipt exists, report rollback as pending or
failed, not complete.

Automatic rollback may select only the last known-good receipt. It may not advance
policy, add accepted inputs, change visibility or ranking, or select unattested bytes.
The A0 release-based rollback remains the production fallback until later migration gates
replace it with tested evidence.

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
3. Keep observed presentation `withdrawn` and retain the public tombstone while deployment
   or probes are pending or failed. Record presentation `active` only after a matching live
   receipt confirms the restoration generation.
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
