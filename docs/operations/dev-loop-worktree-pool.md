<!-- Copyright 2026 Joe Harris / BenchBox Project. Licensed under the MIT License. -->

# Worktree pool — maintainer dev loop

```{tags} contributor, operations, dev-loop
```

BenchBox uses a **retained pool of 10 git worktrees** (`POOL_SIZE = 10`)
for the maintainer + AI-agent dev loop. New work claims a free slot,
runs there until the PR merges, then releases it back to the pool. The
slot survives — including its `.venv/` — so subsequent claims skip the
expensive setup.

This page is the maintainer/agent reference for that workflow. External
contributors working from a fork do not need the pool — they clone,
commit on their own branch, and open a PR; see
[development.md](../development/development.md) for that flow.

## At a glance

```text
Layout (siblings of the main clone):
  /Users/joe/Developer/BenchBox          ← main clone, always on develop
  /Users/joe/Developer/BenchBox.pool-01  ← pool slot 1
  /Users/joe/Developer/BenchBox.pool-02  ← pool slot 2
  ...
  /Users/joe/Developer/BenchBox.pool-10  ← pool slot 10
```

A free slot is detached at `origin/develop` with a clean working tree.
A claimed slot is on a feature branch (`chore/…`, `fix/…`, `feat/…`,
`docs/…`).

## Common commands

The minimum surface for routine work — start here.

| When | Command | Effect |
|---|---|---|
| Start a new task | `make worktree-claim BRANCH=fix/foo` | Pick a free slot, fetch + reset to current `origin/develop`, create branch, refresh `.venv/` only if `uv.lock`/`pyproject.toml` changed. Prints `WORKTREE_PATH=…`. |
| Inside the slot, ship the work | `make pr-preflight && make pr-open` | Run the local lint + fast-test gate, push, open PR vs `develop`, enable squash auto-merge. Walk away — auto-merge lands it once CI is green. |
| After the PR merges | `make worktree-release` | Detach the slot back to `origin/develop`, delete the local feature branch. Refuses unless the PR state is `MERGED` (use `FORCE=1` to escape — only when intentional). |
| See pool state any time | `make worktree-pool-status` | Tabular: pool, path, branch, state, claim age, venv health, disk size. Read-only; safe to run during other operations. |
| Recover forgotten slots | `make worktree-pool-sweep-stale` | Auto-release every slot whose PR is `MERGED` and tree is clean. Idempotent; refuses dirty/claimed-no-PR/unknown slots. Auto-runs once before `worktree-claim` fails. |

Pre-approved in Claude Code's user-global settings; agents can run them
without prompting.

## Slot states

Reported by `make worktree-pool-status`:

| State | Meaning | Recovery |
|---|---|---|
| `free` | Detached HEAD, clean tree — claimable. | None needed. |
| `claimed` | On a feature branch, no PR yet or PR open. Active work. | Continue work or `make pr-open`. |
| `stale` | On a feature branch whose PR is `MERGED`. | `make worktree-pool-sweep-stale` (or `worktree-release` from inside). |
| `dirty` | Uncommitted changes (excluding `.benchbox/` scratch). | Review, commit/discard manually, then release. |
| `aborted` | A `.benchbox/claim_in_progress` marker survived a crashed claim. | `make worktree-pool-reset POOL=NN` after reviewing what's there. |
| `unknown` | `gh` lookup for the branch's PR state failed (auth/network/rate limit). | Re-run when `gh auth status` is clean. |
| `missing` | Slot directory absent. | `make worktree-pool-init` to recreate. |

Venv health column:

| Venv | Meaning |
|---|---|
| `ok` | `.venv/pyvenv.cfg` exists and is at least as new as `uv.lock` + `pyproject.toml`. |
| `stale` | `.venv` exists but a dependency manifest is newer — next claim re-syncs. |
| `missing` | `.venv` absent — next claim recreates it. |

## Common scenarios

### Pool is full when I try to claim

`worktree-claim` automatically runs `worktree-pool-sweep-stale` once on
the first miss and retries. If still full afterwards, every slot is
either `claimed` (active work), `dirty` (uncommitted), or `unknown` (gh
flake). Inspect:

```bash
make worktree-pool-status
```

Then either finish/abandon a claimed slot, or — only after reviewing
the diff — manually reset one:

```bash
make worktree-pool-reset POOL=04           # refuses if dirty
make worktree-pool-reset POOL=04 FORCE=1   # interactive RESET prompt
```

### `claim` says my branch already exists

The atomic-claim retry path can trip if a previous claim half-succeeded
(branch created, slot marked free again). Delete the stale local
branch and retry:

```bash
git branch -D chore/foo
make worktree-claim BRANCH=chore/foo
```

### Slot has uncommitted changes I don't recognise

Stay calm — this is the design. The pool deliberately does **not**
auto-reap dirty slots, because a crashed agent session might have left
work that's only on disk. Inspect from inside:

```bash
cd ../BenchBox.pool-04
git status
git diff
```

Decide: commit + open a PR, or reset (with FORCE after reviewing).

### Disk is filling up

Pytest, coverage, and ruff caches accumulate per slot. Strip them
across all 10 slots:

```bash
make worktree-pool-disk-clean
```

Reports per-slot freed bytes. Does not touch `.venv/` — that's
intentional, it's the expensive thing the pool retains.

### Bootstrap a new workstation

Once, after cloning the main repo:

```bash
make worktree-pool-init
```

Creates `BenchBox.pool-01..10` as detached siblings, runs `uv sync
--group dev` and `pre-commit install` in each. Idempotent — re-running
leaves existing slots alone, only fills missing ones. Override defaults
via env: `POOL_SIZE=N` and `WORKTREE_POOL_PARENT=…` (used by the test
suite for disposable pools).

### Publish across many open branches

If several pool slots have unpushed work:

```bash
make pr-fanout
```

Walks every worktree (skipping the main clone) and runs `make pr-open`
with bounded parallelism (`PR_FANOUT_JOBS ?= 4`). Sequenced so the
local pre-push hook lock doesn't bottleneck it.

## Full Make target reference

| Target | Use |
|---|---|
| `make worktree-pool-init` | Bootstrap missing slots; idempotent. |
| `make worktree-claim BRANCH=<type>/<slug>` | Claim a free slot atomically. `<type>` ∈ `chore\|fix\|feat\|docs`. |
| `make worktree-release [FORCE=1]` | Release the current pool slot back to detached `origin/develop`. |
| `make worktree-pool-status` | Read-only state listing for all slots. |
| `make worktree-pool-sweep-stale` | Auto-release MERGED-and-clean slots. |
| `make worktree-pool-reset POOL=NN [FORCE=1]` | Per-slot manual escape hatch. |
| `make worktree-pool-disk-clean` | Strip pytest/coverage/ruff caches across all slots. |
| `make worktree-list` | `git worktree list` passthrough. |
| `make worktree-prune` | Legacy non-pool worktree cleanup; explicitly skips pool slots. |
| `make worktree-add BRANCH=…` | **Deprecated** alias of `worktree-claim`; tracked for removal. |

## Invariants

These are guaranteed by the targets above; agents and humans can rely
on them:

- **Idempotent init.** `worktree-pool-init` never destroys or resets
  existing slots — re-running is safe.
- **Atomic claim.** Concurrent `worktree-claim` invocations always
  pick distinct slots (serialized via `.git/pool.lock`).
- **Retained `.venv/`.** Slots keep their virtualenv across
  release/claim cycles. `uv sync` only re-runs at claim time when a
  dependency manifest is newer than the venv.
- **No silent reaping.** Dirty slots and `aborted` slots are never
  auto-recovered — surfacing them via `pool-status` is intentional, so
  uncommitted work is never discarded without operator review.
- **Pool slots never check out `develop`.** Free state is detached
  `origin/develop`. The main clone owns the local `develop` branch and
  Git forbids the same branch in two worktrees.
- **`worktree-prune` skips pool slots.** Routine end-of-session prune
  is no longer needed — slots are released, not removed.

## See also

- `CLAUDE.md` and `AGENTS.md` — session-start rules and pre-approved
  command lists for AI agents.
- [release-guide.md](release-guide.md) — release-branch flow that runs
  alongside this dev loop.
- [repo-admin-settings.md](repo-admin-settings.md) — GitHub-side admin
  state (rulesets, required checks, incident labels) the dev loop
  depends on.
