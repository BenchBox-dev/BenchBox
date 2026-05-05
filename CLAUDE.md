# CLAUDE.md - Quick Reference

→ **See AGENTS.md for full guidance.** Claude Code-specific shortcuts only.

**Critical rules**: Always `uv run` (never bare `python`/`pytest`/`ruff`/`ty`). Never `git add -A`. Dev PRs target `develop`, never `main` (`main` is release-only and `develop` is PR-gated — no direct push to either). **All agent edits and commits happen in a worktree off `develop`. If a session begins in the main clone (`/Users/joe/Developer/BenchBox`), creating a worktree is the FIRST action (see "Session start" below). Never `git checkout`/`switch`/`branch -m` in the main clone without explicit user approval — that clone stays on `develop`.** **Never open a PR or enable auto-merge as a side-effect of a review, audit, or research action — see the synced `SHARED/review-protocol` skill §1. Landing changes requires explicit user authorization in a separate turn; this fires before any "auto-commit" or "file-first capture" mandate elsewhere.** TPC-DS SF<1 requires the patched dsdgen bundled with BenchBox (stock dsdgen crashes at SF<1; see `patch-and-redistribute-tpcds-dsdgen-subscale-support`). No `-o "addopts="` with pytest.

## Session start

**First action of any new session that might write to the repo**: confirm
you are in a worktree, not the main clone.

```bash
git rev-parse --show-toplevel
# If the output is /Users/joe/Developer/BenchBox you are in the main
# clone. Stop. Claim a retained pool worktree BEFORE any edit, commit,
# or branch switch:
BRANCH=fix/short-slug   # choose chore|fix|feat|docs
WORKTREE_PATH=$(make -s worktree-claim BRANCH="$BRANCH" | sed -n 's/^WORKTREE_PATH=//p')
cd "$WORKTREE_PATH"
```

Pick the branch name from the user's stated task (e.g.
`fix/explorer-cold-load`, `chore/claude-md-rules`,
`feat/query-row-limit`). If the task is unclear, ask the user before
creating the worktree.

**Read-only carveout.** Pure Q&A / exploration sessions — no edits,
no commits, no state-mutating commands — may stay in the main clone.
The instant the session turns into a write task, create a worktree
before the first edit.

BenchBox uses a retained pool of 10 worktrees. `make worktree-claim`
atomically picks a free `BenchBox.pool-NN`, resets it to current
`origin/develop`, checks out the requested branch, and prints
`WORKTREE_PATH=...`. `uv sync --group dev` runs only when `uv.lock` or
`pyproject.toml` is newer than the existing `.venv`, so repeat claims
after a clean release skip the sync. If anything fails after the
branch is created, the slot is rolled back to detached
`origin/develop` automatically. After the PR merges, run
`make worktree-release` inside that pool worktree to return it to
detached `origin/develop`.

`make worktree-pool-status` reports each slot's state (free / claimed /
stale / dirty / unknown / missing), venv health (ok / stale / missing),
and disk usage. After a busy session, `make worktree-pool-sweep-stale`
auto-releases slots whose PRs are MERGED on origin and whose trees are
clean — idempotent. Reach for `make worktree-pool-reset POOL=NN` only
as a last-resort manual escape hatch after reviewing what will be
discarded. `make worktree-add` remains as a deprecated one-release
compatibility path for legacy non-pool worktrees.

**If you find the main clone on a non-`develop` branch**, surface it
to the user and ask before writing anything to it — that may be the
user's in-progress work; do not reflexively `git checkout develop` to
"clean up", that can discard uncommitted state.

## Git workflow

Single repo, single remote (`origin` → `joeharris76/BenchBox`). Working
clone: `/Users/joe/Developer/BenchBox` (the canonical path; the old
private clone was retired to `BenchBox.retired-20260427/` alongside it
during the single-repo migration).

> **Remote sanity check.** If `git remote -v` shows anything other than
> a single `origin → joeharris76/BenchBox`, stop and ask — that's a
> leftover from the pre-migration two-remote setup (`private` /
> `public`) and pushing without confirming could leak intent across
> repos. There is **no** `private` or `public` remote anymore; all
> work goes to `origin` and PRs target `develop` (or `main` for
> releases).

- **Branches**: `develop` is the long-lived dev branch; `main` is
  release-only.
- **Dev PRs**: feature branch off `develop` → PR → squash-merge to
  `develop`. Required CI reports through the `ci-required-result`
  umbrella. The active `develop` ruleset has strict-base off; do not treat
  routine dev work as a branch-protection deployment.
- **CI split**: routine `develop` PRs run the required lightweight gate
  through `.github/workflows/pr.yml`. The shared path ruleset is
  `.github/path-filters.yml`: content-only PRs run content validation
  and skip Python fast tests; code, infra, workflow, tooling, and unknown
  paths run the post-Step-3 lint/type + Ubuntu 3.12 fast-test gate.
  Broad non-required validation (OS/Python compatibility, security,
  integration smoke/table-format, package install, parity, and PySpark)
  runs through `.github/workflows/nightly.yml` on schedule or
  `workflow_dispatch`, and remains available on `main`/release paths.
  `main` PRs and tag releases keep release-grade validation.
- **One-shot PR flow** (the canonical path — use this, not bare git):
  - From a feature branch: `make pr-preflight && make pr-open`.
    `make pr-preflight` uses the same `path-filters.yml` classifier as CI:
    content-only branches run the cheap content guard and skip only the
    local Python fast-test lane, while code/infra/unknown branches run
    the full local lint + fast-test gate. `make pr-open` opens the PR vs
    `develop` and enables `gh pr merge --auto --squash` so it lands the
    moment CI is green. Walk away — don't poll.
  - `make pr-open` is **idempotent** — safe to rerun. If a PR already
    exists for the current branch it reuses that open PR; auto-merge is
    (re)enabled either way. Use this to flip auto-merge on for a PR
    opened via the GitHub UI or `gh pr create` directly.
  - Before pushing, `pr-open` runs `git merge-tree` against every other
    open PR head and warns on textual conflicts (~1s, no CI). Warn-only
    — does not block. Catches content conflicts and modify-vs-delete
    conflicts deterministically.
  - In Claude Code, the project-local `/pr` slash command
    (`.claude/commands/pr.md`) wraps this end-to-end (commit if needed,
    preflight, push, open PR, enable auto-merge). Prefer `/pr` over the
    user-global `/commit-push-pr` plugin in this repo — `/pr` targets
    `develop`, runs preflight, and enables auto-merge.
  - Expensive pre-push hooks are opt-in. Set `BENCHBOX_PREPUSH=1` for pushes
    where you want `.pre-commit-config.yaml` to run the timing fast lane and
    the path-aware fast-test lane. Otherwise, `make pr-preflight` is the
    explicit local gate.
  - **Backstop**: `.github/workflows/auto-merge-on-open.yml` enables
    squash auto-merge on any non-draft PR opened against develop, so PRs
    opened outside `make pr-open` still auto-land.
  - **Post-merge safety net**: `.github/workflows/develop-post-merge.yml`
    runs the lightweight lint + fast-test mirror on the actual `develop`
    tip after a PR lands. If `develop` goes red, the workflow opens a
    revert PR labeled `incident:develop-red`, or an issue labeled
    `incident:develop-red-revert-conflict` if the revert conflicts.
    Agents do not need to monitor CI proactively after auto-merge; the
    revert PR or conflict issue is the alert. The workflow also uploads
    a `metrics` JSON artifact; `make dev-loop-metrics` downloads recent
    artifacts and reports PR-to-merge P50/P95, post-merge red rate,
    conflict rate, and total runner minutes. The GitHub-side admin
    state this depends on (ruleset required-checks, default workflow
    permissions, incident labels) is documented in
    `docs/operations/repo-admin-settings.md`.
  - **If develop goes red**:
    - The post-merge workflow detects the failed `develop` tip within the
      normal GitHub Actions scheduling window and attempts `git revert` of
      the offending squash SHA.
    - If the revert applies, it opens an `auto-revert/<sha>` PR against
      `develop`, labels it `incident:develop-red`, links the failed run and
      originating PR, and requests review from the original PR author when
      GitHub permits it.
    - If the revert conflicts, it opens an issue labeled
      `incident:develop-red-revert-conflict` with the failing SHA, run URL,
      originating PR, and attempted branch name.
    - To repair, claim a fresh pool worktree with
      `make worktree-claim BRANCH=fix/<original-issue>`, fix the root cause,
      run the normal preflight, and resubmit with `make pr-open`.
- **Worktrees** for parallel branches (this is how agents work in
  this repo — see "Session start" above; not an optional optimisation):
  - `~/Developer/BenchBox/` stays on `develop`, always. **Agents must
    not run `git checkout`, `git switch`, `git branch -m`, or any
    other command that changes the current branch in the main clone
    without explicit user approval.** All feature work happens in a
    retained pool worktree (`make worktree-claim BRANCH=...`).
  - `make worktree-claim BRANCH=fix/foo` atomically claims a free
    `BenchBox.pool-NN`, resets it to current `origin/develop`, checks out
    `fix/foo`, runs `uv sync --group dev`, and prints `WORKTREE_PATH=...`.
    `cd` into that path, work, run `make pr-open`, then release it with
    `make worktree-release` after the PR merges.
  - `make worktree-pool-status` lists free, claimed, stale, and dirty
    slots. For stale recovery, inspect the slot first; use
    `make worktree-pool-reset POOL=NN` only as a manual escape hatch.
  - `make worktree-add BRANCH=fix/foo` remains for one release as a
    deprecated legacy creator for non-pool worktrees; prefer
    `worktree-claim`.
  - `make pr-fanout` walks every worktree (skipping the main clone) and
    runs `make pr-open` with bounded parallelism (`PR_FANOUT_JOBS ?= 4`).
    Use this when you've worked across several branches and want to ensure
    each has a PR with auto-merge on.
  - `make pr-refresh` remains a manual escape hatch when a branch genuinely
    needs `origin/develop` merged before `make pr-open`. If a merge conflicts,
    resolve it in that worktree and rerun `make pr-open`.
  - The operating model is retained worktree pool + auto-merge, with
    `.github/workflows/develop-post-merge.yml` as the develop-tip safety net.
    Step 2 owns the worktree pool commands.
  - **Drafts are intentional.** Open as draft when you don't want
    auto-merge yet (spike, RFC, parked work). Mark ready when you do —
    the auto-merge-on-open workflow respects this.
  - `make worktree-prune` removes legacy non-pool worktrees whose branches
    are gone upstream. Pool worktrees are retained and returned with
    `make worktree-release`.
  - **`.gitignore` ∩ tracked-files** is CI-blocked
    (`.github/workflows/gitignore-lint.yml`). New ignore rules that match
    tracked files on the PR head must untrack them in the same PR. Rules
    matching files tracked on the base branch require an explicit
    `# benchbox-ignore-lint: allow-next-line tracked` waiver immediately
    before the pattern; use it only for isolated untracking PRs because
    it can force open branches to refresh.
- **Releases** (2-command flow): on `develop`, `make release-cut
  VERSION=X.Y.Z` cuts the `vX.Y.Z` branch, bumps version, drafts the
  changelog (opens `$EDITOR`), curates dev-only paths, opens the PR vs
  `main`, and sweeps prior `v*` branches. After CI green, `make
  release-finalize VERSION=X.Y.Z` squash-merges the PR, tags `main`,
  and pushes the tag → `release.yml` publishes to PyPI. **`develop` is
  intentionally not modified post-release** — dev-only paths
  (`_project/`, `_blog/`, agent configs, etc.) live only on develop by
  design. Full runbook: `docs/operations/release-guide.md`.

## Review workflow — blind-spot capture

Behavior is governed by the synced `SHARED/review-protocol` skill. When that
protocol authorizes a blind-spot capture, BenchBox bindings are:

- Path: `_project/blind-spots/YYYY-MM-DD-HHMMSS-<slug>.md`
- Schema: see `_project/blind-spots/README.md` (storage spec)
- Validate: `uv run --project _project/scripts -- python _project/scripts/validate_blind_spot.py _project/blind-spots/<file>.md`
- Sweep: `make blind-spots-{list,report,sweep}` — promotion to TODO is a sweep-step decision
- Chat marker: prefix the body quote with `Recorded: _project/blind-spots/<file>.md`

Per SHARED §4, the capture is local-only: do not commit any file,
including the capture file, do not push, do not run `make pr-open`. The user
authorizes any PR in a separate turn. Apply the SHARED §2 defect gate
before recording — defects belong in the severity table and TODOs, not
in the blind-spots directory.

The `/blind-spot` slash command (`.claude/commands/blind-spot.md`) is the
explicit-recording entrypoint and follows the same protocol.

## Commands

| Task | Command |
|------|---------|
| pytest | `uv run -- python -m pytest {test}` |
| smoke | `uv run -- python -m pytest -m fast -q` |
| format | `uv run ruff format .` |
| lint | `uv run ruff check .` |
| lint+fix | `uv run ruff check --fix .` |
| typecheck | `uv run ty check` |
| sweep validator-clean rate (sweep-shape UATs) | `uv run -- python scripts/uat_validator_rollup.py <results-dir> --output -` (see `docs/operations/uat-methodology.md`) |

### CLI
```bash
benchbox run --platform duckdb --benchmark tpch --scale 0.01        # basic
benchbox run --platform duckdb --benchmark tpch --queries Q1,Q6,Q17 # subset
benchbox run --dry-run ./preview --platform snowflake --benchmark tpcds
benchbox run --platform duckdb --benchmark tpch --force datagen
benchbox run --platform duckdb --benchmark tpch --compression zstd:9
benchbox run --platform duckdb --benchmark tpch --validation full
benchbox run --platform polars-df --benchmark tpch --scale 0.1      # dataframe
benchbox run --platform duckdb --benchmark tpch --platform-option driver_version=1.2.0
benchbox run --platform duckdb --benchmark nyctaxi --benchmark-option taxi_types=yellow,green
benchbox run --help | --help-topic all | --help-topic examples | --help-topic benchmarks
```

| Option | Values |
|--------|--------|
| `--platform` | duckdb, sqlite, snowflake, databricks, clickhouse-cloud, motherduck, polars-df, pandas-df, etc. |
| `--benchmark` | tpch, tpcds, ssb, clickbench, nyctaxi, tsbs-devops, h2odb, datavault, etc. |
| `--scale` | Scale factor [default: 0.01] |
| `--phases` | generate,load,warmup,power,throughput,maintenance |
| `--queries` | Subset e.g. Q1,Q6,Q17 - max 100; alphanumeric+dash/underscore, ≤64 chars; power/standard only; breaks TPC-H compliance. Ranges: TPC-H 1-22, TPC-DS 1-99, SSB 1-13 |
| `--table-mode` | native (default), external |
| `--tuning` | tuned, notuning, auto, YAML path |
| `--dry-run` | Preview without execution |
| `--force` | all, datagen, upload |
| `--compression` | zstd, zstd:9, gzip:6, none |
| `--validation` | exact, loose, range, disabled, full |
| `--platform-option K=V` | Repeatable. Keys: driver_version (pin driver pkg), driver_auto_install (true/false, auto-install via uv), engine_version (Athena Spark engine) |
| `--benchmark-option K=V` | Repeatable. Benchmark-specific params (e.g. taxi_types=yellow,green for nyctaxi, skew_preset=heavy for tpch_skew). Run `--help-topic benchmarks` for full list. |

## Pre-approved Commands
- **Dev/Test**: `make test-*`, `make coverage*`, `make lint`, `make format`, `make typecheck`, `uv run -- python -m pytest *`
- **PR/Worktree (read-only)**: `make pr-preflight`, `make pr-preflight-fast-tests`, `make pr-content-guard *`, `make pr-status`, `make dev-loop-metrics`, `make worktree-pool-status`, `make worktree-pool-check`, `make worktree-list`, `git worktree list*`, `gh pr list*`, `gh pr view*`, `gh pr checks*`
- **PR/Worktree (write — feature/pool worktrees only)**: `make pr-open`, `make pr-fanout`, `make pr-refresh`, `make worktree-claim BRANCH=*`, `make worktree-release`, `make worktree-pool-sweep-stale`, `git push -u origin chore/*`, `git push -u origin fix/*`, `git push -u origin feat/*`, `git push -u origin docs/*`, `git push origin chore/*`, `git push origin fix/*`, `git push origin feat/*`, `git push origin docs/*`, `gh pr create --fill*`, `gh pr merge --auto --squash*`
  - **Manual/admin escape hatches, not broad auto-allow**: `make worktree-pool-init`, `make worktree-pool-reset POOL=NN`, `make worktree-prune`
  - **Never auto-allowed**: `git push * develop`, `git push * main`, `git push --force*`, `gh pr create --base main*`. These remain prompt-on-use.
- **Files**: `ls*`, `find*`, `cat*`, `head*`, `tail*`, `wc*`, `file*`, `stat*`, `du*`, `tree*`, `which*`
- **Git**: `git status`, `git diff*`, `git log*`, `git show*`, `git branch*`, `git remote*`, `git config --list`, `git worktree list*`
- **Python**: `uv tree`, `uv pip list`, `uv pip show*`, `uv export`, `uv run -- python -c*`, `uv run -- python -m*`
- **TPC**: `timeout 30s _binaries/tpc-{h,ds}/<platform>/dsdgen*`, `timeout 60s _binaries/tpc-{h,ds}/<platform>/dsqgen*`
- **TODO**: `uv run --project _project/scripts -- python _project/scripts/todo_cli.py list*|show*|stats|ready|next*|done*|check-graph`, `uv run --project _project/scripts -- python _project/scripts/validate_todo.py*`, `uv run _project/scripts/generate_indexes.py`, `uv run _project/scripts/migrate_todo_format.py*`
- **Blind-spots**: `make blind-spots-list`, `make blind-spots-report`, `make blind-spots-sweep`, `uv run --project _project/scripts -- python _project/scripts/sweep_blind_spots.py *`, `uv run --project _project/scripts -- python _project/scripts/validate_blind_spot.py *`
- **UAT framework** (operator targets; see `docs/operations/uat-framework.md`): `make uat-cell PLATFORM=* BENCHMARK=* SCALE=*`, `make uat-stress`, `make uat-stress PLATFORM=* BENCHMARK=* SCALE=*`, `make uat-sweep CONFIG=*`, `make uat-execute CONFIG=*`, `make uat-validate RESULTS_DIR=* OUTPUT_TSV=*`, `make uat-package CONFIG=* SUBMISSIONS_DIR=* RESULTS=*`, `make uat-explorer-smoke BUNDLES_DIR=* OUTPUT_DIR=* LOG_DIR=*`, `make uat-report CELLS_JSONL=* OUTPUT_TSV=*`
- **System**: `ps*`, `uname*`, `whoami`, `pwd`, `env | grep*`
