# CI fast-test skip and shard decision

Date: 2026-08-31

Outcome: KEEP_IDLE

## Decision

Do not open a CI skip, split, shard, or demotion follow-up from this evidence.
Keep every measured fast-test lane unchanged.

The remeasurement shows that code-routed pull requests and merge groups carry
substantial total workflow time, but it does not attribute that cost to the
fast-test step. The overlap inventory finds matching fast-test selector text
across lanes, but the retained Actions evidence has neither sorted collected
node IDs nor per-step runner-minute allocation. It therefore cannot establish
exact selection identity or quantify a safe saving from removing or splitting
any lane. Matching outcome totals are not a substitute for collected-node
identity.

Existing required regression reproducers also remain deliberate coverage. The
completed `required-ci-coverage-deepest-reproducers` work promoted bounded,
load-bearing cells into required pull-request CI; this decision does not weaken
that protection.

## Evidence boundary

The evidence covers only the current pull-request, merge-group, post-merge,
and nightly fast-test lanes described by the 2026-08-31 remeasurement and
overlap inventory. Independent-publication workflows, controller jobs, and
future canaries are outside the measured population.

This is a bounded evidence decision, not a claim that the lanes are identical
or permanently optimal. A later proposal would need new authority and direct
evidence of collected-node identity, attributable lane cost, and preserved
required coverage. This item creates no follow-up TODO.

## Sources

- `_project/analysis/ci-waste-remeasure-2026-08-31.md`
- `_project/analysis/ci-waste-fast-lane-overlap-2026-08-31.md`
- `_project/decisions/strict-base-refresh-activation-2026-08-14.md`
- Live tracker state for `required-ci-coverage-deepest-reproducers`
