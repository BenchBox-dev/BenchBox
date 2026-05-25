---
iteration: shrink-dead-tpc-compliance
date: 2026-05-25
surface: unreferenced legacy TPC compliance framework
branch: chore/shrink-dead-tpc-compliance
pr:
raw_cloc_delta: 343
credited_reduction: 343
uncredited_relocation: 0
repair_only_delta: 0
generated_python_delta: 0
moved_content: none
decision_gate: conservative default; delete only undocumented, unexported, production-unreferenced legacy compliance framework code
verification:
  - make shrink-rollup
  - cloc --include-lang=Python benchbox/
  - cloc --by-file --include-lang=Python benchbox/core/tpc_compliance.py tests/unit/test_tpc_compliance.py tests/integration/test_tpc_compliance_integration.py tests/performance/test_tpc_performance_duckdb.py tests/validation/validate_tpc_compliance.py
  - rg reference check for removed TPC compliance module/symbols
  - uv run -- ruff check benchbox/core/results/metrics.py tests/integration/test_tpc_compliance_integration.py tests/performance/test_tpc_performance_duckdb.py
  - uv run -- python -m compileall -q benchbox/core
  - uv run -- python -m pytest tests/unit/core/results/test_metrics.py tests/integration/test_tpc_compliance_integration.py -q -n 0
  - make pr-preflight
---
## Thesis

Shrink iteration using the smaller-subsystem exception. The target subsystem is the single-file legacy
`benchbox/core/tpc_compliance.py` framework, which measures 343 maintained-Python code lines and has no production
imports, no `benchbox.core` package export, and no source-doc or public-contract references.

The module defines parallel TPC result/config/test ABCs, a connection manager, a validator, and a `TPCOfficialMetrics`
wrapper. Current TPC-H/TPC-DS runtime code uses benchmark-specific power/throughput/maintenance classes plus
`benchbox.core.results.metrics.TPCMetricsCalculator` for official metric math. The only direct consumers found are
tests and a validation script dedicated to this legacy framework.

This slice deletes the runtime module, deletes the dedicated unit test and stale validation script, and retargets mixed
TPC-H/TPC-DS integration/performance tests to the current `TPCMetricsCalculator` where they still cover live metric
behavior. Expected credited reduction is 343 maintained-Python lines. Test-code removals are uncredited.

## Guardrail Evidence

- Current rollup on `origin/develop`: 11 merged fragments; cumulative merged credited reduction 3,258; remaining to
  12,000 floor 8,742; remaining to stretch 15,742; raw cloc delta sanity 2,110.
- Current raw maintained-Python size: `cloc --include-lang=Python benchbox/` reports 203,749 Python code lines.
- Target runtime size: `cloc --by-file --include-lang=Python benchbox/core/tpc_compliance.py ...` reports 343 Python
  code lines in `benchbox/core/tpc_compliance.py`.
- Open PR overlap check:
  - PR #633 touches `_project/shrink-ledger/shrink-tpcdi-dead-spec-validator.md`,
    `benchbox/core/tpcdi/specification_validator.py`, and its dedicated tests.
  - PR #626 touches JoinOrder TODO/queries/tests only.
- Whole-tree reference check before editing found direct imports only in:
  - `tests/unit/test_tpc_compliance.py`
  - `tests/integration/test_tpc_compliance_integration.py`
  - `tests/performance/test_tpc_performance_duckdb.py`
  - `tests/validation/validate_tpc_compliance.py`
- `benchbox/core/__init__.py` exposes an empty `__all__`; the target module is not exported by the package.
- `rg -n "tpc_compliance|TPCCompliance|TPCOfficialMetrics" docs/reference/public-contracts.md docs/reference/backward-compatibility.md benchbox/core/__init__.py benchbox/__init__.py pyproject.toml --glob '!docs/_build/**'`
  found no public-contract, package-export, or packaging references.
- Moved-content classification: none. This slice deletes dead logic and does not move Python, SQL, query surface, YAML,
  metadata, catalog content, or generated Python.

## Verification

- `make shrink-rollup`: 11 merged fragments; cumulative merged credited reduction 3,258; remaining to 12,000 floor
  8,742; raw cloc delta sanity 2,110.
- `cloc --include-lang=Python benchbox/`: 928 files, 203,406 Python code lines after edits, down 343 from the
  203,749-line slice baseline.
- `cloc --by-file --include-lang=Python benchbox/core/tpc_compliance.py tests/unit/test_tpc_compliance.py tests/integration/test_tpc_compliance_integration.py tests/performance/test_tpc_performance_duckdb.py tests/validation/validate_tpc_compliance.py`:
  pre-edit runtime target measured 343 code lines; post-edit mixed integration/performance tests measure 287 and 160
  uncredited test code lines, and deleted files are absent.
- Removed-symbol reference check:
  `rg -n "benchbox\\.core\\.tpc_compliance|from benchbox\\.core\\.tpc_compliance|import benchbox\\.core\\.tpc_compliance|\\bTPCCompliance\\b|\\bTPCOfficialMetrics\\b|\\bTPCPowerTest\\b|\\bTPCThroughputTest\\b|\\bTPCMaintenanceTest\\b|\\bTPCTestResult\\b|\\bTPCTestConfig\\b|\\bTPCQueryResult\\b|\\bTPCValidator\\b|\\bTPCConnectionManager\\b|\\bTPCCompliantBenchmark\\b" benchbox tests docs README.md pyproject.toml --glob '!docs/_build/**'`:
  no matches.
- `uv run -- ruff check tests/integration/test_tpc_compliance_integration.py tests/performance/test_tpc_performance_duckdb.py benchbox/core/results/metrics.py`:
  pass.
- `uv run -- ruff format --check tests/integration/test_tpc_compliance_integration.py tests/performance/test_tpc_performance_duckdb.py`:
  pass.
- `uv run -- python -m compileall -q benchbox/core tests/integration/test_tpc_compliance_integration.py tests/performance/test_tpc_performance_duckdb.py`:
  pass.
- `uv run -- python -m pytest tests/unit/core/results/test_metrics.py tests/integration/test_tpc_compliance_integration.py -q -n 0`:
  27 passed, 12 deselected.
- `uv run -- python -m pytest tests/performance/test_tpc_performance_duckdb.py::TestTPCPerformanceDuckDB::test_tpc_metrics_calculation_performance -q -n 0 -m "performance and stress"`:
  1 passed.
- `make pr-preflight`: pass; `ci-lint` passed and fast tests reported 22,930 passed, 5 skipped, 47 warnings, and
  4 subtests passed.

## Residual Risk

External users could import `benchbox.core.tpc_compliance` directly despite the module not being documented, exported,
or used by BenchBox runtime code. Keeping it would preserve a stale parallel framework whose live metric behavior is
already implemented and tested in `benchbox.core.results.metrics`.

## Next Target

After this slice lands, re-run `make shrink-rollup` from merged `develop` before choosing the next non-overlapping
candidate. Avoid deleting documented reporting/monitoring surfaces even when production imports are sparse.
