---
iteration: shrink-platform-hook-boilerplate
date: 2026-05-24
surface: platform config/from_config/tuning hook boilerplate
branch: chore/shrink-platform-hook-boilerplate
pr:
raw_cloc_delta: 538
credited_reduction: 538
uncredited_relocation: 0
repair_only_delta: 0
generated_python_delta: 0
moved_content: logic
decision_gate: conservative default
verification:
  - cloc --include-lang=Python benchbox/ (205013 -> 204475)
  - uv run -- ruff check <touched source and tests>
  - uv run -- python -m compileall -q benchbox/platforms
  - uv run -- python -m pytest tests/unit/platforms/base/test_platform_config_helpers.py tests/unit/platforms/test_presto_trino_utils.py tests/unit/platforms/base/test_spark_execution_mixin.py -q
  - uv run -- python -m pytest <targeted platform hook files> -q (1194 passed)
  - uv run -- python _project/scripts/reference_usage_audit.py --summary
  - make pr-preflight
---

## Thesis

Shrink iteration across repeated platform hook plumbing by consolidating
structurally identical `from_config` field-copy routines, cloud-Spark tuning
application, hook dispatch, file/table discovery helpers, and explicit
tuning-support predicates.

Baseline evidence:

- `make shrink-rollup`: 1,841 merged credited lines, 10,159 remaining to the
  committed 12,000 floor, 17,159 remaining to stretch.
- `cloc --include-lang=Python benchbox/`: 205,013 Python code lines.
- Code-only structural duplicate scan: `from_config` assembly, repeated Spark
  and SQL execution wrappers, constraint/unified tuning hooks, table-discovery
  helpers, and tuning-support predicates form a coherent hook surface.
- Open develop PRs #622, #623, and #624 do not touch platform hook/config files.

Reduction path:

- Add explicit helper functions for standard adapter config assembly,
  tuning-support set checks, standard unified tuning dispatch, informational
  constraint hooks, and cloud-Spark tuning application.
- Replace repeated bodies with explicit public methods or grep-findable function
  bindings; preserve public function names, signatures, `__name__`, and
  `__qualname__`.
- Do not delete platforms, change support status, move Python into data files,
  add generated Python, or change live/cloud execution semantics.

Actual credited reduction: 538 maintained-Python code lines. The post-edit
`cloc --include-lang=Python benchbox/` delta cleared the 500-line shrink
iteration floor.

## Guardrail evidence

Pre-edit public hook fingerprint:

- `/tmp/shrink-platform-hooks-fingerprint-pre.txt`

Planned guardrails:

- Post-edit hook fingerprint must preserve public signatures and config builder
  callable names/qualnames. Owner relocation to shared mixins/base hook is
  expected and captured in `/tmp/shrink-platform-hooks-fingerprint.diff`.
- Pure helper behavior is characterized by targeted unit tests for
  `build_adapter_config`, `supports_named_tuning_type`, informational
  constraint hooks, standard unified tuning dispatch, Spark execution wrapper
  delegation, and shared `SHOW TABLES` table discovery.
- Whole-tree references for touched hook names must remain valid.
- No import-time I/O, no dynamic module-global mutation, no registry-key changes,
  and no live/cloud tests without explicit approval.

## Verification

- `make shrink-rollup` before editing: 1,841 merged credited lines; 10,159
  remaining to the committed 12,000 floor; 17,159 remaining to stretch.
- `cloc --include-lang=Python benchbox/`: 205,013 before, 204,475 after; raw
  maintained-Python delta 538.
- Fingerprints:
  - pre: `/tmp/shrink-platform-hooks-fingerprint-pre.txt`
  - post: `/tmp/shrink-platform-hooks-fingerprint-post.txt`
  - diff: `/tmp/shrink-platform-hooks-fingerprint.diff`
- `uv run -- ruff check ...` for all touched source/test files: passed.
- `uv run -- python -m compileall -q benchbox/platforms`: passed.
- `uv run -- python -m pytest tests/unit/platforms/base/test_platform_config_helpers.py tests/unit/platforms/test_presto_trino_utils.py tests/unit/platforms/base/test_spark_execution_mixin.py -q`: 79 passed.
- `uv run -- python -m pytest tests/unit/platforms/test_doris_adapter.py tests/unit/platforms/test_spark_adapter.py tests/unit/platforms/test_lakesail_adapter.py tests/unit/platforms/test_redshift_adapter.py tests/unit/platforms/test_starrocks_adapter.py tests/unit/platforms/test_starrocks_tuning.py tests/unit/platforms/test_azure_synapse_adapter.py tests/unit/platforms/test_bigquery_adapter_coverage.py tests/unit/platforms/test_cedardb.py tests/unit/platforms/test_pg_duckdb_adapter.py tests/unit/platforms/test_databricks_adapter.py tests/unit/platforms/test_databricks_adapter_coverage.py tests/unit/platforms/test_firebolt_coverage.py tests/unit/platforms/test_presto_adapter.py tests/unit/platforms/test_velox_adapter.py -q`: 1,194 passed.
- `uv run -- python _project/scripts/reference_usage_audit.py --summary`: passed
  with 78 reference hits and 0 parse errors.
- `make pr-preflight`: passed; the final fast-test gate reported 22,775
  passed, 5 skipped, 47 warnings, and 4 subtests passed.

## Residual risk

The touched surface spans live/cloud adapters. The change is restricted to pure
configuration and hook dispatch boilerplate, with behavior pinned by helper-level
tests, existing platform tests, and callable fingerprints. The largest remaining
risk is inherited-method ownership changing from adapter-local methods to shared
mixins/base hooks; signatures, public names, and platform-specific messages are
kept stable where behavior depends on them.

## Next target

If this slice lands, reassess smaller platform hook residues separately; do not
stack unrelated adapter behavior into this PR.
