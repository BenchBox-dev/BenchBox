# MCP conformance baseline

The automated conformance gate is pinned to protocol `2026-07-28` and
conformance revision `81eb1c3edaed87d7fd585d7b80186da7a2960660` (short SHA
`81eb1c3`). The Inspector package and integrity pins live in
`benchbox.mcp.readiness`. The verifier allows exactly two server-stateless
fixture failures; every other failure or warning is unexpected and blocks the
gate.

| Conformance check | Expected status | Classification | Why it is bounded and non-waiving |
| --- | --- | --- | --- |
| `server-stateless:sep-2575-server-rejects-undeclared-capability` | Expected failure | Fixture non-applicability | The upstream scenario requires a diagnostic `test_missing_capability` tool. BenchBox intentionally publishes no diagnostic or sampling tool, so the MUST cannot be exercised. The compatibility test asserts that this tool is absent. |
| `server-stateless:sep-2575-missing-capability-http-400` | Expected failure | Fixture non-applicability | This HTTP status check is conditional on the same missing-capability error. Without the diagnostic fixture there is no status claim to waive; an actual BenchBox capability error remains gate-blocking. |
| `server-stateless:sep-2575-server-sends-prompts-list-changed-on-subscription` | Must pass | Static-registry contract | BenchBox's prompt registry is assembled at startup and has no supported runtime mutation path. The server retains the subscription transport for protocol compatibility but explicitly advertises `prompts.listChanged=false`. |
| `server-stateless:sep-2575-server-sends-tools-list-changed-on-subscription` | Must pass | Static-registry contract | BenchBox's tool registry is assembled at startup and has no supported runtime mutation path. The server retains the subscription transport for protocol compatibility but explicitly advertises `tools.listChanged=false`. |

The two expected capability failures are not a security exception: BenchBox
does not claim to implement the absent diagnostic capability. The two
list-change checks must pass because BenchBox explicitly does not advertise
runtime list mutation. The guard in
`tests/integration/mcp/test_protocol_compatibility.py` checks the absence of
the diagnostic tool, the stability of tool and prompt listings, and the
`listChanged=false` capability contract for both supported handshake modes.
Any future dynamic registration path must add its own notification behavior,
tests, and a new revision-bound baseline review.

## MVP and production use

A current pass is one of the two MCP MVP modernization release checks; the
other is DuckDB execution from a clean install of the built wheel's `mcp`
extra. This loopback proof does not require an external deployment. A future
shared service must rerun and bind the same gate to its exact deployed artifact
under the deferred post-release production-publication matrix.

## Rerun and retirement policy

Run:

```bash
uv run -- python scripts/verify_mcp_conformance.py --protocol-version 2026-07-28
```

The exact two expected-failure IDs are declared individually in
`scripts/verify_mcp_conformance.py`. Do not broaden the baseline to a prefix,
scenario, or “known failures” bucket. Unexpected warnings are fail-closed too.
When upstream removes a fixture gap or BenchBox adds a dynamic mutation path,
rerun the pinned gate, remove the resolved entry, and update this document in
the same change. A stale or unexpected result blocks the MCP MVP conformance
claim and keeps future production publication closed.
