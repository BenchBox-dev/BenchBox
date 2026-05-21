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
| Top-level Python wrapper facades, for example `benchbox.TPCH(...)` | `beta-public` | benchmark-api | Wrapper imports and facade methods covered by `tests/unit/test_wrapper_facades_fast.py` remain supported. | Registry row in `docs/reference/backward-compatibility.md`, migration to canonical API, beta-cycle review. | `uv run -- python -m pytest tests/unit/test_wrapper_facades_fast.py -q` | `benchbox/__init__.py`, top-level wrapper modules, wrapper facade tests |
| `benchbox.base.BaseBenchmark` | `beta-public` | core-runtime | Public base for wrapper benchmarks and orchestration helpers; result helper compatibility is tracked. | Compatibility registry row when kwargs, result helpers, or method contracts change. | Runtime contract and wrapper tests. | `benchbox/base.py`, `docs/reference/backward-compatibility.md` |
| `BaseBenchmark.run_with_platform` | `beta-public` | core-runtime | Standard programmatic execution hook for CLI-adjacent tools and MCP; callers pass an adapter and run options. | ADR or contract-map update before replacing it as the orchestration API. | MCP benchmark tests plus runtime contract tests. | `benchbox/base.py`, `_project/DONE/mcp-integration/active/refactor-mcp-use-public-api.yaml` |
| `benchbox.core.base_benchmark.BaseBenchmark` | `deprecated` | core-runtime | Internal compatibility base retained while remaining core benchmarks migrate. | Remove only after the compatibility registry target is satisfied. | Backward-compatibility registry review and benchmark loader/runtime tests. | `benchbox/core/base_benchmark.py`, `docs/reference/backward-compatibility.md` |
| Adapter subclassing hooks and base mixins | `beta-public` | platform-runtime | Adapter authors can depend on documented `PlatformAdapter` hooks, ABC signatures, and adapter authoring docs. | Adapter refactor map update, migration note, and representative adapter tests. | `tests/unit/platforms/test_abc_conformance.py`, focused adapter tests. | `benchbox/platforms/base/`, `docs/development/adapter-refactor-map.md`, `docs/development/adding-new-platforms.md` |
| Platform registry metadata | `beta-public` | platform-runtime | Registry metadata is the source for platform discovery, capabilities, dependency hints, and future support status. | Same-PR metadata/docs migration; aliases require compatibility note. | Platform registry tests and docs drift checks. | `benchbox/core/platform_registry.py` |
| MCP tools | `beta-public` | mcp | Tool schemas and documented parameters are supported as an automation/control-plane surface. MCP must not import CLI command internals. | MCP reference update and contract tests; product-tier changes need a decision note. | `tests/unit/mcp/`, MCP docs/schema checks. | `benchbox/mcp/`, `docs/reference/mcp.md` |
| Result JSON bundles | `beta-public` | results | Schema-versioned result bundles are product data consumed by CLI, submission validation, hosted results, and explorer. | Schema policy and hosted-results contract update before changing accepted versions or field semantics. | Result schema policy, loader, normalizer, submission, and explorer tests. | `benchbox/core/results/schema_policy.py`, `benchbox/core/results/schema.py`, `docs/reference/result-formats.md`, `docs/reference/hosted-results-contract.md` |
| Explorer read model and generated browser inputs | `generated` | results-explorer | Browser data stores are generated from accepted result bundles; generated outputs should be reproducible from source bundles and pipeline code. | Read-model version bump or pipeline contract update. | Explorer pipeline contract tests and browser release gates. | `_project/scripts/explorer_pipeline/`, results explorer generated data |
| Public submission validator behavior | `beta-public` | hosted-results | PR-based public result submissions must receive deterministic validation errors and privacy/trust handling. | Hosted-results contract update and validator tests. | `validate-submission` workflow, submission validator tests. | `scripts/validate_submission.py`, `docs/contributing-results.md`, `docs/reference/hosted-results-contract.md` |
| SQL compatibility rule catalog | `internal` | sql-compat | Current catalog is governance and transformation metadata; downstream TODOs decide which parts are authoritative runtime behavior. | sql_compat README and contract-map update before claiming broader enforcement. | `make compat-docs-check`, `benchbox.sql_compat.inventory`. | `benchbox/sql_compat/`, `docs/compat/` |
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

Follow-up migrations should add exactly one `support_status` to every platform
and benchmark registry entry. Until that lands, count claims in user-facing docs
must either be generated/checked from registry metadata or explicitly marked as
editorial summaries.

## Count and Drift Policy

Evidence snapshot at `8937681`:

| Source | Current evidence | Contract implication |
|---|---|---|
| `benchbox.core.benchmark_registry` | 23 benchmark metadata entries and 23 loader-resolved IDs. | Benchmark count claims must derive from registry metadata or avoid exact counts. |
| `benchbox.core.platform_registry.PlatformRegistry.get_all_platform_metadata()` | 50 platform metadata entries: 45 SQL-capable, 19 DataFrame-capable, 14 dual-mode. | README and platform docs must not carry unqualified hand-maintained platform counts. |
| `benchbox.core.results.schema_policy` | Current result schema version: `2.1`; runtime/explorer accepted versions: `2.0`, `2.1`; public submission accepts numeric `2.x`. | Result schema version claims must update with the named consumer policy or defer to this policy module. |
| `README.md` before this TODO | Landing-page bullets claimed 22 benchmarks, 42 SQL platforms, and 9 DataFrame platforms. | Exact counts were stale relative to registry metadata; README now links to this policy instead of being authoritative. |

Authoritative count statements should come from registry metadata once the
support-status migration lands. Editorial lists may remain in narrative docs,
but they must not claim to be exhaustive unless a generated or tested check keeps
them synchronized.

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
