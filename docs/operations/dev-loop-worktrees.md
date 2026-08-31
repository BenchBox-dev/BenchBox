# Disposable development worktrees

BenchBox does not retain or reuse a worktree pool. Each agent task gets one
ordinary linked worktree and removes that exact worktree when the task is
complete.

## Start a task

Run from the primary clone, which remains read-only for agent changes:

```bash
WORKTREE_PATH=../BenchBox.wt-fix-example
make worktree-create BRANCH=fix/example WORKTREE_PATH="$WORKTREE_PATH"
cd "$WORKTREE_PATH"
make agent-write-preflight
uv sync --group dev
uv run -- pre-commit install
```

The branch must use one of the repository's feature prefixes: `chore/`,
`fix/`, `feat/`, or `docs/`. The standard base is `origin/develop`.
Creation checks both local and `origin` branch refs before creating anything,
so `origin` must be reachable; it fails closed when remote collision state
cannot be verified.

## Finish a task

After the PR merges and the worktree is clean, remove the exact registration:

```bash
cd /Users/joe/Developer/BenchBox
make worktree-remove WORKTREE_PATH="$WORKTREE_PATH"
```

Removal refuses the primary clone, detached worktrees, dirty or untracked files
(including files under `.benchbox/`), missing paths, unregistered paths, and
locked worktrees.
If identity setup fails during creation, the helper removes the exact
worktree and branch created by that invocation. It does not unlock,
force-remove an existing worktree, delete an existing branch, query GitHub, or
prune registrations. Clean local branch cleanup is a separate operation.

If a worktree is locked with an `agentbox mount guard`, confirm that the mount
is inactive before running the separate operator action:

```bash
git worktree unlock /absolute/path/to/worktree
```

Never unlock or prune a worktree while its `.git` directory is mounted by a
container.

Local branches created with plain `git checkout -b` (no worktree) are not
swept by `worktree-remove`. After the PR merges, preview and sweep only those
worktree-less branches still at the exact commit GitHub merged:

```bash
make branch-prune-merged DRY_RUN=1   # preview (requires gh)
make branch-prune-merged             # delete only historically proven merge-time heads
```

`branch-prune-merged` skips the current branch, `develop`/`main`/`release`/
`published-results`, and any branch still attached to a worktree. It fetches
`origin/develop`, proves the latest PR's historical merge-time head from the
GitHub timeline plus paginated PR commit list, requires the local tip to equal
that immutable head, and verifies the PR merge commit is reachable from the
fresh target. A branch re-created under an old merged name, carrying post-merge
commits, or lacking complete evidence is reported and kept. Evidence collection
or branch deletion failures return nonzero rather than reporting false success.
The final ref deletion is an expected-OID compare-and-swap, so a branch changed
after evidence collection is preserved.

## Inspection

Use native Git and the read-only audit tool for inspection:

```bash
make worktree-list
make worktree-audit
make worktree-audit FORMAT=json
make branch-prune-merged DRY_RUN=1
git -C /absolute/path/to/worktree status --short
```

`make worktree-audit` performs a bounded, fail-closed inventory combining live
Git structure, exact GitHub PR evidence, and structural-branch policies. It
records point-in-time snapshot files under `_project/reports/worktree-lifecycle/`
(gitignored), never mutates Git state, never prunes, and never unlocks.
Per Spec §9, audit reports carry zero deletion authority; removal requires manual verification.

Existing registrations created by the retired workflow are not automatically
reset or removed by this workflow. Review and remove them separately,
preserving dirty, locked, divergent, or ambiguous worktrees.
