# PR base branch policy

BenchBox does **not** support stacked PRs (a PR whose base is another feature
branch). Open every change against an integration branch and rebase children
after each parent lands.

## Allowed bases

| Base | When |
| --- | --- |
| `develop` | Normal development PRs |
| `release` | Release-lane PRs only |
| `published-results` | Published-results lane only |

Any other base (including a sibling feature branch) is out of policy.

## Why stacked bases get zero CI

Almost every PR workflow filters on those integration branches:

```yaml
on:
  pull_request:
    branches: [develop]   # or release / published-results
```

A PR opened against `fix/parent` therefore triggers **no** `pr.yml`, no
`ci-required-result`, and no browser lane. The GitHub PR page looks calm
(empty check list) rather than broken, and the change can reach `develop`
only when the parent merges — never validated on its own and attributed to
the parent's PR.

That silence is intentional branch-filter design, not a CI outage. We do
**not** widen every workflow's branch filter to "support" stacking; that
would dilute the integration-branch contract and still leave squash-merge
chains needing rebases.

## Loud failure: `pr-base-guard.yml`

`.github/workflows/pr-base-guard.yml` is the one PR workflow **without** a
`branches:` filter. It always reports:

- Base is `develop` / `release` / `published-results` → pass in seconds; the
  normal CI lanes apply.
- Base is anything else → fail with an explicit message to retarget or fold
  into the parent.

It also listens for `edited` so retargeting an open PR re-evaluates (a PR
opened on `develop` and later pointed at a feature branch must not keep a
stale green result).

Unit pins live in `tests/unit/workflows/test_stacked_pr_base_guard.py`.

## After a parent merges

`develop` is squash-merge only. A stacked chain would need a rebase and
force-push after every parent merge anyway. Preferred workflow:

1. Open each PR against `develop` (or the appropriate integration base).
2. If work depends on an unmerged parent, wait or fold into the parent PR.
3. After the parent squash-merges, rebase the child onto the updated base and
   force-push with `--force-with-lease` on the feature branch only.

## "No checks" is not one failure mode

Use REST `mergeable_state` vocabulary from `docs/operations/pr-triage.md`
(GraphQL `mergeable: CONFLICTING` is the same situation as REST `dirty`):

| Symptom | Cause | What to do |
| --- | --- | --- |
| Guard red; other lanes absent | Base is not an integration branch | Retarget to `develop` (or the correct lane base) |
| No checks at all, `mergeable_state: dirty` (GraphQL `mergeable: CONFLICTING`) | Conflicts with the base tip | Rebase/resolve onto the base tip |
| Required checks missing/stuck on an integration base; `mergeable_state: blocked` | CI unfinished, path gate, or ruleset | Inspect check runs — do not retarget |

Do not treat an empty check list on a feature base as "CI is fine" or as the
same problem as `dirty` (conflicts) or `blocked` (unfinished gates) on
`develop`.

A conflicting PR is the easiest of these to misread, because it produces **zero**
`pull_request` workflow runs rather than a failure: GitHub cannot build the merge
ref, so no workflow is ever dispatched, and nothing on the PR says so. An empty
check list on a correct base therefore means conflicts at least as often as it
means a path filter. Check `gh pr view <N> --json mergeable` before diagnosing
missing CI as a workflow or filter problem.

## Agent checklist

- `make pr-open` (and manual `gh pr create`) must target `develop` unless the
  change is explicitly for `release` or `published-results`.
- Never open a PR with `--base` set to another feature branch.
- If `pr-base-guard` fails, fix the base; do not try to "add CI" to the
  stacked base by editing branch filters.
- Short agent-facing summary: `AGENTS.md` → section **PR base branch
  (stacked PRs unsupported)**.
