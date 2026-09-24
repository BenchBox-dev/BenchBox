# Visual-regression job census, 2026-09-17..2026-09-24

This is the reproducible job-level census behind the follow-up measurement in
[`public-site-visual-required-check-2026-09-24.md`](../decisions/public-site-visual-required-check-2026-09-24.md).
It was collected from the GitHub Actions API for the `docs.yml` workflow over
the exact window in the title, using the same method as
[`docs-failure-visual-census-2026-09-17.md`](docs-failure-visual-census-2026-09-17.md):
list every run created in the window, resolve the jobs payload for each failed
run, and keep only jobs whose conclusion was `failure`.

Rows are `job_id (run run_id, created_at, event)`.

Window totals: 558 `docs.yml` runs created in the window (421 `pull_request`,
136 `push`, 1 `workflow_dispatch`) and 26 failed runs (25 `pull_request`,
1 `push`). The 25 failed `pull_request` runs split into 23 with a failed
visual-compare job and 2 linkcheck-only failures; no run failed both. The one
failed `push` run (35492799833, 2026-09-20T05:53:09Z on `develop`) failed
`linkcheck` only.

The decision record cites 21 visual failures among 23 failed documentation PR
runs. That is the state of the window at the moment the decision was committed
(`96dc78778`, 2026-09-24T16:34:24Z). Two later `chore/sync-develop-v0-4-1`
visual failures postdate that commit and are listed separately; including them
gives 23 visual failures among 25 failed PR runs.

## Visual-compare job failures at the decision commit

21 rows:

- 105606842195 (run 35346059060, 2026-09-18T12:42:05Z, pull_request)
- 105903035928 (run 35444661067, 2026-09-19T13:03:53Z, pull_request)
- 105906755175 (run 35446010334, 2026-09-19T13:31:15Z, pull_request)
- 105937857942 (run 35457752465, 2026-09-19T17:19:53Z, pull_request)
- 105971963099 (run 35470326593, 2026-09-19T21:24:37Z, pull_request)
- 106007513867 (run 35482820388, 2026-09-20T02:00:03Z, pull_request)
- 106016340366 (run 35486485840, 2026-09-20T03:24:30Z, pull_request)
- 106016317830 (run 35486496080, 2026-09-20T03:24:43Z, pull_request)
- 106016093300 (run 35486515233, 2026-09-20T03:25:11Z, pull_request)
- 106021158285 (run 35488518217, 2026-09-20T04:11:41Z, pull_request)
- 106021352421 (run 35488528454, 2026-09-20T04:11:55Z, pull_request)
- 106027040697 (run 35490731214, 2026-09-20T05:04:10Z, pull_request)
- 106030670088 (run 35492161939, 2026-09-20T05:37:51Z, pull_request)
- 106031619552 (run 35492268909, 2026-09-20T05:40:23Z, pull_request)
- 106087184528 (run 35513460842, 2026-09-20T13:25:30Z, pull_request)
- 106096982298 (run 35517293885, 2026-09-20T14:42:08Z, pull_request)
- 106998111331 (run 35802319125, 2026-09-23T00:29:58Z, pull_request)
- 107243492727 (run 35876393445, 2026-09-23T14:44:24Z, pull_request)
- 107244982716 (run 35876615350, 2026-09-23T14:46:10Z, pull_request)
- 107253677628 (run 35880132909, 2026-09-23T15:14:57Z, pull_request)
- 107303775528 (run 35895770269, 2026-09-23T17:27:52Z, pull_request)

## Visual-compare job failures after the decision commit

Excluded from the 21-row figure because both were created after `96dc78778`:

- 107831824586 (run 36056979358, 2026-09-24T20:45:11Z, pull_request)
- 107848288544 (run 36062332119, 2026-09-24T21:34:24Z, pull_request)

Both are on `chore/sync-develop-v0-4-1` and are the published-version badge
moving from `v0.4.0` to `v0.4.1`, an intentional release-sync change rather
than a site defect.

## Linkcheck-only failures

2 runs, each failing only `linkcheck`:

- 105985562903 (run 35476125539, 2026-09-19T23:26:20Z, pull_request)
- 106507509077 (run 35652344773, 2026-09-21T20:38:32Z, pull_request)

## Reproduction

The window spans 2026-09-17T00:00:00Z to the decision commit at
2026-09-24T16:34:24Z, or 7.691 days. The decision record's "about 68 red runs
per 25 days" is that measured rate scaled to a 25-day span, so it is directly
comparable with the prior window's 119 visual failures over
2026-08-23..2026-09-16: `21 / 7.691 * 25 = 68.3`.

The two windows use different spans by construction. This one ends at a commit
rather than a calendar boundary, so its denominator is elapsed time. The prior
window is the 25 inclusive calendar days its title names, and its census rows
actually span 2026-08-23T00:12:00Z to 2026-09-15T21:26:45Z. Both rates are
therefore approximate, and the comparison supports "the failure rate stayed
high" rather than an exact ratio.

Reproduce with the Actions API:

```bash
# Every failed docs.yml pull_request run created in the window.
gh api "repos/BenchBox-dev/BenchBox/actions/workflows/docs.yml/runs?per_page=100&created=%3E%3D2026-09-17T00:00:00Z" \
  --jq '.workflow_runs[] | select(.conclusion=="failure" and .event=="pull_request") | "\(.id) \(.created_at) \(.head_branch)"'

# For each failed run ID, resolve which jobs failed.
gh api "repos/BenchBox-dev/BenchBox/actions/runs/<run_id>/jobs?per_page=100" \
  --jq '.jobs[] | select(.conclusion=="failure") | "\(.id) \(.name) \(.created_at)"'
```

Filter the first query's output to `created_at <= 2026-09-24T16:34:24Z` to
reproduce the 21/23 figure exactly. The `created=>=` query parameter must be
percent-encoded (`%3E%3D`) in a shell.

Run and job IDs are stable once published, so the rows above stay verifiable
until GitHub's workflow-run retention removes them. As of this writing the
oldest retrievable `docs.yml` run was created 2026-02-23T21:11:50Z, about 213
days before this census; the checked-in IDs are the durable record after that.
