# Results Explorer Display Contract Policy

Date: 2026-05-11
Source evidence: `_project/verification-logs/results-explorer-display-contract-policy-gate/w0.log`
Checked SHA: `66f207ee03182dbff4b3e5bc368d2c9be282a9b5`
Evidence corpus: read-only generated Results Explorer snapshot from the
primary checkout public data directory, pinned in `w0.log` by SHA256
`7cb861d6cd43f98979b5647813c8c4cbacf2eee05beee0d91152f9df241b05b7`.

## Decision

The Results Explorer must separate publication/provenance from display,
ranking, and comparison evidence. A public result can remain visible for audit
while being excluded from leaderboards, charts, and winner claims.

## Vocabulary

| State | Meaning | Source of truth | Frontend may infer? |
|---|---|---|---|
| `publishable` | Result is allowed in the public corpus and receipt/detail views. | pipeline/read model, currently `visibility` + bundle publication path | No |
| `displayable` | Result may appear in default analytical surfaces as normal evidence. Requires public provenance and at least one valid display timing or a valid primary metric for its surface. | pipeline/read model field: `display_exclusion_reason` is null | No |
| `has_display_timing` | At least one per-query timing is positive, finite, and measured from passing measurement runs. | pipeline/read model field | No |
| `valid_query_count` | Count of query timings usable for charting/comparison: `display_ms > 0` and finite. | pipeline/read model field | No |
| `rankable` | Row can receive rank and contribute to cohort totals. Requires `is_ranking_eligible=true`, valid primary metric, and no ranking exclusion reason. | pipeline/read model field: `ranking_exclusion_reason` is null | No |
| `comparable` | Row can be selected for Compare winner claims and ratios. Requires enough valid query evidence and no comparison exclusion reason. | pipeline/read model field: `comparison_exclusion_reason` is null | No |
| `validation passed` | Result validation status is clean. This is provenance quality, not timing quality. | existing validation status helpers | No |
| `trusted` / trust tier | Maintainer/community/local provenance tier. Trust does not imply rankability or comparability. | existing `trust_label` | No |
| `missing run` / `No run` | A platform has no public result for a cohort cell. It is not a result row and must not have receipt/run links. | frontend can infer from absent cell within emitted cohort matrix | Yes, only from missing read-model row |
| `missing timing` | A public result exists but has no valid display timing for a query/result/cohort. | pipeline/read model exclusion reason | No |
| `sub-millisecond timing` | Positive measured value below 1 ms. It may display as `<1 ms` while remaining positive in data. | pipeline/read model keeps original positive value | No |

## Timing Semantics

Exact `display_ms = 0.0` is invalid for ranking, comparison, geomeans,
percentiles, CDFs, box plots, heatmaps, and winner claims unless a future
pipeline can prove it is a positive measured value rounded to zero. The current
safe rule is:

- positive fractional timings may display as `<1 ms`;
- exact zero timings remain auditable in details/receipts;
- exact zero timings do not count toward `valid_query_count`;
- exact zero timings require an exclusion reason when they suppress display,
  ranking, or comparison.

This matches the existing Python aggregate behavior, which already excludes
non-positive values from percentile and geomean calculations.

## Compare Winner Threshold

Compare may emit winner language only when no selected result has a row-level
comparison exclusion and the selected set has enough common valid query
evidence:

- at least 2 common comparable queries; and
- at least 50% of the cohort query set has valid positive timings for every
  selected result.

If either threshold fails, Compare must show an insufficient-evidence summary,
suppress winner/headline language such as "X is faster", keep raw query diffs
available, and explain excluded query counts. The AMPLab evidence in `w0.log`
shows the failure case: the selected runs have only one query where all three
rows have positive timings, yet current Compare emits a 1.59x winner claim.

## Page-Level Behavior

| Surface | Default behavior | Provenance path |
|---|---|---|
| Home meta leaderboard | Include only ranked leaderboard cohorts. Copy must say leaderboard/cohort scope, not full public corpus scope. | Separate browse/corpus counts may link to public result detail pages. |
| Benchmark matrix/rank/list | Default analysis views include display-safe rows only. All-unrankable cohorts must not present as authoritative leaderboards. | Excluded runs disclosure with reason and receipt/detail links. |
| Chart panels | Use `valid_query_count` / valid timing fields consistently. Do not silently include zero timings in one chart and exclude them in another. | Excluded-count or reason near the chart when rows are withheld. |
| Platform detail tables | Comparable rows keep normal selection and links. Excluded rows show reason and cannot be selected for Compare. | Receipt/detail link remains visible. |
| Compare selection | Disable or omit rows with `comparison_exclusion_reason`; disabled controls require accessible reason text. | Detail/receipt links remain available outside selection controls. |
| Query Workbench rows | Public rows can be listed, but non-comparable rows cannot be selected for Compare as valid evidence. | Keep result links and show exclusion reason. |

## TODO Sequence Review

The dependent TODO sequence already matches this contract:

1. `results-explorer-read-model-eligibility-contract` emits the authoritative
   read-model fields and invariant checks.
2. `results-explorer-frontend-eligibility-normalization` consumes those fields
   through one frontend helper.
3. `results-explorer-rank-and-compare-evidence-gates` applies route behavior
   and winner suppression.
4. `results-explorer-home-scope-theme-and-identity` fixes scope copy,
   formatting, theme, and identity density after semantics are normalized.
5. `results-explorer-contract-release-gate` verifies the full sequence against
   SQL invariants, tests, and browser routes.

No dependent TODO guardrail changes are required by this policy gate.
