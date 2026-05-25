---
iteration: 20
date: 2026-05-25
surface: internal TPC-DI file-parser helper package
branch: chore/shrink-dead-tpcdi-file-parsers
pr:
raw_cloc_delta: 324
credited_reduction: 324
uncredited_relocation: 0
repair_only_delta: 0
generated_python_delta: 0
moved_content: none
decision_gate: conservative default; internal/test-only helper deletion, no public-contract or benchmark/platform surface removed
verification: passed
---

## Thesis

Shrink iteration using the smaller-subsystem exception. The remaining
`benchbox/core/tpcdi/tools/` package is 324 maintained-Python code lines:
`file_parsers.py` plus a package `__init__.py` that only re-exports parser
classes from that module. Exact reference sweeps found no runtime imports, no
user documentation references, and no public-contract entry for the package,
module, parser classes, or convenience functions. The only active references
are the package re-export, a dedicated characterization test, and one
pandas-upgrade TODO that still names this dead helper as a future audit target.

Measured credited reduction is 324 maintained-Python lines: delete the unused
file-parser helper module and its package re-export. The dedicated unit test
and stale TODO path references are uncredited cleanup.

## Guardrail evidence

- `make shrink-rollup` at `origin/develop` reported 19 merged ledger fragments,
  9,211 credited lines, 2,789 remaining to the committed floor, and 9,789
  remaining to the stretch target.
- `cloc --include-lang=Python benchbox/` reported 921 Python files and 197,796
  maintained-Python code lines.
- `cloc --include-lang=Python benchbox/core/tpcdi/tools/file_parsers.py
  benchbox/core/tpcdi/tools/__init__.py` reported 324 maintained-Python code
  lines in the production helper surface.
- Exact pre-edit reference sweep for the module path, package path, exported
  parser classes, `ParseResult`, `MultiFormatParser`, and parser convenience
  functions across `benchbox`, `tests`, `docs`, `_project/TODO`,
  `pyproject.toml`, `scripts`, and `.github` found production references only
  in `benchbox/core/tpcdi/tools/__init__.py`. Remaining active references were
  the dedicated unit test and a stale pandas-upgrade TODO path note.
- Public-contract check: this internal helper package is not a documented
  top-level facade, deprecated/beta-public surface, benchmark registry entry,
  platform adapter, query callable, or experimental package.
- No moved content. This is deletion of unused maintained-Python helper logic,
  not relocation to data, generated Python, SQL, YAML, or docs.

## Verification

Passed:

- Post-edit `make shrink-rollup` still reported the current merged baseline:
  19 ledger fragments, 9,211 credited lines, 2,789 remaining to the committed
  floor, and 9,789 remaining to the stretch target.
- Post-edit `cloc --include-lang=Python benchbox/` reported 919 Python files
  and 197,472 maintained-Python code lines, a 324-line reduction from the
  slice baseline.
- Exact reference sweep for the deleted module path, package path, exported
  parser classes, `ParseResult`, `MultiFormatParser`, parser convenience
  functions, and `test_file_parsers_simplified` across `benchbox`, `tests`,
  `docs`, `_project/TODO`, `pyproject.toml`, `scripts`, and `.github` found no
  remaining active references.
- Fingerprint check: `git diff --name-status` shows only this ledger fragment,
  the pandas-upgrade TODO cleanup, the deleted internal TPC-DI tools package,
  and the removed dedicated parser characterization test. No benchmark
  registry, platform registry, query, generated-callable, public-wrapper, or
  experimental file changed.
- `uv run -- python -m compileall -q benchbox/core/tpcdi tests/unit/tpcdi
  tests/unit/core/tpcdi` passed.
- `uv run -- ruff check benchbox/core/tpcdi tests/unit/tpcdi
  tests/unit/core/tpcdi` passed.
- `uv run -- ruff format --check benchbox/core/tpcdi tests/unit/tpcdi
  tests/unit/core/tpcdi` passed.
- `uv run --project _project/scripts -- python _project/scripts/todo_cli.py
  validate` passed (`1,052 valid, 0 invalid`).
- `uv run --project _project/scripts -- python _project/scripts/todo_cli.py
  check-graph` passed (49 active items checked).
- `git diff --check` passed.
- `uv run -- python -m pytest -n 0 tests/unit/tpcdi
  tests/unit/core/tpcdi -q` passed (`363 passed in 5.25s`).
- `uv run -- python -m pytest -n 0 tests/unit/test_wrapper_facades_fast.py
  -q` passed (`14 passed in 0.17s`).
- Self-review with the code review checklist found no correctness, contract,
  security, performance, or readability findings requiring changes.
- `make pr-preflight > /tmp/shrink-dead-tpcdi-file-parsers-pr-preflight.log
  2>&1` passed: 22,783 passed, 5 skipped, 47 warnings, and 4 subtests passed
  in 108.62s.

## Residual risk

The main residual risk is an external caller importing an undocumented internal
helper package directly. That risk is accepted under the conservative default
because the helper is not documented, not registry-backed, not a
backward-compatibility row, and not used by BenchBox runtime code.
