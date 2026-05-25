---
iteration: 16
date: 2026-05-25
surface: legacy TPC-DI ETL batch scaffolding
branch: chore/shrink-dead-tpcdi-etl-batch
pr:
raw_cloc_delta: 1656
credited_reduction: 1656
uncredited_relocation: 0
repair_only_delta: 0
generated_python_delta: 0
moved_content: none
decision_gate: conservative default
verification: passed
---

## Thesis

Remove `benchbox/core/tpcdi/etl/batch.py`, a legacy internal TPC-DI batch
orchestration scaffold that is not on the production TPC-DI runtime path. The
active benchmark imports and initializes `TPCDIETLPipeline` and
`ParallelBatchProcessor`; it does not import `BatchProcessor` or the
`benchbox.core.tpcdi.etl.batch` module.

Maintained-Python credit is 1,656 lines: 1,654 lines from
`benchbox/core/tpcdi/etl/batch.py` plus the two package-export lines that keep
the dead module importable. Test-only removals and configuration cleanup are not
credited.

## Guardrail evidence

- `make shrink-rollup` at `origin/develop` reported 15 merged ledger fragments,
  5,111 credited lines, 6,889 remaining to the committed floor, and 13,889
  remaining to the stretch target.
- `cloc --include-lang=Python benchbox/` reported 925 Python files and 201,896
  maintained Python code lines.
- `rg -F "benchbox.core.tpcdi.etl.batch" benchbox tests docs _project
  pyproject.toml scripts .github` found only two test imports and one test
  patch target.
- `rg -F "BatchProcessor" benchbox tests docs _project pyproject.toml scripts
  .github` found the dead package re-export, the dead module, its tests, and the
  separate active `ParallelBatchProcessor` path.
- `docs/reference/public-contracts.md` classifies public surfaces explicitly;
  this internal ETL helper module is not listed as beta-public, deprecated, or a
  top-level benchmark facade.
- `docs/reference/backward-compatibility.md` has no row for
  `benchbox/core/tpcdi/etl/batch.py` or `BatchProcessor`.
- Open PR overlap check found only PR #626 touching JoinOrder files; this slice
  touches TPC-DI ETL internals, TPC-DI tests, coverage config, and this ledger.
- Post-edit `cloc --include-lang=Python benchbox/` reported 924 Python files and
  200,240 maintained Python code lines, a 1,656-line reduction from the slice
  baseline.
- Active TODO reference cleanup removed stale paths for the deleted TPC-DI batch
  module and the already-removed TPC-DI data-cleaners helper.

## Verification

- Reference cleanup for `benchbox.core.tpcdi.etl.batch`, `BatchProcessor`,
  `BatchStatus`, `ExtractOperation`, `TransformOperation`, `LoadOperation`,
  `ValidationOperation`, `ParallelConfig`, and `ParallelExecutionContext` found
  no remaining active references under `benchbox`, `tests`, `docs`,
  `_project/TODO`, `pyproject.toml`, `scripts`, or `.github`.
- `uv run -- python -m compileall benchbox/core/tpcdi tests/unit/core/tpcdi`
  passed.
- `uv run -- ruff check benchbox/core/tpcdi/etl/__init__.py
  tests/unit/core/tpcdi/test_etl_transformations_batch_scd.py` passed.
- `uv run -- ruff format --check benchbox/core/tpcdi/etl/__init__.py
  tests/unit/core/tpcdi/test_etl_transformations_batch_scd.py` passed.
- `uv run -- python -m pytest -m fast tests/unit/core/tpcdi -q` passed
  (`265 passed in 4.32s`).
- `uv run -- python -m pytest -n 0
  tests/unit/core/tpcdi/test_etl_transformations_batch_scd.py
  tests/unit/core/tpcdi/test_worker_pool_pipeline_sources.py
  tests/unit/tpcdi/test_phase3_etl_enhanced.py -q` passed
  (`55 passed in 0.17s`).
- `uv run -- python -m pytest -n 0 tests/unit/core/tpcdi
  tests/unit/tpcdi/test_phase3_etl_enhanced.py -q` passed
  (`342 passed in 4.28s`).
- `uv run --project _project/scripts -- python _project/scripts/todo_cli.py
  validate` passed (`1052 valid, 0 invalid`).
- `git diff --check` passed.
- `make pr-preflight` passed (`22818 passed, 5 skipped, 47 warnings,
  4 subtests passed in 132.62s`).

No registry, query, or generated-callable consolidation is planned; callable
surface change is limited to removing the unreferenced internal package export.

## Residual risk

External callers could have imported the unlisted internal
`benchbox.core.tpcdi.etl.BatchProcessor` helper despite the public contract map.
That risk is accepted under the conservative default because the helper is not
documented, not registry-backed, not a backward-compatibility row, and not used
by BenchBox runtime code.

## Next target

Continue looking for autonomous-safe dead internal helpers or true dedup
clusters; do not expand into benchmark, platform, experimental, or documented
surface removal without approval.
