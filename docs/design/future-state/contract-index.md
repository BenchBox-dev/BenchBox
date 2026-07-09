<!-- Copyright 2026 Joe Harris / BenchBox Project. Licensed under the MIT License. -->

# Architecture Contract Decision Index

```{tags} contributor, architecture
```

This index connects future-state proposals and compatibility registry decisions
to the active implementation surfaces they govern. It does not replace
`docs/reference/public-contracts.md`; it is the planning-side index for decisions
that are not fully implemented yet.

| Decision | Status | Owner | Blocking gate | Current implementation surface |
|---|---|---|---|---|
| Formalize MCP internal API references as public exports | Future-state proposal, Tier 2 | mcp | Export tests for the three symbols and no `benchbox.cli` command imports from MCP. | `docs/design/future-state/formalize-mcp-internal-apis/README.md`, `benchbox/mcp/` |
| Define benchmark family plugin seam before core package extraction | Future-state proposal, Tier 2 | benchmark-api | Keep public wrapper tests green, lock registry/wrapper/loader counts, and pilot one family interface before moving packages. | `docs/design/future-state/benchmark-family-plugin-seam/README.md`, `docs/reference/public-contracts.md`, `benchbox/core/benchmark_loader.py` |
| Isolate experimental core subsystems | Future-state proposal, Tier 1 | architecture | Decide whether `benchbox.experimental` remains packaged, moves behind an extra, or becomes a companion package. | `docs/design/future-state/isolate-experimental-core-subsystems/README.md`, `benchbox.experimental`, `pyproject.toml` |
| Preserve top-level wrapper facades while benchmark API cleanup proceeds | Active compatibility boundary | benchmark-api | Wrapper facade tests stay green or a deprecation row/migration lands. | `docs/reference/backward-compatibility.md`, `tests/unit/test_wrapper_facades_fast.py`, top-level `benchbox/*.py` wrappers |
| Retain `benchbox.core.base_benchmark.BaseBenchmark` during staged migration | Deprecated compatibility surface | core-runtime | Dedicated migration/removal item completes and updates the compatibility registry. | `docs/reference/backward-compatibility.md`, `benchbox/core/base_benchmark.py` |

## Review Rule

When a future-state proposal becomes implementation work, the PR should update
both this index and the public contract map if it changes a public,
beta-public, generated, deprecated, or experimental surface.
