---
iteration: shrink-tpcdi-dead-data-cleaners
date: 2026-05-25
surface: internal TPC-DI data-cleaning helper module
branch: chore/shrink-tpcdi-dead-data-cleaners
pr:
raw_cloc_delta: -329
credited_reduction: 329
uncredited_relocation: 0
repair_only_delta: 0
generated_python_delta: 0
moved_content: none
decision_gate: conservative default; internal/test-only helper deletion, no public-contract or benchmark/platform surface removed
verification: cloc, reference sweep, ruff, compileall, TPC-DI unit tests, pr-preflight
---

## Thesis

Shrink iteration using the smaller-subsystem exception. The named subsystem is
`benchbox/core/tpcdi/tools/`, measured at 653 maintained-Python code lines before
editing. `benchbox/core/tpcdi/tools/data_cleaners.py` is 327 code lines, and its
only production-tree reference is the package-level re-export in
`benchbox/core/tpcdi/tools/__init__.py`. Exact search found no runtime imports,
no user documentation references, and no public-contract entry for the cleaner
module or its functions/classes. The production TPC-DI transformation path uses
`benchbox/core/tpcdi/etl/transformations.py`, not this helper module.

Measured reduction is 329 credited maintained-Python lines: delete the unused
cleaner module and remove the package re-export lines. Tests that only
characterize the dead helper module are deleted as uncredited test cleanup.

## Guardrail evidence

- Open develop PR overlap checked: PR #634 touches TPC compliance files only;
  PR #626 touches JoinOrder DataFrame plan-shape files only.
- Public contract check: `docs/reference/public-contracts.md` covers
  `benchbox.tpcdi.TPCDI` benchmark behavior and beta-public top-level wrapper
  facades, not `benchbox.core.tpcdi.tools.data_cleaners`.
- Exact reference check before editing:
  `rg -n "TPCDITableCleaners|BasicDataCleaner|CleaningResult|clean_whitespace|clean_null_values|clean_dates|clean_numeric_values|remove_duplicates|validate_required_fields|standardize_phone_numbers|standardize_email|create_cleaner|DataCleaningRule" benchbox tests docs README.md pyproject.toml --glob '!docs/_build/**'`.
  Production references are limited to `benchbox/core/tpcdi/tools/__init__.py`;
  remaining hits are the dedicated unit test and duplicate-check metadata.
- No moved content; this is deletion of unused maintained-Python helper logic,
  not relocation to data, generated Python, SQL, YAML, or docs.

## Verification

Completed post-edit measurement and tests:

- `cloc --include-lang=Python benchbox/`: 927 files, 202,556 code lines
  after editing, down from 202,885 at slice start.
- Exact post-edit reference check for deleted symbols/module: no matches.
- `uv run -- ruff check benchbox/core/tpcdi/tools/__init__.py`: passed.
- `uv run -- ruff format --check benchbox/core/tpcdi/tools/__init__.py`:
  passed.
- `uv run -- python -m compileall -q benchbox/core/tpcdi`: passed.
- `uv run -- python -m pytest tests/unit/core/tpcdi/test_etl_transformations_batch_scd.py tests/unit/core/tpcdi/test_tpcdi_etl_backend.py tests/unit/tpcdi/test_phase3_etl_enhanced.py -q -n 0`:
  58 passed.
- `uv run -- python -m pytest tests/unit/tpcdi tests/unit/core/tpcdi -q -n 0`:
  409 passed.

- `make pr-preflight > /tmp/shrink-tpcdi-dead-data-cleaners-preflight.log 2>&1`:
  passed; artifact hygiene passed; CI lint passed; fast tests reported
  22,895 passed, 5 skipped, 47 warnings, 4 subtests passed in 138.27s.

## Residual risk

Low but nonzero import-compatibility risk for external callers importing an
undocumented internal module. The contract map classifies public TPC-DI access
through the top-level benchmark API; this helper is not documented or used by
runtime code.

## Next target

Continue searching for internal TPC-DI helper/test-only surfaces or proven
platform/SQL-compat dedup after this slice lands.
