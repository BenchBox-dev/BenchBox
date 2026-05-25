---
iteration: 21
date: 2026-05-25
surface: TPC-Havoc exact duplicate DataFrame variant bodies
branch: chore/shrink-tpchavoc-exact-duplicates
pr:
raw_cloc_delta: 301
credited_reduction: 301
uncredited_relocation: 0
repair_only_delta: 0
generated_python_delta: 0
moved_content: logic
decision_gate: conservative default; exact duplicate implementation bodies only, query registry/callable fingerprint pinned
verification: targeted checks and pr-preflight passed
---

## Thesis

Shrink iteration for `benchbox/core/tpchavoc/dataframe_queries/`, currently
5,173 maintained-Python code lines. The reduction path is true deduplication:
replace exact duplicate implementation bodies within the same TPC-Havoc
DataFrame variant package with explicit named delegates to the retained
implementation body.

The duplicate scan found 334 duplicated lines across ten exact duplicate groups
inside TPC-Havoc query modules. After those internal duplicates were replaced,
a follow-up duplicate scan found three remaining TPC-Havoc variant bodies that
were exact matches for their canonical TPC-H base implementations. This slice
only targets duplicate copies whose source bodies are exact matches under
`make duplicate-check-json`:

- `q9_v7_pandas_impl` and `q9_v8_pandas_impl` delegate to
  `q9_v2_pandas_impl`.
- `q15_v5_pandas_impl` and `q15_v7_pandas_impl` delegate to
  `q15_v2_pandas_impl`.
- `q11_v9_pandas_impl` and `q11_v10_pandas_impl` delegate to
  `q11_v4_pandas_impl`.
- `q11_v7_pandas_impl` delegates to `q11_v2_pandas_impl`.
- `q7_v7_pandas_impl` delegates to `q7_v2_pandas_impl`.
- `q5_v7_pandas_impl` delegates to `q5_v5_pandas_impl`.
- `q10_v5_pandas_impl` delegates to `q10_v4_pandas_impl`.
- `q13_v10_expression_impl` delegates to `q13_v7_expression_impl`.
- `q13_v5_expression_impl` delegates to `q13_v2_expression_impl`.
- `q14_v4_pandas_impl` delegates to `q14_v2_pandas_impl`.
- `q9_v7_expression_impl` delegates to `_q9_expr_base`.
- `q11_v10_expression_impl` delegates to `_q11_expr_base`.
- `q13_v5_pandas_impl` delegates to `_q13_pandas_base`.

The helper used for delegation preserves callable `__name__`, `__qualname__`,
and `__module__` so query identity fingerprints stay stable. No benchmark,
platform, deprecated/beta-public surface, generated Python, or Python-to-data
relocation is removed.

## Guardrail evidence

- `make shrink-rollup` at `origin/develop` reported 19 merged ledger fragments,
  9,211 credited lines, 2,789 remaining to the committed floor, and 9,789
  remaining to the stretch target. PR #642 is open and not counted.
- `cloc --include-lang=Python benchbox/` reported 921 Python files and 197,796
  maintained-Python code lines.
- `cloc --include-lang=Python benchbox/core/tpchavoc/dataframe_queries`
  reported 26 files and 5,173 maintained-Python code lines in the target
  surface.
- Pre-edit query/callable fingerprint:
  `/tmp/shrink-tpchavoc-exactdup-baseline-fingerprint.json`, SHA256
  `ca10a95eefd81640c0c393f3e3e06119fc814f3c17aa41a01eb9f02d48d064ec`.
- `make duplicate-check-json` captured at
  `/tmp/shrink-tpchavoc-exactdup-duplicate-check-json.log` found 334 duplicate
  lines in exact duplicate TPC-Havoc-internal implementation groups.
- Open PR overlap check found #642 touching TPC-DI files only, #641 touching
  ClickBench orientation docs/code, and #626 touching JoinOrder files only.
- No moved content to data, generated Python, SQL, YAML, or docs. This is
  source-level deduplication with callable identity pinned.

## Verification

- Post-edit `cloc --include-lang=Python benchbox/` reported 921 Python files
  and 197,495 maintained-Python code lines, a 301-line reduction from the
  197,796-line baseline.
- Post-edit `cloc --include-lang=Python benchbox/core/tpchavoc/dataframe_queries`
  reported 26 files and 4,872 maintained-Python code lines, a 301-line
  reduction from the 5,173-line target-surface baseline.
- Post-edit query/callable fingerprint:
  `/tmp/shrink-tpchavoc-exactdup-post-fingerprint.json`, SHA256
  `ca10a95eefd81640c0c393f3e3e06119fc814f3c17aa41a01eb9f02d48d064ec`.
  `cmp -s` confirmed it is byte-identical to the pre-edit fingerprint.
- Final `make duplicate-check-json` captured at
  `/tmp/shrink-tpchavoc-exactdup-final-duplicate-check-json.log`; targeted
  reference search found no remaining duplicate groups involving the replaced
  TPC-Havoc symbols.
- Whole-tree reference sweep for replaced symbols found 44 hits, all in YAML
  registry bindings, delegate assignments, the retained helper, or local
  delegation calls.
- `uv run -- python -m compileall -q benchbox/core/tpchavoc/dataframe_queries tests/unit/core/tpchavoc`
  passed.
- `uv run -- ruff check benchbox/core/tpchavoc/dataframe_queries tests/unit/core/tpchavoc/test_tpchavoc_dataframe_queries.py`
  passed.
- `uv run -- ruff format --check benchbox/core/tpchavoc/dataframe_queries tests/unit/core/tpchavoc/test_tpchavoc_dataframe_queries.py`
  passed.
- `uv run -- python -m pytest -n 0 tests/unit/core/tpchavoc/test_tpchavoc_dataframe_queries.py -q`
  passed: 33 passed, 1 existing deprecation warning.
- `git diff --check` passed.
- `make pr-preflight` passed with output at
  `/tmp/shrink-tpchavoc-exactdup-pr-preflight.log`: 22,811 passed, 5 skipped,
  47 warnings, 4 subtests passed in 113.51s.

## Residual risk

The main risk is TPC-Havoc query-shape drift from replacing duplicate bodies
with delegates. This slice constrains replacements to exact duplicate bodies,
preserves callable identity metadata, and requires the full TPC-Havoc
DataFrame registry fingerprint to remain byte-identical after editing.
