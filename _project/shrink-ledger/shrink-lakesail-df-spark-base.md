---
iteration: shrink-lakesail-df-spark-base
date: 2026-05-24
surface: LakeSail DataFrame adapter Spark API dedup
branch: chore/shrink-lakesail-df-spark-base
pr:
raw_cloc_delta: 254
credited_reduction: 254
uncredited_relocation: 0
repair_only_delta: 0
generated_python_delta: 0
moved_content: logic
decision_gate: conservative default
verification:
  - make shrink-rollup
  - cloc --include-lang=Python benchbox/
  - cloc --by-file --include-lang=Python benchbox/platforms/dataframe/pyspark_df.py benchbox/platforms/dataframe/lakesail_df.py
  - make duplicate-check-json
  - uv run -- python -m pytest tests/unit/platforms/dataframe/test_lakesail_df.py tests/unit/platforms/dataframe/test_pyspark_df_fast_coverage.py -q -n 0
  - uv run -- python -m pytest tests/unit/platforms/dataframe/test_lakesail_df.py tests/unit/platforms/dataframe/test_pyspark_df_fast_coverage.py tests/unit/platforms/dataframe/test_package_init.py tests/unit/platforms/test_platform_adapter_init_and_loading.py -q -n 0
  - uv run -- python scripts/check_complexity.py --source-root benchbox/platforms/dataframe --no-fail --top 20
  - uv run ty check
  - uv run -- python - <<'PY' ... # manual LakeSail/PySpark adapter fingerprint
  - make pr-preflight
---

## Thesis

Shrink iteration under the smaller-subsystem exception. The subsystem is the
Spark-expression DataFrame adapter pair:
`benchbox/platforms/dataframe/pyspark_df.py` and
`benchbox/platforms/dataframe/lakesail_df.py`, measured at 775 Python code
lines before edits. LakeSail explicitly documents that it uses the standard
PySpark client through Spark Connect and is nearly identical to
`PySparkDataFrameAdapter`.

The reduction path is true deduplication: keep `LakeSailDataFrameAdapter` as an
explicit, grep-findable public class, but inherit the shared PySpark-compatible
DataFrame expression API instead of maintaining a second copy of the same
methods. LakeSail-specific behavior remains local: constructor defaults, Spark
Connect session creation, `platform_name`, `close`, platform info, and tuning
summary fields.

Credited reduction is 254 maintained-Python lines and 32.8% of the subsystem.
There is no benchmark/platform deletion, deprecated/beta-public surface
removal, generated Python, or Python-to-data relocation.

## Guardrail Evidence

- Iteration type: shrink iteration, smaller-subsystem exception.
- Subsystem: `benchbox/platforms/dataframe/pyspark_df.py` plus
  `benchbox/platforms/dataframe/lakesail_df.py`; baseline 775 Python cloc,
  below the 1,000-line smaller-subsystem cap.
- Minimum gate: remove at least 250 credited Python lines and at least 10% of
  the subsystem. Final measurement is 254 lines, 32.8% of the subsystem.
- Moved-content classification: logic consolidation only.
- Decision-gate status: conservative default. The public adapter class remains
  explicit; no dynamic symbol injection, generated implementation, or
  permissive unresolved policy gate is used.
- Open PR overlap: after PR #618 merged, `gh pr list --state open --base
  develop --json number,title,headRefName,baseRefName,state,mergeStateStatus
  --limit 30` returned `[]`.
- Baseline duplicate evidence: `make duplicate-check-json` reports duplicated
  Spark DataFrame adapter methods including `union_all`, `read_csv`,
  `_build_window_spec`, `_build_aggregate_window_spec`, `scalar`,
  `get_platform_info`, `to_polars`, `window_count`, and `explain`.
- Baseline behavior evidence: `uv run -- python -m pytest
  tests/unit/platforms/dataframe/test_lakesail_df.py
  tests/unit/platforms/dataframe/test_pyspark_df_fast_coverage.py -q -n 0`
  reported 53 passed before edits.
- Baseline callable fingerprint captured LakeSail constructor signature,
  method signatures, platform info, tuning summary, and explicit adapter
  configuration without opening a Spark Connect session.

## Verification

- `make shrink-rollup` before edits: cumulative merged credited reduction 252;
  remaining floor 11,748, stretch 18,748.
- `make shrink-rollup` after PR #618 merged before this PR opened: cumulative
  merged credited reduction 502; remaining floor 11,498, stretch 18,498.
- `cloc --include-lang=Python benchbox/` before edits: 206,602 Python code
  lines.
- `cloc --by-file --include-lang=Python
  benchbox/platforms/dataframe/pyspark_df.py
  benchbox/platforms/dataframe/lakesail_df.py` before edits: 390 code lines in
  `pyspark_df.py`, 385 in `lakesail_df.py`, 775 total.
- `cloc --include-lang=Python benchbox/` after rebasing onto `origin/develop`
  with PR #618 merged: 206,098 Python code lines. The slice-local delta remains
  254 credited lines from the Spark DataFrame adapter subsystem.
- `cloc --by-file --include-lang=Python
  benchbox/platforms/dataframe/pyspark_df.py
  benchbox/platforms/dataframe/lakesail_df.py` after edits: 390 code lines in
  `pyspark_df.py`, 131 in `lakesail_df.py`, 521 total.
- `make duplicate-check-json`: repo duplicate summary moved from 305 groups /
  413 instances / 7,699 duplicated lines to 298 groups / 405 instances / 7,559
  duplicated lines; LakeSail-specific duplicate groups for `read_csv`,
  `_build_window_spec`, `_build_aggregate_window_spec`, `scalar`,
  `to_polars`, `window_count`, and `explain` no longer appear.
- `uv run -- ruff check benchbox/platforms/dataframe/lakesail_df.py
  tests/unit/platforms/dataframe/test_lakesail_df.py
  tests/unit/platforms/dataframe/test_pyspark_df_fast_coverage.py`: passed.
- `uv run -- python -m pytest tests/unit/platforms/dataframe/test_lakesail_df.py
  tests/unit/platforms/dataframe/test_pyspark_df_fast_coverage.py -q -n 0`: 53
  passed.
- `uv run -- python -m pytest tests/unit/platforms/dataframe/test_lakesail_df.py
  tests/unit/platforms/dataframe/test_pyspark_df_fast_coverage.py
  tests/unit/platforms/dataframe/test_package_init.py
  tests/unit/platforms/test_platform_adapter_init_and_loading.py -q -n 0`: 167
  passed.
- `uv run -- python scripts/check_complexity.py --source-root
  benchbox/platforms/dataframe --no-fail --top 20`: passed; module-family mean
  remains 3.8, worst CC remains 12 in pre-existing `unified_frame.py` helpers.
- `uv run ty check`: exited 0 with the existing repository warning set.
- Manual pre/post LakeSail fingerprint matched after normalizing PySpark and
  LakeSail type-alias names to their shared Spark types and excluding the
  expected working-directory value. It covered constructor signature, method
  parameter signatures, `platform_name`, constructor-stored fields, platform
  info, tuning summary, PySpark availability, and PySpark version.
- `make pr-preflight`: passed; broad fast suite reported 22,775 passed, 5
  skipped, 47 warnings, and 4 subtests passed.

## Residual Risk

The primary risk is that LakeSail and PySpark look API-identical but differ in
session lifecycle and reporting semantics. The slice keeps those LakeSail
behaviors overridden locally and fingerprints public signatures, platform
metadata, tuning metadata, and constructor-stored fields before and after the
change. Return annotations on inherited shared DataFrame methods now reference
the PySpark aliases rather than LakeSail aliases, but those aliases resolve to
the same Spark `DataFrame` and `Column` types; LakeSail-specific public aliases
remain exported.

## Next Target

If this lands with credit, continue through another explicit duplicate
maintenance surface that does not overlap open shrink PRs.
