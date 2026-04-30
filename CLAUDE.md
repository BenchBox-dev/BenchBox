# CLAUDE.md - Quick Reference

→ **See AGENTS.md for full guidance.** Claude Code-specific shortcuts only.

**Critical rules**: Always `uv run` (never bare `python`/`pytest`/`ruff`/`ty`). Never `git add -A`. Dev PRs target `develop`, never `main` (`main` is release-only and `develop` is PR-gated — no direct push to either). **All agent edits and commits happen in a worktree off `develop`. If a session begins in the main clone (`/Users/joe/Developer/BenchBox`), creating a worktree is the FIRST action (see "Session start" below). Never `git checkout`/`switch`/`branch -m` in the main clone without explicit user approval — that clone stays on `develop`.** TPC-DS SF<1 requires the patched dsdgen bundled with BenchBox (stock dsdgen crashes at SF<1; see `patch-and-redistribute-tpcds-dsdgen-subscale-support`). No `-o "addopts="` with pytest.

## Session start

**First action of any new session that might write to the repo**: confirm
you are in a worktree, not the main clone.

```bash
git rev-parse --show-toplevel
# If the output is /Users/joe/Developer/BenchBox you are in the main
# clone. Stop. Create a worktree BEFORE any edit, commit, or branch
# switch:
make worktree-add BRANCH=<type>/<short-slug>   # type: chore|fix|feat|docs
cd ../BenchBox.<type>-<short-slug>/
uv sync --group dev
```

Pick the branch name from the user's stated task (e.g.
`fix/explorer-cold-load`, `chore/claude-md-rules`,
`feat/query-row-limit`). If the task is unclear, ask the user before
creating the worktree.

**Read-only carveout.** Pure Q&A / exploration sessions — no edits,
no commits, no state-mutating commands — may stay in the main clone.
The instant the session turns into a write task, create a worktree
before the first edit.

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
  `develop`. Required CI: `lint` + `test (ubuntu-latest, 3.12)`.
- **One-shot PR flow** (the canonical path — use this, not bare git):
  - From a feature branch: `make pr-preflight && make pr-open`. Opens
    the PR vs `develop` and enables `gh pr merge --auto --squash` so it
    lands the moment CI is green. Walk away — don't poll.
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
  - Pre-push hook (`pr-preflight-fast-tests` in `.pre-commit-config.yaml`)
    runs the fast lane on every push. Activate once with `pre-commit install`.
  - **Backstop**: `.github/workflows/auto-merge-on-open.yml` enables
    squash auto-merge on any non-draft PR opened against develop, so PRs
    opened outside `make pr-open` still auto-land.
  - **Post-merge safety net**: `.github/workflows/develop-post-merge.yml`
    runs the lightweight lint + fast-test mirror on the actual `develop`
    tip after a PR lands.
- **Worktrees** for parallel branches (this is how agents work in
  this repo — see "Session start" above; not an optional optimisation):
  - `~/Developer/BenchBox/` stays on `develop`, always. **Agents must
    not run `git checkout`, `git switch`, `git branch -m`, or any
    other command that changes the current branch in the main clone
    without explicit user approval.** All feature work happens in a
    worktree (`make worktree-add BRANCH=...`).
  - `make worktree-add BRANCH=fix/foo` creates `../BenchBox.fix-foo/`
    off `origin/develop` with branch `fix/foo` checked out. `cd` into it,
    run `uv sync --group dev`, work, `make pr-open` from inside.
  - `make pr-fanout` walks every worktree (skipping the main clone) and
    runs `make pr-open` sequentially. Use this when you've worked across
    several branches and want to ensure each has a PR with auto-merge on.
    Sequential by design — the pre-push fast-test hook serializes via a
    flock, so parallelizing invites lock-contention failures.
  - `make pr-refresh` is the stale-PR escape hatch when GitHub shows PRs
    as CLEAN but they are behind `develop` and strict required checks need
    current-base CI. Run it from the stale PR worktree: it merges
    `origin/develop` into the current branch, pushes, and re-enables
    auto-merge. Drain stale PRs one at a time, oldest first — refresh one,
    wait for it to land, then refresh the next — otherwise the first merge
    can stale the rest again. If a merge conflicts, resolve it in that
    worktree and rerun `make pr-open`.
  - **One PR per file area at a time.** Don't open three PRs touching the
    same file in 25 minutes; sequence them so the second sees the first
    landed. The cost of a 10-minute wait beats a multi-PR semantic
    conflict resolution. The pairwise warning above will flag obvious
    overlap; convention covers the rest.
  - **Drafts are intentional.** Open as draft when you don't want
    auto-merge yet (spike, RFC, parked work). Mark ready when you do —
    the auto-merge-on-open workflow respects this.
  - `make worktree-prune` removes worktrees whose branches are gone
    upstream (post-merge cleanup). Pairs with auto-merge: PR merges →
    branch deleted on origin → next prune sweeps the worktree. Run
    this at end-of-session.
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

## Review workflow — blind-spot capture (mandatory)

When you produce a **Blind-Spot Audit (L2)** during any review (ultrareview,
`/review`, ad-hoc code review, research, planning), you MUST:

1. **Write the finding to disk first** at
   `_project/blind-spots/YYYY-MM-DD-HHMMSS-<slug>.md`, using the frontmatter
   schema and body shape in `_project/blind-spots/README.md`.
2. **Then** quote the finding in your chat reply, prefixed with one line:
   `Recorded: _project/blind-spots/<file>.md`.

Do not skip the file write because the finding "feels minor" — sweep-time
triage is where dismissals belong, not write-time. Findings printed only in
chat get lost; file-first capture is what makes the L2 audit habit pay off.
If a review response contains an L2 audit without a `Recorded:` pointer for
each finding, treat the response as protocol drift and record the missing
finding before continuing.

Sweep / triage findings with `make blind-spots-{list,report,sweep}`. Promotion
to a TODO is a sweep-step decision, not a write-step decision. See
`_project/blind-spots/README.md` for the full protocol.

The `/blind-spot` slash command (`.claude/commands/blind-spot.md`) wraps the
file-first capture flow when you want to record one explicitly outside a review.

## Commands

| Task | Command |
|------|---------|
| pytest | `uv run -- python -m pytest {test}` |
| smoke | `uv run -- python -m pytest -m fast -q` |
| format | `uv run ruff format .` |
| lint | `uv run ruff check .` |
| lint+fix | `uv run ruff check --fix .` |
| typecheck | `uv run ty check` |

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
- **PR/Worktree (read-only)**: `make pr-preflight`, `make pr-status`, `make worktree-list`, `make worktree-prune`, `git worktree list*`, `gh pr list*`, `gh pr view*`, `gh pr checks*`
- **PR/Worktree (write — feature branches only)**: `make pr-open`, `make pr-fanout`, `make pr-refresh`, `git push -u origin chore/*`, `git push -u origin fix/*`, `git push -u origin feat/*`, `git push -u origin docs/*`, `git push origin chore/*`, `git push origin fix/*`, `git push origin feat/*`, `git push origin docs/*`, `gh pr create --fill*`, `gh pr merge --auto --squash*`
  - **Never auto-allowed**: `git push * develop`, `git push * main`, `git push --force*`, `gh pr create --base main*`. These remain prompt-on-use.
- **Files**: `ls*`, `find*`, `cat*`, `head*`, `tail*`, `wc*`, `file*`, `stat*`, `du*`, `tree*`, `which*`
- **Git**: `git status`, `git diff*`, `git log*`, `git show*`, `git branch*`, `git remote*`, `git config --list`, `git worktree list*`
- **Python**: `uv tree`, `uv pip list`, `uv pip show*`, `uv export`, `uv run -- python -c*`, `uv run -- python -m*`
- **TPC**: `timeout 30s _binaries/tpc-{h,ds}/<platform>/dsdgen*`, `timeout 60s _binaries/tpc-{h,ds}/<platform>/dsqgen*`
- **TODO**: `uv run --project _project/scripts -- python _project/scripts/todo_cli.py list*|show*|stats|ready|next*|done*|check-graph`, `uv run --project _project/scripts -- python _project/scripts/validate_todo.py*`, `uv run _project/scripts/generate_indexes.py`, `uv run _project/scripts/migrate_todo_format.py*`
- **Blind-spots**: `make blind-spots-list`, `make blind-spots-report`, `make blind-spots-sweep`, `uv run --project _project/scripts -- python _project/scripts/sweep_blind_spots.py *`, `uv run --project _project/scripts -- python _project/scripts/validate_blind_spot.py *`
- **System**: `ps*`, `uname*`, `whoami`, `pwd`, `env | grep*`
