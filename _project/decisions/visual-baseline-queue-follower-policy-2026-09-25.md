# Merge-queue follower visual baseline policy

Date: 2026-09-25
Status: Decided. Governance doc updated; no workflow change.

## Observation

During the 2026-09-25 merge-queue run, leader #2346 (real base `2d97c55f3`)
passed visual acceptance in queue run 36128856741, while follower #2341
(queue branch `pr-2341-f2321782`, `GROUP_BASE_SHA=f23217827234ec7f1e6fef862f11a8dbfe26b65b`)
failed both queue attempts at the baseline-download step (runs 36125414422,
36129430763) and sat UNMERGEABLE at position 2.

Root cause: a follower's speculative base is the leader's speculative head.
Protected baselines are produced only by `push` to `develop`, so a speculative
head can never carry one. The exact-base download fails closed, as designed.

## Options considered

- **(a) Ancestor resolution**: resolve the speculative base to the nearest
  baselined develop ancestor and compare against that. REJECTED: the follower
  does not merge onto that ancestor, so the comparison would certify a tree
  that never lands. It weakens the exact-base guarantee that justifies the
  gate, trading a real invariant for queue throughput.
- **(b) Re-queue-after-leader as expected flow**: treat the follower failure
  as correct fail-closed behavior. After the leader merges, the follower
  re-queues against the new develop head. ACCEPTED.

## Decision

Option (b). The follower's own `pull_request` run already proves the
comparison against its real base; the fresh queue run compares against the
updated head. No workflow or download-script change. Recorded in
`docs/operations/merge-queue-governance.md` ("Merge-queue follower visual
baseline policy"). Do not add ancestor-resolution fallback to
`download-public-site-visual-baseline.mjs`.
