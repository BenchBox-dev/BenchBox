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
interarrival (p50 27.5 min; 51.5% of gaps under 31 min). Open-time currency
does not close that in-flight residual. Live `shadow_eligible` yield on
the 10 newest shadow artifacts is **0**. Therefore neither 07a nor 07b is
justified from this item.

## What this does not do

- Does not treat open-time currency as sufficient against interarrival.
- Does not recommend updating every open PR (refresh storm).
- Does not unblock 07a or 07b. Activation remains
  `strict-base-refresh-06-activation-decision-and-selected-path-handoff`.

## Correction (2026-10-09)

The superseded sentence described merge interarrival as
“p50 31.3 min; 50% of gaps under 31 min.”
Both this record and its audit originally reported 31.3 minutes over
32 gaps in PR #1756 (`0dd61b48b`). PR #1774 (`fe3b352c0`) recomputed
the audit over 33 gaps to a p50 of 27.5 minutes, with 51.5% of gaps
under 31 minutes, but left this record's figures unchanged.
The decision above now matches the revised audit. The 31.4-minute
required-gate duration and the decision to keep `SHADOW_ONLY` are unchanged.

The same stale p50 in the skill-integrity lane comparison is corrected
with its own dated erratum. The citation in
`_project/analysis/pr-process-acceptance-baseline.json` is preserved because
that file is a frozen preregistration bound by a content digest to measured
reports; its historical 31.3-minute citation is superseded by this correction.
