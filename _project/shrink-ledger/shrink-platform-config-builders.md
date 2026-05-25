---
iteration: shrink-platform-config-builders
date: 2026-05-25
surface: platform hook config-builder and data-source resolver boilerplate
branch: chore/shrink-platform-config-builders
pr:
raw_cloc_delta: 276
credited_reduction: 276
uncredited_relocation: 0
repair_only_delta: 0
generated_python_delta: 0
moved_content: logic
decision_gate: conservative default; explicit factory-bound config builders preserve static names and hook registration keys
verification:
  - make shrink-rollup
  - cloc --include-lang=Python benchbox/
  - cloc --include-lang=Python --by-file benchbox/platforms/base/config_utils.py <platform builder modules>
  - make duplicate-check-json -> groups=278 duplicated_lines=6210
  - uv run -- ruff check $(git diff --name-only -- '*.py')
  - uv run -- python -m pytest <targeted platform/config/data-loading tests> -q -n 0 -> 1539 passed
  - uv run -- python -m pytest <Presto/Trino/Starburst adapter tests> -q -n 0 -> 204 passed
  - /tmp/shrink-platform-config-fingerprint-after.json matched 17 pre-existing builders
  - /tmp/shrink-platform-config-pg-cedardb-after.json matched PostgreSQL/CedarDB pre-edit fingerprints
  - make pr-preflight
---

## Thesis

Shrink iteration under the smaller-subsystem exception. The platform adapter
boilerplate subsystem is the repeated platform hook config-builder wrappers
plus standard `DataSourceResolver` delegates. The initial config-builder target
was 17 `_build_*_config` callables that already delegate to
`benchbox.platforms.base.config_utils.build_platform_config`, measured at 643
source lines before edits. The final slice also folds the adjacent
PostgreSQL/CedarDB config builders and the standard resolver delegates used by
cloud/Presto-family adapters, keeping the named subsystem under 1,000 source
lines while removing 276 credited maintained-Python code lines.

The reduction path is true boilerplate deduplication, not platform deletion or
Python-to-data relocation: add a shared factory that creates a typed config
builder callable and sets `__name__`, `__qualname__`, and `__module__`, then
replace repeated function/import/return/register scaffolding with explicit
module-level assignments. Platform-specific field lists, platform type,
credential key, display name, driver package, base options, and the Athena and
BigQuery post-processing steps remain local to their existing modules. The
resolver reduction adds one shared `resolve_adapter_data_source()` helper and
leaves each adapter's return shape intact.

Credited reduction is 276 maintained-Python lines, above the 250-line and 10%
smaller-subsystem floor.

## Guardrail evidence

- Baseline campaign rollup: 2,379 merged credited lines; 9,621 remaining to the
  committed 12,000 floor; 16,621 remaining to stretch.
- Baseline raw maintained Python: `cloc --include-lang=Python benchbox/` =
  204,628 code lines.
- Baseline touched-file raw Python for the initial config-builder target:
  11,020 code lines.
- Builder-body baseline: 17 functions, 643 source lines; expanded final
  subsystem stayed under the smaller-subsystem 1,000-line ceiling.
- Duplicate evidence: `make duplicate-check-json` reports a 7-copy,
  180-duplicated-line group across cloud config builders plus additional
  repeated Redshift/TimescaleDB/Postgres-family builders.
- Open PR overlap: only PR #626 is open and it touches JoinOrder revert files,
  not platform config builders.
- Moved-content classification: logic consolidation only. No benchmark,
  platform, deprecated/beta-public surface, generated Python, SQL/query surface,
  catalog, or YAML migration changes.
- Decision-gate status: conservative default. The factory binds explicit
  module-level callable names and static registry keys; no dynamic symbol
  injection or permissive open gate is used.
- Behavior preservation: pre/post fingerprint each builder's callable name,
  module, registry key, returned `DatabaseConfig` type/name/options/top-level
  fields, saved-credential merge priority, explicit option priority, and runtime
  override priority. PostgreSQL and CedarDB received separate before/after
  fingerprints because their previous wrappers had different default-option and
  override-consumption behavior.

## Verification

- `make shrink-rollup` at slice start: 2,379 merged credited lines; 9,621
  remaining to the 12,000 floor.
- `cloc --include-lang=Python benchbox/`: final raw maintained Python =
  204,352 code lines, down 276 from the 204,628 pre-slice baseline.
- `make duplicate-check-json`: groups=278, duplicate_instances=361,
  duplicated_lines=6,210.
- `uv run -- ruff check $(git diff --name-only -- '*.py')`: passed.
- Targeted tests:
  `uv run -- python -m pytest tests/unit/platforms/base/test_platform_config_helpers.py tests/unit/cli/test_platform_hooks.py tests/unit/platforms/test_data_loading.py tests/unit/platforms/test_presto_trino_utils.py tests/unit/platforms/test_postgresql_adapter.py tests/unit/platforms/test_cedardb.py tests/unit/platforms/test_pg_duckdb_adapter.py tests/unit/platforms/test_pg_mooncake_adapter.py tests/unit/platforms/test_timescaledb_adapter.py tests/unit/platforms/test_clickhouse_cloud_coverage.py tests/unit/platforms/test_bigquery_adapter.py tests/unit/platforms/test_bigquery_adapter_coverage.py tests/unit/platforms/test_redshift_adapter.py tests/unit/platforms/test_redshift_adapter_coverage.py tests/unit/platforms/test_snowflake_adapter.py tests/unit/platforms/test_snowflake_adapter_coverage.py tests/unit/platforms/test_spark_adapter.py tests/unit/platforms/test_databend_adapter.py tests/unit/platforms/test_azure_synapse_adapter.py tests/unit/platforms/test_firebolt_coverage.py tests/unit/platforms/test_firebolt_adapter.py -q -n 0`
  -> 1,539 passed.
- Presto/Trino/Starburst adapter follow-up:
  `uv run -- python -m pytest tests/unit/platforms/test_presto_adapter.py tests/unit/platforms/test_trino_adapter.py tests/unit/platforms/test_starburst.py tests/unit/platforms/test_presto_trino_utils.py -q -n 0`
  -> 204 passed.
- `/tmp/shrink-platform-config-fingerprint-after.json`: matched all 17
  pre-existing builder fingerprints.
- `/tmp/shrink-platform-config-pg-cedardb-after.json`: matched PostgreSQL and
  CedarDB pre-edit fingerprints.

## Residual risk

Residual risk is low but concentrated in introspection and test mocks: replacing
direct `def` functions with factory-built callables could change callable
metadata or hook registration, and centralizing resolver delegation moves the
mock boundary. The factory pins callable metadata, fingerprints prove config
values and builder identity, and the tests now pin the helper-level resolver
contract.

## Next target

After merge, re-run `make shrink-rollup` and reassess the remaining low-risk
reservoir. Do not move static query/catalog content for credit unless a human
approves that credit class.
