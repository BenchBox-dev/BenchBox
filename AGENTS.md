# BenchBox Agent Guide

Consistent tooling, safe defaults, minimal surprises. Research first, make
scoped changes, verify before return.

## Workflow

Use `rg`; read files in focused chunks. Prefer existing local helpers and
patterns. For write work, research the affected path, change the narrowest
surface that solves the problem, verify, then commit only authorized files.

## Worktree Isolation

BenchBox uses retained pool worktrees for routine write work. This is a
BenchBox-local rule, not a global agent preference.

Before any write action, first classify the task:

- Read-only review, research, audit, or explanation: the primary clone is OK.
- Any task that may edit files, switch branches, rebase, commit, push, or open
  a PR: do not work in the primary clone. From `/Users/joe/Developer/BenchBox`,
  claim a pool slot first:

```bash
make worktree-claim BRANCH=fix/descriptive-slug
cd <WORKTREE_PATH>
make agent-write-preflight
```

If `git rev-parse --show-toplevel` is `/Users/joe/Developer/BenchBox`, stop
before editing and claim a worktree. Do not run `git switch`, `git checkout`,
`git rebase`, `apply_patch`, commit, or `make pr-open` in the primary clone.

Emergency release or hotfix work in the primary clone requires explicit user
authorization in the prompt plus `BENCHBOX_ALLOW_MAIN_CLONE_WRITE=1` on the
guarded command. State the exception in the final response.

## Tooling

`make` wrappers are preferred when present. Direct Python tools still run
through `uv run -- ...`. Do not use destructive git/filesystem commands or live
cloud tests without explicit approval.

## Output Discipline

Broad commands are final gates. Long output is an artifact, not chat, and
temporary evidence is not source.

- Path lists before content; targeted hunks before whole files.
- Commands likely to emit >100 lines (preflight, full suites, Docker pulls,
  large diffs, `gh pr view --json body,files`): redirect to `/tmp/<slug>.log`;
  report command, status, counts, failure tail. UAT logs use the run root below.
- Do not commit raw stdout logs, browser reports, screenshots, or generated
  binary evidence. Summarize the durable facts in markdown/TODOs and keep raw
  captures in `/tmp`, CI artifacts, or `BENCHBOX_OUTPUT_DIR`.
- Visual QA may cite route, viewport, checked SHA, and screenshot filenames, but
  full screenshot batches stay out of git unless they are product docs/blog
  assets with a durable reader-facing purpose.
- Any intentionally committed binary or raw evidence file must state its
  durable consumer, size, and why a compact text summary is insufficient.
- Verification ladder: read TODO `verification:`; run the narrowest listed or
  targeted check that proves the change; fast suite once pre-commit;
  `make pr-preflight` once pre-`pr-open`.
- Delegate boilerplate gates to a low-effort subagent when available: full/fast
  suites, `make pr-preflight`, `make pr-open`, PR-followup runners, and bounded
  CI checks. The main agent chooses the command and interprets failures; the
  subagent only runs it, captures status/log tail/PR URL, and reports back.
- PR triage uses compact `gh pr list --json <fields>` first (for example,
  `number,title,headRefName,baseRefName,state,mergeStateStatus`); inspect
  failed-job JSON before logs. Do not poll — pending is a valid terminal state.
- Force-push: `--force-with-lease`, feature/pool branches only.

## Long-Running UAT

See `docs/operations/uat-framework.md`. For UAT, stress, Docker matrices, or
runs >10min: announce command, max runtime, log path, and stop condition
before launch. Use `BENCHBOX_OUTPUT_DIR=~/Developer/benchmark_runs`; UAT logs
under that root, never under a worktree or `/tmp`. Sequential platforms; one
Docker stack at a time (`up → run → down` via project targets; no global prune
without approval). Below disk safety threshold, stop new workload.

## Code Style

Python 3.10+, 4 spaces, 120 columns, Ruff only, type hints on public APIs.
Standardize where it reduces real duplication; avoid generic frameworks for
one-off cases.

## Package Management

Python tooling is `uv` only: use `uv run -- ...`, `uv add`, `uv sync`, and
`uv lock`. Do not use bare `python`, `pytest`, `ruff`, `pip`, conda, poetry,
manual venvs, or `requirements.txt`.

Common commands:

```bash
uv run -- python -m pytest -m fast -q
uv run -- ruff check .
uv run -- ruff format .
uv run -- ty check
```

## Tests

- Smoke: `uv run -- python -m pytest -m fast -q`
- Standards: `uv run -- python -m pytest -m "tpch or tpcds" --tb=short`
- Coverage: `make coverage-fast` or `make coverage-all`
- Docker: `make test-docker-<platform>`
- Cloud: `make test-live-<platform>` only with approval

`tests/conftest.py` excludes slow/stress/live/resource-heavy unless requested.
`pytest -n auto` uses `~/.benchbox/test.lock`; concurrent runs fail fast.

## Sandbox & Security

No credentials in repo. Use env vars or gitignored `.env`; redact secrets in
logs. Stop on user interrupt or redirect. Do not revert user changes unless
explicitly asked.

## CLI Modes

CLI supports non-interactive mode with `--non-interactive` or
`BENCHBOX_NON_INTERACTIVE=true`. Dry-run:

```bash
benchbox run --dry-run <DIR> --platform <plat> --benchmark <bm> --scale <sf> [--phases ...]
```

Phases: `generate`, `load`, `power`, `throughput`, `maintenance`. Defaults are
generate+load+execute; always propagate `--phases`. Use `--seed <int>` for
deterministic runs. Scale >=1 must be whole integer; default smoke is 0.01.

## DataFrame Support

Production DataFrame platforms include `polars-df`, `pandas-df`,
`datafusion-df`, and `dask-df`; others may need Spark/Ray/CUDA/cloud
credentials. Most SQL benchmarks have matching `dataframe_queries/`
implementations. Expression-family platforms use lazy context; pandas-family
uses eager frames. Validate against DuckDB SQL at SF=0.01.

Examples:

```bash
benchbox run --platform polars-df --benchmark tpch --scale 0.01 --queries Q1,Q6
benchbox run --platform pandas-df --benchmark tpch --scale 0.01 --non-interactive
```

## Data/Reporting/Logging/Timing

Outputs go under `benchmark_runs/`; manifests enable reuse. Compression
defaults to zstd and may fall back to none. Quick restart state is
`~/.benchbox/last_run.yaml`. Canonical result key is
`execution_time_seconds`; `execution_time_ms` is compatibility-only.

## Commits & PRs

Do not use `git add -A`; stage explicit paths only. Repo `origin` is
`joeharris76/BenchBox`. Long-lived branches: `develop` for dev, `main` for
release. Dev PRs target `develop`, squash-merge, linear history. `develop` is
PR-gated; do not direct-push routine work.

Run the local write guard before the first edit and before PR creation:

```bash
make agent-write-preflight
```

Push-to-PR gate (the implement-to-PR ritual is in "Default write-task
close-out" below):

```bash
make pr-preflight
make pr-open
```

`pr-open` is idempotent: pushes, opens/reuses a PR to `develop`, and enables
squash auto-merge when CI passes. Do not poll; post-merge safety opens a
revert PR or incident issue if `develop` goes red.
Run `make pr-preflight` and `make pr-open` through a low-effort subagent when
the agent environment supports it.

Use retained pool worktrees for parallel work:

```bash
make worktree-claim BRANCH=fix/foo
cd <WORKTREE_PATH>
make pr-preflight && make pr-open
make worktree-release
```

For the example above, prefer delegating the `make pr-preflight && make pr-open`
step to a low-effort subagent with a log path and clear stop condition.

Inspect with `make worktree-pool-status`; sweep with
`make worktree-pool-sweep-stale`. Use `make worktree-pool-reset POOL=NN` only
when intentionally discarding a slot. Claude Code should prefer project `/pr`
over global `/commit-push-pr`.

Release flow is `make release-cut VERSION=X.Y.Z` then
`make release-finalize VERSION=X.Y.Z`; see `docs/operations/release-guide.md`.

## Default write-task close-out

After implementing, self-review with the `code` skill's `review` action and
fix every finding — issues, considerations, AND nits — before `make pr-open`.
The review-fix loop is part of "implement", not optional polish; skip only
when the user explicitly opts out (typo fix, already-reviewed change).

## Planning & TODOs

TODOs live in `_project/TODO/{worktree}/{phase}/{item}.yaml`; completed items
move to `_project/DONE/`. Stable `id` is filename slug. Use flat `work[]` with
`needs` edges; inter-item deps go in `deps.needs`; deferred work goes in
`deferred[]`.

CLI:

```bash
uv run --project _project/scripts -- python _project/scripts/todo_cli.py list|show|stats|ready|next|done|check-graph|validate|reindex|cleanup
```

Indexes under `_project/{TODO|DONE}/_indexes/` are generated. Guardrails:
`must_preserve`, `approach`, `anti_patterns`, `verification`, `scope_limit`.

## Reuse anchors

Search these before designing new BenchBox infrastructure:

| Concept | File |
|---|---|
| Per-benchmark data path | `benchbox/utils/path_utils.py:resolve_benchmark_runs_dir`, `benchbox/cli/config.py:get_datagen_path` |
| External data download + cache | `benchbox/core/nyctaxi/downloader.py` |
| Verbosity / quiet | `benchbox/utils/verbosity.py` |
| Compression | `benchbox/utils/compression_mixin.py` |
| Result bundle publishing | `benchbox/core/publishing/` |

Add anchors as patterns are extracted.

## Skills & Workflow

High-level wrappers remain stable: `code`, `test`, `todo`, `blog`, `docs`,
`benchbox-workflow`, `skill-sync`, `tidy-perms`. Preserve action names and
triggers. Review-shaped actions are read-only except local capture;
write-shaped actions require research, verification, explicit-path commit, and
push when authorized.

BenchBox workflow actions: `test`, `quality`, `compliance`, `dialect`,
`binary`, `compare`, `live`, `architecture`, `plan`.

Skill source of truth is `/Users/joe/.skill-sync/skills`. Project-local
`.claude/skills`, `.codex/skills`, and `.gemini/skills` are generated mirrors;
regenerate them with `make skill-sync` instead of editing them directly.
`/Users/joe/.claude/skills` may be a symlink to canonical, so writes through it
can mutate the canonical repo.

## Recipes

```bash
make skill-sync-check
uv run -- python _project/scripts/timing_audit.py --report
uv run -- python _project/scripts/timing_policy_check.py --strict
uv run -- python _project/scripts/reference_usage_audit.py --summary
```

## Structure

- `benchbox/`: runtime, adapters, SQL compatibility, and CLI code.
- `tests/`: fast/unit/integration and benchmark-specific suites.
- `docs/`: user, operations, and development documentation.
- `_project/`: TODOs, blind spots, audits, and project scripts.
- `benchmark_runs/`: generated run artifacts, normally not hand-edited.

## Timing Policy

Measured durations must use `benchbox.utils.clock.mono_time()` /
`elapsed_seconds()`. Wall-clock is allowed only for event/audit timestamps and
OS metadata.

Audits:

```bash
uv run -- python _project/scripts/timing_audit.py --report
uv run -- python _project/scripts/timing_policy_check.py --strict
```

## Result Validation

Validation modes: `exact`, `loose`, `range`, `full`, `disabled`. Use CLI
`--validation <mode>` or stage toggles (`--preflight`, `--postgen-manifest`,
`--postload`). Cross-platform validation compares row-by-row and reports diff
samples.

## Adapter Authoring

Add SQL platforms by subclassing `PlatformAdapter`, implementing
connection/execution/load hooks, registering with `@register_platform`, and
keeping SDK imports lazy. Check `docs/development/adapter-refactor-map.md`
before adding base responsibilities.

Every adapter CREATE TABLE rewrite must be registered in
`benchbox/sql_compat/rules/ddl_optimize/<platform>_ddl_rewrites.py` under
`Phase.DDL_OPTIMIZE`; adapters either inherit `BaseDdlOptimizer` for runtime
dispatch or mark the rule `governance_only=True` for a local rewrite path.
`make compat-docs-check` runs the generated docs drift gate and
`uv run -- python -m benchbox.sql_compat.inventory --check-ddl-drift`.

## Dependency Upper Bounds

Default is unbounded. Current high-risk caps: `sqlglot<31`, `click<9`,
`pydantic<3`, `pyarrow<24`, `duckdb<2`. Add caps only for known breaking
release history or deep internal coupling. Bump only after validating the new
major on fast + standards suites, then update `pyproject.toml` rationale and
`uv.lock`.

## Test Markers

Markers: `fast`, `unit`, `integration`, `tpch`, `tpcds`, `ssb`,
`platform_smoke`, `docker_integration`, `live_integration`, `slow`,
`resource_heavy`, `stress`.

## Further Reading

- Run lifecycle: `docs/development/run-lifecycle-map.md`
- Result validation: `docs/development/result-integrity-validation.md`
- SQL platforms: `docs/development/adding-new-platforms.md`
- DataFrame platforms: `docs/development/adding-dataframe-platform.md`
- Adapter refactor: `docs/development/adapter-refactor-map.md`
- SQL compatibility: `benchbox/sql_compat/README.md`
- Dependency compatibility: `docs/development/dependency-compatibility.md`
- Test taxonomy and lock: `tests/README.md`
