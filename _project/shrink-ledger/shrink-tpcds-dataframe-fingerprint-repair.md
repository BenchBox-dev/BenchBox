---
iteration: shrink-tpcds-dataframe-fingerprint-repair
date: 2026-05-24
surface: TPC-DS DataFrame query guardrail repair
branch: chore/shrink-tpcds-dataframe-fingerprint-repair
pr:
raw_cloc_delta: 0
credited_reduction: 0
uncredited_relocation: 0
repair_only_delta: 0
generated_python_delta: 0
moved_content: none
decision_gate: conservative default
verification:
  - make shrink-rollup
  - cloc --include-lang=Python benchbox/
  - cloc --include-lang=Python benchbox/core/tpcds/dataframe_queries/queries.py
  - uv run -- ruff check tests/unit/core/tpcds/test_tpcds_dataframe_queries.py
  - uv run -- ruff format --check tests/unit/core/tpcds/test_tpcds_dataframe_queries.py
  - uv run -- python -m pytest tests/unit/core/tpcds/test_tpcds_dataframe_queries.py -q -n 0
  - make pr-preflight
---

## Thesis

Guardrail repair iteration. The large candidate surface is
`benchbox/core/tpcds/dataframe_queries/queries.py`, currently 7037
maintained-Python code lines. It is a plausible future shrink target because it
already uses YAML-backed helper specs and generated implementations, but the
active shrink control document forbids approving generated-callable
consolidation without explicit fingerprints for registry IDs, callable names,
categories, and callable identity.

This repair adds focused characterization coverage for the current TPC-DS
DataFrame query surface before any consolidation. It pins:

- the complete registered query-id set (`Q1` through `Q99`),
- expression/pandas implementation names and qualnames,
- category invariants that every query remains tagged as TPC-DS, and
- the module-level generated callable attributes that current registration
  resolves through `globals()`.

Expected credited reduction is 0. The payoff is a safe future attempt to remove
dynamic/global callable registration and then consolidate the high-line query
surface with evidence instead of assertion.

## Guardrail evidence

- Iteration type: guardrail repair.
- Future shrink surface: `benchbox/core/tpcds/dataframe_queries/queries.py`;
  `cloc --include-lang=Python` reports 7037 code lines before this repair.
- Campaign baseline: `make shrink-rollup` reports 0 cumulative merged credited
  reduction, 12000 remaining to the committed floor, 19000 remaining to stretch,
  and one merged ledger fragment.
- Raw tree sanity check: `cloc --include-lang=Python benchbox/` reports 929
  Python files and 206854 code lines before editing.
- Open PR overlap: `gh pr list --base develop --state open --json ...` returns
  `[]`; no open develop PR overlaps this test/ledger surface.
- Decision-gate status: conservative default. This slice does not approve any
  objective-function, import-loading, generated-callable, codegen/runtime-source,
  query-surface, SQL, or catalog/YAML migration gate.
- Moved-content classification: none. The repair adds tests only and does not
  move Python, SQL, query metadata, or benchmark data.
- Behavior preservation plan: no runtime code changes; fingerprint tests fail if
  query IDs, implementation names, qualnames, categories, or generated module
  attributes drift in later shrink attempts.

## Verification

- `make shrink-rollup`:
  - cumulative merged credited reduction: 0
  - remaining floor: 12000
  - raw cloc delta sanity check: 0
- `cloc --include-lang=Python benchbox/`: 929 files, 206854 code lines.
- `cloc --include-lang=Python benchbox/core/tpcds/dataframe_queries/queries.py`: 7037 code lines.
- `uv run -- ruff format --check tests/unit/core/tpcds/test_tpcds_dataframe_queries.py`: pass.
- `uv run -- ruff check tests/unit/core/tpcds/test_tpcds_dataframe_queries.py`: pass.
- `uv run -- python -m pytest tests/unit/core/tpcds/test_tpcds_dataframe_queries.py -q -n 0`: 34 passed.
- Whole-tree reference check:
  `rg -n "TPCDS_DATAFRAME_QUERIES|q[0-9]+_(expression|pandas)_impl" benchbox tests docs _project --glob '*.py' --glob '*.md'`
  captured 4 current references in `/tmp/shrink-tpcds-fingerprint-reference-check.log`.
- `make pr-preflight`: pass; `ci-lint` passed, fast lane reported 22775 passed,
  5 skipped, 47 warnings, and 4 subtests passed.

## Residual risk

This repair does not reduce maintained Python lines. It is intentionally scoped
to evidence capture so the next TPC-DS DataFrame shrink can change generated
callable registration with a concrete no-drift guardrail.

## Next target

After this repair merges, return to `benchbox/core/tpcds/dataframe_queries/queries.py`
and attempt the smallest runtime change that removes dynamic `globals()` writes
or import-time spec loading while preserving the new fingerprints.
