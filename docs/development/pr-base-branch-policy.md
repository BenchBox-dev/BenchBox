# PR base branch policy

Only PRs based on an integration branch enter the merge queue. Stacking is
allowed narrowly: a stack belongs to one author and one tracker item and is at
most three PRs deep. Every PR above the bottom one is a **draft** that targets
its parent branch, so it gets Codex connector review and CI there. When the
parent squash-merges, retarget the child to `develop`, rebase it onto the
squash commit with `git rebase --onto origin/develop <old parent tip>`, let CI
rerun, and only then arm it. `make pr-open` always targets `develop`, so open
an upper draft with `gh pr create --draft --base <parent branch>`.
`make pr-arm` refuses a PR whose base is not `develop`.

## Allowed bases

| Base | When |
| --- | --- |
| `develop` | Normal development PRs |
| `release` | Release-lane PRs only |
| `published-results` | Published-results lane only |

The only other allowed base is the parent branch of a draft PR in a stack. A
ready PR on any other base, including a sibling feature branch, is out of
policy.

## Why stacked bases used to get zero CI

Before the single `ci.yml`, almost every PR workflow filtered on those integration branches:

```yaml
on:
  pull_request:
    branches: [develop]   # or release / published-results
```

A PR opened against `fix/parent` triggered **no** required checks. The GitHub
PR page looked calm (empty check list) rather than broken, and the change could
reach `develop` only when the parent merged — never validated on its own and
attributed to the parent's PR.

`.github/workflows/ci.yml` has **no** `branches:` filter on `pull_request`, so
a PR against any base now gets the six unit results. Units run against a
parent branch validate the child on top of its parent, not the tree that lands
on `develop`, so the rebase onto `develop` and the CI rerun after it are what
gate the merge.

## Loud failure: the `base-guard` job

The `base-guard` job in `.github/workflows/ci.yml` runs on every
`pull_request` and is a `needs` of the `tooling` unit, so a bad base turns the
required `tooling` check red. It always reports:

- Base is `develop` / `release` / `published-results` → pass in seconds; the
  normal CI lanes apply.
- Base is anything else and the PR is a draft → pass; the PR cannot be armed
  until it is retargeted at `develop`.
- Base is anything else and the PR is ready → fail with an explicit message to
  retarget to `develop` after the parent merges.

`ci.yml` also listens for `edited`, `ready_for_review` and
`converted_to_draft` so retargeting a PR or changing its draft state
re-evaluates (a PR pointed at a feature branch, or a draft marked ready, must
not keep a stale result). On a ready PR against a non-integration base,
`tooling` is red by design and the other five units still report, which is
expected, not a separate defect.

Unit pins live in `tests/unit/workflows/test_stacked_pr_base_guard.py`.

`published-results` carries only its own workflow, so the guard does not run
there. Porting it is a manual maintainer step (see
`docs/operations/results-phase-2-runbook.md`).

## After a parent merges

`develop` is squash-merge only, so a child stacked on a merged parent must be
rebased before it can land:

1. Retarget the child PR to `develop`.
2. Rebase it onto the squash commit with
   `git rebase --onto origin/develop <old parent tip>` and force-push with
   `--force-with-lease` on the feature branch only.
3. Wait for CI on the new head. For a soundness-path change, also wait for a
   Codex connector review or thumbs-up on the rebased head: the rebase
   rewrites the head, so review of the draft against its parent no longer
   covers it.
4. Arm it with `make pr-arm`.

## "No checks" is not one failure mode

Use REST `mergeable_state` vocabulary from `docs/operations/pr-triage.md`
(GraphQL `mergeable: CONFLICTING` is the same situation as REST `dirty`):

| Symptom | Cause | What to do |
| --- | --- | --- |
| Guard red on a ready PR; other lanes absent | Base is not an integration branch | Retarget to `develop` (or the correct lane base), or convert to a draft if it is an upper stack PR |
| `mergeable_state: dirty` (GraphQL `mergeable: CONFLICTING`) | Conflicts with the base tip | Rebase/resolve onto the base tip |
| Required checks missing/stuck on an integration base; `mergeable_state: blocked` | CI unfinished, path gate, or ruleset | Inspect check runs — do not retarget |

Do not treat an empty check list on a feature base as "CI is fine" or as the
same problem as `dirty` (conflicts) or `blocked` (unfinished gates) on
`develop`.

On a conflicting PR, GitHub cannot build the merge ref, so `pull_request`
workflows, including `ci.yml`, never start and no unit reports. Diagnose with
`gh pr view <N> --json mergeable` plus the expected check names — do not infer
conflicts, or a filter bug, from an empty or partial check list alone.

## Agent checklist

- `make pr-open` (and manual `gh pr create`) must target `develop` unless the
  change is explicitly for `release` or `published-results`.
- Open a PR with `--base` set to another feature branch only as a draft in a
  stack (one author, one tracker item, depth 3 or less); never arm it before
  it is retargeted at `develop`.
- If `base-guard` fails on a ready PR, fix the base; do not try to "add CI" to
  the stacked base by editing branch filters.
- Short agent-facing summary: `AGENTS.md` → section **Verification and
  close-out** (stacking rule).
