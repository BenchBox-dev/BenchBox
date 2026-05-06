# UAT Framework — Operator Guide

The UAT framework lives at `tests/uat/`. It composes seven phases —
preflight, enumerate, execute, validate, package, explorer-smoke,
report — driven by YAML configs under `tests/uat/configs/`. Configs
declare what to run; the framework runs it.

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

## Output artefacts

By default every BenchBox runtime artefact lands under the shared
`~/Developer/benchmark_runs/` root:

```
~/Developer/benchmark_runs/
├── datagen/                       # generated source data; preserved across runs
├── databases/                     # loaded DBs; pruned at safe reuse boundaries
├── results/                       # per-cell result JSON files
├── logs/uat_<date>/               # per-cell logs + matrix_summary.tsv
└── submissions/<name>/            # local-stage / draft-pr bundles
```

The UAT runner passes this root to every `benchbox run` subprocess as
`BENCHBOX_OUTPUT_DIR`, so datagen, loaded databases, and result JSONs
stay outside the worktree even when the sweep is launched from a pool
worktree. Override the root with `output.benchmark_runs_dir_template`;
override only logs or staged submissions with `output.logs_dir_template`
and `output.submissions_dir_template`.

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

## Frozen vs editable configs

Files under `tests/uat/configs/` are either FROZEN historical replays
(first line `# FROZEN`) or editable templates (first line `# TEMPLATE`).
Hashes for FROZEN files live in `.frozen-hashes.json`; PR CI fails on
edits. New sweeps clone an existing config:

```bash
cp tests/uat/configs/uat-2026-05-02.yaml tests/uat/configs/uat-<new>.yaml
# edit `name:`, then run `make uat-sweep CONFIG=tests/uat/configs/uat-<new>.yaml`
```

## Relationship to scripts/local_stress_test.sh

The bash script remains operative for muscle-memory continuity.
`make uat-stress` is the preferred path going forward; both honour
the same `PLATFORM=`, `BENCHMARK=`, `SCALE=` env-var inputs. A
deprecation cycle is out of scope for this TODO and will file as a
separate decision after `make uat-stress` proves adoption.

## Sequential platform execution

Per UAT W3 line 222 in
`_project/handoffs/results-explorer-uat-retrospective-20260502.md`,
parallel platforms contaminate timings. The framework hard-rejects
`execute.parallel_platforms: true` at config load time; do not work
around this.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Preflight aborts on disk | `<5 GiB free at ~/Developer/benchmark_runs` | free space, or override `preflight.free_space_min_gib` |
| Skipped-unreachable platforms | local Docker / TCP services not running | `docker compose up` for the relevant services, or set `execute.skip_unreachable: false` to surface as failures |
| Validator clean rate breaches floor | bundle quality regression | run `make uat-validate` standalone, inspect rollup TSV |
| Make target missing | new release not synced | `make worktree-pool-status` to check pool freshness |
