# Remote MCP security and tenancy

BenchBox Streamable HTTP is local-only unless an operator supplies a complete
security policy. Stateless transport removes sticky protocol sessions; it does
not authenticate callers, authorize tools, isolate files, or coordinate load.

## Threat model

| Asset | Trust boundary | Primary abuse cases | Control |
|---|---|---|---|
| Database credentials and bearer tokens | Client, OAuth issuer, reverse proxy, BenchBox | disclosure through errors, logs, traces, or audit | bearer values exist only during SDK verification; config stores SHA-256 digests; MCP logs and audit omit raw arguments and exception text |
| Benchmark execution capacity | Untrusted authenticated caller to platform adapters | expensive platforms/scales, request floods, worker hopping | per-tool scopes and platform/benchmark/scale policy; transactional shared rate, queue, and concurrency limits |
| Results, charts, exports, and jobs | One authenticated principal to another | guessed names, traversal, caller-selected workspace, cross-worker identity confusion | stable principal derived from SDK client ID, issuer, and subject; server-owned workspace root; existing path-containment checks run inside that tenant root |
| HTTP endpoint | Browser/network to MCP process | public accidental bind, DNS rebinding, hostile Host/Origin, missing auth | loopback default; non-loopback startup requires the full policy and HTTPS public URLs; SDK bearer, Host, Origin, and content-type middleware validate every request |
| Audit and coordination database | All MCP workers to durable storage | process-local quota bypass, restart reset, secret-rich audit | transactional shared SQLite store; bounded audit schema contains only opaque principal, tool, decision, execution ID, and artifact basename |

The pre-provisioned token verifier is a resource-server integration seam, not
an authorization server. Tokens must be issued out of band. For horizontally
scaled deployments, every worker must mount the configured state database and
workspace root from storage with shared locking and durability semantics. Do
not use node-local files on multiple hosts. A later production-readiness gate
must pass before publishing a shared endpoint.

## Configuration

The policy file is JSON. It must contain no raw token; provision each token as
the lowercase SHA-256 digest of its exact bearer value.

```json
{
  "issuer_url": "https://login.example.com",
  "resource_server_url": "https://benchbox.example.com/mcp",
  "allowed_hosts": ["benchbox.example.com"],
  "allowed_origins": ["https://console.example.com"],
  "workspace_root": "/srv/benchbox/mcp/workspaces",
  "state_db": "/srv/benchbox/mcp/state/security.sqlite3",
  "tokens": [
    {
      "token_sha256": "<64 lowercase hex characters>",
      "client_id": "automation-client",
      "subject": "team-a",
      "scopes": ["benchbox:read", "benchbox:write", "benchbox:execute"]
    }
  ],
  "allowed_platforms": ["duckdb"],
  "allowed_benchmarks": ["tpch"],
  "max_scale_factor": 1.0,
  "admission": {
    "requests_per_minute": 120,
    "global_concurrency": 8,
    "principal_concurrency": 2,
    "queue_limit": 32,
    "queue_timeout_seconds": 5,
    "lease_seconds": 3600
  }
}
```

The scope contract is:

- `benchbox:read`: discovery, system profile, result reads, analytics, and chart suggestions;
- `benchbox:write`: chart generation and other non-benchmark artifact writes;
- `benchbox:execute`: `run_benchmark`, still constrained by platform,
  benchmark, and maximum-scale policy.

## Fail-closed deployment

Run the process behind a TLS-terminating reverse proxy. The externally visible
issuer and resource-server URLs must use HTTPS. The proxy must preserve the
validated `Host`, `Origin`, `Content-Type`, and `Authorization` headers and must
not log bearer values.

```bash
benchbox-mcp \
  --transport streamable-http \
  --host 10.0.0.12 \
  --port 8000 \
  --security-config /etc/benchbox/mcp-security.json
```

Startup is rejected if a non-loopback host has no policy, if its public URLs
are not HTTPS, or if Host/Origin/token allowlists are empty. Stdio keeps its
existing local behavior and rejects the remote-only policy option.

The SQLite file is a durable shared backend only for workers on storage that
provides correct cross-process locking. Before multi-host use, replace or mount
it on an explicitly supported shared storage service and pass the production
readiness acceptance matrix. Statelessness must never substitute for this
coordination.

## Audit contract

Each protected tool decision records an opaque principal ID, tool name,
decision, and optional bounded execution/artifact identifiers. Audit records do
not contain token digests, bearer values, OAuth claims, tool arguments,
database URLs, result payloads, or exception messages. Operators should apply
normal access control, retention, backup, and integrity monitoring to the state
database.
