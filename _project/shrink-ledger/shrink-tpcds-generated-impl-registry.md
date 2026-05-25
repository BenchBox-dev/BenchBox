---
iteration: shrink-tpcds-generated-impl-registry
date: 2026-05-25
surface: TPC-DS DataFrame generated implementation registry
branch: chore/shrink-tpcds-generated-impl-registry
pr:
raw_cloc_delta: -12
credited_reduction: 0
uncredited_relocation: 0
repair_only_delta: -12
generated_python_delta: 0
moved_content: none
decision_gate: conservative default
verification:
  - make shrink-rollup
  - cloc --include-lang=Python --by-file benchbox/core/tpcds/dataframe_queries/queries.py tests/unit/core/test_dataframe_generated_impl_registry.py
  - TPC-DS registry/callable fingerprint diff
  - uv run -- ruff check benchbox/core/tpcds/dataframe_queries/queries.py tests/unit/core/test_dataframe_generated_impl_registry.py
  - uv run -- ruff format --check benchbox/core/tpcds/dataframe_queries/queries.py tests/unit/core/test_dataframe_generated_impl_registry.py
  - uv run -- python -m compileall -q benchbox/core/tpcds/dataframe_queries
  - uv run -- python -m pytest tests/unit/core/tpcds/test_tpcds_dataframe_queries.py tests/unit/core/test_dataframe_generated_impl_registry.py -q -n 0
  - uv run -- python _project/scripts/reference_usage_audit.py --summary
  - make pr-preflight
---

## Thesis

Guardrail repair iteration. The TPC-DS DataFrame query module is a large future
shrink surface at 7037 maintained-Python code lines, and the previous
fingerprint repair established the callable identity contract required before
changing generated implementations. The next blocker is that generated TPC-DS
query implementations are still injected into module globals at import time.

This slice replaces the dynamic `globals()[name] = impl` writes with an explicit
generated-implementation registry plus PEP 562 `__getattr__` lookup. It keeps the
current public behavior that named generated callables are resolvable from the
module, keeps the registry/callable fingerprint stable, and makes the generated
surface match the safer pattern already used by Read Primitives and JoinOrder.

Expected credited reduction is 0. This is a repair-only slice that unlocks a
later credited TPC-DS consolidation attempt without self-approving a
generated-callable shrink gate.

## Guardrail evidence

- Iteration type: guardrail repair.
- Campaign baseline: `make shrink-rollup` reports 2379 cumulative merged
  credited reduction, 9621 remaining to the committed floor, and 16621 remaining
  to stretch.
- Open PR overlap: `gh pr list --base develop --state open --json ...` found
  PR #626 touching JoinOrder/TODO files only; no overlap with this TPC-DS
  generated-registry surface.
- Target file baseline:
  `cloc --include-lang=Python --by-file benchbox/core/tpcds/dataframe_queries/queries.py tests/unit/core/test_dataframe_generated_impl_registry.py`
  reports 7061 total Python code lines, including 7037 in
  `benchbox/core/tpcds/dataframe_queries/queries.py`.
- Post-edit target files report 7082 total Python code lines, including 7049 in
  `benchbox/core/tpcds/dataframe_queries/queries.py`. The maintained runtime
  source delta is +12 code lines, ledgered as `raw_cloc_delta: -12`.
- Post-edit raw maintained Python:
  `cloc --include-lang=Python benchbox/` reports 931 files and 204628 code
  lines.
- Pre-edit fingerprint:
  `/tmp/shrink-tpcds-generated-registry-fingerprint-pre.txt` captures 99
  registered TPC-DS DataFrame queries with categories, expression/pandas
  callable names, qualnames, and module attribute identity checks.
- Post-edit fingerprint:
  `/tmp/shrink-tpcds-generated-registry-fingerprint-post.txt` has the same 99
  rows and `diff -u` against the pre-edit fingerprint is empty.
- Moved-content classification: none. This slice does not move Python, SQL,
  YAML, metadata, or benchmark data.
- Decision-gate status: conservative default. This slice does not approve
  deleting benchmarks/platforms, changing query semantics, changing the TPC-DS
  spec-loading model, or consolidating generated query logic.

## Verification

- `uv run -- ruff check benchbox/core/tpcds/dataframe_queries/queries.py tests/unit/core/test_dataframe_generated_impl_registry.py` passed.
- `uv run -- ruff format --check benchbox/core/tpcds/dataframe_queries/queries.py tests/unit/core/test_dataframe_generated_impl_registry.py` passed.
- `uv run -- python -m compileall -q benchbox/core/tpcds/dataframe_queries` passed.
- `uv run -- python -m pytest tests/unit/core/tpcds/test_tpcds_dataframe_queries.py tests/unit/core/test_dataframe_generated_impl_registry.py -q -n 0` passed, 39 tests.
- `uv run -- python _project/scripts/reference_usage_audit.py --summary` passed
  with 78 hits and 0 parse errors.
- `git diff --check` passed.
- Self-review finding fixed before preflight: `_impl_for` now returns the typed
  `QueryImpl` protocol instead of `Any`.
- `make pr-preflight` passed: `ci-lint` passed, and the fast suite reported
  23025 passed, 5 skipped, 47 warnings, and 4 subtests passed.

## Residual risk

This repair does not reduce maintained Python lines. It only removes the
dynamic module-global registration pattern that blocks safer future
consolidation of the TPC-DS query surface.
