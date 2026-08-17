# Decision: keep SHADOW_ONLY after behind-PR throughput measurement

Date: 2026-08-16
Status: Accepted. Recommendation only. This record does not skip jobs,
change required contexts, mutate GitHub settings, or unblock
`strict-base-refresh-07a-reduced-fast-refresh-rollout` or
`strict-base-refresh-07b-native-merge-queue-migration`.
Observed tip: `origin/develop` `360cd918756597b298af3f0d18434f35387b0fe1`.

Evidence: `_project/audits/behind-pr-occurrence-throughput-2026-08-16.md`.
Policy: `_project/decisions/behind-pr-occurrence-2026-08-16.md`.

## Decision

**Keep `SHADOW_ONLY`.**

The sample (33 develop merges, 2026-08-14 through 2026-08-17) shows
required-gate duration (19.7–31.4 min) is a material fraction of merge
interarrival (p50 31.3 min; 50% of gaps under 31 min). Open-time currency
does not close that in-flight residual. Live `shadow_eligible` yield on
the 10 newest shadow artifacts is **0**. Therefore neither 07a nor 07b is
justified from this item.

## What this does not do

- Does not treat open-time currency as sufficient against interarrival.
- Does not recommend updating every open PR (refresh storm).
- Does not unblock 07a or 07b. Activation remains
  `strict-base-refresh-06-activation-decision-and-selected-path-handoff`.
