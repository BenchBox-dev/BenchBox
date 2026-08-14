# ADR: Core Kernel and Runtime Composition Boundary

## Status

Accepted. This decision gates the architecture-simplification program's
composition work. It does not authorize a repo-wide import migration or a
production adapter fold in this item.

## Date

2026-08-13

## Context

BenchBox declares the layering `utils < core < platforms < cli` in
`.importlinter`. The current implementation has approximately 34 allowlisted
core-to-platforms edges. The most important split is already visible in the
run service: `benchbox.core.run_service.execute_run(...)` receives an
`AdapterFactory`, while `benchbox.core.runner.runner` still imports
`get_platform_adapter` directly at its module boundary and retains a fallback
lookup in `_configure_lifecycle_adapter(...)`.

The choice is between two composition models:

- **Option A — core is the kernel.** Core owns contracts, lifecycle policy, and
  platform-neutral primitives. Platform construction, connection details, and
  platform-specific behavior arrive through protocols, callbacks, or injected
  factories. Allowlisted edges are removed in dependency order.
- **Option B — `benchbox.runtime` is the composition layer.** Add a new package
  above both `core` and `platforms` and move orchestration and dependency
  assembly there. `benchbox.runtime` does not exist today.

The SQL execute/validate edge is a useful decision test because two existing
primitives already disagree:

| Incumbent | Current boundary | Observable behavior |
|---|---|---|
| `CursorValidationQueryExecutionMixin` in `benchbox/core/benchmark_mixins.py` | Core mixin inherited by Firebolt and Presto-family adapters | Always creates and closes `connection.cursor()`, attaches shared query statistics/resource usage, logs validation PASS/FAIL, does not rollback, and does not emit a result digest. |
| `execute_sql_query` in `benchbox/platforms/base/sql_execution.py` | Platform-layer helper called by Psycopg, MySQL-wire, QuestDB, and StarRocks paths | Accepts a connection or pre-created cursor, rolls back failures, emits the canonical legacy result through `QueryExecution`, supports the gated result digest, and does not attach the mixin's PASS/FAIL log or query-statistics fields. |

Folding either implementation into the other without first choosing its home
layer would silently change cursor ownership, transaction recovery, result
shape, or validation observability.

## Decision

Choose **Option A: core is the kernel**.

The canonical SQL execute/validate primitive will live in the **core layer**,
behind a small protocol and injected hooks for platform-specific concerns. The
platform layer may supply connection/cursor acquisition, query rewriting, and
platform query-statistics hooks, but it must not own a competing generic SQL
execution implementation. The canonical behavior must be assembled from the
characterized requirements: pre-created-cursor support, rollback after failed
DB-API execution, canonical `QueryExecution` result conversion, gated result
digests, query statistics/resource usage, and explicit validation logging.

This is a target boundary, not a production fold in this ADR. The executable
prototypes in
`tests/unit/platforms/test_composition_boundary_sql_prototypes.py` preserve the
current two behaviors and make their deltas visible before a later migration.
The runner prototype in
`tests/unit/core/runner/test_composition_boundary_runner_prototype.py` proves
that `run_service.AdapterFactory` and a prebuilt adapter can cross the core
boundary without a platform import at the call site.

`benchbox.runtime` is **not introduced**. The existing run service already
provides the needed composition seam; adding a third package would create a
new public-looking boundary, move rather than remove the allowlisted edges,
and require a second orchestration migration before the SQL primitive can be
made canonical.

## Prototype findings

### SQL execute/validate edge

The core-mixin prototype and platform-injected-function prototype both execute
the same fake DB-API query. The tests prove that they cannot be considered
behaviorally interchangeable today:

1. The core mixin owns and closes a newly created cursor and attaches
   `query_statistics` and `resource_usage` to a successful result.
2. The platform helper can run on a pre-created stream cursor and leaves cursor
   ownership with its caller.
3. The platform helper rolls back a failed query; the core mixin returns a
   failure without rolling back.
4. The core mixin has validation PASS/FAIL logging hooks; the platform helper
   has the result-digest and canonical `QueryExecution` path.

The migration must therefore be characterization-first and must name every
intentional result-field, logging, cursor-lifecycle, and rollback change in
its own implementation PR.

### Runner edge

`run_service.execute_run(...)` already receives and invokes `AdapterFactory`
before calling `run_benchmark_lifecycle(..., platform_adapter=adapter)`. The
runner prototype passes a prebuilt adapter through
`_configure_lifecycle_adapter(...)` while making a fallback factory call fail;
the explicit injection path succeeds. This is the first deletion target for
the runner's direct `get_platform_adapter` dependency, but the fallback remains
until all direct lifecycle callers are migrated or an explicit compatibility
policy is approved.

## Allowlist deletion order

Deletion is ordered by fan-out and by the availability of an existing injected
replacement. Each edge is removed only after a focused contract test proves the
replacement path and `make lint-imports` is green.

1. **Runner composition edges.** Migrate all lifecycle callers to the
   `AdapterFactory`/prebuilt-adapter seam, then remove
   `benchbox.core.runner.runner -> benchbox.platforms` and its fallback lookup
   at `runner.py:1132`. Next move the runner's format-capability, runtime
   metadata, and DataFrame phase imports behind core protocols or injected
   policy objects.
2. **Generic loading and write-primitives edges.** Replace direct imports from
   `benchbox.platforms.base.data_loading` in core DataFrame and write-primitives
   code with core-owned loader contracts and platform-provided implementations.
   Migrate the DuckDB and PySpark maintenance edges only with behavior tests for
   file formats, table modes, and maintenance semantics.
3. **Core dry-run, comparison, and DataFrame maintenance edges.** Introduce
   narrow capability/result protocols for `dryrun`, comparison/equivalence, and
   DataFrame maintenance consumers. Do not remove an allowlist entry merely
   because an import becomes lazy; the dependency direction must change.
4. **Registry and benchmark-specific equivalence edges last.** The platform
   registry/factory, platform capability projections, and benchmark-specific
   equivalence adapters have the highest fan-out and the greatest compatibility
   risk. Retain their explicit allowlist entries until their replacement
   contracts and public registry counts are independently verified.

No `.importlinter` ignore is deleted by this ADR. The ordered removal belongs to
later implementation items, one validated boundary at a time.

## Alternatives rejected

### Option B — introduce `benchbox.runtime`

Rejected for this program. It is greenfield, has no current consumer that sits
above both core and platforms, and would add a third composition vocabulary
while the existing `run_service.AdapterFactory` seam is still underused. It
would also postpone the concrete SQL decision rather than resolve it. Revisit
only if a measured requirement demonstrates that a composition layer must own
state or policy that cannot live in core without importing platform modules.

### Mechanical `benchbox.core` package split

Rejected. The benchmark-family plugin seam already rejects moving files without
first establishing dependency direction. This ADR chooses a boundary and an
allowlist order; it does not turn directory movement into an architecture.

### Keep both SQL primitives as specialized variants

Rejected for the generic path. Platform-specific query rewrites and statistics
hooks remain valid extension points, but two generic execute/validate cores
would preserve the current drift in rollback, cursor ownership, result fields,
and validation logging.

## Consequences

Positive:

- Core remains the reusable engine below CLI and MCP, consistent with the
  one-engine decision in
  [`adr-one-engine-scoped-surfaces.md`](adr-one-engine-scoped-surfaces.md).
- The SQL edge gets one future home and a concrete characterization suite
  before behavior changes.
- The existing `AdapterFactory` seam becomes the first practical allowlist
  deletion path without introducing a new package.

Costs and safeguards:

- The eventual SQL migration must reconcile real behavior, not just imports;
  rollback, cursor lifetime, digest gates, query statistics, and validation
  messages require explicit compatibility tests.
- The core layer gains a small protocol surface and must stay free of concrete
  platform imports. `make lint-imports` remains a required gate for every
  deletion wave.
- Until the later migration lands, the two incumbents remain intentionally
  present and their divergence is documented rather than hidden.

## Follow-up ownership

- `arch-canonical-sql-execute-primitive` owns the later canonical SQL helper
  implementation after this ADR is merged.
- `arch-ssb-family-plugin-seam-pilot` may use the same core-kernel boundary but
  must not introduce `benchbox.runtime` or a third execution helper.
- `arch-retire-compat-surfaces` owns compatibility cleanup that is independent
  of this decision; it must not delete the reserved dataframe-runner stub
  before its own `is_dataframe_execution` migration is complete.
