# MCP production-readiness gate

BenchBox MCP is production-ready only for a specific source revision and only
while every row in the following matrix has current evidence. A pending,
failed, stale, or revision-mismatched row blocks shared-endpoint publication.
Local stdio and loopback Streamable HTTP remain development interfaces and do
not imply production certification.

## Acceptance matrix

| Layer | Required evidence | Owner | Maximum age |
| --- | --- | --- | --- |
| Protocol | Pinned MCP conformance scenarios and pinned Inspector smoke test | MCP maintainer | 7 days |
| Compatibility | Modern `2026-07-28` sessionless and supported legacy `2025-11-25` handshakes | MCP maintainer | 7 days |
| Multi-worker | Alternating-worker auth, tenancy, shared quota, durable job, cancellation, and artifact tests | MCP maintainer | 7 days |
| Observability | W3C parent propagation plus bounded, redacted OTLP attributes | Service operator | 7 days |
| Cache policy | Public metadata only; result and system-profile resources private and immediately stale | Security owner | 7 days |
| Edge security | TLS proxy, Host/Origin policy, bearer-token verification, and request-size limits | Service operator | 7 days |
| Persistence | Shared SQLite-compatible state, tenant artifact storage, backup, and restore exercise | Storage owner | 30 days |
| Operations | Scale test, rollback exercise, dashboards, alerts, and incident runbook | Service operator | 30 days |

The automated verifier owns the first five rows. The operator supplies the
external evidence for the final three rows. Evidence is tied to the deployed
source revision and cannot be reused after a code change.

## Protocol policy

- `2026-07-28` is the current protocol and the production conformance target.
- `2025-11-25` is the only explicitly supported legacy handshake. It uses the
  same stateless HTTP route and receives no sticky server session.
- Earlier revisions are not production-supported. Adding one requires a
  compatibility test, an owner, and an update to this matrix.
- Streamable responses remain enabled (`json_response=False`) so progress,
  notifications, and future request-scoped streaming are not designed out.

## Evidence lifecycle

Run `uv run -- python scripts/verify_mcp_conformance.py --protocol-version
2026-07-28`. The verifier uses exact upstream revisions, starts a loopback
BenchBox endpoint, and runs protocol and Inspector checks. A production launch
must additionally record the external rows above. Failed runs are retained as
diagnostic evidence but never satisfy the gate.

The publication gate validates evidence freshness, source revision, exact tool
pins, the evidence-file digest supplied out of band, and every required row.
Do not weaken or bypass the gate to publish an endpoint.
