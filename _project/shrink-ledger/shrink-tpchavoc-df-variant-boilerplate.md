---
iteration: shrink-tpchavoc-df-variant-boilerplate
date: 2026-05-25
surface: TPC-Havoc DataFrame variant boilerplate
branch: chore/shrink-tpchavoc-df-variant-boilerplate
pr:
raw_cloc_delta: 517
credited_reduction: 517
uncredited_relocation: 0
repair_only_delta: 0
generated_python_delta: 0
moved_content: logic
decision_gate: conservative default
verification:
  - make shrink-rollup
  - cloc --include-lang=Python benchbox/
  - cloc --include-lang=Python benchbox/core/tpchavoc/dataframe_queries
  - uv run -- python -m pytest tests/unit/core/tpchavoc/test_tpchavoc_dataframe_queries.py -q -n 0
  - manual TPC-Havoc registry/callable fingerprint before and after
  - rg reference check for TPC-Havoc DataFrame registry and implementation symbols
---

## Thesis

Shrink iteration. The slice targets `benchbox/core/tpchavoc/dataframe_queries/`,
currently 5,690 maintained-Python code lines. The reduction path is true
boilerplate deduplication:

- centralize repeated `DataFrameQuery` variant construction that is copied
  across the YAML-backed TPC-Havoc query modules, and
- replace exact duplicate variant implementation bodies, plus one reviewed
  step-for-step duplicate pandas body, with explicit named delegates to the
  identical current operation.

Most duplicated implementation candidates are exact AST matches after removing
docstrings, not heuristic similarity. The only non-AST replacement is
`q2_v8_pandas_impl`, which was reviewed against `q2_v7_pandas_impl` and has the
same table reads, filters, joins, aggregation, projection, sort, and limit. The
slice keeps every query id, description, category, implementation callable name,
qualname, module, expected row metadata, timeout, and skip-platform list pinned
by a pre/post fingerprint.

No benchmarks, platforms, deprecated/beta-public surfaces, generated Python, or
Python-to-data relocation are removed. YAML metadata already exists and remains
unchanged; this PR does not create a new catalog migration. The expected credited
reduction is above the 500-line shrink-iteration floor after combining the
registry-construction boilerplate and exact duplicate implementation bodies.

## Guardrail evidence

- Campaign rollup before editing: 1,324 merged credited lines, 10,676 remaining
  to the committed floor, 17,676 remaining to stretch.
- Raw maintained Python before editing: `cloc --include-lang=Python benchbox/`
  reports 930 files and 205,530 code lines.
- Target surface before editing: `cloc --include-lang=Python
  benchbox/core/tpchavoc/dataframe_queries` reports 26 files and 5,690 code
  lines.
- Open PR overlap: `gh pr list --state open --base develop --json ...` returned
  `[]`.
- Baseline fingerprint:
  `/tmp/shrink-tpchavoc-baseline-fingerprint.json`, SHA256
  `a343ca49b611465776b9458477f39c93b3111d7d8c2b475e6e29c39544a81f1e`.
- Exact duplicate scan:
  `/tmp/shrink-tpchavoc-duplicate-candidates.txt` found 15 large exact-body
  replacements with estimated source-span savings of 396 lines before the
  shared registry-builder reduction.
- Baseline focused tests:
  `uv run -- python -m pytest
  tests/unit/core/tpchavoc/test_tpchavoc_dataframe_queries.py -q -n 0` passed
  with 33 tests and 1 pre-existing warning.

## Verification

- `cloc --include-lang=Python benchbox/`: 930 files, 205,013 code lines;
  raw maintained-Python delta 517 lines.
- `cloc --include-lang=Python benchbox/core/tpchavoc/dataframe_queries`: 26
  files, 5,173 code lines; target-surface delta 517 lines.
- `uv run -- ruff check benchbox/core/tpchavoc/dataframe_queries`: passed.
- `uv run -- ruff format --check benchbox/core/tpchavoc/dataframe_queries`:
  passed; 26 files already formatted.
- `uv run -- python -m pytest
  tests/unit/core/tpchavoc/test_tpchavoc_dataframe_queries.py -q -n 0`: 33
  passed, 1 pre-existing warning.
- Post-edit fingerprint:
  `/tmp/shrink-tpchavoc-post-fingerprint.json`, SHA256
  `a343ca49b611465776b9458477f39c93b3111d7d8c2b475e6e29c39544a81f1e`,
  byte-identical to the baseline fingerprint.
- Whole-tree reference check:
  `/tmp/shrink-tpchavoc-reference-check.log` captured 546 references across
  `benchbox`, `tests`, and `docs`; `_project` had no additional matches.
- `make pr-preflight`: passed; log retained at
  `/tmp/shrink-tpchavoc-pr-preflight.log` with 32,907 lines. Fast test summary:
  22,775 passed, 5 skipped, 47 warnings, 4 subtests passed.

## Residual risk

The main risk is benchmark-shape drift for TPC-Havoc variants. This slice limits
implementation-body replacement to exact duplicate bodies and keeps callable
identity metadata pinned. Delegate wrappers add one Python call for duplicated
variants; the measured DataFrame operation is unchanged because the delegated
implementation is byte-for-byte equivalent to the current variant body.

## Next target

After this PR merges, re-run `make shrink-rollup` and continue through another
explicit duplicate-maintenance surface that does not overlap open shrink PRs.
