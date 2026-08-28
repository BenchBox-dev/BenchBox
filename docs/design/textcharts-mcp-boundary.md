# Textcharts MCP surface boundary decision

**Status:** Accepted (separate-client)
**Date:** 2026-08-08
**Decision scope:** Whether BenchBox should bundle or proxy the external `textcharts-mcp` server versus keeping it as a separate client

## Context

BenchBox publishes result-aware visualization tools (`suggest_charts`, `generate_chart`) that render from typed BenchBox result bundles via the internal semantic chart registry (`benchbox/core/visualization`). The external `textcharts-mcp` server provides raw textcharts primitives (bar, line, etc.) that accept arbitrary data arrays. Both surfaces exist on the same MCP server list for local stdio clients, but they are different trust and product boundaries.

The three candidate shapes were:

- **Separate-client** — textcharts-mcp runs as its own MCP server entry, configured by the user alongside `benchbox-mcp`. No code, packaging, or runtime import connects them.
- **Bundled deployment** — `benchbox` wheels vendors textcharts-mcp code or declares it as a dependency, starts it in-process or as a child process, and re-exposes its tools.
- **Server-side proxying** — `benchbox-mcp` registers textcharts tools on behalf of the external server, forwards calls, and returns results as if they were native BenchBox tools.

## Decision

**Keep separate-client configuration.** Do not bundle or proxy textcharts-mcp in this product boundary.

### Selected option

- Users configure textcharts-mcp separately when they need raw chart primitives (e.g., `claude` MCP config with two entries: `benchbox` and `textcharts`). BenchBox documentation points to the external repository for install and versioning. No import, subprocess spawn, or tool registration for textcharts occurs in `benchbox/mcp` or `benchbox/core/visualization`. The existing result-aware chart contract (`docs/reference/mcp.md` Visualization) remains the only chart surface BenchBox publishes.

### Rejected alternatives

- **Bundled** — rejected for namespace, tenant, and lifecycle reasons:
  - Tool namespace collisions (`generate_chart` vs textcharts primitives) require prefixing or aliasing that breaks the result-aware contract.
  - Tenant isolation: a bundled server would share the same process or workspace root, widening the blast radius for raw renderer input limits (unbounded data arrays, SVG injection) beyond BenchBox's bounded visualization registry.
  - Package/licensing/support ownership: textcharts-mcp is an external package with its own release cadence and license; vendoring locks BenchBox wheels to that cadence and makes security updates a BenchBox release.
  - Rollback: a bundled chart bug forces a BenchBox release to roll back visualization, even when core benchmark logic is unaffected.

- **Proxying** — rejected for the same reasons plus sessionless HTTP behavior:
  - A server-side proxy would re-expose external tool schemas as BenchBox tools, mixing the product boundary and requiring BenchBox to validate and bound arbitrary textcharts payloads.
  - Sessionless HTTP (`streamable-http`) has no sticky session; proxy state, progress notifications, and error mapping would be reimplemented in BenchBox rather than delegated to the external server.
  - The proxy would need to handle textcharts-specific resource and prompt lifecycles that BenchBox does not own.

## Consequences

- BenchBox MCP continues to publish only `suggest_charts` and `generate_chart` (result-aware) until a separate, explicitly approved follow-on item changes the surface. No `benchbox.mcp` code, visualization registry, or `textcharts/` directory changes are made in this decision.
- Documentation (`docs/reference/mcp.md`, `docs/reference/public-contracts.md`) records the separate-client posture and the rejected bundle/proxy alternatives.
- If demand for bundled or proxied textcharts emerges, the follow-on implementation must provide: (1) a namespaced tool prefix, (2) tenant and workspace isolation tests, (3) raw input bounds and SVG sanitization, (4) pinned version and license audit, (5) sessionless HTTP compatibility verification, and (6) a rollback plan that does not require a BenchBox core release.

## Acceptance criteria for any future implementation

- No widening of the BenchBox visualization registry beyond the semantic, result-aware IDs without a contract-map update.
- All textcharts payloads bounded at the MCP admission layer (array length, string length, numeric ranges) with explicit `MCPValidationError` cases.
- Integration tests proving separate-client, bundled, and proxied shapes behave correctly under `benchbox-mcp --transport streamable-http` (different workers, shared storage).
- Release notes and support docs updated to reflect the new surface ownership and upgrade/rollback path.

## Related

- `benchbox/core/visualization/*` — result-aware chart registry and ASCII runtime (intentionally narrow).
- `textcharts/` — external dependency boundary, not vendored.
- `benchbox/mcp/tools` — tool registration boundary for BenchBox's own 12 local tools.
