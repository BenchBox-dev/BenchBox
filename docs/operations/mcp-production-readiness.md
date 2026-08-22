# MCP post-release production-publication gate

This runbook governs a future shared, non-loopback MCP deployment. It is **not**
a release-readiness gate for the existing MCP MVP. MVP modernization is limited
to two release blockers: proving DuckDB execution from the shipped `mcp` extra
and passing the pinned current-protocol conformance gate. Local stdio and
loopback Streamable HTTP are the MVP deployment modes and do not require an
external target, registry, service operator, or production approver.

External production publication is deferred until after the release. When that
work is resumed, BenchBox MCP is production-ready only for a specific deployed
source revision and only while every row below has current evidence. A pending,
failed, stale, or revision-mismatched row blocks only shared-endpoint
publication; it does not block the local MVP or the release containing it.

## Post-release acceptance matrix

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

Every row in this matrix is `DEFERRED_POST_RELEASE`. The automated verifier can
later certify protocol, compatibility, and the local observability/cache
regressions for a deployment candidate. It deliberately leaves `multiworker`
false: an operator must replace that value only after a deployment-grade run
proves process-level coordination on the deployed shared storage class. The
operator also supplies the external evidence for the final three rows. Evidence
is tied to the deployed source revision and cannot be reused after a code
change.

## MVP release boundary

Only these two checks block completion of MCP MVP modernization:

1. **DuckDB package and execution proof.** Build the release wheel, install that
   wheel with its `mcp` extra into a clean environment, confirm `duckdb` imports,
   and run a small real DuckDB benchmark through the MCP `run_benchmark`
   surface. PR #1716 fixed the dependency declaration; current-wheel execution
   evidence is still required.
2. **Current protocol proof.** Run the pinned conformance verifier for
   `2026-07-28` and resolve every unexpected failure or warning. The two exact
   fixture non-applicabilities documented in
   [MCP conformance baseline](mcp-conformance-baseline.md) remain the only
   permitted expected failures.

The shortest operator actions are:

```bash
# Blocker 1: clean release-artifact proof
proof_root="$(mktemp -d)"
uv build --wheel --out-dir "${proof_root}/dist"
wheel="$(find "${proof_root}/dist" -name 'benchbox-*.whl' -print -quit)"
uv venv "${proof_root}/venv"
uv pip install --python "${proof_root}/venv/bin/python" "${wheel}[mcp]"
"${proof_root}/venv/bin/python" -c \
  "import duckdb, benchbox.mcp; print(duckdb.__version__)"
# Then invoke run_benchmark(platform="duckdb", benchmark="tpch",
# scale_factor=0.01) through a local stdio MCP client and retain the redacted result.

# Blocker 2: current protocol/Inspector proof
uv run -- python scripts/verify_mcp_conformance.py \
  --protocol-version 2026-07-28
```

These commands need current, redacted evidence, but no image publication,
external deployment, production transcript, or named approval.

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
BenchBox endpoint, and runs protocol and Inspector checks. This current-protocol
result is an MVP release check. Reuse for a later production launch is not
implicit: production publication must additionally record every external row
above against the exact deployed artifact. Failed runs are retained as
diagnostic evidence but never satisfy either claim.

After release, the publication gate validates evidence freshness, source
revision, exact tool pins, the evidence-file digest supplied out of band, and
every required row. Do not weaken or bypass that gate to publish an endpoint.

The exact conformance baseline and its fixture-bound rationale are maintained
in [MCP conformance baseline](mcp-conformance-baseline.md). A baseline entry
does not waive a real protocol, security, or tenancy defect.
