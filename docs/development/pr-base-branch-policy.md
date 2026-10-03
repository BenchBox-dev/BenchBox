# PR base branch policy

Open every change against an integration branch. Stacked PRs (a PR whose base is
another feature branch) are allowed only under the conditions in the Stacked PRs
section below; retarget and rebase children after each parent lands.

## Allowed bases

| Base | When |
| --- | --- |
| `develop` | Normal development PRs |
| `release` | Release-lane PRs only |
| `published-results` | Published-results lane only |

Any other base is out of policy, except the parent branch of a stacked PR (see Stacked PRs below).

## Stacked PRs

A stack is allowed when all of these hold:

- One author owns every PR in the stack, and the stack serves one tracker item.
- The stack is at most three PRs deep.
- Only the bottom PR targets `develop`. Each upper PR is a draft that targets its
  parent's branch.

When the parent squash-merges, retarget the child to `develop` and replay only
the child's own commits before arming it:

```bash
gh pr edit <child> --base develop
git fetch origin develop
git rebase --onto origin/develop <old parent tip> <child branch>
git push --force-with-lease
```

`<old parent tip>` is the last commit of the parent branch before it was
squash-merged. Do not arm a child before it is retargeted and rebased.

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
a PR against any base now gets the six unit results. Running the units against
a feature base does not validate the tree that lands on `develop`, which is why
an upper PR stays a draft and is retargeted and rebased after its parent merges.

## Loud failure: the `base-guard` job

The `base-guard` job in `.github/workflows/ci.yml` runs on every
`pull_request` and is a `needs` of the `tooling` unit, so a bad base turns the
required `tooling` check red. It always reports:

- Base is `develop` / `release` / `published-results` → pass in seconds; the
  normal CI lanes apply.
- Base is anything else → fail with an explicit message to retarget or fold
  into the parent.

`ci.yml` also listens for `edited` so retargeting an open PR re-evaluates (a
PR opened on `develop` and later pointed at a feature branch must not keep a
stale green result). On a PR against a non-integration base, `tooling` is red
by design and the other five units still report, which is expected, not a
separate defect.

Unit pins live in `tests/unit/workflows/test_stacked_pr_base_guard.py`.

`published-results` carries only its own workflow, so the guard does not run
there. Porting it is a manual maintainer step (see
`docs/operations/results-phase-2-runbook.md`).

## After a parent merges

`develop` is squash-merge only, so a stacked chain needs a retarget, rebase and
force-push after every parent merge. Workflow:

1. Open the bottom PR against `develop` (or the appropriate integration base).
2. If work depends on an unmerged parent, either stack under the conditions
   above, wait, or fold into the parent PR.
3. After the parent squash-merges, retarget the child to `develop`, run
   `git rebase --onto origin/develop <old parent tip>`, and force-push with
   `--force-with-lease` on the feature branch only.

## "No checks" is not one failure mode

Use REST `mergeable_state` vocabulary from `docs/operations/pr-triage.md`
(GraphQL `mergeable: CONFLICTING` is the same situation as REST `dirty`):

| Symptom | Cause | What to do |
| --- | --- | --- |
| Guard red; other lanes absent | Base is not an integration branch | Retarget to `develop` (or the correct lane base) |
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
- Never open a PR with `--base` set to another feature branch unless it is an upper PR of a stack that meets the conditions in the Stacked PRs section.
- If `pr-base-guard` fails, fix the base; do not try to "add CI" to the
  stacked base by editing branch filters.
- Short agent-facing summary: `AGENTS.md` → section **Verification and
  close-out** (stacked/feature-base PRs are unsupported).
