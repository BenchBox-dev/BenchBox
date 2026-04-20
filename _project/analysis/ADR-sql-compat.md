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

### Typed Action Payloads

`CompatibilityDecision.payload` is a typed union — not `dict[str, Any]` — so that `frozen=True`
is valid (all payload types are frozen and hashable) and downstream code can pattern-match on
payload type instead of string keys. Callables are referenced by `transformer_id` (a registry
lookup key) rather than inline functions, which keeps payloads serializable.

```python
from __future__ import annotations
from dataclasses import dataclass
from typing import Union

@dataclass(frozen=True)
class BlockBenchmarkPayload:
    reason: str

@dataclass(frozen=True)
class SkipQueryPayload:
    reason: str
    query_id: str

@dataclass(frozen=True)
class SelectVariantPayload:
    variant_key: str   # key into the benchmark's variant dict (e.g. "clickhouse")
    variant_sql: str   # the actual SQL text already in the target dialect

@dataclass(frozen=True)
class RewriteQueryPayload:
    transformer_id: str   # registry key → Callable[[str], str] at runtime
    description: str

@dataclass(frozen=True)
class RewriteDDLPayload:
    transformer_id: str   # registry key → Callable[[str], str] at runtime
    description: str

@dataclass(frozen=True)
class SetSessionPolicyPayload:
    settings: tuple[tuple[str, str], ...]   # key-value pairs emitted before query
    issue_url: str | None                   # link documenting why AST rewrite is not viable

@dataclass(frozen=True)
class PostTranslatePayload:
    transformer_id: str   # registry key → Callable[[str], str] at runtime
    description: str

# NATIVE action carries no payload — use None
CompatPayload = Union[
    BlockBenchmarkPayload,
    SkipQueryPayload,
    SelectVariantPayload,
    RewriteQueryPayload,
    RewriteDDLPayload,
    SetSessionPolicyPayload,
    PostTranslatePayload,
    None,  # NATIVE
]
```

### CompatibilityDecision

```python
@dataclass(frozen=True)
class CompatibilityDecision:
    rule_id: str              # "{phase}.{platform}.{scope}.{slug}"
    action: CompatAction
    support_level: SupportLevel
    failure_mode: FailureMode
    payload: CompatPayload    # typed per action; None for NATIVE
    reason: str               # human-readable rationale
```

### Structured Capability Example — StarRocks PK

Capabilities are **not** bare booleans. The StarRocks PK rule is the canonical example of why:
StarRocks silently ignores PKs whose columns are not the first N columns of the table.

```python
# Expressed as a CompatibilityDecision with a typed, hashable payload:
CompatibilityDecision(
    rule_id="schema_emit.starrocks.pk.first_n_columns_only",
    action=CompatAction.REWRITE_DDL,
    support_level=SupportLevel.DEGRADED,
    failure_mode=FailureMode.SILENT_CORRUPTION,
    payload=RewriteDDLPayload(
        transformer_id="starrocks.pk_reorder_or_drop",
        description=(
            "Reorders PK columns to be first N in the table or drops the PK "
            "if reordering is not possible. StarRocks accepts PRIMARY KEY DDL "
            "but silently ignores PKs that violate the first-N-columns rule."
        ),
    ),
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
- `schema_emit.starrocks.write_primitives.pk_lock_table_unsupported`
- `schema_emit.datafusion.write_primitives.pk_lock_table_unsupported`
- `query_adapter.clickhouse.tpch.subquery_alias_session_policy`

Note: the write_primitives lock-bypass at `benchmark.py:171` is a DDL operation (creating a lock
table with a PRIMARY KEY column) performed during setup — it is a `schema_emit` decision, not a
`benchmark_gate` one. `benchmark_gate` is reserved for pre-run blocking of an entire
platform×benchmark combination before any execution begins.

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

### Granularity Rule

`@compat_local` exempts **all** dialect branches within the decorated callable. This means:

- **Apply at the narrowest scope possible.** Decorate a helper that only does type mapping, not a
  top-level function that mixes type mapping with a PK-policy branch. If a function contains both a
  legitimate local branch and an unregistered compatibility-policy branch, split it into two
  callables before applying the decorator.
- **Mixed-branch functions are a lint error even if decorated.** If a `@compat_local`-decorated
  function contains a branch that matches a `kind` not covered by the decorator arguments (e.g., a
  `schema_emit`-style branch inside a `kind="type_mapping"` function), the linter must flag it as
  a misuse of the decorator. The decorator's `kind` is an assertion, not a blanket exemption.

### Linter Attribution Rule

The lint rule (`scripts/compat_lint.py`) fires when: a dialect-branch (`if dialect`,
`if "platform" in dialect`, etc.) appears inside `benchbox/core/` or `benchbox/benchmarks/` AND
the containing callable is not `@compat_local`-decorated (with a matching `kind`) AND has no
registered rule for the detected platform × phase combination.

The linter ships **warn-only** (exit 0) in `w4` and is promoted to **error** (exit 1) at the end
of `w15` (after schema-generation branches are classified).

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

## CLI Preflight (benchmark_gate phase)

`benchmark_gate` decisions are resolved at CLI preflight inside
`_check_benchmark_platform_compatibility()` (`cli/commands/run.py:804`), **before** the SQL or
DataFrame pipeline runs. This is the only place where `block_benchmark` fires.

```
CLI run command
    │
    └── _check_benchmark_platform_compatibility()
            │
            └── Resolver(CompatibilityContext(phase=benchmark_gate, ...))
                    │
                    ├── BLOCK_BENCHMARK → print error, exit(1)
                    └── NATIVE          → continue to execution
```

The `caps.unsupported_benchmarks` field on `PlatformCapability` becomes a view computed from
registry `benchmark_gate` rules (implemented in `w16`). Until then, `w9` wires the CLI preflight
to consult the registry for PK-requiring benchmarks.

## SQL Pipeline Head

The SQL pipeline head sits at `platforms/base/execution.py` (query execution entry point). It
receives a `CompatibilityContext` and consults the registry before running a query. It handles
query-execution phases only (`query_source`, `query_compile`, `query_adapter`,
`execution_filter`); `benchmark_gate` is handled at CLI preflight above.

```
┌──────────────┐    CompatibilityContext     ┌─────────────┐
│ execution.py │ ──────────────────────────▶ │   Resolver  │
│ (SQL head)   │ ◀── CompatibilityDecision── │             │
└──────────────┘                             └─────────────┘
        │
        ├── SKIP_QUERY       → skip, log
        ├── SELECT_VARIANT   → use variant_sql from payload, bypass sqlglot
        ├── SET_SESSION_POLICY → emit settings, then run query
        ├── REWRITE_QUERY    → apply transformer (via transformer_id), then run
        ├── POST_TRANSLATE   → apply transformer after sqlglot pass
        └── NATIVE           → run original SQL unchanged
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
- Version-gated rules (rules with a `platform_version` constraint satisfying
  `context.platform_version`) take precedence over rules without a version constraint.
- If `context.platform_version is None`, no version-gated rule fires for that context; the
  non-versioned rule at the same tier applies. This is the explicit fallback: unknown version →
  non-versioned behavior, never version-gated.

If two rules at the same specificity level produce conflicting actions for the same context, it is
a registry error and the resolver raises `CompatibilityRegistryConflict`.

### Multi-Action Composition

**A query may require multiple compatibility actions in a single execution pass — one per phase.**
The pipeline calls the resolver independently at each phase, so actions compose sequentially:

```
query_source    → SELECT_VARIANT (pick H2O Q9 ClickHouse constant)
query_compile   → NATIVE (variant is already in target dialect, skip sqlglot)
query_adapter   → SET_SESSION_POLICY (joined_subquery_requires_alias=0)
execution_filter → NATIVE
```

Within a single phase, **at most one action fires** per (platform, benchmark, query_id) tuple.
If two rules at the same specificity level match the same phase context, it is a registry error
(raised as `CompatibilityRegistryConflict`).

The composition rule means there is never a need for a "combined" rule that does both a rewrite and
a session policy in one action — split them across `query_compile` and `query_adapter` instead.

---

## CompilationPlan

The resolver pre-computes a `CompilationPlan` at run start for each (platform, benchmark) pair and
caches it in the benchmark execution context. Warmup, power, and throughput phases reuse the same
plan without re-querying the registry.

```python
from __future__ import annotations
from dataclasses import dataclass, field

@dataclass(frozen=True)
class PhasedDecision:
    """One resolved decision keyed by (query_id | None, Phase)."""
    query_id: str | None
    phase: Phase
    decision: CompatibilityDecision

@dataclass
class CompilationPlan:
    platform: str
    benchmark: str
    # Outer key: query_id (None = applies to all queries in this phase)
    # Inner key: Phase
    # Value: the winning CompatibilityDecision after specificity resolution
    decisions: dict[tuple[str | None, Phase], CompatibilityDecision] = field(default_factory=dict)

    def get(self, query_id: str | None, phase: Phase) -> CompatibilityDecision | None:
        """Return the decision for (query_id, phase), falling back to (None, phase)."""
        return self.decisions.get((query_id, phase)) or self.decisions.get((None, phase))
```

`CompilationPlan` is not frozen because it is populated incrementally by the resolver during plan
construction. Once the resolver hands it to the benchmark runner it must not be mutated; the
runner enforces this by not retaining a reference to the resolver.

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
  "rule_id": "schema_emit.starrocks.write_primitives.pk_lock_table_unsupported",
  "platform": "starrocks",
  "benchmark": "write_primitives",
  "query_id": null,
  "phase": "schema_emit",
  "legacy_outcome": "NATIVE",
  "registry_outcome": "REWRITE_DDL"
}
```

The `rule_id` prefix must always match the `phase` field — both reflect the
`CompatibilityContext.phase` used when the resolver was called. A null `rule_id` is valid when the
registry has no matching rule (registry outcome = "no_decision").

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
