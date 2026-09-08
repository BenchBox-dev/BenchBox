# Native queue local landing

Supersedes the ancestry-freshness gate for author-side publication while the
approved native merge queue guards `refs/heads/develop`.

## Decision

When the queue configuration is verified (SQUASH, ALLGREEN, 1/5/5, 60-minute
timeout, 0 wait, `ci-required-result` + Results Explorer browser gate +
`ruleset-drift` required; `scripts/ruleset_drift_check.py::merge_queue_findings`
green), a branch behind `origin/develop` publishes WITHOUT an author-side
refresh merge. Queue integration tests the speculative merge, so the refresh
only destroys a nearly-complete gate to no benefit. See
`scripts/pr_landing.py::stale_base_decision`.

## Fallbacks (conservative, unchanged)

- Queue absent, unreadable, unsupported, or misconfigured: `require-current`
  (existing ancestry gate stands; no behavior removed).
- Genuine conflict (not mere behindness): `resolve-conflict-first`; no
  refresh merge can fix a conflict and none is attempted.
- Nearly-complete gates measure from the lifecycle baseline
  (`_project/analysis/ci-lifecycle-baseline.json`); queue-eviction cost is
  judged against queue outcomes, never against a single wall-clock sample,
  and re-entry follows the retry bound (one per unchanged head) in
  `scripts/pr_landing.py::allow_retry`.

## Verification

`scripts/ruleset_drift_check.py` reports protected-setting changes for
operator action and never repairs them. Queue parameter changes are blocking
findings; an invisible queue rule is a non-blocking warning, never silent
approval. A canary branch (conflict-free, one commit behind) that does not
merge after the queue is enabled defeats this decision and restores
`require-current` until the wiring is fixed.
