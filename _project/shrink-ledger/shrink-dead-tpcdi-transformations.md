---
iteration: 18
date: 2026-05-25
surface: internal TPC-DI transformation engine export
branch: chore/shrink-dead-tpcdi-transformations
pr:
raw_cloc_delta: 1690
credited_reduction: 1690
uncredited_relocation: 0
repair_only_delta: 0
generated_python_delta: 0
moved_content: none
decision_gate: conservative default; internal/test-only helper deletion, no public-contract or benchmark/platform surface removed
verification: passed
---

## Thesis

Remove `benchbox/core/tpcdi/etl/transformations.py`, a legacy internal TPC-DI
transformation engine/helper module maintained only by an `etl` package
re-export and dedicated unit coverage. The active TPC-DI benchmark path now
uses `TPCDIETLPipeline`, ETL backends, source generation, and the separate SCD
processor path; it does not import the transformation engine module or its
helper classes.

Measured maintained-Python credit is 1,690 lines: 1,688 lines from the
deleted helper module plus two package-export lines. Test-only deletions are
uncredited.

## Guardrail evidence

- `make shrink-rollup` at `origin/develop` reported 18 merged ledger fragments,
  7,521 credited lines, 4,479 remaining to the committed floor, and 11,479
  remaining to the stretch target.
- `cloc --include-lang=Python benchbox/` reported 922 Python files and 199,486
  maintained-Python code lines.
- `cloc --include-lang=Python --by-file
  benchbox/core/tpcdi/etl/transformations.py
  benchbox/core/tpcdi/etl/__init__.py
  tests/unit/core/tpcdi/test_etl_transformations_batch_scd.py` reported 1,688
  code lines in `transformations.py`, 18 code lines in the ETL package init,
  and 297 code lines in the mixed transformation/SCD test file.
- Exact reference sweep for the transformation module path and exported
  symbols found only `benchbox/core/tpcdi/etl/__init__.py`, the module itself,
  and the mixed transformation/SCD unit test. No active production, docs, TODO,
  pyproject, or script references were found.
- Open PR overlap check found only PR #626 touching JoinOrder TODO/test files;
  this slice touches only TPC-DI ETL internals, TPC-DI unit coverage, and this
  ledger fragment.
- Public-contract check: this internal helper module is not a documented
  top-level facade, deprecated/beta-public surface, benchmark registry entry,
  platform adapter, query callable, or experimental package.
- No moved content. This is deletion of unused maintained-Python helper logic,
  not relocation to data, generated Python, SQL, YAML, or docs.
- Post-edit `cloc --include-lang=Python benchbox/` reported 921 Python files
  and 197,796 maintained-Python code lines, a 1,690-line reduction from the
  slice baseline.

## Verification

Passed:

- Post-edit `make shrink-rollup` still reported the current merged baseline:
  18 ledger fragments, 7,521 credited lines, 4,479 remaining to the committed
  floor, and 11,479 remaining to the stretch target.
- Post-edit `cloc --include-lang=Python benchbox/` reported 921 Python files
  and 197,796 maintained-Python code lines.
- Exact reference sweep for the deleted module path, package export, classes,
  helper test filename, and transformation helper symbols across `benchbox`,
  `tests`, `docs`, `_project/TODO`, `pyproject.toml`, `scripts`, and `.github`
  found no active references.
- Filename sweep under `benchbox`, `tests`, `docs`, `_project/TODO`, `scripts`,
  and `.github` found no remaining `transformations.py` module or
  `test_etl_transformations_batch_scd.py` test path.
- Fingerprint check: `git diff --name-status origin/develop...HEAD` shows only
  this ledger, the internal
  TPC-DI ETL package export, the deleted internal transformation module, the
  removed transformation unit test path, and the new SCD processor unit test
  path. No benchmark registry, platform registry, query, generated-callable,
  or public-wrapper file changed.
- `uv run -- python -m compileall benchbox/core/tpcdi tests/unit/core/tpcdi`
  passed.
- `uv run -- ruff check benchbox/core/tpcdi/etl/__init__.py
  tests/unit/core/tpcdi/test_etl_scd_processor.py` passed.
- `uv run -- ruff format --check benchbox/core/tpcdi/etl/__init__.py
  tests/unit/core/tpcdi/test_etl_scd_processor.py` passed.
- `uv run -- python -m pytest -n 0
  tests/unit/core/tpcdi/test_etl_scd_processor.py -q` passed
  (`1 passed in 0.07s`).
- `uv run -- python -m pytest -m fast tests/unit/core/tpcdi -q` passed
  (`258 passed in 6.22s` after the test rename).
- `uv run -- python -m pytest -n 0 tests/unit/core/tpcdi
  tests/unit/tpcdi/test_phase3_etl_enhanced.py -q` passed
  (`334 passed in 4.45s` after the test rename).
- `uv run -- python -m pytest -n 0 tests/unit/test_wrapper_facades_fast.py -q`
  passed (`14 passed in 0.17s`).
- `uv run --project _project/scripts -- python _project/scripts/todo_cli.py
  validate` passed (`1,052 valid, 0 invalid`).
- `uv run --project _project/scripts -- python _project/scripts/todo_cli.py
  check-graph` passed (49 active items checked).
- `git diff --check` passed.
- Final amended-commit `make pr-preflight` passed: 22,811 passed, 5 skipped,
  47 warnings, and 4 subtests passed in 211.63s.

## Residual risk

The main residual risk is an external caller importing an unlisted internal
helper module directly. That risk is accepted under the conservative default
because the helper is not documented, not registry-backed, not a
backward-compatibility row, and not used by BenchBox runtime code.
