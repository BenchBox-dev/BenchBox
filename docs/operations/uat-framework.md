# UAT Framework — Operator Guide

The UAT framework lives at `tests/uat/`. It composes six configured
phases — preflight, execute, validate, package, explorer-smoke, report —
driven by YAML configs under `tests/uat/configs/`. Configs declare what
to run; the framework runs it. Cell enumeration is internal to the
execute phase, not a public phase.

This is **operator** documentation — what to type, what to read.
The design contract is `_project/specs/uat-framework.md`. The
developer guide for hacking on the framework itself is
`tests/uat/README.md`.

## Quick reference

| Goal | Command |
|---|---|
| Smoke a single cell | `make uat-cell PLATFORM=duckdb BENCHMARK=tpch SCALE=0.01` |
| Stress preset (one scale, no validate/package/explorer) | `make uat-stress` |
| Stress, single platform / benchmark | `make uat-stress PLATFORM=duckdb BENCHMARK=tpch` |
| Full sweep from a config | `make uat-sweep CONFIG=tests/uat/configs/uat-2026-05-02.yaml` |
| Validate a directory of bundles | `make uat-validate RESULTS_DIR=<dir> OUTPUT_TSV=<path>` |
| Package staged bundles via terminal-state YAML | `make uat-package CONFIG=<path> SUBMISSIONS_DIR=<path> RESULTS="r1.json r2.json"` |
| Explorer build + Playwright smoke | `make uat-explorer-smoke BUNDLES_DIR=<path> OUTPUT_DIR=<path> LOG_DIR=<path>` |
| TSV roll-up from a cells JSONL | `make uat-report CELLS_JSONL=<path> OUTPUT_TSV=<path>` |
| Single-phase execute (already-validated config) | `make uat-execute CONFIG=<path>` |
| Discover subcommands and options | `uv run -- python -m tests.uat._cli --help` |

## Output artefacts

By default every BenchBox runtime artefact lands under the shared
`~/Developer/benchmark_runs/` root:

```
~/Developer/benchmark_runs/
├── datagen/                       # generated source data; preserved across runs
├── databases/                     # loaded DBs; pruned at safe reuse boundaries
├── results/                       # per-cell result JSON files
├── logs/uat_<date>_<time>/         # per-cell logs + matrix_summary.tsv
└── submissions/<name>/            # local-stage / draft-pr bundles
```

The UAT runner passes this root to every `benchbox run` subprocess as
`BENCHBOX_OUTPUT_DIR`, so datagen, loaded databases, and result JSONs
stay outside the worktree even when the sweep is launched from a pool
worktree. Override the root with `output.benchmark_runs_dir_template`;
override only logs or staged submissions with `output.logs_dir_template`
and `output.submissions_dir_template`.

## Local-artifact hygiene (external-root invariant)

**Invariant:** when an external output root is configured — `BENCHBOX_OUTPUT_DIR`
set (or `--output` pointing outside the worktree) — the worktree-local
`benchmark_runs/` must **not** grow. Datagen, databases, and result JSONs all
belong under the external root. This guards the 2026-06-01 incident, where a
corpus sweep launched from a pool worktree with
`BENCHBOX_OUTPUT_DIR=~/Developer/benchmark_runs` still accumulated ~4.2 GB
under the worktree-local `benchmark_runs/datagen/`.

The guardrails are **report-only** — they detect and name the offending paths
but never delete or move artifacts.

* The UAT runner (`tests/uat/runner.py`) snapshots `cwd/benchmark_runs` before
  each external-root cell and fails loudly if it grows, naming both the
  unexpected local path and the configured external root.
* `make uat-artifact-hygiene` audits the live worktree (no-op unless an
  external root is configured) and is wired into `make pr-preflight`. Ordinary
  default local runs (no `BENCHBOX_OUTPUT_DIR`) are never blocked.

  ```bash
  # Audit the current worktree (skips silently with no external root):
  make uat-artifact-hygiene
  # Or target an explicit root / raise the byte budget:
  make uat-artifact-hygiene OUTPUT=~/Developer/benchmark_runs THRESHOLD_BYTES=0
  ```

### Compact audit commands

If a sweep is configured for an external root, confirm nothing leaked into the
worktree-local tree:

```bash
# Total size of the local tree (should be ~empty under an external root):
du -sh benchmark_runs 2>/dev/null || echo "no local benchmark_runs"
du -sh benchmark_runs/datagen 2>/dev/null

# Files written under the local tree in the last day (recent leak detector):
find benchmark_runs -type f -mtime -1 2>/dev/null

# Largest local artifacts, top 20 (find the heavy offenders):
find benchmark_runs -type f -printf '%s\t%p\n' 2>/dev/null | sort -rn | head -20
```

## Docker storage cleanup

Loaded databases under `benchmark_runs/databases/` are pruned at safe
reuse boundaries, but Docker containers, networks, and named volumes live
outside that tree. For storage-constrained Docker sweeps, use UAT-owned
Docker lifecycle management instead of manually pruning the Docker daemon:

```yaml
cleanup:
  preserve_datagen: true
  prune_databases: true
  docker_manage_platforms: true
  docker_platform_switch: "volumes"   # down -v --remove-orphans at platform switch
  docker_project_prefix: "benchbox-uat"
  docker_start_timeout_s: 300
  docker_fixed_container_name_policy: "fail"
```

`preserve_datagen: false` is deliberately rejected by the config
validator; UAT may prune loaded databases at safe reuse boundaries, but
it does not delete generated source data.

With `docker_manage_platforms: true`, the execute phase starts a
project-scoped compose stack before each Docker-backed platform, runs all
cells for that platform, then tears down that same UAT-owned project in a
`finally` block before moving on. The generated commands are targeted:
`docker compose -p <benchbox-uat-...> -f <compose-file> down -v
--remove-orphans`. UAT never runs `docker system prune`, `docker volume
prune`, or unqualified `docker compose down` automatically.

The default remains externally managed Docker:

```yaml
cleanup:
  docker_manage_platforms: false
  docker_platform_switch: "off"
```

In that mode UAT only probes local TCP ports and skips unreachable
Docker-backed platforms when `execute.skip_unreachable: true`; it reports
Docker cleanup as disabled. Config validation rejects non-`off` Docker
cleanup when `docker_manage_platforms` is false so the storage-saving
setting cannot silently become a no-op.

Use `tests/uat/configs/stress-docker-managed.yaml` as the starting point
for storage-constrained smoke sweeps. It intentionally starts with the
`docker-fast` group for quick smoke coverage; switch to the broader
`docker` group when you want every Docker-backed platform, including the
PostgreSQL-family stacks that share localhost port 5432 but run
sequentially under UAT-managed lifecycle control.
Inspect a UAT-owned stack with:

```bash
docker compose -p <benchbox-uat-project> ps
```

If a UAT run is interrupted hard enough that the execute-phase `finally`
block cannot run, recover by inventorying Docker's compose-labelled
resources:

```bash
make uat-docker-cleanup
```

The default is a dry run. It lists UAT-owned resources whose compose
project label starts with `benchbox-uat`, shows when each item was
created, and prints the targeted cleanup commands it would run.
It also lists non-UAT containers, volumes, networks, and images that it
will not remove automatically, with a manual cleanup command for each
item. To remove only UAT-owned leftovers:

```bash
make uat-docker-cleanup APPLY=1
```

Use `PREFIX=<value>` only for a deliberately different UAT project
prefix. The recovery command still does not run `docker system prune`,
`docker volume prune`, or `docker image prune`; non-UAT cleanup remains
an explicit operator decision using the commands printed in the report.

### Container engine resolution

Every UAT Docker command (compose lifecycle, the preflight reachability
probe, `make uat-bring-up`, and `make uat-docker-cleanup` in its default
`ENGINE=docker` mode) shells out through one resolved binary, not a
hardcoded `docker`. Resolution order: `BENCHBOX_CONTAINER_CLI` env override
(honored verbatim) > platform default -- on macOS, `mocker` (the
Docker-CLI-compatible shim over Apple Containerization) if it is on `PATH`,
else `docker`; on every other platform, always `docker` (no mocker probing
happens off darwin, so a docker-only Linux host is unaffected). A missing
resolved binary is a hard error, not a silent fallback. The engine is
resolved once per process and cached.

The resolved binary and its `--version` output are recorded as an `[engine]`
line in `uat_lifecycle.log` at sweep start, and as `container_engine` in the
`cells.jsonl.accounting.json` sidecar (`null` when resolution itself failed
before any Docker-managed platform needed one).

On macOS with mocker resolved, managed teardown also sweeps named volumes
mocker 0.5.4's `compose down -v` leaks: a project-scoped `mocker volume ls` +
targeted `volume rm`, never a global prune, run only when the requested
cleanup mode asked for volume removal (`volumes` or `images`, matching
docker's own `-v` semantics -- a `containers`-mode teardown keeps volumes for
platform reuse and is left alone). A `volume-sweep` lifecycle event records
what, if anything, was removed.

`make uat-docker-cleanup`'s default `ENGINE=docker` mode routes its
inventory listing through the resolved engine too. When that engine is
mocker, the Docker-shaped `--format json` inventory it normally relies on is
unusable (`container`/`image ls --format json` echo the literal string
`json` instead of JSON; `volume inspect` takes one name at a time and returns
a lowercase, non-Docker schema) -- rather than crash, it falls back to
mocker's one faithful plain-text verb (`mocker volume ls`) to find and remove
leaked named volumes, and the report's `NOTE:` line says container/image/
network inventory was skipped. On macOS, prefer `ENGINE=container` for
reliable native inventory and cleanup of images/containers/networks (see
AGENTS.md "Apple container cleanup"); that mode speaks the native `container`
CLI directly and does not go through `resolve_container_cli()`. It cannot see
mocker-managed named volumes, though -- Apple's native `container volume ls`
is empty for them; mocker tracks its own compose-created volumes separately.
Use `ENGINE=docker` (the default) for volume cleanup and `ENGINE=container`
for everything else.

## Explorer smoke (browser)

`make uat-explorer-smoke` invokes Playwright directly against a freshly
built Explorer app, mirroring the `results-explorer-browser.yml` workflow
entrypoint. Each invocation runs three steps inside `results-explorer/`
in order:

1. `npm ci` — clean install of Explorer JS dependencies.
2. `npm run build` — full Explorer production build.
3. `npx playwright test --grep @uat-external-corpus --project <browser>` —
   the UAT smoke run, against the staged data dir.

The UAT smoke is intentionally separate from the Results Explorer developer
fixture route suite. Before launching Playwright, it validates that the
packaged corpus has at least one result bundle with `run`, `benchmark`,
`scale_factor`, and `platform` metadata, then writes the compact contract to
`explorer_corpus_contract.json` under the UAT log directory. The browser test
discovers benchmark, platform, result, and query evidence from the mounted
corpus, so a valid LakeSail-only or otherwise narrow UAT run is not coupled to
the deterministic DuckDB/TPC-H fixture IDs.

Steps 1 and 2 are not cached locally, so a single `make uat-explorer-smoke`
invocation pays the full npm cost every time. The CI workflow caches
`node_modules/` and the build output; a developer-loop sweep does not. If
you are iterating on a UAT change unrelated to the Explorer browser smoke,
prefer running the targeted test (`uv run -- python -m pytest
tests/uat/test_explorer_smoke.py -m fast`) and reserve
`make uat-explorer-smoke` for end-to-end validation.

The fixed developer fixture route regressions still run from
`results-explorer/` with `npm run test:e2e:fixtures && npm run build &&
npx playwright test --grep @smoke --project chromium`.

## Artifact provenance and abort evidence

Every non-dry-run sweep captures the current git commit once at sweep
start and threads that source identity into durable artifacts. `cells.jsonl`
records `source_commit_sha`, `source_commit_short_sha`, `source_dirty`,
`terminal_state`, and a bounded `failure_tail` for failed or missing-result
cells. `matrix_summary.tsv` includes source and terminal-state columns, and
its footer records `run_status=COMPLETED` plus the same source identity.

If a sweep aborts before the configured report phase, the orchestrator still
emits `cells.jsonl`, `compatibility_pruned.jsonl`, and
`matrix_summary.partial.tsv`. The partial report footer records
`run_status=ABORTED`, the aborting phase, and the abort reason. Failed
per-cell logs also receive a bounded `UAT_FAILURE_TAIL` block so the run
directory remains debuggable without relying on an operator tee log.

Every durable artifact (`cells.jsonl`, its `.accounting.json` sidecar,
`compatibility_pruned.jsonl`, `validator_rollup.tsv`, and the
`matrix_summary` TSVs) is written atomically: content lands in a `.tmp`
sibling first, gets `fsync`'d, then `os.replace`s the real path. A crash or
error mid-write leaves the previous good artifact (or nothing, on a first
write) in place instead of a torn file. `cells.jsonl` is written before its
accounting sidecar, so a crash between the two writes cannot leave a fresh
sidecar next to a stale (or absent) cell stream.

## Disk-budget estimate

Preflight prints a disk-budget line and a per-root free-space report before
workload cells run:

```text
Disk budget estimate: 12.34 GiB peak (10.50 GiB steady; cells=141; unknown=4)
Free space: tmp                     18.63 GiB (required 12.34 GiB) /tmp
Free space: output                 240.12 GiB (required 12.34 GiB) ~/Developer/benchmark_runs
Free space: benchmark-data         240.12 GiB (required 12.34 GiB) ~/Developer/benchmark_runs/datagen
Free space: docker-data            240.12 GiB (required 12.34 GiB) ~/Developer/benchmark_runs
```

The estimate comes from `tests/uat/data/disk_budget_table.tsv`, an
operator-maintained inventory from prior sweeps. Preflight gates the
sweep on the largest configured scale's estimated peak against every
required root (`/tmp`, the output root, the datagen root, and the
managed Docker data root when Docker lifecycle management is enabled).
Unknown cells are still reported in the count and as a preflight warning;
they are not treated as zero. Treat a large `unknown=` count as a prompt
to partition the sweep into smaller configs or refresh the table after
the next run.

The free-space floor and per-cell disk watch are always on for every
execute-bearing run, independent of the `phases:` list — omitting
`"preflight"` skips the pre-sweep budget report/abort only, not the
mid-sweep interlock. A crash inside the budget estimator (bad table row,
unreadable TSV) is a hard preflight failure with the underlying
exception, not a silent downgrade to the flat cutoff; unknown cells
remain advisory and stay a warning.

Operators who know a run fits can override the disk gates by explicitly
setting `preflight.free_space_min_gib: 0`. Use that only for supervised
reruns; it disables both the static free-space floor and the budget
headroom gate, prints a `[disk-gate] DISABLED by config` warning at
sweep start, and records `disk_gate_disabled: true` in the
`cells.jsonl.accounting.json` sidecar.

When a sweep aborts on the free-space floor (or any other phase), it does
not write a resumable manifest -- resume was retired as fragile (see
`_project/specs/uat-framework.md` Section 3, "Resume (retired)"). Just
rerun the config; datagen reuse and reuse-aware database pruning make a
full rerun cheap, and the abort-safe artifacts (`cells.jsonl`,
`compatibility_pruned.jsonl`, `matrix_summary.partial.tsv`) from the
aborted run remain on disk as evidence.

## Submission terminal states

The package phase reads `package.submit_terminal_state` from YAML;
the four-word vocabulary (from
`uat-template-success-metric-terminal-state-and-gating`) is:

- `local-stage` — `benchbox submit --output <dir>`; no upstream action
- `cloud-uploaded` — `benchbox submit --service <url>`; requires `package.service`
- `draft-pr` — open PR vs `published-results`, no auto-merge
- `merged-to-published-results` — open PR vs `published-results`, auto-merge

PR-opening modes delegate to the existing `published-results` flow
(owned by `results-explorer-uat-corpus-integrate-validated-bundles`,
in DONE).

## Cross-scale coverage assertion (opt-in)

`report.cross_scale_coverage_min_pairs: N` in YAML enables the
optional teeth from the methodology spec's Finding 1: report exits
non-zero if fewer than `N` (platform, benchmark) pairs passed AND
validator-cleaned every rung. Default null (off) — convention is the
primary enforcement, tooling teeth are opt-in.

## Compatibility Pruning

UAT compatibility pruning is explicit policy, not an implicit skip. Rules live
in `tests/uat/compatibility.py` and carry a `rule_id`, `status`, reason, and
source evidence. Runtime SQL rewrite rules stay in `benchbox/sql_compat/`;
UAT rules only explain why a platform/benchmark cell is not attempted.

When a rule blocks a cell, the execute phase records it in
`compatibility_pruned.jsonl` with the rule metadata. The report footer includes
candidate, executed, compatibility-pruned, early-stop-pruned, passed, failed,
and timed-out counts, followed by a run-status/source-provenance footer.
Early-stop pruning is separate from compatibility pruning and must not be
treated as a pass or a compatibility exclusion.

## Config lifecycle (three classes)

Every file under `tests/uat/configs/` has one of three lifecycle classes. The
class is signalled by the first-line header and, for generated shards, by
location:

1. **Editable template** (`# TEMPLATE`) — a reusable starting point. Clone it
   for a new sweep; the original stays generic.
2. **Historical evidence** (`# HISTORICAL`) — an immutable replay of a past
   sweep, retained for provenance. Historical configs are evidence: reviewed,
   not re-run as-is. There is no hash ceremony or `.frozen-hashes.json` guard.
3. **Generated rerun shard** — operational scratch emitted by an operator's
   manual follow-up to a sweep (re-running a triaged subset of failed cells,
   often one file per platform). These are NOT reusable templates. They live
   under `tests/uat/configs/generated-rerun-shards/` (see that directory's
   README), not at the top level, so they cannot masquerade as editable
   starting points.

New sweeps clone a template:

```bash
cp tests/uat/configs/uat-2026-05-02.yaml tests/uat/configs/uat-<new>.yaml
# edit `name:`, then run `make uat-sweep CONFIG=tests/uat/configs/uat-<new>.yaml`
```

## Sequential platform execution

Per UAT W3 line 222 in
`_project/handoffs/results-explorer-uat-retrospective-20260502.md`,
parallel platforms contaminate timings. The framework hard-rejects
`execute.parallel_platforms: true` at config load time; do not work
around this.

### Managed Docker startup failures are non-fatal

A managed Docker compose-up failure (e.g. a heavy stack exceeding
`cleanup.docker_start_timeout_s`) is treated as a per-platform
infrastructure failure, not a sweep abort. The failure is recorded in
`uat_lifecycle.log` (`action=up status=failed`), the platform's cells are
recorded as skipped-unreachable, the half-started stack is torn down, and
the sweep advances to the next stack — one stack at a time. Genuine global
aborts (disk free-space, teardown failure, fixed `container_name` policy)
still stop the sweep.

Setting `docker_start_timeout_s` for a slow stack (e.g. LakeSail Spark
Connect): **measure a healthy startup first, then set the timeout above it.**
Bring the stack up in isolation (`make uat-bring-up PLATFORM=lakesail`),
confirm the service becomes healthy, time it, and set
`cleanup.docker_start_timeout_s` to a value comfortably above the observed
healthy time. Do not raise it blindly — a longer timeout on a broken service
just wastes the timeout window each attempt.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Preflight aborts on disk | `<5 GiB free at ~/Developer/benchmark_runs` | free space, or override `preflight.free_space_min_gib` |
| Mid-sweep execute aborts on disk | free space fell below `preflight.free_space_min_gib` after a platform | inspect `uat_lifecycle.log`; increase space or reduce the matrix before resuming |
| Skipped-unreachable platforms | local Docker / TCP services not running and Docker is externally managed | `docker compose up` for the relevant services, or set `execute.skip_unreachable: false` to surface as failures |
| Docker daemon unavailable in managed mode | `cleanup.docker_manage_platforms: true` requires `docker ps` and `docker compose` | start Docker Desktop/daemon; preflight treats Docker as required in managed mode |
| Compose stack startup timeout | image pull/build or healthcheck exceeded `cleanup.docker_start_timeout_s` | the sweep records the stack as failed and advances (see "Managed Docker startup failures are non-fatal"); inspect compose logs and raise the timeout only after measuring a healthy startup |
| Cleanup command failed | UAT-owned `docker compose down ...` returned non-zero | inspect `uat_lifecycle.log`, then run the logged command manually if safe |
| Fixed `container_name` collision | a compose file declares a global container name already in use | stop the conflicting developer stack or keep that platform external-only until the compose file is fixed |
| Validator clean rate breaches floor | bundle quality regression | run `make uat-validate` standalone; it validates via `benchbox.validation.bundle` and writes the rollup TSV |
| Make target missing | new release not synced | `make worktree-pool-status` to check pool freshness |

## Release-gate re-run

A release-gate sweep produces the sign-off evidence (a COMPLETED report per
config with a commit SHA). It runs in four stages, in this order, so that all
native and dataframe platforms finish before any Docker stack starts — the
ordering the 2026-05-28/29 evidence violated.

Stages (run each to completion before starting the next):

1. **Native SQL + dataframe** — `tests/uat/configs/release-gate-01-native-dataframe.yaml` (scales 0.01/0.1/1)
2. **Docker non-OLTP** — `tests/uat/configs/release-gate-02-docker-nonoltp.yaml` (scales 0.01/0.1/1)
3. **Docker OLTP** — `tests/uat/configs/release-gate-03-docker-oltp.yaml` (scale 0.01)

(Stage 1 covers release-gate stages 1–2 of the contract — native SQL then
dataframe — in a single Docker-free sweep; stages 2 and 3 are the Docker tiers.)

Run rules:

- Use a **fresh run root** under `BENCHBOX_OUTPUT_DIR=~/Developer/benchmark_runs`;
  never resume into the failed 2026-05-28/29 dirs (they are non-evidentiary).
- Record the run **seed** (`BENCHBOX_SEED`) in the release-gate log.
- One platform / one Docker stack at a time (`execute.parallel_platforms` is
  hard-rejected). A single Docker stack's compose-up failure records FAIL and
  the sweep advances; it does not truncate the run.
- For slow Docker stacks (e.g. LakeSail), set `cleanup.docker_start_timeout_s`
  from a measured healthy startup (see "Managed Docker startup failures are
  non-fatal") before the stage-2 run.

Every sweep writes a machine-readable `uat_gate_summary.json` beside
`cells.jsonl` (versioned schema; verdict `green|red`, or `dry_run` for
dry-run sweeps): config name, source provenance, container engine,
completion timestamp, per-phase exit codes, accounting counts, validator
clean rate vs floor, cross-scale pairs vs floor, and explorer-smoke status.

Ordering + aggregation check: after the three runs,

```bash
make uat-gate-check STAGE1=<stage1-run-dir> STAGE2=<stage2-run-dir> STAGE3=<stage3-run-dir>
```

reads the three stage summaries, verifies from their machine-recorded
`completed_at` timestamps that no Docker `action=up` in stages 2/3 preceded
stage-1 completion (nor stage 3 before stage-2 completion), enforces the
mechanized APPROVE items below, and writes the combined evidence file to
`_project/release-evidence/uat-gate-summary.json`. Exit 0 means APPROVE:
review the evidence file and commit it — `scripts/release_readiness_check.py`
requires it on the release PR (see `docs/operations/release-guide.md`).

`cross_scale_coverage_min_pairs` in each config is the report-phase teeth: a
breach forces a non-zero report exit, so a partial or regressed sweep cannot
be APPROVED. The values are derived, not hand-picked: floor =
max(stage minimum, floor(0.8 × cross-scale-eligible pairs from
`enumerate_cells_with_pruning`)) — each config carries its derivation comment,
and `tests/uat/test_config.py` pins the sound band.

### APPROVE / HOLD gate

`make uat-gate-check` mechanizes this checklist: all stages verdict-green
(every phase exit 0, incl. validator and cross-scale floors), accounting
sidecar present (`unreachable_is_estimated=false`), explorer smoke actually
ran for stages that configure it, one clean `source_commit_sha` across
stages (`source_dirty=false`), and no ordering violations. Exit 0 = APPROVE;
any HOLD reason is printed and lands in the evidence file's `reasons`.

Still manual before committing the evidence: DuckDB (the reference) is green
or its cells are explicitly pruned, and no `NO_JSON` cell lacks captured
error text.
