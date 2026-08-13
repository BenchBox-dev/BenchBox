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
| Full sweep from a config | `make uat-sweep CONFIG=tests/uat/configs/uat-tuned-followup-20260505.yaml` |
| Validate a directory of bundles | `make uat-validate RESULTS_DIR=<dir> OUTPUT_TSV=<path>` |
| Package staged bundles via terminal-state YAML | `make uat-package CONFIG=<path> SUBMISSIONS_DIR=<path> RESULTS="r1.json r2.json"` |
| Explorer build + Playwright smoke | `make uat-explorer-smoke BUNDLES_DIR=<path> OUTPUT_DIR=<path> LOG_DIR=<path>` |
| TSV roll-up from a cells JSONL | `make uat-report CELLS_JSONL=<path> OUTPUT_TSV=<path>` |
| Single-phase execute (already-validated config) | `make uat-execute CONFIG=<path>` |
| Discover subcommands and options | `uv run -- python -m tests.uat._cli --help` |

## Output artefacts

By default every BenchBox runtime artefact lands under the shared
`benchmark_runs/` root alongside the checkout — `~/Developer/benchmark_runs/`
for a clone at `~/Developer/BenchBox`, and the same root for every sibling
linked worktree:

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
stay outside the worktree even when the sweep is launched from a disposable
linked worktree.

Two ways to change the root, in precedence order: an explicit
`output.benchmark_runs_dir_template` (and/or `output.logs_dir_template`,
`output.submissions_dir_template`) in the config always wins. The three
release-gate configs intentionally leave those keys unset, so setting
`BENCHBOX_OUTPUT_DIR` before a stage overrides the
`~/Developer/benchmark_runs` base for runs, logs, and local-stage submissions;
this also matches bare `make uat-cell` (which has always read the env var).
A config with an explicit template ignores `BENCHBOX_OUTPUT_DIR` for that
path — no silent root switching for a configured sweep.

## Local-artifact hygiene (external-root invariant)

**Invariant:** whenever the resolved output root lies outside the worktree, the
worktree-local `benchmark_runs/` must **not** grow. Datagen, databases, and
result JSONs all belong under that root. This guards the 2026-06-01 incident,
where a corpus sweep launched from a linked worktree with
`BENCHBOX_OUTPUT_DIR=~/Developer/benchmark_runs` still accumulated ~4.2 GB
under the worktree-local `benchmark_runs/datagen/`.

Since the default root became the work tree's sibling (`../benchmark_runs`),
"outside the worktree" is the **ordinary** case. The UAT runner and the
`make uat-artifact-hygiene`/`make pr-preflight` gates audit that case; a plain
`benchbox run` itself only resolves its output root and does not snapshot or
fail on worktree-local growth. The guard steps aside only when the resolved
root is *inside* the worktree, or when the run starts outside a Git work tree
(where the historical cwd-anchored default applies and any growth is local by
definition).

The guardrails are **report-only** — they detect and name the offending paths
but never delete or move artifacts.

* The UAT runner (`tests/uat/runner.py`) snapshots the worktree-local
  `benchmark_runs/` before each external-root cell and fails loudly if it
  grows, naming both the unexpected local path and the configured external
  root. The guard resolves the enclosing Git worktree, so launching UAT from a
  nested directory does not create a second, misleading local boundary.
* `make uat-artifact-hygiene` audits the live worktree and is wired into `make
  pr-preflight`. It is a no-op when the resolved root is inside the worktree,
  or when the run starts outside a Git work tree with no explicit external
  root configured (the cwd-local default is preserved). An explicit external
  root remains audited even when the launch directory is outside Git.

  ```bash
  # Audit the current worktree (also a no-op outside a Git worktree with no
  # external root configured):
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
  docker_settle_s: 10                 # settle before the one-shot post-`up --wait`
                                      # readiness check; catches immediate crashes
                                      # only, see below
  docker_fixed_container_name_policy: "fail"

execute:
  liveness_probe_timeout_s: 2.0       # per-cell liveness probe; 0 disables.
                                      # This is what catches a stack dying
                                      # LATER, see below
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

### Compose project naming and the container-id limit

`compose_project_name()` builds a deterministic project name from
`docker_project_prefix`, the config name, and the platform, then truncates
(sha1-suffixed for determinism) so it fits under a length budget. That budget
is *not* simply compose's own 63-char project-name ceiling: compose derives
the actual CONTAINER name as `<project>-<service>-<replica>`, and mocker
rejects any container id over 64 chars. A project name that itself fits under
63 chars can still produce an oversized container id once the longest
service name a platform starts (e.g. `lakesail-connect`) and the replica
suffix are appended.

The budget is therefore derived per platform: `min(63, 64 - <longest started
service name> - <replica suffix headroom> - 1)`. The replica suffix headroom
reserves room for a two-digit index (`-10`..`-99`), not just `-1`, so a
scaled service does not silently overflow the moment it reaches its 10th
replica. Every registered `DockerPlatformSpec.services` tuple is populated at
module load from the platform's compose file(s) (the full set for platforms
that start everything, a documented host-run-only subset for lakesail and
velox), so this lookup never parses YAML on the hot teardown path.

A guard test (`tests/uat/test_docker_assets.py::test_container_name_budget_fits_every_config_and_platform`)
enumerates every checked-in `tests/uat/configs/*.yaml` config against every
registered Docker platform and asserts the resulting container id fits.
`docker_project_prefix` stays fully operator-configurable -- a longer prefix
still produces a valid, distinct project name, just truncated sooner.

**Migration note (container-id budget tightening, 2026-08).** Deriving the
budget from the 64-char container-id limit instead of compose's looser
63-char project-name ceiling is strictly tighter, so it renames roughly half
of the checked-in (config, platform) project names -- always shorter, never
longer, so it never reintroduces an overflow. The rename itself is safe, but
teardown matches by exact `-p <project-name>`: containers started by a
pre-upgrade sweep are registered under the OLD, longer project name, so the
first post-upgrade sweep's teardown will not match and stop them, and they
keep holding their host ports. They are not lost -- `make uat-docker-cleanup`
inventories by the `benchbox-uat` project-label *prefix* (see above), which
every generation of this name has always shared, old and new alike. Every
affected operator is on macOS/mocker (this overflow is mocker-only), so the
default `ENGINE=docker` pass alone is NOT sufficient: as "Container engine
resolution" above explains, that mode's inventory listing degrades to
named-volumes-only when the resolved engine is mocker and reports no
containers at all -- an operator who runs only that pass sees a clean
"applied" report while the orphaned containers keep holding ports (5432,
8080, 9000, ...), and the next sweep's `compose up --wait` then fails on a
port conflict, the exact symptom this note exists to prevent. After
upgrading, run BOTH passes once to catch any pre-upgrade leftovers:

```bash
make uat-docker-cleanup ENGINE=container APPLY=1
make uat-docker-cleanup APPLY=1
```

The first pass (`ENGINE=container`) removes containers, networks, and
images via the native `container` CLI. The second (default `ENGINE=docker`)
pass sweeps mocker-managed named volumes, which `ENGINE=container` cannot
see. Together they remove only `benchbox-uat`-prefixed resources and leave
everything else for manual review, per the recovery command's normal
`APPLY=1` semantics above.

### Mocker validation status

Apple silicon + macOS 26, LOCAL DEV ONLY -- never CI (CI runs `test-docker-*`
on ubuntu with real docker). Validated on mocker: `questdb` + `postgresql`
lifecycle parity and end-to-end `test-docker-questdb` (load + query).

NOT validated: multi-service stacks. `docker/databend/docker-compose.yml`
declares three services (`minio`, `minio-setup`, `databend`); databend stays
healthy on docker, but its `minio` service exits under mocker. This was last
observed 2026-07-03 against a 4-service databend and 3-service doris/
starrocks (TODO `migrate-test-docker-stacks-to-mocker`, w2); all three
compose files have since been rewritten, and current service counts are
pinned by the test below, but the failure has not been re-measured against
today's compose files. Set the resolver override
`BENCHBOX_CONTAINER_CLI=docker` for UAT's own compose lifecycle
(`resolve_container_cli()`, above -- this is the path a macOS operator
actually takes; on macOS it otherwise resolves to mocker when present).
`CONTAINER_ENGINE=docker` is a different knob: it only feeds
`make test-docker-*`'s `$(COMPOSE)` (`Makefile:462`) and is already the
default there, so setting it is a no-op for that path. This databend/minio
failure is specific to its dependency on a separate MinIO container for
S3-compatible storage -- it is not evidence that mocker cannot run
multi-service compose stacks in general. `docker/doris/docker-compose.yml`
and `docker/starrocks/docker-compose.yml` each declare exactly one service
(the official all-in-one FE+BE image); databend's separate-MinIO failure
mode does not apply to them structurally, but they are not separately
validated under mocker.

`tests/uat/test_docker_assets.py` pins these compose files' service *names*
(not just counts) so this guidance cannot silently drift out of sync again.
It drifted once already: commit `fd29aa77c0` compressed AGENTS.md's former
"Mocker as a local test-docker engine" section -- which is where this
databend/minio caveat originally lived, not this file -- down to a vague
"Mocker is local-only and unsuitable for the known multi-service stacks"
line with no named platform.

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

### Incremental durability and killed-run detection

During the execute phase each cell's `cells.jsonl` row is appended and
`fsync`'d the moment that cell completes, so a sweep that dies mid-run keeps
every row it had already earned instead of losing the whole batch. Two
sentinel files beside `cells.jsonl` record the run's lifecycle:

- `cells.jsonl.inprogress` — written when streaming begins.
- `cells.jsonl.finalized` — written last, at an orderly sweep end (normal
  completion *or* a controlled abort), which also clears `.inprogress`.

A run interrupted by a signal (see below) or a hard crash leaves `.inprogress`
without `.finalized`. `make uat-report` treats such a run as `INCOMPLETE` and
exits nonzero — a partial stream of all-passed rows never reads as a clean
sweep. A legacy artifact that carries *neither* sentinel (it predates this
machinery) still regenerates exactly as before.

### Signal teardown (SIGTERM behaves like Ctrl-C)

For the duration of a sweep the process installs a SIGTERM handler that raises
a cancellation, so an operator `kill` (or a CI cancellation) unwinds through
the same path Ctrl-C already took: the per-platform `finally` tears the
managed Docker stack down, no finalize marker is written (the run stays
`INCOMPLETE`), and the process exits nonzero. The cancellation — signal name,
phase in flight, and timestamp — is recorded to `uat_lifecycle.log` as a
`[cancel]` line. The shim is scoped to the sweep process only; cell
subprocesses keep their own timeout/process-group kill semantics, and the
previous SIGTERM handler is always restored when the sweep returns.

## Disk-budget estimate

Preflight prints a disk-budget line, a coverage disclosure, a verdict, and a
per-root free-space report before workload cells run. With every one of the
141 checked-in TSV rows currently `unmeasured` (see "The disk budget is a
lower bound, not a certification" below), this is what a real default-group
run prints today:

```text
Disk budget estimate: 12.34 GiB peak (10.50 GiB steady; cells=141; unknown=4)
Disk budget coverage: PARTIAL -- this estimate is a LOWER BOUND, not a certification that the sweep fits. Measured rows cover 0 of 21 platform(s); 137 of 141 largest-scale cell(s) have any row and 0 of 141 have a measured loaded-database footprint. Unmeasured platform(s): cedardb, clickhouse-local, clickhouse-server, databend, datafusion, doris, +15 more
Disk budget verdict: no shortfall detected against a lower-bound requirement of 12.34 GiB; real demand may be higher (see coverage above)
Free space: tmp                     18.63 GiB (required >= 12.34 GiB) /tmp
Free space: output                 240.12 GiB (required >= 12.34 GiB) ~/Developer/benchmark_runs
Free space: benchmark-data         240.12 GiB (required >= 12.34 GiB) ~/Developer/benchmark_runs/datagen
Free space: docker-data            240.12 GiB (required >= 12.34 GiB) ~/Developer/benchmark_runs
```

The estimate comes from `tests/uat/data/disk_budget_table.tsv`, an
operator-maintained inventory from prior sweeps. Preflight gates the
sweep on the largest configured scale's estimated peak against every
required root (`/tmp`, the output root, the datagen root, and the
managed Docker data root when Docker lifecycle management is enabled) --
in practice, with today's inventory, that estimate is almost always a
**lower bound**, not an exact figure: the `required >= ...` marker and the
`Disk budget coverage:`/`Disk budget verdict:` lines above say so
explicitly, and "The disk budget is a lower bound, not a certification"
below explains why and what it takes to remove the caveat. Unknown cells
are still reported in the count and as a preflight warning; they are not
treated as zero. Treat a large `unknown=` count as a prompt to partition
the sweep into smaller configs or refresh the table after the next run.

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

### The disk budget is a lower bound, not a certification

Every figure the disk gate produces comes from
`tests/uat/data/disk_budget_table.tsv`, an operator-maintained inventory
of prior sweeps. That inventory is partial in two independent ways, and
preflight discloses both rather than letting either read as zero demand:

1. **Cells with no row.** They contribute 0 GiB and are counted as
   `unknown_cells`. As of 2026-08 the table covers four platforms
   (`clickhouse-local`, `datafusion`, `duckdb`, `lakesail`) of the ~21 a
   default sweep enumerates.
2. **Rows whose loaded-database footprint was never measured.** Every
   checked-in row carries `peak_database_gib = 0.000000` and declares
   `peak_database_gib_status = unmeasured`. The loaded-database term of
   the estimate is therefore identically zero -- for want of data, not
   because loaded databases are small. A default sweep's estimate is
   essentially the datagen term alone (~22 GiB).

`assess_budget_coverage(...)` measures both gaps over exactly the cells
the gate gated on, and preflight prints the result on every run, alongside
a verdict that is deliberately not the word "fits":

```text
Disk budget estimate: 25.20 GiB peak (25.20 GiB steady; cells=1127; unknown=1000)
Disk budget coverage: PARTIAL -- this estimate is a LOWER BOUND, not a certification that the sweep fits. Measured rows cover 0 of 21 platform(s); 41 of 419 largest-scale cell(s) have any row and 0 of 419 have a measured loaded-database footprint. Unmeasured platform(s): cedardb, clickhouse-local, clickhouse-server, databend, datafusion, doris, +15 more
Disk budget verdict: no shortfall detected against a lower-bound requirement of 22.04 GiB; real demand may be higher (see coverage above)
```

The same partial-coverage state raises a preflight warning and marks the
free-space table's requirement as a floor (`required >= 22.04 GiB`) rather
than an exact figure the operator's free space comfortably clears. Once an
inventory covers every gated cell with measured values, the block instead
reads `Disk budget coverage: COMPLETE` and the verdict states plainly that
the measured requirement fits.

**Direction matters.** Refusing a sweep because even this lower bound does
not fit is always sound -- a lower bound that already exceeds free space
cannot shrink. Passing means only "no shortfall detected against the
measured subset". Treat a `PARTIAL` verdict as "not yet ruled out", not as
clearance, and keep watching `uat_lifecycle.log`: the mid-sweep free-space
floor in `execute` is the backstop for what preflight could not know.

Filling gap (2) needs a real measured sweep. Do not populate the column by
estimating -- a guessed per-platform constant converts a disclosed gap
into an undisclosed fabrication, and `check_disk_headroom`'s
`max(preflight.free_space_min_gib, estimate)` already guarantees the
configured floor holds regardless of how low the estimate runs.

> **Withdrawn: `execute.platform_chunking`.** An earlier iteration of this
> section proposed a config flag that pruned each platform's loaded
> databases at the platform boundary, on the premise that the flat
> estimate hides a per-platform term and that ~11 platforms' databases
> coexist at 90-150 GiB. Both premises were wrong. With the default
> `cleanup.prune_databases: true` (`tests/uat/config.py`), `_maybe_prune_completed`
> (`tests/uat/phases/execute.py`) already runs after every benchmark
> including a platform's last, and `remaining_consumers` only counts
> same-platform pending cells -- so at a platform boundary that platform's
> databases are already pruned and the proposed step measured zero bytes
> freed in every realistic case. (With `prune_databases: false` nothing is
> pruned at all, platform boundary or not, so the flag would not have
> helped there either.) And with the loaded-database column
> unmeasured (gap 2 above), the "concurrent" and "chunked" figures differ
> by under 1 MiB on every checked-in config, so the recommendation could
> never fire. The flag, its execute wiring and its preflight branch were
> removed; the honest disclosure above replaces them. Reopen this only
> with measured per-platform database footprints in hand.

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
cp tests/uat/configs/stress-default.yaml tests/uat/configs/uat-<new>.yaml
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
recorded as `startup_failed` (not `skipped_unreachable` — that accounting
split is deliberate, see "Post-start readiness re-check" below), the
half-started stack is torn down, and the sweep advances to the next stack —
one stack at a time. Genuine global aborts (disk free-space, memory
headroom, teardown failure, fixed `container_name` policy) still stop the
sweep.

Setting `docker_start_timeout_s` for a slow stack (e.g. LakeSail Spark
Connect): **measure a healthy startup first, then set the timeout above it.**
Bring the stack up in isolation (`make uat-bring-up PLATFORM=lakesail`),
confirm the service becomes healthy, time it, and set
`cleanup.docker_start_timeout_s` to a value comfortably above the observed
healthy time. Do not raise it blindly — a longer timeout on a broken service
just wastes the timeout window each attempt.

### Detecting a stack that dies after `up --wait` succeeds

`docker compose up -d --wait` exiting 0 only proves the stack reported
started/healthy **at that instant**. It does not prove the stack is still
running afterwards. Live-observed 2026-08-04: `mocker compose up --wait`
reported CedarDB `Started`, and `mocker compose ps` showed
`diag-net-cedardb-1 Exited` roughly **29 seconds** later — the container's
own log showed why (`Running under cgroup memory limit: 1024 MB`, then
`FATAL: unable to register fixed io_uring buffer`, a host-memory-exhaustion
failure, see "Memory headroom gate" below). Because nothing re-checked the
stack after `up --wait` returned, UAT ran all 171 remaining cells against
the dead stack and recorded every one as a **cell failure** — hiding the
real cause behind 171 misleading rows.

Two separate mechanisms now cover this, and they cover **different windows**.
Neither replaces the other.

#### 1. Post-start readiness check — immediate crashes only

After a successful `up --wait`, the execute phase waits
`cleanup.docker_settle_s` seconds (default 10), then:

1. runs `compose ps -a` and fails the platform if any service's STATUS is
   not up-and-serving: `Exited`, compose-v1 `Exit N`, `Restarting`,
   `Created`, `Dead`, `Paused`, or `Up … (unhealthy)`. `-a` is required —
   plain `compose ps` lists only *running* containers, so a service that
   started and then died is simply absent and an empty table reads as
   healthy. An empty table is likewise treated as **not ready**: `ps -a`
   finding nothing for a project that was just `up`'d means the containers
   are gone.
2. probes host reachability once.

**What this can and cannot catch.** It runs exactly once and has rendered
its verdict roughly twelve seconds after `up --wait` returned. It catches a
container that is *already dead by then* — an immediate crash. It does not
catch a container that dies later, and **no value of `docker_settle_s`
changes that**, because the check does not repeat. Concretely: this check
would **not** have caught the 2026-08-04 incident above. Raising
`docker_settle_s` to chase a late death only lengthens every platform
boundary; it buys no additional coverage.

It is also not a substitute for `docker_start_timeout_s` — `up --wait`
already reported the stack Started/healthy by the time this runs, so raising
that timeout in response to a readiness failure just waits longer on
something the engine already declared done.

This check runs only for `cleanup.docker_manage_platforms: true` and is
skipped for `dry_run: true`.

#### 2. Per-cell liveness probe — deaths at any later time

This is the mechanism that actually covers the 2026-08-04 failure mode.

At the start of a platform's cell list, UAT probes reachability once. If the
platform *is* reachable, the liveness probe is **armed** for that platform,
and a fresh (never cached) reachability probe runs immediately before every
single cell. The first probe that fails ends the platform: the cell about to
run, the rest of its benchmark, and every benchmark still queued for that
platform are recorded in a dedicated `died_mid_platform` bucket, a
`[liveness]` line is written to `uat_lifecycle.log`, the stack is torn down,
and the sweep advances to the next platform.

Arming matters: a platform that was *never* reachable is not armed, so
`skip_unreachable: false` configs that deliberately attempt unreachable
platforms are unaffected. `died_mid_platform` means "was up, then died", and
nothing else.

`died_mid_platform` is deliberately its own bucket, disjoint from the
neighbours it could have been folded into:

| Bucket | Meaning |
|---|---|
| `startup_failed` | the stack never started (`compose up` or readiness check failed) |
| `skipped_unreachable` | a reachability probe never found anything listening |
| `died_mid_platform` | the stack started, served cells, then went away mid-run |
| cell `failed` rows | a cell ran and the benchmark itself failed |

Recording a mid-run death as cell failures is the original bug; recording it
as `startup_failed` would assert the stack never started, which is false.
The count appears in `matrix_summary.tsv` (`died_mid_platform=N` in the
footer plus a `# DIED_MID_PLATFORM_CELLS=N release_gate_attention=required`
line), in `uat_gate_summary.json` (`accounting.died_mid_platform`), in
`cells.jsonl`'s accounting sidecar (`died_mid_platform_count`), and in
`uat report --json` (`died_mid_platform`). It feeds `total_defined` and
makes the report exit nonzero, exactly like `unreachable` and
`startup_failed` do — losing a platform mid-sweep is a real failure, not a
clean skip.

**Cost.** One loopback TCP connect per cell. Measured on the 2026-08-05 dev
host: **0.074 ms** for a successful connect, 0.034 ms for a refused one.
The three release-gate stages define 525 + 215 + 251 = 991 cells, of which
only the 466 Docker-stage cells open a socket at all (a platform with no
reachability endpoint, e.g. `duckdb`, short-circuits without a syscall), so
the added cost of a full three-stage release gate is about **35 ms** against
a run measured in hours. The pathological case — a probe that times out
rather than being refused — is bounded by
`execute.liveness_probe_timeout_s` (default 2.0 s) and can happen at most
once per platform, since the first failure ends that platform.

**Disabling it.** `execute.liveness_probe_timeout_s: 0` turns the probe off
entirely, the same 0-disables convention as `preflight.free_space_min_gib`
and `preflight.free_memory_min_gib`. With it off, a stack dying mid-platform
is invisible again and its cells are recorded as ordinary cell failures —
which is precisely why the default is not 0.

## Memory headroom gate

Preflight gates free **disk** space (`preflight.free_space_min_gib`), but
under mocker each Docker-managed platform is its own VM with independent
memory sizing — free disk space says nothing about whether the host has
enough free memory left to start the next container's VM. The 2026-08-04
incident above was ultimately a host-memory-exhaustion failure, not a
mocker defect: the host had **72 MB free of 16 GB, with 11.7 of 13.3 GB
swap already in use** when CedarDB's container (cgroup-limited to 1024 MB)
failed to register an io_uring buffer and exited.

`preflight.free_memory_min_gib` (default 2.0) mirrors
`preflight.free_space_min_gib`'s shape, including the 0-disables
convention: `preflight.free_memory_min_gib: 0` disables the gate exactly
like `free_space_min_gib: 0` disables the disk gate, and prints a
`[memory-gate] DISABLED by config` warning. The gate runs immediately before
starting each Docker-managed platform (mirroring the disk floor's
platform-boundary check in `execute.py`) and gates on **measured free
memory**, never total RAM — a 16 GB host with 72 MB free is not "fine"
because it has 16 GB of capacity. Every check, pass or fail, logs a
`[free-memory]` line to `uat_lifecycle.log` with the resolved container
engine (`docker`/`mocker`), the measured free memory against the configured
floor, swap-used percentage alongside (telemetry only — it never gates the
decision by itself), and the platform's declared VM/container memory
request (from the compose file's `mem_limit` or
`deploy.resources.limits.memory`, or "no declared memory limit (engine
default)" when neither is set — most UAT compose files, including
CedarDB's, declare none, so the 1024 MB cgroup limit above came from the
engine's own default sizing, not this repo's compose files).

Free memory is measured with `psutil.virtual_memory().available` (`psutil`
is a hard project dependency) on macOS, Linux, and Windows alike. If the
measurement itself cannot be taken (psutil unavailable, a sandboxed
process denied access, …), the gate degrades safely: it logs that the
reading is unavailable and does **not** gate — it never silently treats an
unmeasurable host as having headroom (fail-open), and never hard-fails an
otherwise-healthy host merely because the measurement failed (fail-closed).

## ClickHouse streaming-memory calibration

The ClickHouse server loader is a bounded native-driver stream. It must not
fall back to the generic 1,000-row application batch helper. Calibration is a
measurement exercise, not permission to publish a new compose limit from total
RAM, `free`, or an unrelated host snapshot. The trace records `available` and
`free` separately, swap pressure, engine/container memory usage and limit,
ClickHouse `MemoryTracking`/resident metrics, cumulative `InsertedRows` and
`InsertedBytes`, driver responsiveness, the requested driver timeout, and the
loader contract.

The only supported rung order is:

| rung | requested memory | load memory | driver timeout | decision |
|---|---:|---:|---:|---|
| `baseline-1g` | 1 GiB | 1 GiB | 300 s | run first; existing baseline, not a new published limit |
| `candidate-4g` | 4 GiB | 4 GiB | 300 s | run only after the baseline fails or cannot complete |
| `candidate-8g` | 8 GiB | 8 GiB | 300 s | run only when the 4 GiB trace justifies escalation |
| `candidate-12g` | 12 GiB | 12 GiB | 300 s | last resort; requires a trace-backed reason |

Wrap the real ClickHouse server UAT command so sampling covers the whole load
and query path (the wrapper writes an atomic JSON artifact even when the child
fails):

```bash
uv run -- python -m tests.uat.clickhouse_memory \
  --output "$BENCHBOX_OUTPUT_DIR/clickhouse-memory-baseline-1g.json" \
  --rung baseline-1g \
  --engine mocker \
  --project-name <managed-compose-project> \
  --compose-file docker/clickhouse/docker-compose.yml \
  -- -- uv run -- benchbox run --platform clickhouse-server \
       --benchmark tpch --scale 0.01 --phases load
```

Run a small smoke cell first. Only if that trace is responsive and free of
OOM/cgroup-kill/timeout evidence should the same rung be tried at SF1. Advance
to the next rung only when the smallest failing or incomplete run has a trace
that explains why. A passing trace is admissible only when it has a successful
responsiveness sample, `native_streaming=true`, and
`application_batch_rows=null`, plus the measured ClickHouse driver timeout. The
current server setup default is 300 seconds and the wrapper records that source
directly from `ClickHouseSetupMixin`; an explicitly configured timeout is also
recorded when the command supports that option. All memory rungs keep the same
timeout so a larger timeout cannot turn a timeout defect into a false memory
success. A trace that reports `1000` rows or cannot establish its timeout is
rejected, even if the command exits zero.
`select_lowest_successful_rung()` chooses the lowest valid passing rung and
fails closed when no such trace exists.

Keep each trace with the UAT evidence. Do not add `mem_limit`,
`CLICKHOUSE_MEMORY_LIMIT`, or a 1 GiB fallback to the compose file from this
calibration step. The subsequent compose-admission TODO consumes a selected
rung only after this trace review and separately verifies the runtime limit and
host reserve.

### ClickHouse managed-stack admission

ClickHouse is the exception to the generic "declared limit or engine default"
diagnostic above. Its managed UAT compose file requires the caller to resolve
`preflight.clickhouse_memory_limit` (default `4g`, the calibration-selected
SF1 rung) into `CLICKHOUSE_MEMORY_LIMIT`; the compose file has no `:-1g` or
other fallback. A missing, empty, or malformed request is an admission error
before `compose up`, never a reason to recreate the historical 1 GiB batch.
An operator override is allowed only when it names a separately measured
calibration rung and is recorded with the run evidence.

The host reserve is configured independently as
`preflight.docker_memory_reserve_gib` (default `2.0`). For ClickHouse the
pre-start requirement is the selected request plus that reserve, compared
with the same `virtual_memory().available` metric used by the generic gate.
After startup UAT also runs a no-stream runtime-stats query, requires an
explicit container memory limit, and requires it to equal the selected
request exactly. It then repeats the host-available check. Unknown runtime
limits or unavailable post-start host memory fail the ClickHouse platform
closed; UAT does not infer a limit from total RAM, engine defaults, or a
driver batch size. The existing `free_memory_min_gib: 0` setting remains an
explicit, supervised opt-out of the pre-start floor, but it does not permit
an unverified ClickHouse runtime limit or post-start reserve shortfall.

For a direct operator compose check, export the selected rung explicitly:

```bash
CLICKHOUSE_MEMORY_LIMIT=4g docker compose -f docker/clickhouse/docker-compose.yml config
```

The UAT harness passes the same environment to `up`, readiness, runtime
stats, and teardown, so every lifecycle action is tied to one request and
cannot silently fall back to a 1 GiB setting.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Preflight aborts on disk | `<5 GiB free at ~/Developer/benchmark_runs` | free space, or override `preflight.free_space_min_gib` |
| Mid-sweep execute aborts on disk | free space fell below `preflight.free_space_min_gib` after a platform | inspect `uat_lifecycle.log`; increase space or reduce the matrix before resuming |
| Preflight prints `Disk budget coverage: PARTIAL` and passes | the inventory does not measure every gated cell (as of 2026-08 no row has a measured loaded-database footprint) -- see "The disk budget is a lower bound" | expected, not an error: the estimate is a floor, so keep headroom beyond the printed requirement and watch the mid-sweep free-space floor. Do not silence it by guessing values into `disk_budget_table.tsv` |
| Sweep passes preflight then exhausts disk mid-run | real demand exceeded the lower-bound estimate -- most likely the unmeasured loaded-database term | inspect `uat_lifecycle.log` for the last platform reached; narrow the matrix or scale ladder, and record the observed footprints into `disk_budget_table.tsv` with `peak_database_gib_status = measured` |
| Skipped-unreachable platforms | local Docker / TCP services not running and Docker is externally managed | `docker compose up` for the relevant services, or set `execute.skip_unreachable: false` to surface as failures |
| Docker daemon unavailable in managed mode | `cleanup.docker_manage_platforms: true` requires `docker ps` and `docker compose` | start Docker Desktop/daemon; preflight treats Docker as required in managed mode |
| Compose stack startup timeout | image pull/build or healthcheck exceeded `cleanup.docker_start_timeout_s` | the sweep records the stack as failed and advances (see "Managed Docker startup failures are non-fatal"); inspect compose logs and raise the timeout only after measuring a healthy startup |
| Platform `startup_failed` shortly after `up --wait` succeeded | container reported Started, then Exited/Restarted, or became unreachable within `docker_settle_s` | inspect `uat_lifecycle.log` `action=ps`/`action=readiness` events and the container's own logs; do NOT raise `docker_start_timeout_s` (see "Post-start readiness re-check") — check host memory first |
| Preflight/execute aborts on memory | host free memory fell below `preflight.free_memory_min_gib` before starting a Docker-managed platform | inspect `uat_lifecycle.log` `[free-memory]` lines (free GiB, swap %, VM request); free host memory or override `preflight.free_memory_min_gib` for a supervised rerun |
| Cleanup command failed | UAT-owned `docker compose down ...` returned non-zero | inspect `uat_lifecycle.log`, then run the logged command manually if safe |
| Fixed `container_name` collision | a compose file declares a global container name already in use | stop the conflicting developer stack or keep that platform external-only until the compose file is fixed |
| Validator clean rate breaches floor | bundle quality regression | run `make uat-validate` standalone; it validates via `benchbox.validation.bundle` and writes the rollup TSV |
| Make target missing | new release not synced | `make help` to check the available Make targets |

## Release-gate re-run

A release-gate sweep produces the sign-off evidence (a COMPLETED report per
config with a commit SHA). It runs in four stages, in this order, so that all
native and dataframe platforms finish before any Docker stack starts — the
ordering the 2026-05-28/29 evidence violated. First time on a machine: work
through `docs/operations/uat-local-provisioning.md` "Fresh machine checklist"
before starting stage 1.

Stages (run each to completion before starting the next):

1. **Native SQL + dataframe** — `tests/uat/configs/release-gate-01-native-dataframe.yaml` (scales 0.01/0.1/1)
2. **Docker non-OLTP** — `tests/uat/configs/release-gate-02-docker-nonoltp.yaml` (scales 0.01/0.1/1)
3. **Docker OLTP** — `tests/uat/configs/release-gate-03-docker-oltp.yaml` (scale 0.01)

(Stage 1 covers release-gate stages 1–2 of the contract — native SQL then
dataframe — in a single Docker-free sweep; stages 2 and 3 are the Docker tiers.)

Run rules:

- Use a **fresh run root** under `BENCHBOX_OUTPUT_DIR=~/Developer/benchmark_runs`
  (the three configs leave their output templates unset, so the env var sets
  the base — see "Output artefacts"); never resume into the failed 2026-05-28/29
  dirs (they are non-evidentiary).
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
