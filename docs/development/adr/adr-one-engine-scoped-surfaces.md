# ADR: One Engine, Scoped Surfaces — CLI and MCP over a Shared Core

## Status

Accepted. Supersedes the 2026-05-21 decision recorded on the tracker item
`mcp-product-surface-and-shared-run-service-decision`, which designated MCP a
"smoke/control-plane surface, not a CLI-equivalent execution surface".

## Date

2026-08-04

## Context

BenchBox exposes benchmark execution through two surfaces: the `benchbox` Click
CLI and the `benchbox-mcp` MCP server. A CLI/MCP consistency review found that
the two surfaces do not merely differ in breadth — they carry independent
implementations of the same logic:

- Statistics (geometric mean, percentiles, standard deviation) are implemented
  separately in `benchbox/cli/commands/aggregate.py`, in
  `benchbox/mcp/tools/analytics.py`, and in `benchbox/core/results/`.
- Regression thresholds and comparison policy are decided in both surface
  layers rather than in one core policy object.
- Run orchestration lives inside CLI command bodies, so MCP re-derives its own
  narrower orchestration from `BaseBenchmark.run_with_platform()`.

The 2026-05-21 decision answered the *product scope* question ("is MCP
CLI-equivalent?") with "no", and deferred the *architecture* question ("where
does the logic live?") behind that answer. Two things overtook it:

1. The remote/tenant MCP investment (#1447–#1513) turned MCP into a durable,
   authenticated, multi-tenant execution service. "Smoke/control-plane" no
   longer describes what the surface is used for.
2. The duplication produced a recurring defect class in which a request was
   accepted by one half of a pair and rejected or mishandled by the other —
   "schema half closed, adapter half open" (#1513, #1514, #1515, #1520).

Those two facts are independent of the product-scope answer. Whether or not MCP
ever reaches CLI option parity, having two implementations of one behavior is
the actual defect source.

## Decision

**One engine, scoped surfaces.**

1. **One engine.** All benchmark business logic — run orchestration, statistics,
   regression policy, result shaping, thresholds, and constants — lives in
   `benchbox.core`, below both surfaces. Neither `benchbox.cli` nor
   `benchbox.mcp` may own an implementation of behavior the other also needs.
   The existing layering constraints are unchanged and remain enforced:
   `benchbox.core` must not import `benchbox.platforms` or `benchbox.cli`
   (adapters reach core through injected factories), and `benchbox.mcp` must not
   import `benchbox.cli`.

2. **Scoped surfaces.** The two surfaces deliberately expose different subsets
   of that engine. Surface asymmetry is a supported, permanent property of the
   design — not a backlog of missing work and not a bug.

3. **Ledgered asymmetry.** Every control the CLI exposes and MCP does not keeps
   an entry in the omission ledger in
   [`docs/reference/mcp.md`](../../reference/mcp.md), tagged with exactly one of
   three ratified tier reasons. The ledger is the mechanism that prevents silent
   drift: an omission that is not ledgered is a defect, and an omission tagged
   with a tier is a decision.

### Tier semantics

| Tier | Durability | Meaning | Promotion path |
|---|---|---|---|
| `security-scoped` | Permanent | Admitting the control would let a request name credentials, endpoints, filesystem or cloud destinations, or unbounded resources — or would trigger destructive or publishing side effects. The narrow surface is what makes remote/tenant mode safe. | None. Parity never applies to credential, destination, or resource-budget controls. A bounded, typed, server-validated subset may be added to the MCP allow-list, which is a *new* narrow control, not a promotion of the CLI flag. |
| `interaction-scoped` | Permanent | The control governs terminal interaction or presentation (progress bars, verbosity, prompts). It has no meaning in a structured request/response protocol. | None. MCP returns structured JSON; there is no console to configure. |
| `not-yet-demanded` | Provisional | Nothing about security or interaction blocks the control. It is absent because no MCP client has asked for it. | Record a deferral on the `one-engine-parity-ledger` tracker item when a client demands it, then add the parameter. Demand-driven expansion is recorded as a deferral, never as a speculative TODO. |

The tiers are about *why the surface is scoped*, not about implementation
difficulty. Because the engine is shared, adding a `not-yet-demanded` control is
a surface-schema change, not a reimplementation.

### What this decision does not change

- MCP security allow-lists (`MCP_PLATFORM_OPTION_ALLOWLIST`), admission, and
  tenant containment stay at the MCP layer as a pre-filter above the shared
  engine. Parity is a statement about business logic, never about access control.
- MCP protocol-scoped behavior — truncation limits, inline-only ASCII chart
  output, structured-JSON responses — stays at the MCP layer.
- Interactive shells, REPLs, and wizards stay in the CLI layer. They are
  interaction, not engine.
- The result-bundle contract: MCP bundles remain schema-comparable to CLI
  bundles and carry `execution_context.entry_point = "mcp"`.

## Alternatives Rejected

### A. Status quo — keep the smoke/control-plane designation

Rejected. The designation is now factually wrong: authenticated remote MCP runs
durable, tenant-owned, long-running benchmarks. More importantly, the
designation was being used to justify duplicated implementations. It answered a
product question and was then cited to close an architecture question it never
addressed. Keeping it preserves the defect class that motivated this ADR.

### B. Full 100% CLI/MCP option parity

Rejected. Parity as a goal is actively harmful for two of the three tiers:

- It would require exposing destination paths, publishing targets, credential-
  adjacent platform options, and unbounded resource controls over a
  multi-tenant protocol. The narrow surface is a security property, not a gap.
- It would require inventing MCP meanings for terminal-only flags (`--quiet`,
  `--no-progress`, interactive prompts), producing parameters that are accepted
  and ignored — the worst kind of contract.

Parity also measures the wrong thing. Two surfaces can have identical flags and
still compute different numbers; that is precisely the state this ADR ends. The
invariant worth enforcing is *one implementation*, not *one flag list*.

### C. Route MCP through the CLI orchestrator

Rejected, and it stays rejected — this was already the correct call in the
superseded decision. Binding MCP to CLI command internals would couple a
protocol surface to Click parsing, console output, and interactive prompting,
and would violate the `benchbox.mcp` → `benchbox.cli` import boundary that the
AST test in `tests/unit/mcp/test_run_surface_contract.py` enforces. The engine
goes *below* both surfaces, not sideways between them.

### D. Extract a shared run service but leave statistics and policy duplicated

Rejected. A shared run service addresses orchestration drift only. The reviewed
defects included numeric drift (three percentile implementations) and policy
drift (regression thresholds decided per surface). Extracting one and not the
others leaves the surfaces free to disagree about what a result *means* while
agreeing about how it was produced.

## Consequences

### Positive

- The "schema half closed, adapter half open" defect class is structurally
  eliminated for anything routed through the shared engine: there is one place
  to be wrong, and it is covered by core tests.
- Numbers are comparable across surfaces by construction, not by convention.
- Asymmetry becomes reviewable. A reviewer can ask "which tier?" and get a
  ratified answer, instead of relitigating product scope per pull request.
- Demand-driven MCP expansion is cheap: a `not-yet-demanded` control becomes a
  schema entry plus a passthrough, with no new logic.

### Negative / costs

- Migration is not free. Moving statistics and policy into core risks silent
  numeric change. This is mitigated by a hard rule: characterization tests land
  *before* any statistics or policy code moves, extractions move code verbatim,
  improvements are separate commits, and every numeric delta is listed
  explicitly in the pull request that causes it.
- The ledger must be maintained. An unledgered omission is a contract defect,
  which means adding a CLI flag now carries a small documentation obligation.
- Core gains surface area and must stay free of platform and CLI imports; the
  `lint-imports` contract becomes load-bearing for a larger fraction of the
  codebase.

### Enforcement

- `tests/unit/mcp/test_run_surface_contract.py` pins the contract wording in
  `docs/reference/mcp.md`, asserts that every ledgered omission carries one of
  the three ratified tiers, and enforces the
  `benchbox.mcp` → `benchbox.cli` import boundary.
- `uv run -- lint-imports` enforces `utils < core < platforms < cli`.
- The MCP tools row in
  [`docs/reference/public-contracts.md`](../../reference/public-contracts.md)
  carries the product-tier statement and its change process.

## Implementation

This ADR is governance only and changes no runtime code. The runtime work lands
in the `one-engine` tracker worktree: a shared core run service, unified
statistics, unified regression policy, unified constants, MCP adoption of the
run service, sink removal in both surfaces, and the parity ledger enforcement
item that owns demand-driven expansion.
