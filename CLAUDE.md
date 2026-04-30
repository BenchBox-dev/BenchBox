# CLAUDE.md - Quick Reference

→ **See AGENTS.md for full guidance.** Claude Code-specific shortcuts only.

**Critical rules**: Always `uv run` (never bare `python`/`pytest`/`ruff`). Never `git add -A`. TPC-DS SF<1 requires the patched dsdgen bundled with BenchBox (stock dsdgen crashes at SF<1; see `patch-and-redistribute-tpcds-dsdgen-subscale-support`). No `-o "addopts="` with pytest.

## Git workflow

Single repo, single remote (`origin` → `joeharris76/BenchBox`). Working
clone: `/Users/joe/Developer/BenchBox` (the canonical path; the old
private clone was retired to `BenchBox.retired-20260427/` alongside it
during the single-repo migration).

- **Branches**: `develop` is the long-lived dev branch; `main` is
  release-only.
- **Dev PRs**: feature branch off `develop` → PR → squash-merge to
  `develop`. Required CI: `lint` + `test (ubuntu-latest, 3.12)`.
- **One-shot PR flow** (the canonical path — use this, not bare git):
  - From a feature branch: `make pr-preflight && make pr-open`. Opens
    the PR vs `develop` with `gh pr create --fill` and enables
    `gh pr merge --auto --squash` so it lands the moment CI is green.
    Walk away — don't poll.
  - In Claude Code, the project-local `/pr` slash command
    (`.claude/commands/pr.md`) wraps this end-to-end (commit if needed,
    preflight, push, open PR, enable auto-merge). Prefer `/pr` over the
    user-global `/commit-push-pr` plugin in this repo — `/pr` targets
    `develop`, runs preflight, and enables auto-merge.
  - Pre-push hook (`pr-preflight-fast-tests` in `.pre-commit-config.yaml`)
    runs the fast lane on every push. Activate once with `pre-commit install`.
- **Worktrees** for parallel branches (the convention):
  - `~/Developer/BenchBox/` stays on `develop`, always. Don't swap
    branches in the main clone.
  - `make worktree-add BRANCH=fix/foo` creates `../BenchBox.fix-foo/`
    off `origin/develop` with branch `fix/foo` checked out. `cd` into it,
    run `uv sync --group dev`, work, `make pr-open` from inside.
  - `make worktree-prune` removes worktrees whose branches are gone
    upstream (post-merge cleanup). Pairs with auto-merge: PR merges →
    branch deleted on origin → next prune sweeps the worktree.
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
- **PR/Worktree**: `make pr-preflight`, `make pr-status`, `make worktree-list`, `make worktree-prune`, `git worktree list*`, `gh pr list*`, `gh pr view*`, `gh pr checks*`
- **Files**: `ls*`, `find*`, `cat*`, `head*`, `tail*`, `wc*`, `file*`, `stat*`, `du*`, `tree*`, `which*`
- **Git**: `git status`, `git diff*`, `git log*`, `git show*`, `git branch*`, `git remote*`, `git config --list`, `git worktree list*`
- **Python**: `uv tree`, `uv pip list`, `uv pip show*`, `uv export`, `uv run -- python -c*`, `uv run -- python -m*`
- **TPC**: `timeout 30s _binaries/tpc-{h,ds}/<platform>/dsdgen*`, `timeout 60s _binaries/tpc-{h,ds}/<platform>/dsqgen*`
- **TODO**: `uv run --project _project/scripts -- python _project/scripts/todo_cli.py list*|show*|stats|ready|next*|done*|check-graph`, `uv run --project _project/scripts -- python _project/scripts/validate_todo.py*`, `uv run _project/scripts/generate_indexes.py`, `uv run _project/scripts/migrate_todo_format.py*`
- **Blind-spots**: `make blind-spots-list`, `make blind-spots-report`, `make blind-spots-sweep`, `uv run --project _project/scripts -- python _project/scripts/sweep_blind_spots.py *`, `uv run --project _project/scripts -- python _project/scripts/validate_blind_spot.py *`
- **System**: `ps*`, `uname*`, `whoami`, `pwd`, `env | grep*`
