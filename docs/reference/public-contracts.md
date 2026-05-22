<!-- Copyright 2026 Joe Harris / BenchBox Project. Licensed under the MIT License. -->

# Public Contracts and Support Taxonomy

**Created:** 2026-05-21
**Originating TODO:** `architecture-contract-map-and-support-taxonomy`
**Checked SHA:** `893768130f3b3aad249549f897538a172a0f8230`

This document classifies BenchBox surfaces by compatibility tier and names the
source of truth for each one. It is intentionally narrower than a full
architecture guide: if a future PR changes a public, beta-public, generated,
deprecated, or experimental surface, that PR must update this map or state why
the map is unchanged.

## Contract Tiers

| Tier | Meaning | Breaking-change rule |
|---|---|---|
| `stable-public` | User-facing surface that should remain compatible across beta patch/minor releases unless a documented migration exists. | Needs migration note and compatibility registry update when behavior changes. |
| `beta-public` | User-facing surface exposed during beta. It is supported, but details can change before 1.0 with documented rationale. | Needs same-PR docs/tests and deprecation path when practical. |
| `internal` | Implementation detail. External callers should not depend on it. | Can change with focused tests; public docs must not promise it. |
| `experimental` | Prototype or research surface. It may ship for convenience without product support. | Can change or disappear; docs must label it experimental. |
| `deprecated` | Compatibility surface retained temporarily. | Must have owner, migration path, and target review/removal window in `backward-compatibility.md`. |
| `generated` | Output derived from source metadata, schemas, fixtures, or build scripts. | Source metadata is authoritative; hand edits are drift unless explicitly marked editorial. |
| `repo-only` | Contributor, planning, audit, or release-support surface that is not a user product API. | May change with repo workflow docs; wheel/API stability does not apply. |

## Public Surface Map

| Surface | Current tier | Owner | Compatibility promise | Deprecation path | Verification gate | Source of truth |
|---|---|---|---|---|---|---|
| CLI commands and documented options | `beta-public` | cli-runtime | Documented commands and option meanings are supported for beta users; option breadth can change with docs/tests. | Release notes plus docs update; backward-compatible aliases when practical. | CLI unit tests, generated CLI reference checks, `make pr-preflight`. | `benchbox/cli/commands/`, `docs/reference/cli/` |
| Top-level Python wrapper facades, for example `benchbox.TPCH(...)` | `beta-public` | benchmark-api | Wrapper imports and facade methods covered by `tests/unit/test_wrapper_facades_fast.py` remain supported. Current count: 21 exported top-level benchmark facades from 23 registry class-name mappings; `ai_primitives` and `joinorder_synthetic` are core-only. | Registry row in `docs/reference/backward-compatibility.md`, migration to canonical API, beta-cycle review. | `uv run -- python -m pytest tests/unit/test_wrapper_facades_fast.py -q`, benchmark API contract count test. | `benchbox/__init__.py`, top-level wrapper modules, wrapper facade tests |
| `benchbox.base.BaseBenchmark` | `beta-public` | core-runtime | Public base for wrapper benchmarks and orchestration helpers; result helper compatibility is tracked. | Compatibility registry row when kwargs, result helpers, or method contracts change. | Runtime contract and wrapper tests. | `benchbox/base.py`, `docs/reference/backward-compatibility.md` |
| `BaseBenchmark.run_with_platform` | `beta-public` | core-runtime | Standard programmatic execution hook for CLI-adjacent tools and MCP; callers pass an adapter and run options. | ADR or contract-map update before replacing it as the orchestration API. | MCP benchmark tests plus runtime contract tests. | `benchbox/base.py`, `_project/DONE/mcp-integration/active/refactor-mcp-use-public-api.yaml` |
| `benchbox.core.benchmark_loader` | `internal` | benchmark-api | Registry-backed runtime loader for CLI/core orchestration. It is not a public Python API and should not be imported by external callers. | Promote only through a contract-map update and migration docs. | Loader/registry parity tests and benchmark API contract tests. | `benchbox/core/benchmark_loader.py`, `benchbox/core/benchmark_registry.py` |
| `benchbox.core.base_benchmark.BaseBenchmark` | `deprecated` | core-runtime | Documented internal compatibility base retained for the remaining `datavault` and `tpcds_obt` core implementations; not an alias and not the extension path for new benchmarks. | Remove only after those implementations migrate to `benchbox.base.BaseBenchmark` and the compatibility registry target is satisfied. | Backward-compatibility registry review, benchmark loader/runtime tests, benchmark API contract tests. | `benchbox/core/base_benchmark.py`, `docs/reference/backward-compatibility.md` |
| Adapter subclassing hooks and base mixins | `beta-public` | platform-runtime | Adapter authors can depend on documented `PlatformAdapter` hooks, ABC signatures, and adapter authoring docs. | Adapter refactor map update, migration note, and representative adapter tests. | `tests/unit/platforms/test_abc_conformance.py`, focused adapter tests. | `benchbox/platforms/base/`, `docs/development/adapter-refactor-map.md`, `docs/development/adding-new-platforms.md` |
| `PlatformAdapter` lifecycle | `beta-public` | platform-runtime | Adapter instances are serial execution objects. One instance may be reused for multiple benchmark runs sequentially; `run_benchmark()` resets run-scoped caches at run start and restores run-config plan-capture overrides at run end. Concurrent calls on one adapter instance are not supported. | A concurrency or service-mode promotion needs a contract-map update and a shared run-context design before claiming support. | `tests/unit/platforms/test_adapter_lifecycle.py`, focused adapter lifecycle tests. | `benchbox/platforms/base/adapter.py`, `benchbox/platforms/base/result_capture.py`, `docs/development/adapter-refactor-map.md` |
| DataFrame adapter execution path | `beta-public` | dataframe-runtime | Production DataFrame execution routes through `benchbox.core.runner.runner` to `adapter.run_benchmark()`, implemented by `BenchmarkExecutionMixin` for production DataFrame platforms such as `polars-df`, `pandas-df`, `datafusion-df`, and `dask-df`. | Changes need DataFrame mixin tests, result-bundle parity coverage, and same-PR docs. | DataFrame mixin tests plus exported SQL/DataFrame result parity. | `benchbox/core/runner/runner.py`, `benchbox/platforms/dataframe/benchmark_mixin.py`, `tests/unit/core/results/test_result_parity.py` |
| `benchbox.core.runner.dataframe_runner.run_dataframe_benchmark` | `deprecated` | dataframe-runtime | Deprecated internal compatibility runner retained for old tests and helper imports. It is not the production DataFrame lifecycle path. | Backward-compatibility registry review after one beta cycle; migrate remaining behavior to `BenchmarkExecutionMixin` before removal. | Compatibility tests only. | `benchbox/core/runner/dataframe_runner.py`, `tests/unit/core/runner/test_dataframe_runner.py`, `tests/unit/core/runner/test_dataframe_runner_lifecycle.py` |
| Platform registry metadata | `beta-public` | platform-runtime | Registry metadata is the source for platform discovery, capabilities, dependency hints, and platform support status. | Same-PR metadata/docs migration; aliases require compatibility note. | Platform registry tests and docs drift checks. | `benchbox/core/platform_registry.py` |
| MCP tools | `beta-public` | mcp | Tool schemas and documented parameters are supported as a smoke/control-plane automation surface, not a CLI-equivalent execution surface. MCP result bundles are schema-comparable to CLI bundles, but MCP must not import CLI command internals or imply CLI option parity. | MCP reference update and contract tests; product-tier or option-parity changes need a decision note and, for CLI equivalence, a shared non-CLI run service below CLI and MCP. | `tests/unit/mcp/test_run_surface_contract.py`, `tests/unit/mcp/`, MCP docs/schema checks. | `benchbox/mcp/`, `docs/reference/mcp.md`, `benchbox/base.py` |
| Visualization semantic chart IDs | `beta-public` | visualization | Result-aware chart IDs accepted by CLI, MCP, templates, ASCII runtime dispatch, and Results Explorer must derive from the semantic registry. Raw textcharts primitive IDs are a separate dependency namespace. | Same-PR registry, template, discovery, Explorer, and parity-fixture updates; deprecate IDs rather than silently removing them. | Visualization registry tests, exporter tests, Explorer registry parity tests, and parity-fixture drift checks. | `benchbox/core/visualization/chart_types.py`, `benchbox/core/visualization/ascii_runtime.py`, `benchbox/core/visualization/templates.py`, `results-explorer/src/lib/chartRegistry.ts`, `tests/parity/fixtures/chart_ids.json` |
| `benchbox.core.visualization.render_ascii_chart` | `beta-public` | visualization | Compatibility data-first ASCII primitive renderer for callers that already have chart-specific data objects. It intentionally has narrower coverage than the result-aware semantic renderer and excludes `power_bar`, which needs normalized BenchBox result context. | Promote a missing semantic chart only when a data-first payload contract exists; otherwise keep the explicit result-aware-only error. | `tests/unit/core/visualization/test_visualization_exporters.py`, visualization registry parity tests. | `benchbox/core/visualization/exporters.py` |
| Result JSON bundles | `beta-public` | results | Schema-versioned result bundles are product data consumed by CLI, submission validation, hosted results, explorer, and SQL/DataFrame comparisons. SQL and DataFrame bundles must preserve the cross-mode invariants below. | Schema policy and hosted-results contract update before changing accepted versions, field semantics, or cross-mode parity guarantees. | Result schema policy, loader, normalizer, submission, explorer, and exported SQL/DataFrame parity tests. | `benchbox/core/results/schema_policy.py`, `benchbox/core/results/schema.py`, `docs/reference/result-formats.md`, `docs/reference/hosted-results-contract.md`, `tests/unit/core/results/test_result_parity.py` |
| Explorer read model and generated browser inputs | `generated` | results-explorer | Browser data stores are generated from accepted result bundles; generated outputs should be reproducible from source bundles and pipeline code. | Read-model version bump or pipeline contract update. | Explorer pipeline contract tests and browser release gates. | `_project/scripts/explorer_pipeline/`, results explorer generated data |
| Public submission validator behavior | `beta-public` | hosted-results | PR-based public result submissions must receive deterministic validation errors and privacy/trust handling. | Hosted-results contract update and validator tests. | `validate-submission` workflow, submission validator tests. | `scripts/validate_submission.py`, `docs/contributing-results.md`, `docs/reference/hosted-results-contract.md` |
| SQL compatibility rule catalog | `internal` | sql-compat | Hybrid governance catalog: every source-detected adapter CREATE TABLE rewrite must be runtime-dispatched by `BaseDdlOptimizer`, registered as `governance_only`, or explicitly exempted. | sql_compat README and contract-map update before changing the governance guarantee. | `make compat-docs-check`, `uv run -- python -m benchbox.sql_compat.inventory --check-ddl-drift`. | `benchbox/sql_compat/`, `benchbox/platforms/`, `docs/compat/` |
| Generated compatibility docs | `generated` | sql-compat | Generated docs must match registry/rule metadata; hand edits are drift unless the section says it is editorial. | Regenerate from source metadata or update the generator. | `make compat-docs-check`. | `benchbox/sql_compat/`, generated docs under `docs/compat/` |
| `benchbox.experimental` namespace | `experimental` | architecture | Ships in the default wheel for developer convenience but is outside the supported beta product surface. | Promote through a contract-map update and tests, or extract/remove through the experimental future-state plan. | Package metadata review and explicit tests for promoted surfaces only. | `README.md`, `pyproject.toml`, `docs/design/future-state/isolate-experimental-core-subsystems/README.md` |
| `_project` scripts, audits, and analysis artifacts | `repo-only` | maintainers | Contributor workflow and project governance aids; not user-facing API. | Repo workflow docs or TODO updates. | Script-specific tests where present. | `_project/` |
| TODO, DONE, and ADR/future-state docs | `repo-only` | maintainers | Planning and decision records guide implementation but do not themselves create runtime API. | Move accepted decisions into user/developer docs when they become product contracts. | TODO validation and review. | `_project/TODO/`, `_project/DONE/`, `docs/design/future-state/` |

## Support Status Taxonomy

`support_status` is a product-support classification for platforms and
benchmarks. It is different from local dependency availability: a stable
platform can be unavailable on a developer machine because an optional SDK is not
installed.

Allowed values:

| Status | Meaning | Packaging | Docs | Registry visibility | MCP exposure | CI coverage | Breakage policy |
|---|---|---|---|---|---|---|---|
| `stable` | Supported product surface for normal users. | Included or installable through documented extras. | Full user docs and examples where relevant. | Listed by default. | Exposed when the MCP surface supports that capability. | Fast/unit plus representative smoke or integration coverage. | Fix promptly or document temporary known issue. |
| `beta` | Supported beta surface with known evolution risk. | Included or installable through documented extras. | Docs must label beta caveats. | Listed by default with beta status. | Exposed if behavior is covered by MCP docs/tests. | Focused tests for core behavior. | Can change with same-PR docs/tests and migration guidance. |
| `experimental` | Prototype or research surface. | May ship in default wheel or optional extra, but must be labeled. | Experimental docs only; no support implication. | Hidden or clearly labeled. | Omitted unless the MCP tool explicitly labels it. | Best-effort targeted tests. | May change or be removed without compatibility promise. |
| `repo_only` | Contributor or source-checkout-only surface. | Not promised in wheels. | Developer/project docs only. | Hidden from user discovery. | Not exposed. | Script or workflow checks only when useful. | May change with repo workflow updates. |
| `deprecated` | Temporarily retained compatibility surface. | Retained until target review/removal window. | Migration path required. | Listed with deprecation status or hidden after warning window. | Exposed only if existing clients need it. | Compatibility tests until removal. | Removal follows registry target and release notes. |
| `document_only` | Documented external concept or planned support with no runtime implementation. | No package promise. | Docs must say it is not executable support. | Not listed as runnable. | Not exposed. | Link/static doc checks only. | No runtime breakage claim. |

Platform and benchmark registry metadata now carry exactly one `support_status`
for every runtime entry. Benchmark support status is distinct from benchmark
`surface` visibility and from capability flags such as `supports_dataframe`.

## Count and Drift Policy

Benchmark API snapshot: **23** registry entries; **23** loader-resolved core families; **22** public discovery entries; **21** top-level Python benchmark facades; **14** lazy facades; **7** eager facades; **2** core-only benchmark IDs. Benchmark support status: **5** stable, **12** beta, **5** experimental, **1** repo-only, **0** deprecated, **0** document-only.

Evidence snapshot updated by `benchmark-support-status-and-discovery-policy`:

| Source | Current evidence | Contract implication |
|---|---|---|
| `benchbox.core.benchmark_registry` | 23 benchmark metadata entries and 23 loader-resolved IDs; support status counts are stable=5, beta=12, experimental=5, repo_only=1, deprecated=0, document_only=0. | Benchmark count and support claims must derive from registry metadata or avoid exact counts. |
| `benchbox.core.platform_registry.PlatformRegistry.get_all_platform_metadata()` | 50 platform metadata entries: 45 SQL-capable, 19 DataFrame-capable, 14 dual-mode. | README and platform docs must not carry unqualified hand-maintained platform counts. |
| `benchbox.core.results.schema_policy` | Current result schema version: `2.1`; runtime/explorer accepted versions: `2.0`, `2.1`; public submission accepts numeric `2.x`. | Result schema version claims must update with the named consumer policy or defer to this policy module. |
| `README.md` before this TODO | Landing-page bullets claimed 22 benchmarks, 42 SQL platforms, and 9 DataFrame platforms. | Exact counts were stale relative to registry metadata; README now links to this policy instead of being authoritative. |

Authoritative count statements should come from the relevant registry metadata.
Editorial lists may remain in narrative docs, but they must not claim to be
exhaustive unless a generated or tested check keeps them synchronized.

## Drift Check Ownership

Each public claim class has one owner and one preferred verification gate:

| Claim class | Owner | Source of truth | Verification gate |
|---|---|---|---|
| Platform counts, platform support status, and optional import health | platform-runtime | `benchbox/core/platform_registry.py` | Platform registry tests and generated platform docs checks. |
| Benchmark counts, benchmark wrapper/loader/discovery reachability, and benchmark support status | benchmark-api | `benchbox/core/benchmark_registry.py`, `benchbox/__init__.py`, `benchbox/core/benchmark_loader.py` | `tests/unit/core/test_benchmark_api_contract.py` plus focused MCP discovery checks. |
| Result schema versions and consumer acceptance policy | results | `benchbox/core/results/schema_policy.py`, result docs | Result schema policy, loader, submission, explorer, and hosted-results contract tests. |
| MCP run parameters and product-surface limits | mcp | `benchbox/mcp/`, `docs/reference/mcp.md` | `tests/unit/mcp/test_run_surface_contract.py` and focused MCP tool tests. |
| SQL compatibility DDL rewrite governance | sql-compat | `benchbox/sql_compat/`, adapter DDL rewrite sites | `make compat-docs-check` and DDL drift inventory checks. |

The contract map is the routing layer for these gates, not the sole source of
every generated table. A PR that changes a claim class should update the owning
source and its gate first, then update this map only when the public contract or
ownership boundary changes.

## Visualization Chart Contract

`benchbox/core/visualization/chart_types.py` is the semantic result-aware chart
registry for CLI, MCP, templates, ASCII runtime dispatch, and Results Explorer.
Adding a semantic chart ID starts there, then updates the result-aware runtime
handler in `benchbox/core/visualization/ascii_runtime.py`, any templates that
should include it, `results-explorer/src/lib/chartRegistry.ts`, and generated
parity fixtures from `make parity-fixtures`. Registry tests must report missing
and extra IDs by name, not only by count.

`benchbox.core.visualization.render_ascii_chart` is a compatibility data-first
renderer for callers that already hold primitive chart payloads. It intentionally
does not cover `power_bar`, because `power_bar` needs normalized BenchBox result
context and is rendered through `render_ascii_chart_from_results()`. Raw
textcharts primitive IDs such as `bar` or `heatmap` are dependency internals, not
BenchBox semantic chart IDs. Textcharts dependency updates should be validated by
the visualization registry tests plus the runtime drift snippet that compares
`ALL_CHART_TYPES`, `_CHART_TYPE_DISPATCH`, and the primitive exporter registry.

## SQL Compatibility Governance Decision

Decision from `sql-compat-governance-ddl-hardening`: `sql_compat` is a hybrid
governance catalog plus optional runtime dispatcher. `BaseDdlOptimizer` is the
preferred dispatch path for ordered statement-to-statement DDL transforms, but
adapters may keep local CREATE TABLE rewrite paths when the rewrite depends on
adapter state, SDK-specific create/load loops, or platform deployment settings.

`governance_only=True` rules are allowed to represent real runtime behavior.
They are not dispatch targets; they are the auditable source of intent that the
drift checker requires before CI can call DDL governance clean. `compat_lint CLEAN`
means the source scanner found no unregistered or uninspectable adapter
CREATE TABLE rewrite behavior. It does not mean every DDL rewrite flows through
`BaseDdlOptimizer`.

## DataFrame Runner Lifecycle Decision

Checked for `dataframe-runner-lifecycle-and-bundle-parity` at
`8604d0a413f6c3d4bd7db211bb472c2370a932c3`.

Production DataFrame execution is `run_benchmark_lifecycle()` ->
`adapter.run_benchmark()` -> `BenchmarkExecutionMixin.run_benchmark()`.
`benchbox.core.runner.dataframe_runner.run_dataframe_benchmark()` is a
deprecated internal compatibility runner. The module still provides internal
mode/query helpers used by CLI/dry-run code, but new lifecycle behavior belongs
in `benchbox/platforms/dataframe/benchmark_mixin.py`.

Production behavior tests are the DataFrame mixin and adapter lifecycle tests,
plus exported result parity in `tests/unit/core/results/test_result_parity.py`.
`tests/unit/core/runner/test_dataframe_runner.py` and
`tests/unit/core/runner/test_dataframe_runner_lifecycle.py` are compatibility
tests for the deprecated standalone runner until the beta review window closes.

Evidence rechecked:

| Evidence | Finding |
|---|---|
| `benchbox/core/runner/runner.py` | DataFrame adapter branches call `adapter.run_benchmark(..., phases=DataFramePhases, options=DataFrameRunOptions)` for execute and load-only paths. |
| `benchbox/platforms/dataframe/benchmark_mixin.py` | The mixin owns production DataFrame result construction, phase status, query execution, skip summaries, and plan-capture counters. |
| `benchbox/core/runner/dataframe_runner.py` | Standalone runner duplicates older result construction and is not called by production lifecycle execution. |
| `docs/design/architecture.md` | DataFrame architecture now points at the adapter mixin path instead of the deprecated standalone runner. |
| `tests/unit/core/results/test_result_parity.py` | Exported JSON bundle parity is enforced after writing through `ResultExporter`. |

## SQL/DataFrame Result Bundle Invariants

SQL and DataFrame runs may use different engines and execution models, but their
exported result bundles must remain schema-comparable.

Fields that must match for the same benchmark, scale, query subset, and run
configuration:

- Result schema version.
- Benchmark identity: `benchmark.id`, `benchmark.name`, `benchmark.scale_factor`, and test type.
- Reproducibility config, excluding execution-mode-specific values: compression, seed, phases, and query subset.
- Presence of the standard phase keys.
- Query IDs in exported `queries`.
- Row counts when both modes report them.
- Validation state and absence/presence of exported error records.
- Execution metadata key shape, except conditional SQL translation metadata
  under `execution.translation`.
- Timing field names and units: run-level milliseconds and query-level `ms`.

Allowed differences:

- `execution.mode` and `config.mode` are expected to be `sql` vs `dataframe`.
- Platform name, version, client version, family, and driver metadata can differ.
- Phase status may differ when the DataFrame benchmark owns loading; for example,
  SQL can report `data_loading=SUCCESS` or `COMPLETED` while DataFrame reports
  `SKIPPED`.
- Optional `tables` blocks can be absent when a DataFrame benchmark manages or
  skips generic loading.
- `execution.translation` is SQL-only additive metadata and may appear when SQL
  dialect translation was attempted. DataFrame bundles are not expected to emit
  matching translation metadata.
- Exact timing values must not be compared across modes.

## Result Model Extension Policy

`BenchmarkResults` is an internal producer model; schema-v2 result JSON is the
compatibility boundary. Model cleanup must not move or remove exported keys
unless the same PR includes loader, validator, explorer, MCP, and public
submission coverage for the migration.

Platform-specific structured data should use the narrowest existing exported
location first:

- Platform identity, deployment, cloud, compute, storage, and raw platform
  details serialize under the `platform` block.
- Lifecycle stage summaries serialize under `phases.<stage>`.
- Cross-engine or cross-platform comparisons serialize under `comparisons`.
- Invocation and validation metadata serialize under `execution` and `summary`.
- New top-level keys require a public-contract update, schema-validator update,
  loader behavior, and explorer input policy review in the same PR.

A future `platform_extensions` block is acceptable only for additive structured
data that has no existing canonical block. Existing fields may move there only
with an alias period: old exported keys keep loading and writing until all
documented consumers are migrated. Unknown nested keys inside documented blocks
may be ignored by read-model consumers, but unknown top-level keys remain
schema-governed and must not bypass schema-v2 validation.

Current extension inventory:

| Internal field/source | Current exported key | Loader behavior | Downstream consumers | Recommended action |
|---|---|---|---|---|
| `native_comparison` | `comparisons.native_duckdb` | Reconstructs `NativeComparison` from `comparisons.native_duckdb`. | Result loader/exporter; public schema validation now accepts the producer key; explorer ignores the comparison block. | Keep exported key; do not move before a comparison read-model design exists. |
| `ExecutionPhases.migration` | `phases.migration` | Reconstructs summary-level `MigrationPhase`; per-table stats are intentionally not serialized. | Result loader/exporter; explorer reads phase durations from `phases.*`. | Keep as canonical lifecycle-stage location. |
| Standalone pg_mooncake migration script | Top-level `migration` in script-emitted payloads | Not reconstructed by result loader. | Script-local reports only; not a canonical schema-v2 result extension. | Leave separate or convert in a dedicated PR to `phases.migration`; do not generalize this top-level key. |
| `platform_info`, `platform_metadata`, `platform_raw_config`, `platform_raw_metadata` | `platform.config`, `platform.raw_config`, `platform.raw_metadata` | Reconstructs platform info and raw metadata blocks. | Loader/exporter, anonymizer, explorer platform/version extraction. | Keep; move internally only if exported keys remain stable. |
| `platform_deployment`, `platform_cloud`, `platform_compute`, `platform_storage` | `platform.deployment`, `platform.cloud`, `platform.compute`, `platform.storage` | Reconstructs the normalized platform facets. | Loader/exporter, environment compatibility tests, explorer environment facets. | Keep as canonical platform facets. |
| `execution_context` | `execution` and selected `config` fields | Loader preserves selected execution metadata, not the full internal context. | CLI/MCP/exporter/explorer metadata consumers. | Keep selected exported fields; expand only by explicit schema policy. |
| `_benchmark_id_override` | `benchmark.id` | Reconstructs from `benchmark.id`. | Filename builder, loader, explorer IDs, result parity tests. | Keep internal compatibility field until builder and loader identity handling are redesigned. |

## Translation and Validation Mode Policy

Decision from `fail-open-policy-and-translation-strictness`: SQL translation is
mode-aware. Interactive/local runs may fail open by returning source SQL with a
warning, but CI, publishing, compatibility governance, and any caller making a
public correctness claim must use strict translation or treat fallback metadata
as uncertainty.

| Mode | Translation failure policy | Result-bundle policy | Consumer expectation |
|---|---|---|---|
| Interactive/local default | Fail open and warn. | `execution.translation.status="fallback"` when translation falls back; `summary.validation="uncertain"` if the result otherwise looked clean. | Users can keep experimenting, but the bundle is not a clean correctness claim. |
| CI and compatibility governance | Fail closed with CLI `--strict-translation`, or by setting `strict_translation=true`, `translation_strict=true`, or `sql_translation_strict=true` in benchmark/runtime options. | Strict failures raise before a result is published as successful. | Gates should fail rather than accept untranslated SQL. |
| Publishing and explorer ingestion | Reject non-clean validation statuses or translation fallback metadata. | `not_run`, `not_validated`, `unknown`, and `uncertain` are non-clean validation statuses; `execution.translation.status="fallback"` and `"failed"` are non-clean translation statuses. | Hosted/public views must not rank or present unchecked/fallback runs as validated results. |

Translation metadata is exported under `execution.translation` without a schema
version bump because it is an additive field inside the existing execution
block. It records strict mode, aggregate status, attempt counts, translators,
source/target dialects, warning/error categories, and compact grouped outcomes.
`summary.validation="passed"` is reserved for runs with evidence that validation
actually ran. When no validation record or validation details exist, lifecycle
finalization labels the result `not_run` instead of `passed`.
Post-load validation that is not applicable because an adapter does not expose
connection validation hooks records no validation stage; exceptions after a
validation attempt remain failed validation stages.

## Evidence Snapshot

This TODO revalidated the contract map against the following files before
editing:

| Evidence | Finding |
|---|---|
| `README.md:35-48` | Beta disclaimer exists; `benchbox.experimental` is explicitly outside the supported beta product surface; feature count bullets were hand-maintained. |
| `docs/reference/backward-compatibility.md:24-84` | Compatibility registry tracks shims; wrapper cleanup notes preserve top-level wrappers and keep `benchbox.core.base_benchmark.BaseBenchmark` pending a dedicated item. |
| `tests/unit/test_wrapper_facades_fast.py:30-260` | Wrapper facades are tested public behavior, not accidental reachability. |
| `_project/DONE/mcp-integration/active/refactor-mcp-use-public-api.yaml:25-47` | Completed decision moved MCP away from CLI internals and onto public benchmark/adapter APIs. |
| `docs/design/future-state/index.md:19-41` | Future-state proposals already classify MCP API formalization and experimental isolation as active architecture decisions. |
| `benchbox/base.py:476` | `run_with_platform` remains the programmatic execution hook used by orchestration tools. |
| `benchbox/core/platform_registry.py:85-89` | Platform registry declares itself the metadata and adapter-registration source of truth. |
| `benchbox/core/benchmark_registry.py:1-5` | Benchmark registry declares itself the shared benchmark metadata source for CLI and MCP. |

## Benchmark API Evidence Snapshot

Checked SHA: `1d454632ba73911bc4ff0cf0a3fb8ec22227a7a8`

| Evidence | Finding |
|---|---|
| `benchbox/base.py` | Public `BaseBenchmark` remains the beta-public base for top-level wrappers and orchestration helpers; `run_with_platform()` remains the beta-public adapter execution hook. |
| `benchbox/core/base_benchmark.py` | Deprecated internal compatibility base remains distinct; only `benchbox/core/datavault/benchmark.py` and `benchbox/core/tpcds_obt/benchmark.py` import it in production code. |
| `tests/unit/test_wrapper_facades_fast.py` | Wrapper methods are asserted behavior and should not be treated as accidental duplicate reachability. |
| `benchbox/__init__.py` | Top-level package exposes 21 benchmark facades: 7 eager imports and 14 lazy `_BENCHMARK_REGISTRY` entries. |
| `benchbox/core/benchmark_loader.py` | Loader is registry-backed and internal; it resolves 23 core benchmark families from `CORE_BENCHMARK_CLASS_NAMES`. |
| `benchbox/core/benchmark_registry.py` | Registry has 23 benchmark metadata entries; public discovery hides only `joinorder_synthetic`, leaving 22 public entries. |
| `docs/reference/backward-compatibility.md` | Compatibility row now records the legacy core base as a retained internal base with a migration target rather than a public extension path. |
