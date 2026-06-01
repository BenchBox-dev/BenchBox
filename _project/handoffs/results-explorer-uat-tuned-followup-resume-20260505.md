# Results Explorer UAT Tuned Follow-Up Resume - 2026-05-05

## Summary

Fresh retained worktree: `/Users/joe/Developer/BenchBox.pool-10` on branch `chore/results-explorer-tuned-followup-resume-20260505`.

PR #221 (`feat/uat-tuned-followup-20260505`) was still open, so this branch was reset/rebased onto that branch content before running. No PR has been opened for this resume branch yet.

Tuned mode remained enforced via `execute.extra_args: ["--tuning", "tuned"]`. Successful result JSONs checked: 337/337 had `execution.tuning_mode == "tuned"`.

## Disk And Runtime Root

Initial post-claim shared-root check after cleanup:

- `df -h ~/Developer/benchmark_runs`: 38 GiB available.
- `du -sh ~/Developer/benchmark_runs/{datagen,databases,results,logs,submissions}`: datagen 15G, databases 0B, results 84M, logs 79M, submissions 35M.
- Removed a pre-existing ignored pool-local `benchmark_runs/` before running.

Final check:

- `df -h ~/Developer/benchmark_runs`: 5.2 GiB available.
- datagen 16G, databases 0B, results 96M, logs 133M, submissions 41M.
- No `benchmark_runs/` directory remains in `/Users/joe/Developer/BenchBox.pool-10`.

Note: `BENCHBOX_OUTPUT_DIR` was passed to every UAT `benchbox run` subprocess. I also added a minimal UAT runner fix to pass `--output ~/Developer/benchmark_runs/datagen`, because some benchmark data generators still use cwd-relative defaults unless the CLI output root is explicit. Any transient pool-local datagen created before that fix was copied to the shared datagen root and then removed.

## Commands Run

Key commands:

```bash
make worktree-claim BRANCH=chore/results-explorer-tuned-followup-resume-20260505
cd /Users/joe/Developer/BenchBox.pool-10
git fetch origin develop pull/221/head:feat/uat-tuned-followup-20260505
git checkout feat/uat-tuned-followup-20260505 && git rebase origin/develop
git checkout chore/results-explorer-tuned-followup-resume-20260505 && git reset --hard feat/uat-tuned-followup-20260505
uv run -- python -m pytest tests/uat -q -m fast -n 0
uv run -- python -m tests.uat._cli sweep --config tests/uat/configs/generated-rerun-shards/uat-tuned-followup-resume-20260505.yaml
make test-docker-up-clickhouse && uv run -- python -m tests.uat._cli sweep --config tests/uat/configs/generated-rerun-shards/uat-tuned-followup-resume-clickhouse-server-20260505.yaml; make test-docker-down-clickhouse
# repeated start/sweep/down pattern for cedardb, starrocks, postgresql, presto, trino, databend, doris, influxdb, questdb
uv run -- python -m tests.uat._cli validate --results-dir ~/Developer/benchmark_runs/submissions/uat-tuned-followup-resume-20260505/bundle --output-tsv ~/Developer/benchmark_runs/logs/uat_tuned_followup_resume_20260505_pool10/validator_rollup_final.tsv --floor 0.80
uv run -- python -m tests.uat._cli explorer-smoke --bundles-dir ~/Developer/benchmark_runs/submissions/uat-tuned-followup-resume-20260505/bundle --output-dir ~/Developer/benchmark_runs/logs/uat_tuned_followup_resume_20260505_pool10/explorer_data_final --log-dir ~/Developer/benchmark_runs/logs/uat_tuned_followup_resume_20260505_pool10 --browsers chromium
cp ~/Developer/benchmark_runs/submissions/uat-tuned-followup-resume-20260505/bundle/*.json results-data/bundles/
cp ~/Developer/benchmark_runs/submissions/uat-tuned-followup-resume-20260505/*.manifest.json results-data/bundles/
uv run -- python scripts/generate_corpus_inventory.py --write
uv run -- python scripts/generate_corpus_inventory.py --check
uv run -- python scripts/validate_submission.py results-data/bundles/
uv run -- python results-data/validate_corpus.py
uv run -- benchbox explorer build --data-dir results-data --output ~/Developer/benchmark_runs/logs/uat_tuned_followup_resume_20260505_pool10/corpus_integration_explorer_data
```

## Matrix Coverage

Registry-enumerated eligible matrix: 1,503 cells across 27 platforms and 22 benchmarks. DataFrame-ineligible SQL-only benchmark pairs were excluded by the UAT registry path.

Combined terminal outcomes are in:

- `~/Developer/benchmark_runs/logs/uat_tuned_followup_resume_20260505_pool10/combined_coverage_cells.tsv`

Outcome counts:

| Outcome | Count |
| --- | ---: |
| passed | 357 |
| failed | 312 |
| timed-out | 18 |
| ladder-pruned | 528 |
| resource-budget-blocked | 288 |
| skipped-unreachable | 0 |

Docker handling: Docker containers were started/stopped per platform where Docker Desktop remained usable. Docker Desktop later became unable to start after image pulls drove the host back to the 5 GiB free-space boundary. `pg-duckdb`, `pg-mooncake`, `timescaledb`, `singlestore`, and `velox` were therefore recorded as resource-budget-blocked.

## Submission, Validation, Explorer

Reconstructed successful result JSON paths from logs: 337. All were tuned-mode.

Submission staging path:

- `~/Developer/benchmark_runs/submissions/uat-tuned-followup-resume-20260505`

Staged by `benchbox submit --output` through the UAT package flow:

- Bundle JSONs: 241
- Manifest JSONs: 241
- Terminal state: `local-stage`

Validator rollup:

- `~/Developer/benchmark_runs/logs/uat_tuned_followup_resume_20260505_pool10/validator_rollup_final.tsv`
- Clean: 134
- Warning-only: 104
- Error: 3
- Refused by validator CLI: 0
- Clean rate: 55.6%

Dominant validator issues:

- Errors: PostgreSQL `ai_primitives` SF 0.01/0.1 and Dask `tpch_skew` SF 0.01 had all-zero query timings.
- Warnings: empty/zero-query DataFrame artifacts (Dask/Pandas/Polars/PySpark), unknown display names for CedarDB/Apache Doris, and AI primitive warnings.

Explorer smoke/build:

- Staged-bundle Explorer data build succeeded (`build_returncode=0`).
- Browser smoke still failed (`smoke_returncode=1`) due the existing UAT browser-smoke contract drift noted in the prior handoff.
- Corpus Explorer build succeeded: `~/Developer/benchmark_runs/logs/uat_tuned_followup_resume_20260505_pool10/corpus_integration_explorer_data` with 525 results across 57 cohorts.

## Corpus Integration

Integrated validator-acceptable staged bundles into:

- `results-data/bundles/`

Removed the 3 validator-error staged bundles from corpus integration before regenerating inventory.

Corpus state:

- `results-data/corpus-inventory.json`: 525 bundles
- `scripts/validate_submission.py results-data/bundles/`: pass after removing validator-error bundles
- `results-data/validate_corpus.py`: found 525 bundles / 57 cohorts; reports 5 sparse-cohort warnings (`tpcds` all rungs, `ai_primitives` SF 1.0, `flightdata` SF 1.0)

## Remaining Defects By Category

Environment/provisioning/resource:

- Docker Desktop became unable to start after image pulls at ~5 GiB free; remaining Docker platforms blocked.
- Lakesail still failed local provisioning.

Benchmark/platform:

- Many platform/benchmark query failures remain, especially primitives, TPCHavoc, DataFrame zero-query paths, and several Docker SQL adapters.
- 18 hard per-cell timeouts were observed.

UAT infrastructure:

- Browser smoke phase still uses stale Results Explorer smoke assumptions.
- Result-path extraction is brittle when Rich wraps `Exported JSON` paths; reconstructed paths were needed for packaging.
- `BENCHBOX_OUTPUT_DIR` alone is insufficient for all datagen code paths; UAT runner now also passes `--output <shared>/datagen`.

Submission/validation:

- `benchbox submit --output` accepted 241 of 337 successful result JSONs.
- Validator clean rate for accepted staged bundles is 55.6%, below the 0.80 floor.

## Artifact Location Note

No runtime artifacts remain under the pool worktree runtime root. The claimed worktree has no `benchmark_runs/` directory after cleanup; reusable datagen, logs, results, and submissions are under `~/Developer/benchmark_runs`.
