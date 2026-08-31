# CI waste dev-loop remeasure (2026-08-31)

## Provenance and bounded cohort

Collected read-only from `BenchBox-dev/BenchBox` on 2026-08-31 UTC against
`origin/develop` at `0f9f6682754a824cc18567fbc71295dfed503eec`.
The exact cohort is committed in
[`ci-waste-remeasure-2026-08-31-manifest.json`](ci-waste-remeasure-2026-08-31-manifest.json).
It pins the pull-request and merge-group snapshot timestamps, every PR number
and head SHA, the `develop` base ref, every PR's merge timestamp and changed
filenames, the code-routed classification, every selected workflow run ID and
event, and every selected check-suite ID. No PR in this cohort had a
manifest-forced code path. Replay it read-only with:

```text
uv run -- python _project/analysis/replay_ci_waste_remeasure.py
```

For each head, the replay first discovers all Actions runs by `head_sha`,
applies the cohort's event filter and snapshot cutoff, and requires the exact
run/event/suite set to equal the manifest. It then fetches those exact run
records and jobs. It retains only `pull_request` and `pull_request_target` runs
for PR rows, only `merge_group` runs for merge rows, and only commit check-runs
whose suite IDs match the selected runs. For PRs, it also requires the live PR
to remain merged with the exact pinned head SHA, merge timestamp, and
`develop` base. The live immutable file list must equal the manifest; replay
then recomputes `needs_code_ci` with the unchanged
`scripts/path_filter_decision.py` rules and requires it to equal `code_routed`.

The replay calls the existing `event_fanout_metrics` contract and checks every
published metric plus merge-unblock, queue-delay availability and distribution,
public runner cost, cancelled/incomplete job counts, schema, and the full
setup/execution distributions. Its offline regression includes negative
controls for an omitted eligible run, altered routing, and an altered expected
metric or PR identity:

```text
uv run -- python _project/analysis/replay_ci_waste_remeasure.py --self-test
```

The cohort contains 13 merged PRs: #1977, #1973, #1976, #1972, #1971,
#1936, #1969, #1946, #1952, #1964, #1966, #1965, and #1962. The 11
code-routed PRs are #1977, #1973, #1972, #1971, #1969, #1966, #1965,
#1964, #1962, #1952, and #1946. The merge-group cohort is the five exact
heads in the manifest; it is not a moving "newest heads" query.

## Results

Values are median / minimum–maximum across valid event rows. Wall clocks are
seconds; runner values are completed runner-minutes. Pull-request and
merge-group observations are separate cohorts.

| Event | Rows | required-gate wall | all-workflow wall | completed runner-min | cancelled runner-min |
|---|---:|---:|---:|---:|---:|
| `pull_request` code-routed | 11 | 1,285 / 1,063–1,537 | 1,290 / 1,069–1,573 | 98.73 / 73.20–103.78 | 0 / 0–0 |
| `pull_request` all | 13 | 1,268 / 78–1,537 | 1,276 / 419–1,573 | 96.58 / 2.75–103.78 | 0 / 0–0 |
| `merge_group` | 5 heads | 1,326 / 81–1,342 | 1,331 / 86–1,345 | 83.07 / 1.85–91.27 | 0 / 0–0 |

The primary `pull_request` code-routed cohort is 11 of 13 rows. This is
classified from each PR's changed filenames using
`scripts/path_filter_decision.py --changed-file` and its `needs_code_ci`
decision; it is not inferred from duration. The all-13 row remains context
for the full observed pull-request sample.

## Sibling fan-out observed

| Cohort | Common workflows | Union / observed exceptions |
|---|---|---|
| `pull_request` (13) | Develop PR; Develop ruleset drift; Results Explorer browser tests; Develop refresh shadow; Auto-merge revocation; PR base guard | Documentation (12/13); Extension Smoke (1/13) |
| `merge_group` (5 heads) | Develop PR; Develop ruleset drift; Results Explorer browser tests | No additional workflow in this bounded sample |

The smaller `merge_group` three-workflow set is event-specific and cannot be
treated as a pull-request saving or evidence that pull-request siblings are
absent.

Setup/execution runner-minute medians were 13.52 / 83.27 for the code-routed
`pull_request` cohort, 13.40 / 80.12 for all pull requests, and 11.60 / 69.45
for `merge_group`. Public standard-runner dollar cost remains 0. Queue delay
is not applicable to the merge-group heads because they have no PR
`merged_at` timestamp; replay asserts zero recorded and five unrecorded
merge-group queue-delay values.

## Definitions and limitations

`required-gate` is the first required-check start through the latest success
of `ci-required-result`, `Results Explorer browser gate`, and `ruleset-drift`.
`all-workflow` spans the earliest workflow start through the last completed
sibling on that head SHA. Completed runner minutes exclude cancelled,
failed, and incomplete jobs; cancelled minutes are reported separately.
For `pull_request`, runs were limited to the exact current PR head SHA and
events `pull_request` or `pull_request_target`; push, merge-group, and other
events were excluded. Commit check-runs were then limited to the selected
run suite IDs. These definitions and the `event_fanout_v1` contract come from
`_project/decisions/strict-base-refresh-ci-profile-2026-08-14.md` and the
existing collector.

This is a pinned, bounded observational sample, not a causal estimate and not
an authorization to skip, demote, extract, or remove CI coverage. The
merge-group cohort has only five heads and required-check availability can
vary by head. The manifest records the expected aggregates; the replay's
suite filter prevents unrelated check-runs on the same commit from entering
the measurement.
