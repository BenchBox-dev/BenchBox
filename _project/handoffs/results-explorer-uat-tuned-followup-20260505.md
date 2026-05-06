# Results Explorer UAT Tuned Follow-Up - 2026-05-05

## Executive Summary

Recommendation: do not promote this tuned corpus as complete. The UAT framework now supports `execute.extra_args: ["--tuning", "tuned"]`, and every successful result JSON from the attempted cells has `execution.tuning_mode=tuned`, but the local sweep could not complete within the available disk budget while preserving reusable datagen.

The run stopped at the 5 GiB safety boundary during `clickhouse-local` after 141 attempted cells. Successful clean submissions were locally staged for the subset that passed `benchbox submit --output`; 87 bundles were staged, 27 result JSONs were refused by the submission contract, and the staged subset validator-clean rate was 95.4%.

## Config And Commands

Worktree: `/Users/joe/Developer/BenchBox.pool-02` on `feat/uat-tuned-followup-20260505`.

Config: `tests/uat/configs/uat-tuned-followup-20260505.yaml`.

Primary commands:

```bash
uv run -- python -m pytest tests/uat -q -m fast
uv run -- python -m pytest tests/uat -q -m fast -n 0
make uat-sweep CONFIG=tests/uat/configs/uat-tuned-followup-20260505.yaml
make uat-package CONFIG=tests/uat/configs/uat-tuned-followup-20260505.yaml SUBMISSIONS_DIR=$HOME/Developer/benchmark_runs/submissions/uat-tuned-followup-20260505 RESULTS="$(cat reconstructed_results.txt)"
make uat-validate RESULTS_DIR=$HOME/Developer/benchmark_runs/submissions/uat-tuned-followup-20260505/bundle OUTPUT_TSV=$HOME/Developer/benchmark_runs/logs/uat_tuned_followup_20260505_pool02_rerun/validator_rollup.tsv FLOOR=0.80
make uat-explorer-smoke BUNDLES_DIR=$HOME/Developer/benchmark_runs/submissions/uat-tuned-followup-20260505/bundle OUTPUT_DIR=$HOME/Developer/benchmark_runs/logs/uat_tuned_followup_20260505_pool02_rerun/explorer_data LOG_DIR=$HOME/Developer/benchmark_runs/logs/uat_tuned_followup_20260505_pool02_rerun BROWSERS=chromium
```

Fast tests passed after the UAT infrastructure changes: `136 passed, 2 deselected`.

## Runtime Path Audit

The sweep was launched from `/Users/joe/Developer/BenchBox.pool-02`. UAT logs and staged submissions landed under the intended shared root because those paths were explicit in YAML, but `benchbox run` subprocesses inherited `BENCHBOX_OUTPUT_DIR` unset. BenchBox therefore used its cwd-relative default and wrote runtime artifacts under `/Users/joe/Developer/BenchBox.pool-02/benchmark_runs`.

Observed pool-local runtime artifacts:

- `/Users/joe/Developer/BenchBox.pool-02/benchmark_runs/results`: 183 JSON files, 5.2 MiB.
- `/Users/joe/Developer/BenchBox.pool-02/benchmark_runs/datagen`: 8.6 GiB.
- `/Users/joe/Developer/BenchBox.pool-02/benchmark_runs/databases`: 21 GiB.

Consolidation performed:

- Copied all 183 pool-local result JSON files into `~/Developer/benchmark_runs/results/`.
- No result filename collisions were present before the copy.
- Post-copy check found 0 missing pool-local result JSONs from the shared results directory.

Remediation in this PR:

- Added `output.benchmark_runs_dir_template`, defaulting to `~/Developer/benchmark_runs`.
- UAT single-cell and execute paths now pass a non-worktree root to every `benchbox run` subprocess as `BENCHBOX_OUTPUT_DIR`.
- Preflight and reuse-aware database cleanup now derive their default paths from the same resolved root.

The 29.6 GiB pool-local datagen/database tree was not deleted because that is a destructive filesystem cleanup and needs explicit approval.

## Coverage

Registry enumeration produced 1,503 eligible cells:

- SQL-platform cells: 1,197.
- DataFrame-platform cells: 306.
- Filtering respected registry scale metadata and DataFrame support.

Terminal or reconstructed outcomes:

| Outcome | Count |
| --- | ---: |
| Candidate cells | 1,503 |
| Attempted cells | 141 |
| Passed | 114 |
| Failed | 25 |
| Timed out | 2 |
| Ladder-pruned | 72 |
| Skipped unreachable | 855 |
| Resource-budget blocked | 435 |

Platform summary is in `~/Developer/benchmark_runs/logs/uat_tuned_followup_20260505_pool02_rerun/coverage_platform_summary.tsv`. Full cell coverage is in `~/Developer/benchmark_runs/logs/uat_tuned_followup_20260505_pool02_rerun/coverage_cells.tsv`.

Reached platforms: `duckdb`, `datafusion`, `lakesail`, `clickhouse-local`.

Unreachable TCP-backed local platforms: `cedardb`, `clickhouse-server`, `databend`, `doris`, `influxdb`, `pg-duckdb`, `pg-mooncake`, `postgresql`, `presto`, `questdb`, `singlestore`, `starrocks`, `timescaledb`, `trino`, `velox`.

Resource-budget blocked platforms/cells include the remaining `clickhouse-local` tail, `sqlite`, `spark`, and all DataFrame platforms (`polars-df`, `pandas-df`, `modin-df`, `pyspark-df`, `dask-df`, `datafusion-df`). Free space crossed the 5 GiB safety boundary and the sweep was stopped at ~4.3 GiB available while preserving generated datagen; the runtime path audit above shows this particular run preserved pool-local datagen because `BENCHBOX_OUTPUT_DIR` was not propagated.

## Tuning Verification

Every attempted command log starts with `--tuning tuned`. All 114 successful result JSONs were checked for `execution.tuning_mode == "tuned"`; none failed this check.

Several logs reported tuned fallback rather than an optimized platform/benchmark template, for example DuckDB NYC Taxi and FlightData: `Tuning: using basic constraints (no optimized template available)`. These are still tuned-mode runs, but not benchmark-specific tuned-template runs.

## Submission And Validation

Submission path: `~/Developer/benchmark_runs/submissions/uat-tuned-followup-20260505`.

Submission package results:

- Result JSONs offered to package: 114.
- Staged bundle JSONs: 87.
- Staged manifests: 87.
- Refused by `benchbox submit --output`: 27.

Dominant package refusals:

- Unofficial TPC-DS compliance classes (`unofficial_subscale`, `unofficial_nonstandard`).
- Passed cells with query-level failures, including DataVault, FlightData/DataFusion, JoinOrder/DataFusion, metadata/read/write/transaction primitives, TPC-DI, TPC-DS OBT, TPCHavoc, and TSBS/DataFusion.

Validator rollup: `~/Developer/benchmark_runs/logs/uat_tuned_followup_20260505_pool02_rerun/validator_rollup.tsv`.

Validator result:

- Clean: 83.
- Warning-only: 4.
- Error: 0.
- Refused by validator CLI: 0.
- Validator-clean rate: 95.4%.

Dominant validator warnings were limited to AI primitives bundles: 4 warning-only rows, each with 2 warnings.

## Explorer Smoke

Explorer build output: `~/Developer/benchmark_runs/logs/uat_tuned_followup_20260505_pool02_rerun/explorer_data`.

Explorer build log: `~/Developer/benchmark_runs/logs/uat_tuned_followup_20260505_pool02_rerun/explorer_build.log`.

Build result: passed. It processed 87 staged result bundles into `results.duckdb` plus copied bundle artifacts.

Browser smoke result: failed before browser assertions. The UAT `explorer_smoke` phase had stale CLI assumptions:

- `benchbox explorer build` now expects `--data-dir`, not `--bundles-dir`.
- `results-explorer/scripts/serve-browser-tests.mjs` does not accept `--data-dir` or `--browsers`; it expects `--dist-dir` and `--fixture-dir` and is a server helper, not a one-shot Playwright runner.

The build-side UAT wiring was partially fixed in this worktree, but the browser smoke phase still needs a real current-contract Playwright invocation rather than starting the server helper incorrectly.

## Regression Against 2026-05-02

The 2026-05-02 retrospective completed 527 attempted cells with 434 passed, 85 failed, 8 timed out, 133 ladder-pruned, and 870 skipped-unreachable. This tuned follow-up reached fewer cells because available disk started lower and the preserved datagen corpus plus ClickHouse Local transient growth forced a stop at the 5 GiB boundary.

Positive regressions:

- Tuned-mode wiring is now expressible through config and covered by fast tests.
- Package phase now calls the actual `benchbox submit` entrypoint.
- Explorer build phase now calls the actual `benchbox explorer build --data-dir` contract.
- The staged subset validates cleanly at 95.4%.

Negative/regression risks:

- Full matrix coverage was not achieved.
- Browser smoke remains incomplete in UAT infrastructure.
- Submission packaging showed that a number of cells that produce result JSONs still hide query-level failures and are refused.

## Defect Classification

Environment/provisioning:

- 15 TCP-backed SQL platforms were unreachable.
- Lakesail failed because local Sail/pysail server was not provisioned.

Resource-budget:

- Sweep stopped at ~4.3 GiB free after crossing the 5 GiB boundary while preserving reusable datagen.
- Remaining native slow and DataFrame platforms were not attempted.

UAT-infrastructure:

- `execute.extra_args` was missing and has been added.
- UAT execute did not propagate the shared `benchmark_runs` root into `benchbox run`; this caused pool-local datagen/database/result artifacts and has been fixed.
- Package phase used a stale `python -m benchbox.cli` invocation and has been fixed.
- Explorer build phase used stale `python -m benchbox.cli` and `--bundles-dir`; build-side wiring has been fixed.
- Explorer browser smoke still uses the wrong current Results Explorer smoke contract.

Submission-contract:

- 27 otherwise captured result JSONs were refused by `benchbox submit --output`, mostly for unofficial TPC-DS compliance or query-level failures.

Explorer:

- Explorer data build succeeded for 87 staged bundles.
- Browser smoke did not complete due UAT phase CLI drift, not a confirmed Explorer UI regression.

Benchmark/platform engineering:

- Query-level failures remain in several passed/result-producing artifacts.
- DuckDB NYC Taxi SF 1.0 and FlightData SF 1.0 timed out during data generation.
- DataFusion AI/vector search failed.

## Corpus Integration

Integrated 87 staged tuned bundles and their 87 manifest sidecars into `results-data/bundles/`.

Commands run:

- `cp ~/Developer/benchmark_runs/submissions/uat-tuned-followup-20260505/bundle/*.json results-data/bundles/`
- `cp ~/Developer/benchmark_runs/submissions/uat-tuned-followup-20260505/*.manifest.json results-data/bundles/`
- `uv run -- python scripts/generate_corpus_inventory.py --write`
- `uv run -- python scripts/generate_corpus_inventory.py --check`
- `uv run -- python scripts/validate_submission.py results-data/bundles/`
- `uv run -- python results-data/validate_corpus.py`
- `uv run -- benchbox explorer build --data-dir results-data --output ~/Developer/benchmark_runs/logs/uat_tuned_followup_20260505_pool02_rerun/corpus_integration_explorer_data`
- `cp /Users/joe/Developer/BenchBox.pool-02/benchmark_runs/results/*.json ~/Developer/benchmark_runs/results/`

Corpus result:

- `results-data/corpus-inventory.json` now indexes 287 bundles.
- Submission contract validation passed for all 287 bundles with 0 errors and 128 warnings.
- Corpus validator found 287 bundles and 53 cohorts; it reported 7 sparse-cohort warnings: `ai_primitives` SF 0.01, 0.1, and 1.0; `joinorder` SF 1.0; `vector_search` SF 0.01, 0.1, and 1.0.
- Explorer corpus build passed, processing 287 results across 53 cohorts into `~/Developer/benchmark_runs/logs/uat_tuned_followup_20260505_pool02_rerun/corpus_integration_explorer_data`.

## Follow-Up TODO Candidates

- `results-explorer-uat-defect-disk-budget-resume-plan`: add resumable UAT execution and/or a preflight disk budget estimator that accounts for preserved datagen and platform transient growth.
- `results-explorer-uat-defect-pool02-artifact-cleanup`: after explicit approval, remove or archive `/Users/joe/Developer/BenchBox.pool-02/benchmark_runs/datagen` and `/Users/joe/Developer/BenchBox.pool-02/benchmark_runs/databases`.
- `results-explorer-uat-defect-explorer-smoke-current-cli`: update `tests/uat/phases/explorer_smoke.py` to build the Explorer app and run a current-contract Playwright smoke against external `benchbox explorer build` output.
- `results-explorer-uat-defect-submit-partial-success-refusals`: make result-producing cells with query-level failures surface as failed UAT cells before package.
- `results-explorer-uat-defect-tuned-template-coverage`: inventory missing tuned templates where tuned mode falls back to basic constraints.
- `results-explorer-uat-defect-local-platform-provisioning`: document or automate readiness for Lakesail and TCP-backed local platforms.
