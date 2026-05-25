---
iteration: 17
date: 2026-05-25
surface: internal TPC-DI helper-only validation and SQL generator exports
branch: chore/shrink-dead-tpcdi-helper-exports
pr: 639
raw_cloc_delta: 754
credited_reduction: 754
uncredited_relocation: 0
repair_only_delta: 0
generated_python_delta: 0
moved_content: none
decision_gate: conservative default; internal/test-only helper deletion, no public-contract or benchmark/platform surface removed
verification: cloc, reference sweep, compileall, ruff, TPC-DI tests, TODO validation, duplicate-check-json, pr-preflight
---

## Thesis

Shrink iteration for two internal TPC-DI helper exports that are maintained only
by package-level re-exports and dedicated characterization tests:

- `benchbox/core/tpcdi/etl/validation.py`: 471 maintained-Python code lines.
- `benchbox/core/tpcdi/generator/sql.py`: 279 maintained-Python code lines.

The runtime TPC-DI benchmark path imports `TPCDIDataGenerator`, ETL backend,
pipeline, transformation, and validation-query modules; it does not import
`BasicDataValidator`, `DataQualityValidator`, or `TPCDISQLGenerator`. Exact
reference sweeps found no active production imports outside
`benchbox/core/tpcdi/etl/__init__.py` and
`benchbox/core/tpcdi/generator/__init__.py`. The remaining references are
dedicated unit tests, duplicate-check ignore rules, and one active pandas-upgrade
TODO path note.

Measured credited reduction is 754 maintained-Python lines: delete the two dead
helper modules and remove their package-export lines. Test deletions and
project metadata cleanup are uncredited.

## Guardrail evidence

- `make shrink-rollup` at `origin/develop` reported 16 merged ledger fragments,
  6,767 credited lines, 5,233 remaining to the committed floor, and 12,233
  remaining to the stretch target.
- `cloc --include-lang=Python benchbox/` reported 924 Python files and 200,240
  maintained-Python code lines.
- Open PR overlap check found PR #638 touching only the codegen/runtime ADR
  docs and shrink goal ledger, and PR #626 touching only JoinOrder plan-shape
  files. This slice touches TPC-DI helper internals, TPC-DI tests, duplicate
  metadata, and the pandas-upgrade TODO reference.
- Public contract check: `docs/reference/public-contracts.md` classifies
  top-level wrapper facades such as `benchbox.tpcdi.TPCDI` as beta-public; it
  does not list `benchbox.core.tpcdi.etl.validation`,
  `benchbox.core.tpcdi.generator.sql`, `DataQualityValidator`, or
  `TPCDISQLGenerator`.
- User docs reference TPC-DI ETL validation through top-level `TPCDI` methods
  and validation queries. They do not import either deleted helper module or
  class.
- No moved content. This is deletion of unused maintained-Python helper logic,
  not relocation to data, generated Python, SQL, YAML, or docs.
- Post-edit `cloc --include-lang=Python benchbox/` reported 922 Python files
  and 199,486 maintained-Python code lines, a 754-line reduction from the
  slice baseline.

## Verification

Passed:

- Exact reference sweeps for deleted module paths, classes, functions, and test
  filenames across `benchbox`, `tests`, `docs`, `_project/TODO`,
  `pyproject.toml`, `scripts`, and `.github` found no active references.
- Deleted-path sweep for `benchbox/core/tpcdi/etl/validation.py`,
  `benchbox/core/tpcdi/generator/sql.py`, and their dedicated test filenames
  found no active references.
- `uv run -- python -m compileall benchbox/core/tpcdi tests/unit/core/tpcdi`
  passed.
- `uv run -- ruff check benchbox/core/tpcdi/etl/__init__.py
  benchbox/core/tpcdi/generator/__init__.py` passed.
- `uv run -- ruff format --check benchbox/core/tpcdi/etl/__init__.py
  benchbox/core/tpcdi/generator/__init__.py` passed.
- `uv run -- python -m pytest -m fast tests/unit/core/tpcdi -q` passed
  (`258 passed in 6.62s`).
- `uv run -- python -m pytest -n 0 tests/unit/core/tpcdi -q` passed
  (`288 passed in 6.45s`).
- `uv run -- python -m pytest -n 0 tests/unit/tpcdi/test_phase3_etl_enhanced.py
  tests/unit/test_wrapper_facades_fast.py -q` passed (`61 passed in 2.27s`).
- `uv run --project _project/scripts -- python _project/scripts/todo_cli.py
  validate` passed (`1,052 valid, 0 invalid`).
- `uv run --project _project/scripts -- python _project/scripts/todo_cli.py
  check-graph` passed (50 active items checked).
- `make duplicate-check-json` completed; summary after deletion was 273 groups,
  356 duplicate instances, and 6,120 duplicated lines.
- `git diff --check` passed.
- `make pr-preflight` passed: 22,811 passed, 5 skipped, 47 warnings, and
  4 subtests passed in 173.28s.

## Residual risk

The main residual risk is an external caller importing internal helper modules
directly despite no public-contract or user-doc promise. The public TPC-DI
facade and active benchmark lifecycle remain unchanged.

## Next target

After this slice, reassess the TPC-DS DataFrame generated-query surface only
after the codegen/runtime ADR repair in PR #638 lands, or choose another
non-overlapping internal dead-code surface if it remains blocked.
