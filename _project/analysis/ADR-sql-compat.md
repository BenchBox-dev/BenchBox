# ADR: sql_compat Phase-Aware Compatibility Pipeline

**Status**: Proposed
**Date**: 2026-04-20
**Workstream**: `build-sql-compat-phase-aware-pipeline`

---

## Context

BenchBox's SQL compatibility decisions are currently scattered across structurally different sites
that disagree with each other:

| Site | Kind | Problem |
|------|------|---------|
| `dialect_utils.py:108` `translate_sql_query()` | Translation core A | Full-featured: identify policy, SQLite fixups, GROUP BY ALL restoration, pre/post processors |
| `dialect_translation.py:33` `DialectTranslationMixin.translate_sql()` | Translation core B | Bare `sqlglot.transpile`, no identify, no processors, default source = "duckdb" not "netezza" |
| `write_primitives/benchmark.py:171` | Lock bypass | Skips PK lock for `("datafusion","clickhouse","starrocks")` |
| `transaction_primitives/benchmark.py:149` | Lock bypass | Skips PK lock for `("datafusion","clickhouse")` — StarRocks **silently missing** |
| `write_primitives/schema.py:352` `_supports_primary_keys()` | PK predicate | Only excludes `datafusion` — ClickHouse and StarRocks pass as PK-capable |
| `transaction_primitives/schema.py:130` | DDL emit | Unconditional PRIMARY KEY emission — no platform guard |
| `clickhouse/query_transformer.py:47` | Query adapter | `add_subquery_aliases` disabled (regex corrupts Q23/Q87); `joined_subquery_requires_alias=0` session setting used instead |
| `h2odb/benchmark.py:106-141` | Variant selection | `_CLICKHOUSE_Q9`, `_STARROCKS_Q9` class constants replace Q9 wholesale for PERCENTILE syntax |
| `nyctaxi/schema.py`, `tsbs_devops/schema.py` | Schema-gen | `dialect ==` branches mixing type-mapping (legitimate local) with compatibility policy |
| `cli/commands/run.py:804` | Benchmark gate | Reads `caps.unsupported_benchmarks` from PlatformRegistry |
| `vector_search/queries.py` | Query source | `QUERY_VARIANTS` dict — non-sqlglot, non-catalog, platform-version-gated variants |

The net effect: the same capability question (e.g., "does this platform enforce PK uniqueness?") has
three different answers depending on which code path asks, and some answers are silent-corruption
failure modes. StarRocks accepts PRIMARY KEY DDL but silently ignores PKs whose columns are not the
first N columns of the table — a boolean `_supports_primary_keys()` cannot represent this.

---

## Decision

Build a `benchbox/sql_compat/` package that centralizes compatibility decision ownership. The
package defines a typed rule engine that produces `CompatibilityDecision` objects across every
decision point. Existing query-storage shapes (catalog-backed managers, dict-based managers,
`QUERY_VARIANTS`) are **preserved** — the engine plugs in behind each manager as a resolver.
Migration lands behind a `BENCHBOX_COMPAT_REGISTRY` feature flag with a dual-run harness.

### Non-Goals

- **Query-storage format unification** (H2O/CoffeeShop dict managers → catalog): deferred to a
  separate future ADR. The decision engine must work behind the existing managers without requiring
  storage migration.
- sqlglot version upgrade or replacement
- New platform or benchmark additions within this workstream
- Result schema or visualization changes
- Polars/Pandas compatibility beyond DataFrame pipeline-head skip/variant actions

---

## Phase Taxonomy

### Derivation Protocol

The phase list below is **provisional**. The `w2` inventory tool will walk the codebase and classify
every dialect-branching decision point. Before any implementation slice begins, the inventory output
(`_project/compat/inventory.jsonl`) is reviewed and these phases are amended if the inventory
surfaces decision shapes that do not fit the provisional taxonomy. The ADR is updated and the
amended phase list is frozen before `w5` (engine scaffold) begins.

Acceptance criteria for freezing: the inventory must successfully classify at minimum:
- The `benchmark_gate` site at `cli/commands/run.py:804`
- The `QUERY_VARIANTS` / version-gated site at `core/vector_search/queries.py`

### Provisional Phase List

| Phase | When it runs | Applicable actions |
|-------|-------------|-------------------|
| `benchmark_gate` | Pre-run preflight, before any execution | `block_benchmark`, `native` |
| `query_source` | Query retrieval — selecting which SQL text to use | `select_variant`, `native` |
| `query_compile` | sqlglot transpile pass | `rewrite_query`, `post_translate`, `native` |
| `query_adapter` | Post-compile per-query platform adjustment | `rewrite_query`, `set_session_policy`, `native` |
| `schema_emit` | DDL generation (`CREATE TABLE`, PK decisions) | `rewrite_ddl`, `native` |
| `ddl_optimize` | Platform-specific DDL transformations | `rewrite_ddl`, `native` |
| `execution_filter` | Per-query skip decision at SQL execution time | `skip_query`, `native` |
| `dataframe_filter` | Per-query skip decision at DataFrame execution time | `skip_query`, `native` |

**Session policy is an action, not a phase.** `set_session_policy` is emitted by a rule in
`query_adapter` phase. It is not promoted to its own phase unless the `w2` inventory demonstrates a
case where session-policy decisions must fire independently of query-adapter decisions.

**`post_translate` is an action within `query_compile`**, not a separate phase. Post-processors
applied after sqlglot transpile are part of the compile pass.

**`dataframe_filter` is intentionally distinct from `execution_filter`**: DataFrame-mode skip
decisions share the registry but use a different pipeline head and different action payloads. Two
pipeline heads share the registry; they do not share actions.

---

## Action Vocabulary

Eight actions cover the full decision surface. Every rule produces exactly one action.

| Action | Enum value | Payload fields | Description |
|--------|-----------|---------------|-------------|
| `block_benchmark` | `CompatAction.BLOCK_BENCHMARK` | `reason: str` | Prevent this benchmark from running on this platform |
| `skip_query` | `CompatAction.SKIP_QUERY` | `reason: str`, `query_id: str` | Exclude a query from execution |
| `select_variant` | `CompatAction.SELECT_VARIANT` | `variant_key: str`, `source: str` | Use a pre-written alternative SQL text |
| `rewrite_query` | `CompatAction.REWRITE_QUERY` | `transformer: Callable[[str], str]`, `description: str` | Apply an AST or string transform to the query |
| `rewrite_ddl` | `CompatAction.REWRITE_DDL` | `transformer: Callable[[str], str]`, `description: str` | Apply a transform to a DDL statement |
| `set_session_policy` | `CompatAction.SET_SESSION_POLICY` | `settings: dict[str, Any]`, `issue_url: str \| None` | Emit session settings before query execution; `issue_url` documents why an AST rewrite was not possible |
| `post_translate` | `CompatAction.POST_TRANSLATE` | `transformer: Callable[[str], str]`, `description: str` | Apply a fix after sqlglot transpile (e.g., GROUP BY ALL restoration) |
| `native` | `CompatAction.NATIVE` | — | No modification needed; short-circuits sqlglot for this decision |

`NATIVE` decisions short-circuit sqlglot. `REPLACED` (select_variant) decisions also short-circuit
sqlglot — the variant SQL is already in the target dialect.

---

## Typed Contract

### CompatibilityContext

```python
from __future__ import annotations
from dataclasses import dataclass
from typing import Literal

@dataclass(frozen=True)
class CompatibilityContext:
    platform: str           # e.g. "starrocks", "clickhouse"
    platform_version: str | None  # e.g. "3.2.1"; None if not known
    benchmark: str          # e.g. "h2odb", "write_primitives"
    query_id: str | None    # e.g. "Q9"; None for non-query phases
    phase: Phase            # one of the provisional Phase enum values
    mode: Literal["sql", "dataframe"]
    dialect: str | None     # sqlglot dialect string; None for non-SQL paths
```

### SupportLevel

```python
class SupportLevel(str, Enum):
    NATIVE      = "NATIVE"       # works without modification
    TRANSLATED  = "TRANSLATED"   # requires sqlglot translation
    REWRITTEN   = "REWRITTEN"    # requires additional AST/string rewrite
    DEGRADED    = "DEGRADED"     # runs but with different semantics
    SKIPPED     = "SKIPPED"      # excluded from this platform
    BLOCKED     = "BLOCKED"      # platform×benchmark combination unsupported
```

### FailureMode

```python
class FailureMode(str, Enum):
    NONE                 = "NONE"       # no failure expected
    SYNTAX_ERROR         = "SYNTAX_ERROR"
    SILENT_CORRUPTION    = "SILENT_CORRUPTION"   # runs, wrong results (e.g. StarRocks PK)
    UNSUPPORTED_FEATURE  = "UNSUPPORTED_FEATURE"
    PERFORMANCE_REGRESSION = "PERFORMANCE_REGRESSION"
```

### CompatibilityDecision

```python
from dataclasses import dataclass, field
from typing import Any

@dataclass(frozen=True)
class CompatibilityDecision:
    rule_id: str                          # "{phase}.{platform}.{scope}.{slug}"
    action: CompatAction
    support_level: SupportLevel
    failure_mode: FailureMode
    payload: dict[str, Any]              # action-specific; see action vocab above
    reason: str                           # human-readable rationale
```

### Structured Capability Example — StarRocks PK

Capabilities are **not** bare booleans. The StarRocks PK rule is the canonical example of why:
StarRocks silently ignores PKs whose columns are not the first N columns of the table.

```python
# Expressed as a CompatibilityDecision with structured payload:
CompatibilityDecision(
    rule_id="schema_emit.starrocks.pk.first_n_columns_only",
    action=CompatAction.REWRITE_DDL,
    support_level=SupportLevel.DEGRADED,
    failure_mode=FailureMode.SILENT_CORRUPTION,
    payload={
        "condition": "pk_cols_must_be_first_n_columns",
        "enforcement": "accepts_ddl_silently_ignores",
        "transformer": "_starrocks_pk_reorder_or_drop",
    },
    reason=(
        "StarRocks accepts PRIMARY KEY DDL but silently ignores PKs unless "
        "the PK columns are the first N columns of the table. A boolean "
        "pk.uniqueness_enforced cannot express this condition."
    ),
)
```

---

## rule_id Format

```
{phase}.{platform}.{scope}.{slug}
```

| Field | Constraints | Examples |
|-------|-------------|---------|
| `phase` | Lowercase phase name | `schema_emit`, `query_source`, `benchmark_gate` |
| `platform` | Platform key (lowercase) | `starrocks`, `clickhouse`, `datafusion` |
| `scope` | Benchmark name or capability area | `h2odb`, `write_primitives`, `pk`, `tpch` |
| `slug` | Snake-case description of the rule | `first_n_columns_only`, `q9_percentile_syntax`, `lock_bypass` |

Examples:
- `schema_emit.starrocks.pk.first_n_columns_only`
- `query_source.clickhouse.h2odb.q9_percentile_syntax`
- `query_source.starrocks.h2odb.q9_percentile_syntax`
- `benchmark_gate.starrocks.write_primitives.lock_bypass`
- `query_adapter.clickhouse.tpch.subquery_alias_session_policy`
- `execution_filter.datafusion.write_primitives.pk_lock_unsupported`

---

## @compat_local Decorator

The `@compat_local` decorator is an attribution mechanism so the inventory linter can distinguish
**legitimate platform-specific rendering** (type mapping, storage layout) from unregistered
compatibility policy. It does not suppress compatibility decisions — it exempts a callable from the
lint rule that requires all dialect branches inside `benchbox/core/` or `benchbox/benchmarks/` to
be registered.

```python
def compat_local(
    kind: Literal["type_mapping", "storage_layout", "rendering"],
    platform_specific: bool,
    reason: str,
) -> Callable:
    """Mark a callable as containing legitimate local platform-specific rendering.

    This exempts the callable from the compat_lint "unregistered dialect branch" rule.
    It does NOT register a rule in the registry.

    Args:
        kind: Category of local rendering — type_mapping, storage_layout, or rendering
        platform_specific: True if the branch is specific to one platform
        reason: Why this is legitimate local rendering, not unregistered policy
    """
```

### When to Use @compat_local vs Register a Rule

| Situation | Use |
|-----------|-----|
| Type mapping (`INT` → `INT32`, `FLOAT` → `DOUBLE`) | `@compat_local(kind="type_mapping")` |
| Storage layout (columnar store specifics, engine selection) | `@compat_local(kind="storage_layout")` |
| Identifier rendering (quoting style, case folding) | `@compat_local(kind="rendering")` |
| Query behavior difference (`GROUP BY ALL` → keyword restore) | Register in registry |
| PK enforcement semantics | Register in registry |
| Query skip or variant selection | Register in registry |
| DDL correctness (drop FK, reorder PK cols) | Register in registry |

### Linter Attribution Rule

The lint rule (`scripts/compat_lint.py`) fires when: a dialect-branch (`if dialect`, `if "platform" in dialect`, etc.) appears inside `benchbox/core/` or `benchbox/benchmarks/` AND the containing callable is not `@compat_local`-decorated AND has no registered rule for the detected platform × phase combination.

The linter ships **warn-only** (exit 0) in `w4` and is promoted to **error** (exit 1) at the end of
`w15` (after schema-generation branches are classified).

---

## Baseline Schema v1

The baseline artifact (`_project/compat/baseline.v1.jsonl`) records the pre-migration behavior of
every (platform, benchmark, query_id, phase) tuple that has a compatibility decision. It is the
parity baseline for dual-run shadow-mode divergence review.

### Record Shape

```json
{
  "schema_version": 1,
  "platform": "starrocks",
  "benchmark": "h2odb",
  "query_id": "Q9",
  "phase": "query_source",
  "mode": "sql",
  "source_sql_hash": "sha256:abc123...",
  "decision": "REWRITTEN",
  "rule_id": null,
  "final_sql_hash": "sha256:def456...",
  "benchmark_gate_outcome": null
}
```

Fields:
- `schema_version`: integer; increment when the shape changes
- `source_sql_hash`: SHA-256 of the query text before any compatibility decision
- `decision`: one of the `SupportLevel` enum values
- `rule_id`: null in the baseline (no rules exist yet); populated after registry lands
- `final_sql_hash`: SHA-256 of the query text after decisions; null for non-SQL phases
- `benchmark_gate_outcome`: `"allowed"` | `"blocked"` | null (only for `benchmark_gate` phase)

### Version-Bump Protocol

When the baseline schema changes:
1. Rename old file: `baseline.v{N}.jsonl` → archived
2. Create `baseline.v{N+1}.jsonl` with the new shape
3. Update `baseline_tool.py` to emit the new version
4. Update the dual-run harness to consume the new version
5. No old-version file is deleted until the dual-run harness is removed in `w16`

### Refresh Protocol

The baseline is regenerated whenever:
- A new platform is added to the test suite
- A new benchmark is onboarded that has compatibility decisions
- A rule is registered that changes an existing decision's `SupportLevel`

The `baseline_tool.py` must be idempotent (same inputs → same outputs) so CI can regenerate and
diff to detect drift.

---

## SQL Pipeline Head

The SQL pipeline head sits at `platforms/base/execution.py` (query execution entry point). It
receives a `CompatibilityContext` and consults the registry before running a query.

```
┌──────────────┐    CompatibilityContext     ┌─────────────┐
│ execution.py │ ──────────────────────────▶ │   Resolver  │
│ (SQL head)   │ ◀── CompatibilityDecision── │             │
└──────────────┘                             └─────────────┘
        │
        ├── SKIP_QUERY  → skip, log
        ├── SELECT_VARIANT → use variant SQL, bypass sqlglot
        ├── SET_SESSION_POLICY → emit settings, then run original
        ├── REWRITE_QUERY → apply transformer, then run
        └── NATIVE → run original SQL
```

Actions that apply at the SQL pipeline head: `skip_query`, `select_variant`, `set_session_policy`,
`rewrite_query`, `post_translate`.

The existing `get_platform_skip_queries()` function becomes a thin facade over the registry
(kept for backwards compatibility until `w16`).

---

## DataFrame Pipeline Head

The DataFrame pipeline head sits at `platforms/dataframe/benchmark_mixin.py`. It shares the same
registry but consults it with `mode="dataframe"` in the context. Only `skip_query` and
`select_variant` actions apply; `rewrite_query`, `set_session_policy`, and `post_translate` do not
apply to DataFrame paths (Polars/Pandas retain existing code paths).

The existing `get_df_platform_skip_queries()` function becomes a thin facade over the registry
(kept for backwards compatibility until `w16`).

---

## Specificity Precedence for Rule Resolution

When multiple rules match the same `CompatibilityContext`, the most specific rule wins:

1. `platform + benchmark + query_id` (most specific)
2. `platform + benchmark`
3. `platform` (most general)

Within the same specificity tier:
- Version-gated rules (rules with `platform_version` constraint) take precedence over rules without
  a version constraint, when `context.platform_version` satisfies the gate.

If two rules at the same specificity level produce conflicting actions, it is a registry error and
the resolver raises `CompatibilityRegistryConflict`.

---

## Dual-Run Harness

Feature flag: `BENCHBOX_COMPAT_REGISTRY={off|shadow|on}` (default: `off` until `w5`; `shadow` after
`w6`; `on` after `w16`).

| Mode | Behavior |
|------|---------|
| `off` | Legacy path only. Registry not consulted. |
| `shadow` | Both legacy and registry paths run. Legacy decision is acted on. Registry decision is logged. Divergences written to `_project/compat/divergence.log`. |
| `on` | Registry is authoritative. Legacy path disabled. |

### Divergence Log Shape

```json
{
  "rule_id": "execution_filter.starrocks.write_primitives.lock_bypass",
  "platform": "starrocks",
  "benchmark": "write_primitives",
  "query_id": null,
  "phase": "benchmark_gate",
  "legacy_outcome": "allowed",
  "registry_outcome": "blocked"
}
```

Cut-over to `on` mode is gated on divergence reaching **zero** for each slice's rule_ids across a
full shadow-mode pass before that slice is merged.

---

## Migration Plan (work unit sequence)

See TODO item `build-sql-compat-phase-aware-pipeline` for full work unit breakdown. High-level:

1. **w1** (this ADR) → **w2** (inventory + freeze phase taxonomy) → **w3** (baseline snapshot)
2. **w4** (parallel with w3): `@compat_local` decorator + warn-only linter
3. **w5**: Scaffold `benchbox/sql_compat/` package (no rules yet)
4. **w6**: Dual-run harness + feature flag
5. **Slices w7–w15**: Migrate each decision site behind the harness; merge only after zero divergence
6. **w16**: Cutover — registry authoritative, harness deleted, feature flag removed
7. **w17–w18**: Doc generator + capability matrix

---

## Consequences

### Positive

- Every compatibility decision is auditable: rule_id, support_level, failure_mode, and reason are
  all first-class fields.
- Silent-failure modes (StarRocks PK first-N-columns) are expressed structurally, not as comments.
- New platform/benchmark additions acquire compatibility rules in one place.
- Generated capability matrix (w18) documents platform support levels for users.
- Linter in error mode after w15 prevents future drift.

### Negative / Risks

- Large surface area: 18 work units across ~15 files. Mitigated by feature flag + dual-run harness.
- Snapshot sign-off for Slice A (translation entrypoint unification) requires per-adapter diff
  review; cannot be auto-approved.
- The inventory tool (w2) may surface additional decision sites not listed in `files_affected`,
  expanding scope. New sites must be explicitly triaged before adding to the workstream.
