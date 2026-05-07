# UAT Framework — Design Document

> **Status:** awaiting user approval before W2 (Python implementation begins).
> **Source TODO:** `_project/TODO/main/planning/uat-framework-tests-uat-runner.yaml`
> **Triggering finding:** `_project/blind-spots/2026-05-03-130000-stress-script-uat-driver-drift.md`
> **Sibling spec (consumed, not duplicated):** `_project/specs/uat-methodology-blind-spot-remediation.md`
> **Author inputs:**
>   - `scripts/local_stress_test.sh` (the existing-but-incomplete framework)
>   - `_project/handoffs/results-explorer-uat-retrospective-20260502.md` (the bespoke driver this spec replaces)
>   - `scripts/uat_validator_rollup.py` (Finding 2 deliverable; consumed as phase)
>   - `_project/DONE/main/active/uat-template-success-metric-terminal-state-and-gating.yaml` (Finding 3 vocab)

## 1. Reframe — what this spec is and is not

### 1.1 The drift gap

`scripts/local_stress_test.sh` and the 2026-05-02 UAT driver are two
parallel surfaces for matrix-shape execution that drift. The bash
script already ships:

- timeout/gtimeout/perl-fallback wrappers (lines 90-123, 359-429)
- registry enumeration via `benchbox.core.benchmark_registry`
  (lines 232-263)
- per-platform port maps, `--platform-option` tables, CLI flags, uv
  extras (lines 142-192, 548-555)
- TCP probing with sentinel-file cache (lines 197-227)
- result-JSON path extraction (line 478)

The 2026-05-02 sweep needed all of that plus:

- scale ladder with early-stop (previous-rung failure or wall-clock > 180s)
- reuse-aware database cleanup (preserve `datagen/`, prune `databases/`
  at safe boundaries)
- sentinel file at sweep start for `find -newer` queries
- matrix-summary TSV
- validator-clean-rate roll-up (now in `scripts/uat_validator_rollup.py`)
- submission packaging with explicit terminal-state declaration
- explorer build + Playwright smoke

None of the second list lived in the bash script and none was reusable
afterwards — it survives only as artifacts under
`~/Developer/benchmark_runs/logs/uat_20260502/` plus the retrospective
prose. The next sweep starts from the same place and reinvents the
same machinery.

### 1.2 Why this is separate from the methodology spec

The methodology spec (`uat-methodology-blind-spot-remediation.md`)
resolves *how UAT TODOs are authored and reviewed*: cross-scale
coverage convention, validator-clean-rate metric, terminal-state
vocab plus `gating: true` open-question schema. Its two
implementation TODOs are now in DONE.

This spec resolves *how UAT machinery is built and reused*. Sibling,
not competitor. The two methodology TODOs ship the inputs this
framework consumes:

- `scripts/uat_validator_rollup.py` — invoked by `make uat-validate`
- `submit_terminal_state` four-word vocab — read from YAML by
  `make uat-package`

### 1.3 What this spec covers

A single Python framework under `tests/uat/` (tracked, version-
controlled), exposed via `make uat-*` operator targets, with
composable phases driven by YAML configs under `tests/uat/configs/`.
Stress testing becomes a degenerate config (one scale, one platform
group, no validate/package/explorer phases).

### 1.4 What this spec does not cover

- Cloud-platform UAT (Snowflake, BigQuery, Redshift, Athena,
  Databricks, ClickHouse Cloud) — deferred to a separate
  `uat-framework-cloud-platforms` TODO if/when the explorer's cloud
  facets are ready.
- Throughput-phase coverage — the 2026-05-02 sweep ran load,power
  only; throughput multiplies wall-clock cost.
- Removal of `scripts/local_stress_test.sh` — W11 documents the
  migration path but does not delete; deprecation is a separate
  decision after `make uat-stress` proves adoption across two-plus
  subsequent UATs.
- A `benchbox uat` CLI subcommand — UAT is a project-developer
  concern, `benchbox` is a project-user concern. `make` targets are
  the developer entrypoint for `worktree-*`, `blind-spots-*`,
  `pr-*`, `dev-loop-metrics`; UAT joins the same pattern.

## 2. tests/uat/ Python package layout

```
tests/uat/
├── __init__.py
├── README.md                      # developer guide (W11 deliverable)
├── matrix.py                      # platform/benchmark enumeration + reachability
├── runner.py                      # single-cell execution (subprocess + timeout + log capture)
├── config.py                      # YAML schema validation, dataclass-style config object
├── timeouts.py                    # signal-based timeout wrapper (replaces bash perl fallback)
├── cleanup.py                     # reuse-aware datagen/databases cleanup
├── docker_assets.py               # UAT-owned Docker compose lifecycle helpers
├── ladder.py                      # scale-ladder + early-stop logic
├── phases/
│   ├── __init__.py
│   ├── preflight.py               # disk, docker, noisy-neighbor scan
│   ├── enumerate.py               # registry-driven matrix with min/max scale enforcement
│   ├── execute.py                 # iterates ladder, invokes runner per cell, applies cleanup
│   ├── validate.py                # subprocess wrapper around scripts/uat_validator_rollup.py
│   ├── package.py                 # invokes benchbox submit per submit_terminal_state
│   ├── explorer_smoke.py          # benchbox explorer build + Playwright via results-explorer/scripts/serve-browser-tests.mjs
│   └── report.py                  # TSV roll-up + cross-scale coverage assertion
├── orchestrator.py                # composes phases per YAML phases: list (uat-sweep entry point)
├── configs/                       # tracked YAML configs
│   ├── README.md                  # content policy (frozen vs editable)
│   ├── uat-2026-05-02.yaml        # frozen replay (W10 deliverable)
│   └── stress-default.yaml        # canned preset for `make uat-stress` (W9 deliverable)
└── test_*.py                      # fast-test coverage (port maps, ladder pruning, schema, etc.)
```

**Responsibility split.**

| Module | Responsibility | Lines (est.) |
|---|---|---|
| `matrix.py` | Port maps, `--platform-option` tables, CLI flags, uv-extra map, TCP probe with cache, registry-driven benchmark enumeration | 250 |
| `runner.py` | Build `benchbox run` argv per cell; capture stdout+stderr to per-run log; extract result-JSON path | 120 |
| `config.py` | Load YAML, validate against schema (Section 3), expose typed access | 180 |
| `timeouts.py` | Signal-based timeout (POSIX `signal.alarm` + `os.killpg`); replaces bash perl wrapper | 80 |
| `cleanup.py` | Track cell completions; prune `databases/` at safe reuse boundaries; preserve `datagen/` | 150 |
| `docker_assets.py` | Map Docker-backed UAT platforms to compose files; build safe project-scoped compose commands | 180 |
| `ladder.py` | Per-(platform, benchmark) rung order; wall-clock and exit-code early-stop; pruning bookkeeping | 100 |
| `phases/preflight.py` | Disk space (configurable cutoff), docker reachability, host load reading | 80 |
| `phases/enumerate.py` | Resolve final cell list given config filters and registry truth; honour min/max scale | 100 |
| `phases/execute.py` | Sequential iteration over (platform, benchmark, rung); invokes runner+ladder+cleanup; owns Docker platform-boundary lifecycle | 220 |
| `phases/validate.py` | `subprocess.run(["uv","run","--","python","scripts/uat_validator_rollup.py", ...])`; consume TSV | 60 |
| `phases/package.py` | Read `submit_terminal_state`; invoke `benchbox submit --output` or `--service`; for `draft-pr`/`merged-to-published-results`, open PR vs `published-results` (auto-merge per state) | 130 |
| `phases/explorer_smoke.py` | `benchbox explorer build` + `node results-explorer/scripts/serve-browser-tests.mjs` | 60 |
| `phases/report.py` | Read each phase's outputs; emit `matrix_summary.tsv`; cross-scale coverage check | 130 |
| `orchestrator.py` | Walk YAML `phases:` list in order; surface phase failures; respect `dry_run:` toggle | 100 |

Total: ~1,500 LOC across 13 modules + tests. The bash script is 600
lines; the framework is roughly the bash script plus the seven
phases the bash script lacks.

## 3. YAML config schema

Schema is the source of truth for what a UAT config can express.
Validation lives in `config.py`; each field below is enforced.

```yaml
# tests/uat/configs/<sweep-name>.yaml

# Identity --------------------------------------------------------------
name: "uat-2026-05-02"          # required, str. Used in log dir name.
description: "..."              # optional, str. One-line description.

# Phase composition -----------------------------------------------------
phases:                          # required, list[str]. Order matters.
  - preflight
  - enumerate
  - execute
  - validate
  - package
  - explorer_smoke
  - report
# Allowed: preflight, enumerate, execute, validate, package,
#          explorer_smoke, report.
# Stress preset omits validate/package/explorer_smoke.

dry_run: false                   # optional, bool, default false. When
                                 # true, every phase prints what it
                                 # would do without invoking benchbox.
                                 # Used by W10 structural-parity test.

# Matrix ----------------------------------------------------------------
platforms:
  groups: ["sql", "dataframe"]   # optional, list[str]. Subset of:
                                 # sql, fast, slow, dataframe, docker,
                                 # docker-fast, docker-slow, all.
  include: []                    # optional, list[str]. Specific platform
                                 # names to add beyond groups.
  exclude: []                    # optional, list[str]. Names to drop.

benchmarks:
  groups: ["all"]                # optional, list[str]. Subset of:
                                 # tpc, primitives, industry, academic,
                                 # timeseries, realworld, aiml,
                                 # experimental, all.
  include: []                    # optional, list[str].
  exclude: []                    # optional, list[str].

scales:
  rungs: [0.01, 0.1, 1.0]        # optional, list[float], default [0.01].
                                 # Per-(platform, benchmark) ladder
                                 # rungs. Filtered by registry
                                 # min_scale/max_scale at enumerate.
  override: null                 # optional, float|null. When set, uses
                                 # this single scale per cell (matches
                                 # bash --scale override). Mutually
                                 # exclusive with rungs.

# Execution -------------------------------------------------------------
execute:
  per_cell_timeout_s: 600        # optional, int, default 600. Hard
                                 # wall-clock cap per cell.
  early_stop_after_s: 180        # optional, int, default 180. If a
                                 # rung's wall-clock exceeds this,
                                 # subsequent higher rungs for that
                                 # (platform, benchmark) are pruned.
  early_stop_on_failure: true    # optional, bool, default true. Prune
                                 # higher rungs on any non-zero exit.
  phases_arg: "load,power"       # optional, str, default "load,power".
                                 # Passed as --phases to benchbox run.
  compression: null              # optional, str|null. Passed as
                                 # --compression when set.
  skip_unreachable: true         # optional, bool, default true. TCP
                                 # probe failures are skipped, not
                                 # counted as failures.
  parallel_platforms: false      # required to be false; reserved field
                                 # rejected at validation time. UAT W3
                                 # line 222: parallel platforms
                                 # contaminate timings.

cleanup:
  preserve_datagen: true         # optional, bool, default true.
  prune_databases: true          # optional, bool, default true. Prune
                                 # at safe reuse boundaries.
  docker_manage_platforms: false # optional, bool, default false.
                                 # false = externally managed stacks;
                                 # UAT only probes/skips. true = UAT
                                 # starts a project-scoped compose stack
                                 # before each Docker-backed platform.
  docker_platform_switch: "off"  # optional, enum: off, containers,
                                 # volumes, images. Non-off values are
                                 # valid only when docker_manage_platforms
                                 # is true. volumes generates targeted
                                 # `docker compose -p <uat> ... down -v
                                 # --remove-orphans` at platform switch.
  docker_project_prefix: "benchbox-uat"
                                 # optional, str. Prefix for deterministic
                                 # UAT-owned compose project names.
  docker_start_timeout_s: 300    # optional, int, default 300. Timeout for
                                 # compose up/down lifecycle commands.
  docker_fixed_container_name_policy: "fail"
                                 # optional, enum: fail, override, allow.
                                 # Current managed mode rejects compose
                                 # files with fixed container_name values
                                 # until a safe override is registered.

# Preflight phase -------------------------------------------------------
preflight:
  free_space_min_gib: 5          # optional, int, default 5. Hard stop
                                 # at sweep start AND watched mid-sweep
                                 # by `cleanup`; if free space falls
                                 # below this, the sweep aborts before
                                 # the next cell. Lives under preflight
                                 # because it is a sweep-abort guardrail,
                                 # not a per-cell cleanup tunable.
  free_space_path: "~/Developer/benchmark_runs"
                                 # optional, str, default
                                 # "~/Developer/benchmark_runs". Path
                                 # `df` is queried against.
  docker_required: false         # optional, bool, default false. When
                                 # true, preflight fails if `docker ps`
                                 # is not reachable. Set true for
                                 # configs that include any Docker
                                 # platform group.
  noisy_neighbor_warn_load: 8.0  # optional, float, default 8.0. Host
                                 # 1-min load average above this prints
                                 # a warning but does not abort.

# Disk-budget estimate --------------------------------------------------
# `tests/uat/data/disk_budget_table.tsv` is an advisory, checked-in
# inventory keyed by (platform, benchmark, scale_factor). Preflight
# prints `Disk budget estimate: ... GiB` before workload execution.
# The estimate never gates execution; unknown cells are surfaced as a
# count and `preflight.free_space_min_gib` remains the hard cutoff.

# Resume manifest -------------------------------------------------------
# On a free-space-floor abort, the orchestrator writes
# `<log-dir>/resume.json` with:
#   version: 1
#   config_name, log_dir, aborted_phase, abort_reason
#   attempted[]: cell_key, platform, benchmark, scale,
#                terminal_state, exit_code, elapsed_s,
#                log_path, result_path
# `--resume <manifest>` on sweep/execute reuses attempted records and
# runs the remaining cells without invalidating datagen reuse.

# Validate phase --------------------------------------------------------
validate:
  validator_clean_rate_floor: 0.80   # optional, float, default 0.80.
                                     # If rate < floor, validate phase
                                     # exit is non-zero (advisory).
  rollup_extra_args: []              # optional, list[str]. Forwarded
                                     # to scripts/uat_validator_rollup.py.

# Package phase ---------------------------------------------------------
package:
  submit_terminal_state: "local-stage"   # required when package phase
                                         # enabled. One of:
                                         #   local-stage,
                                         #   cloud-uploaded,
                                         #   draft-pr,
                                         #   merged-to-published-results.
  service: null                          # optional, str|null. Required
                                         # when state=cloud-uploaded;
                                         # passed as --service.
  pr_target_branch: "published-results"  # optional, str. Used by
                                         # draft-pr and
                                         # merged-to-published-results
                                         # states.

# Explorer smoke phase --------------------------------------------------
explorer_smoke:
  build_args: []                       # optional, list[str]. Extra args
                                       # to `benchbox explorer build`.
  playwright_browsers: ["chromium"]    # optional, list[str], default
                                       # ["chromium"]. Subset of
                                       # chromium, firefox, webkit.
  performance_marks: true              # optional, bool, default true.
                                       # Capture performance log.

# Report phase ----------------------------------------------------------
report:
  matrix_summary_tsv: "matrix_summary.tsv"     # optional, str.
                                                # Filename under log dir.
  cross_scale_coverage_min_pairs: null         # optional, int|null,
                                                # default null. When set,
                                                # report exits non-zero
                                                # if the count of
                                                # (platform, benchmark)
                                                # pairs with all rungs
                                                # validator-clean falls
                                                # below this. OPT-IN per
                                                # methodology spec
                                                # Finding 1 scoping.

# Output paths ----------------------------------------------------------
output:
  logs_dir_template: "~/Developer/benchmark_runs/logs/uat_{date}"
                                       # optional, str. {date} expands
                                       # to YYYYMMDD at sweep start.
  submissions_dir_template: "~/Developer/benchmark_runs/submissions/{name}"
                                       # optional, str. {name} expands
                                       # to top-level `name:` field.
```

**Schema enforcement.**

| Rule | Effect |
|---|---|
| `phases:` references unknown phase | Validation error at load time |
| `parallel_platforms: true` | Validation error (UAT W3 line 222) |
| `package` in `phases:` without `package.submit_terminal_state` | Validation error |
| `package.submit_terminal_state` not in 4-word vocab | Validation error |
| `submit_terminal_state: cloud-uploaded` without `service:` | Validation error |
| `scales.rungs` and `scales.override` both set | Validation error |
| `cross_scale_coverage_min_pairs` set but `report` not in phases | Validation error |
| `validator_clean_rate_floor` outside `[0.0, 1.0]` | Validation error |
| `preflight.free_space_min_gib` <= 0 | Validation error |
| `preflight` not in `phases:` but `preflight.free_space_min_gib` set | Validation warning (telemetry-only run) |

**Default-off teeth.** Per the methodology spec's Finding 1 scoping,
`cross_scale_coverage_min_pairs` defaults `null` (no enforcement).
Sweep authors opt in explicitly.

## 4. Make targets

| Target | Args | Purpose |
|---|---|---|
| `make uat-cell` | `PLATFORM=`, `BENCHMARK=`, `SCALE=` | Single-cell execution. Smallest debugging unit. (W3) |
| `make uat-execute` | `CONFIG=` | Full execute phase: enumerate + ladder + cleanup. Stops after report. (W4) |
| `make uat-validate` | `RESULTS_DIR=` | Standalone validate phase against an existing results dir. (W5) |
| `make uat-package` | `CONFIG=` | Standalone package phase. Reads `submit_terminal_state` from YAML. (W6) |
| `make uat-explorer-smoke` | `RESULTS_DIR=` | Standalone explorer build + Playwright. (W7) |
| `make uat-report` | `LOGS_DIR=` | Standalone TSV roll-up. (W8) |
| `make uat-sweep` | `CONFIG=` (and optional `DRY_RUN=1`) | Full sweep: walks `phases:` list. (W9) |
| `python -m tests.uat._cli preflight` | `--config <path>` | Advisory disk-budget estimate plus current preflight status. |
| `make uat-stress` | `PLATFORM=`, `BENCHMARK=`, `SCALE=` (all optional) | Canned preset; feature parity with `scripts/local_stress_test.sh` for stress-test use. (W9) |

**Invocation contract.**

- All targets accept `BENCHBOX_OUTPUT_DIR` for runs root, defaulting
  to `~/Developer/benchmark_runs/` (matches the bash script).
- All targets exit non-zero on phase failure; the report phase exit
  code is the highest non-zero seen across phases.
- Logs land under `output.logs_dir_template` resolved from the YAML
  (or, for single-cell debugging, under `~/Developer/benchmark_runs/
  logs/uat_<date>/`).
- `make uat-stress` accepts the same `PLATFORM=`, `BENCHMARK=`,
  `SCALE=` env-var inputs as today's bash script for muscle-memory
  continuity. Internally it loads `tests/uat/configs/stress-default.yaml`
  and applies a closed set of env-var overrides defined below.

**Env-var override contract for `make uat-stress`.** Only three
overrides are recognised; any other `MAKE_VAR=` is ignored (no
silent passthrough):

| Env var | YAML field overridden | Type | Effect when unset |
|---|---|---|---|
| `PLATFORM` | `platforms.include` (set to `[$PLATFORM]`) and `platforms.groups` cleared | str | `platforms.groups` from YAML used as-is |
| `BENCHMARK` | `benchmarks.include` (set to `[$BENCHMARK]`) and `benchmarks.groups` cleared | str | `benchmarks.groups` from YAML used as-is |
| `SCALE` | `scales.override` (set to `float($SCALE)`); `scales.rungs` cleared | float | YAML's `scales.rungs` or `scales.override` used as-is |

If `PLATFORM` and `BENCHMARK` are both set, the YAML's `groups`
fields are both cleared and `include` lists are both replaced.
If `SCALE` and YAML's `scales.rungs` are both present, `SCALE`
wins (this is the documented muscle-memory behaviour: the bash
`--scale` flag also overrides per-benchmark smoke scales).

Other targets (`make uat-cell`, `make uat-execute`, `make
uat-sweep`, etc.) do not honour these env vars; they read the
YAML config verbatim. The override mechanism is specific to the
canned stress preset.

**No `benchbox` CLI surface change.** `git diff origin/develop --
benchbox/cli/` must produce no diff over the lifetime of this TODO.
This is enforced by the verification block in the parent TODO.

## 5. Migration plan for `scripts/local_stress_test.sh`

**Default outcome: leave untouched.** The bash script remains
operative for the duration of this TODO. Users with muscle memory
keep working. `make uat-stress` is documented as the preferred path
in `docs/operations/uat-framework.md` (W11) but adoption is opt-in.

**Opt-in delegation (W11 user choice).** Sweep author may, with
explicit user approval at W11, refactor the bash script to delegate
to `make uat-stress`:

```bash
#!/usr/bin/env bash
# scripts/local_stress_test.sh — thin delegator (opt-in)
exec make -s -C "$(git rev-parse --show-toplevel)" uat-stress "$@"
```

The argv-to-env-var translation lives in the Makefile target
(`make uat-stress` already accepts `PLATFORM=`, `BENCHMARK=`,
`SCALE=`).

**Removal: out of scope.** A separate `deprecate-local-stress-test`
TODO files only after `make uat-stress` proves adoption across
two-plus subsequent UATs (per anti-pattern in the parent TODO).

**Drift detection during the transition.** While both surfaces
coexist, the W2 port of port maps / `--platform-option` tables /
CLI flags / uv-extra map MUST match the bash script exactly. The
fast-test for `tests/uat/test_matrix.py` includes a structural
parity assertion: every key in the bash script's case statements
must appear in the Python dict (and vice versa) with the same value.
If the bash script is updated post-merge, the parity test fails and
the framework's port is updated in the same PR.

## 6. Replay artifact spec — `tests/uat/configs/uat-2026-05-02.yaml`

Encode the 2026-05-02 sweep as a frozen replay config:

```yaml
name: "uat-2026-05-02"
description: "Frozen replay of the 2026-05-02 results-explorer multi-scale corpus sweep"

phases: [preflight, enumerate, execute, validate, package, explorer_smoke, report]

platforms:
  groups: ["sql", "dataframe"]
  exclude: []
benchmarks:
  groups: ["all"]
scales:
  rungs: [0.01, 0.1, 1.0]
execute:
  per_cell_timeout_s: 600
  early_stop_after_s: 180
  early_stop_on_failure: true
  phases_arg: "load,power"
  skip_unreachable: true
cleanup:
  preserve_datagen: true
  prune_databases: true
  docker_manage_platforms: false
  docker_platform_switch: "off"
preflight:
  free_space_min_gib: 5
  free_space_path: "~/Developer/benchmark_runs"
validate:
  validator_clean_rate_floor: 0.80
package:
  submit_terminal_state: "local-stage"
explorer_smoke:
  playwright_browsers: ["chromium"]
report:
  matrix_summary_tsv: "matrix_summary.tsv"
  cross_scale_coverage_min_pairs: null
output:
  logs_dir_template: "~/Developer/benchmark_runs/logs/uat_20260502_replay"
```

**Structural parity assertion (W10).** The slow-marked test
`tests/uat/test_replay_2026_05_02.py` runs:

```python
make uat-sweep CONFIG=tests/uat/configs/uat-2026-05-02.yaml DRY_RUN=1
```

and asserts that the dry-run TSV columns and row count match
`~/Developer/benchmark_runs/logs/uat_20260502/matrix_summary.tsv`
(within scale-ladder pruning tolerance — the historical retrospective
reports 1,530 candidate cells, 527 real attempted terminal cells,
133 ladder-pruned, 870 reachability-skipped). The columns must match
exactly:

```
platform | benchmark | scale | status | elapsed_s | log_path | result_path | submit_terminal_state | validator_status
```

The `submit_terminal_state` column was inserted in PR #247 between
`result_path` and `validator_status`; the historical fixture
(`tests/uat/fixtures/uat-2026-05-02-matrix-summary-header.tsv`)
was bumped at the same time. External consumers parsing the TSV by
positional index (`awk '{print $8}'`) must move `validator_status`
from column 8 to column 9 to stay correct.

Wall-clock match is impossible (dry-run prints intent without
invoking benchbox); structural parity is the bar.

**Frozen status.** This config is immutable historical record. The
file's first line includes `# FROZEN — do not edit. Clone to a new
file for new sweeps.` Section 9 expands on the content policy.

## 7. Open questions for the user

Reply yes/no per question (or "accept defaults" to take all five
defaults). Anything unaddressed defaults to the "Default" line below.

1. **`tests/uat/` vs `tests/uat_runner/` for the package directory
   name?**
   - Default: `tests/uat/`. Brevity matches `tests/integration/`,
     `tests/e2e/`, `tests/performance/`.
   - Consequence of `tests/uat_runner/`: clearer intent but four
     extra characters in every import path.

2. **Does the W1 spec require an independent reviewer beyond the
   user?**
   - Default: no. User reviews; the adversarial framing in Section 8
     mitigates self-bias finding 084354.
   - Consequence of yes: file a sub-TODO for an independent reviewer
     pass before W2 unlocks.

3. **Should `make uat-stress` eventually replace
   `scripts/local_stress_test.sh`, or coexist indefinitely?**
   - Default: coexist. W11 documents the migration path; a separate
     deprecation TODO files only after adoption proves out across
     two-plus subsequent UATs.
   - Consequence of "replace": file `deprecate-local-stress-test`
     when this TODO completes; bash script becomes a thin delegator
     in W11.

4. **`tests/uat/configs/uat-2026-05-02.yaml` — frozen replay
   (immutable historical record) or starting template (editable)?**
   - Default: frozen replay. New sweep configs cloned from it via
     `cp tests/uat/configs/uat-2026-05-02.yaml tests/uat/configs/
     uat-NEW.yaml`. Section 9 codifies this.
   - Consequence of "starting template": reduces config sprawl but
     loses the historical-fidelity guarantee that motivates W10's
     parity test.

5. **`submit_terminal_state` default for the stress preset — should
   `make uat-stress` have NO package phase, or emit `local-stage` by
   default?**
   - Default: stress preset omits `package` from `phases:` entirely.
     Terminal-state is irrelevant for stress runs (verification
     focus is "does it run", not "does the bundle validate").
   - Consequence of "local-stage default": stress runs auto-package;
     extra disk+wall-clock for no return because the bundles are
     never submitted.

## 8. Adversarial framing — strongest argument against each design choice

Per blind-spot finding 084354 (self-bias risk in stress-tests),
self-designed adversarial framing tends to under-weight failure
modes the proposer didn't already consider. The user is the
independent reviewer; this section starts the conversation, not
ends it.

### 8.1 Against building a Python framework at all

> "Convention plus a small wrap-script is sufficient. The bash script
> works for stress; the next sweep author can read the script for
> patterns and write a new bespoke driver. Framework adds engineering
> cost and a YAML schema to learn for marginal benefit."

**Counter.** The bash script IS the framework that already exists; it
just lacks half the phases. The 2026-05-02 sweep author DID read the
script for patterns and still re-invented its timeout wrapper. The
"read for patterns" path empirically produces drift, not reuse. The
framework is the next iteration of the bash script, not a new
abstraction.

### 8.2 Against `tests/uat/` location

> "UAT is operator tooling, not a test category. `tests/` should hold
> pytest tests. Put the framework in `_project/scripts/uat/` or
> `tools/uat/` and don't pollute the test directory."

**Counter.** Per user direction (2026-05-03), `_project/` is a mixed
dev-private tree (handoffs, blind-spots, audits, baselines); critical
machinery must live in tracked, version-controlled directories. The
existing `tests/` siblings (`integration/`, `e2e/`, `performance/`,
`system/`, `validation/`, `parity/`, `contracts/`) cover test-flavoured
infrastructure that doesn't fit the unit-test mould either. UAT is
structurally a long, side-effect-heavy, multi-platform test category;
`tests/uat/` follows the precedent. The fast tests added in W2/W3/W4
ARE pytest, covering unit-level logic (port maps, ladder pruning,
schema validation).

### 8.3 Against YAML configs

> "YAML is over-engineered for what amounts to a function call. Just
> let sweep authors write a Python script that calls `tests.uat.runner.
> sweep(...)` directly. Configs become docstrings."

**Counter.** The 2026-05-02 sweep parameters need to be replayable
deterministically. A Python script is mutable code; a YAML config
under version control is the historical record. Section 9's frozen
content policy depends on YAML being declarative data, not code. The
schema doubles as documentation: a sweep author reads the schema in
Section 3 and knows what the framework can express.

### 8.4 Against `make` targets (vs a `benchbox uat` subcommand)

> "Adding a `benchbox uat` subcommand keeps everything in one CLI.
> Users already know `benchbox`; learning `make uat-*` is friction."

**Counter.** `benchbox` ships on PyPI to project users. UAT is a
project-developer concern; sweep machinery on PyPI bloats the user
CLI surface and pulls dev-only deps into the install. The repo
already uses `make` for every other developer concern (`worktree-*`,
`blind-spots-*`, `pr-*`, `dev-loop-metrics`); UAT joins the same
pattern. The friction of one `make` target name is real but
bounded; the friction of bloated user-CLI surface is permanent.

### 8.5 Against an explicit `submit_terminal_state` field

> "The four-word vocab is over-formalised. Sweep authors know what
> they meant. Inferring from the presence of a `--service` flag or
> a PR-target branch is enough."

**Counter.** Inference is exactly what bit the 2026-05-02 sweep
(Finding 3 in the methodology spec). The agent inferred `local-stage`
from validation evidence; the TODO could not have *forced* a
different choice. Required, declarative, no inference. The validation
rule in Section 3 ("required when package phase enabled") makes the
declaration unavoidable.

### 8.6 Against the structural-parity replay test

> "It's a slow test that asserts a TSV row count matches a historical
> file. The historical file is one snapshot; future code changes that
> legitimately alter ladder pruning will keep failing this test
> forever."

**Counter.** The test is `@pytest.mark.slow` and excluded from the
fast-test default. It runs on demand or when the framework's matrix
logic changes. When ladder pruning legitimately changes, the
historical file is updated as part of the same PR (the file is in
`~/Developer/benchmark_runs/logs/`, off-tree; the test compares a
snapshot copy committed under `tests/uat/fixtures/`). The
fixture-update flow makes intentional changes explicit.

### 8.7 Against opt-in `cross_scale_coverage_min_pairs`

> "Optional teeth nobody enables are decorative. Either default it on
> (forces UAT authors to think about cross-scale coverage) or remove
> it entirely (the methodology spec already covers this via convention)."

**Counter.** The methodology spec (Finding 1) explicitly scoped
tooling enforcement OUT — false-positive risk from refusing `done`
on a satisfied-but-via-absence-note unit. Default-off keeps the
framework consistent with that scoping. Removing the field entirely
forecloses the option of adding teeth later if the convention drifts;
keeping it opt-in lets a future sweep author enable it without a
schema change.

### 8.8 Against the W1 user-approval gate

> "An 11-work-unit TODO with a hard spec gate is over-process. Just
> ship W2-W11 and review at PR time. The user reviews PRs anyway."

**Counter.** Each W has its own PR per the TODO's "vertical slices"
discipline. Without a spec gate, the user reviews 11 PRs against an
implicit shared design. The spec gate is one review of one document
that pre-empts wrong directions across all 11. The 2026-05-02 sweep
ran with implicit shared design; the retrospective is the cost.

## 9. `tests/uat/configs/` content policy

The `tests/uat/configs/` directory holds two kinds of YAML files,
distinguished by file-header comment:

### 9.1 Frozen replay configs

```yaml
# FROZEN — do not edit. Clone to a new file for new sweeps.
name: "uat-2026-05-02"
...
```

- Immutable historical record.
- Edits rejected at PR time by `tests/uat/test_frozen_configs.py`,
  which computes a hash of every file with the `# FROZEN` header and
  compares to a checked-in `tests/uat/configs/.frozen-hashes.json`.
- New sweep authors run `cp tests/uat/configs/uat-2026-05-02.yaml
  tests/uat/configs/uat-<new>.yaml` and edit the copy.

### 9.2 Editable templates

```yaml
# TEMPLATE — copy and edit for sweep-specific runs.
name: "stress-default"
...
```

- Mutable; PRs may edit them.
- The canned `stress-default.yaml` is the canonical example; future
  templates (e.g. a `tpch-only-fast-platforms.yaml`) follow the same
  header convention.

### 9.3 PR conventions

| Action | Header | Reviewer expectation |
|---|---|---|
| Add a new frozen replay (post-sweep snapshot) | `# FROZEN` | Verify the `name:` field encodes the sweep's date/identity. |
| Add a new editable template | `# TEMPLATE` | Verify the template's `phases:` list and defaults match a real reuse case. |
| Edit a `# FROZEN` file | (rejected) | PR fails `test_frozen_configs.py`; resubmit as a clone. |
| Edit a `# TEMPLATE` file | `# TEMPLATE` | Standard review; no special protocol. |

The hash check is mechanical; the conceptual policy is "frozen
configs are evidence, editable templates are starting points."

## 10. Migration of existing artifacts

| Artifact | Action | Owner |
|---|---|---|
| `scripts/local_stress_test.sh` | Leave untouched (default); thin-delegate at W11 (opt-in) | W11 |
| `scripts/uat_validator_rollup.py` | Unchanged; framework consumes its public CLI | (no change) |
| `scripts/validate_submission.py` | Unchanged; only invoked transitively via the rollup | (no change) |
| `~/Developer/benchmark_runs/logs/uat_20260502/` | Snapshot a copy of `matrix_summary.tsv` to `tests/uat/fixtures/uat-2026-05-02-matrix-summary.tsv` for the W10 parity test | W10 |
| `_project/handoffs/results-explorer-uat-retrospective-20260502.md` | No retrofit; historical document | (no change) |
| `tests/uat/configs/uat-2026-05-02.yaml` | New file at W10; FROZEN | W10 |
| `tests/uat/configs/stress-default.yaml` | New file at W9; TEMPLATE | W9 |
| `Makefile` | Add `uat-cell` (W3), `uat-execute` (W4), `uat-validate` (W5), `uat-package` (W6), `uat-explorer-smoke` (W7), `uat-report` (W8), `uat-sweep`/`uat-stress` (W9) | W3-W9 |
| `CLAUDE.md` Pre-approved Commands | Add `make uat-*` entries | W11 |
| `docs/operations/uat-framework.md` | New operator guide | W11 |
| `tests/uat/README.md` | New developer guide | W11 |

## 11. Implementation sequencing and PR cadence

One PR per work unit, vertical slices. No monolithic delivery.

| Work unit | Delivers | Test added | Make target |
|---|---|---|---|
| W1 | This spec | (none) | (none) |
| W2 | `tests/uat/matrix.py`, `tests/uat/test_matrix.py` (matches the parent TODO's W2 scope verbatim — matrix machinery only) | Fast | (none) |
| W3 | `tests/uat/runner.py`, `tests/uat/timeouts.py`, `tests/uat/config.py` (minimal — only the fields W3 needs: top-level `name`, `execute.per_cell_timeout_s`, `execute.phases_arg`), `tests/uat/test_runner.py`, `tests/uat/test_timeouts.py`, `tests/uat/test_config.py` | Fast | `make uat-cell` |
| W4 | `tests/uat/ladder.py`, `tests/uat/cleanup.py`, `tests/uat/phases/{preflight,enumerate,execute}.py`, full `config.py` schema coverage (remaining sections), fast tests | Fast | `make uat-execute` |
| W5 | `tests/uat/phases/validate.py`, fast test | Fast | `make uat-validate` |
| W6 | `tests/uat/phases/package.py`, fast test | Fast | `make uat-package` |
| W7 | `tests/uat/phases/explorer_smoke.py`, fast test | Fast | `make uat-explorer-smoke` |
| W8 | `tests/uat/phases/report.py`, fast test | Fast | `make uat-report` |
| W9 | `tests/uat/orchestrator.py`, `tests/uat/configs/stress-default.yaml`, fast test for orchestrator | Fast | `make uat-sweep`, `make uat-stress` |
| W10 | `tests/uat/configs/uat-2026-05-02.yaml`, `tests/uat/fixtures/uat-2026-05-02-matrix-summary.tsv`, `tests/uat/test_replay_2026_05_02.py`, `tests/uat/test_frozen_configs.py` | Slow + fast | (none) |
| W11 | `docs/operations/uat-framework.md`, `tests/uat/README.md`, `CLAUDE.md` updates, optional bash-script delegation | (no new tests) | (none) |

**Verification at each W.** Per the parent TODO's `verification:` block,
each PR adds tests and the sweep verification commands stay green. The
final-state verification commands (after W11) are:

```bash
test -f _project/specs/uat-framework.md
make uat-cell PLATFORM=duckdb BENCHMARK=tpch SCALE=0.01
make uat-stress PLATFORM=duckdb BENCHMARK=tpch
make uat-sweep CONFIG=tests/uat/configs/uat-2026-05-02.yaml DRY_RUN=1
uv run -- python -m pytest -m fast -q
git diff origin/develop -- scripts/local_stress_test.sh   # empty unless W11 delegates
git diff origin/develop -- benchbox/cli/                  # empty
```

## 12. Open risks, watched but not blocking

- **Risk: Python timeout wrapper drifts from the bash perl wrapper.**
  Mitigation: the W2 fast test exercises the timeout wrapper with a
  3-second sleep and a 1-second cap; same exit-code semantics
  (124 on timeout).
- **Risk: registry-driven enumeration races a registry rename.**
  Mitigation: the framework imports `benchbox.core.benchmark_registry`
  directly (no eval, no shell-out); a registry rename surfaces as a
  Python ImportError at enumerate time, not a silent skip.
- **Risk: parallel-platform restriction is enforced at config load
  but bypassable via direct `phases/execute.py` invocation.**
  Mitigation: `phases/execute.py` itself reads
  `config.execute.parallel_platforms` and asserts False; the YAML
  validation is the first line of defence, the runtime assertion is
  the second.
- **Risk: the 2026-05-02 retrospective TSV row count drifts from the
  W10 fixture.** Mitigation: the fixture is a snapshot copy committed
  under `tests/uat/fixtures/`; the historical log file under
  `~/Developer/benchmark_runs/` may be tidied off the host without
  breaking the parity test.

## Appendix — pointers to source material

- Source TODO: `_project/TODO/main/planning/uat-framework-tests-uat-runner.yaml`
- Source blind-spot: `_project/blind-spots/2026-05-03-130000-stress-script-uat-driver-drift.md`
- Sibling spec (consumed): `_project/specs/uat-methodology-blind-spot-remediation.md`
- 2026-05-02 sweep retrospective: `_project/handoffs/results-explorer-uat-retrospective-20260502.md`
- Methodology helper (consumed): `scripts/uat_validator_rollup.py`
- Bash framework (translated, not modified): `scripts/local_stress_test.sh`
- Self-bias caveat: `_project/blind-spots/2026-05-03-084354-stress-test-self-bias.md`
- Spec ergonomics caveat: `_project/blind-spots/2026-05-03-084923-spec-approval-ergonomics.md`
