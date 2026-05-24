# BenchBox Core Python Shrink Ledger

Goal: reduce maintained Python under `benchbox/` to at most 79,632 `cloc` code
lines while preserving public behavior, safety, platform compatibility,
benchmark semantics, validation behavior, and result integrity.

Original campaign baseline: 234,211 Python code lines.

## 2026-05-23 - TPC-Havoc DataFrame Q1/Q6 single-table variant consolidation

- branch/worktree: `chore/shrink-core-python-gated-session` in `/Users/joe/Developer/BenchBox.pool-06`
- iteration type: shrink iteration using the smaller-subsystem exception
- subsystem: `benchbox/core/tpchavoc/dataframe_queries/q01.py` and `q06.py`
- starting `cloc --include-lang=Python benchbox/`: 213,488 code lines
- official 66% target: 79,632 code lines
- starting distance to target: 133,856 code lines
- subsystem baseline: `q01.py` + `q06.py` = 866 Python code lines
- final `cloc --include-lang=Python benchbox/`: 213,072 code lines
- final distance to target: 133,440 code lines
- expected credited reduction: at least 250 maintained Python lines and more than 10% of the Q1/Q6 subsystem
- final subsystem size: `q01.py` + `q06.py` = 450 Python code lines
- reduction path: replace hand-expanded variant implementations with explicit per-query builders that preserve the 10
  existing variant callables, descriptions, categories, and single-table DataFrame operation shapes
- moved-content classification: logic consolidation; no Python-to-data relocation; no generated Python; no SQL/query blobs
- decision-gate status: conservative default; no benchmark-intent reclassification, no new catalog/YAML migration, no new
  dynamic symbol injection, no new import-time I/O
- behavior/benchmark preservation plan: compare Q1/Q6 expression and pandas outputs against a pre-edit deterministic
  fingerprint, preserve callable names, run existing TPC-Havoc DataFrame tests, run focused import/reference checks, then
  run the repo preflight before PR open
- guardrail evidence before edit:
  - open PRs checked: #601 touches SSB DataFrame queries; #581 touches TPC-DS schema YAML, so this slice is non-overlapping
  - TPC-Havoc docs state Q1-Q15 variants intentionally vary filter timing, column pruning, intermediate DataFrames, join
    order, and aggregation formulation while preserving canonical output
  - Q1 and Q6 are single-table variants, avoiding benchmark-shape reclassification risk from complex joins/subqueries
- verification:
  - pre/post deterministic fingerprint for Q1/Q6 expression and pandas variants: PASS, byte-for-byte match
  - `uv run -- ruff format benchbox/core/tpchavoc/dataframe_queries/q01.py benchbox/core/tpchavoc/dataframe_queries/q06.py`
  - `uv run -- ruff check benchbox/core/tpchavoc/dataframe_queries/q01.py benchbox/core/tpchavoc/dataframe_queries/q06.py`
  - `uv run -- ty check benchbox/core/tpchavoc/dataframe_queries/q01.py benchbox/core/tpchavoc/dataframe_queries/q06.py`
  - `uv run -- python -m pytest tests/unit/core/tpchavoc/test_tpchavoc_dataframe_queries.py -q`
  - `uv run -- python -m pytest -m fast -q`: PASS, 22,736 passed, 5 skipped, 47 warnings, 4 subtests passed
  - focused registry/import assertion for 220 TPC-Havoc DataFrame query IDs and preserved Q1/Q6 callable identities
  - whole-tree reference search for Q1/Q6 DataFrame variant symbols and IDs
  - guardrail grep found no new import-time I/O, YAML/catalog loading, or dynamic symbol injection in touched Python files
  - `git diff --check -- benchbox/core/tpchavoc/dataframe_queries/q01.py benchbox/core/tpchavoc/dataframe_queries/q06.py _project/shrink-ledger.md`
- raw `cloc` delta: -416 maintained Python code lines in `benchbox/`
- credited reduction: 416 maintained Python code lines, provisional until PR merge
- uncredited relocation: 0
- repair-only delta: 0
- generated-Python delta: 0
- PR number: pending
- merge status: pending; campaign accounting not credited until merge
- residual risk: Q1/Q6 variant bodies now use closure builders rather than top-level `def` bodies; exported callable names,
  registry identities, descriptions, categories, and deterministic expression/pandas outputs are preserved by verification.
