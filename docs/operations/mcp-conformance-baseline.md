# MCP conformance baseline

The automated conformance gate is pinned to protocol `2026-07-28` and
conformance revision `81eb1c3edaed87d7fd585d7b80186da7a2960660` (short SHA
`81eb1c3`). The Inspector package and integrity pins live in
`benchbox.mcp.readiness`. The verifier allows exactly four server-stateless
entries; every other conformance result is unexpected and blocks the gate.

| Baseline entry | Classification | Why it is bounded and non-waiving |
| --- | --- | --- |
| `server-stateless:sep-2575-server-rejects-undeclared-capability` | Fixture non-applicability | The upstream scenario requires a diagnostic `test_missing_capability` tool. BenchBox intentionally publishes no diagnostic or sampling tool, so the MUST cannot be exercised. The compatibility test asserts that this tool is absent. |
| `server-stateless:sep-2575-missing-capability-http-400` | Fixture non-applicability | This HTTP status check is conditional on the same missing-capability error. Without the diagnostic fixture there is no status claim to waive; an actual BenchBox capability error remains gate-blocking. |
| `server-stateless:sep-2575-server-sends-prompts-list-changed-on-subscription` | Static-registry limitation | BenchBox's prompt registry is assembled at startup and has no supported runtime mutation or diagnostic trigger. The server's subscription transport is retained for the stateless protocol, but no prompt-list change is promised. |
| `server-stateless:sep-2575-server-sends-tools-list-changed-on-subscription` | Static-registry limitation | BenchBox's tool registry is assembled at startup and has no supported runtime mutation or diagnostic trigger. The server's subscription transport is retained for the stateless protocol, but no tool-list change is promised. |

The two capability entries are not a security exception: BenchBox does not
claim to implement the absent diagnostic capability. The two list-change
entries are not permission to mutate registries silently: any future dynamic
registration path must add its own notification behavior, tests, and a new
revision-bound baseline review. The guard in
`tests/integration/mcp/test_protocol_compatibility.py` checks the absence of
the diagnostic tool and the stability of tool and prompt listings across
requests for both supported handshake modes. The upstream notification
requirements are named `promptsListChanged` and `toolsListChanged`; those
capabilities have no supported BenchBox mutation trigger today.

## Rerun and retirement policy

Run:

```bash
uv run -- python scripts/verify_mcp_conformance.py --protocol-version 2026-07-28
```

The exact four IDs are declared individually in
`scripts/verify_mcp_conformance.py`. Do not broaden the baseline to a prefix,
scenario, or “known failures” bucket. When upstream removes a fixture gap or
BenchBox adds a dynamic mutation path, rerun the pinned gate, remove the
resolved entry, and update this document in the same change. A stale or
unexpected result remains fail-closed and keeps the production-readiness gate
closed.
