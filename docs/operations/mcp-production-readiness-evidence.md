# MCP local-staging evidence and production gaps

This record preserves observations from a controlled local Apple Container
exercise. It is not production acceptance. None of the observations below is
bound by one replayable transcript to the same readiness digest, image digest,
source revision, and timestamp. Production publication remains fail-closed.

## Identity and immutable inputs

deployment_revision: 96d1b040724c19d182792c99aaf3b960e5ad503e

deployment_target: local Apple Container staging on joe-mac-mini.local

operator: Joe Harris (joe@joe-mac-mini.local)

evidence_owner: Joe Harris

local_staging_authorization: user-authorized local exercise on 2026-08-13

record_updated_at: 2026-08-13T22:22:54Z

image: local/benchbox-mcp:96d1-local

image_index_digest: sha256:9987f018b327b5358fe7a0a1dec7294d3075110abc9cc103c77a8cbfc7ba027e

image_arm64_digest: sha256:7181b222a3a2ff284a7ff7d48d7bf9d611c95c013152784ed97096189c8640f0

prior_image_digest: sha256:9ac904581ea6f275c6def76b7f42615296feccdd55e5f6dbdf5c1a5c1a8f86de

state_backup_sha256: 3822a0a170ec1a89870a07c63027a7fa2cd0387dc3a5b20e550a67be062ad592

## Evidence binding audit

evidence_binding_status: INCOMPLETE

The earlier TLS, backup, rollback, and OTLP containers were configured with
readiness digest
`ec253e4e…`, not the later recorded digest
`c063de3498fdcf0bab0b002027e4671be75d39709f3375b82375d230a91d8fb4`.
The inspected container using `c063de…` started at approximately
`2026-08-13T15:20:57Z`, after the former record's claimed generation time of
`2026-08-13T15:19:58Z`, and did not replay the full matrix. No durable redacted
transcript maps every gate to one revision, immutable image, readiness digest,
and timestamp. These observations therefore cannot satisfy a production gate
or a freshness window.

## Local observations

| Local check | Status | Observation | Production gap |
| --- | --- | --- | --- |
| TLS proxy and authentication | `OBSERVED_UNBOUND` | A self-signed loopback proxy at `https://127.0.0.1:18443/mcp` forwarded authenticated MCP traffic; an invalid bearer token returned HTTP 401. | No approved production TLS or identity edge, non-loopback endpoint, request-size limit, timeout evidence, or digest-bound transcript. |
| Storage backup and restore | `OBSERVED_UNBOUND` | A local native ext4 volume was backed up, cleared, restored, and checked with marker `local-apple-container-restore-ok`. | No approved shared storage class or WAL-safe proof covering queued, completed, expired, quota, and cross-tenant state across separate workers. |
| Scaling and rollback | `PARTIAL_UNBOUND` | Two processes in one container read shared state. The prior immutable image above started against preserved state before the current local image returned. | No separate-container or multi-host scale test, digest-bound rollback transcript, dashboards, alerts, or incident drill. |
| OTLP receipt | `OBSERVED_UNBOUND` | A local receiver accepted 11 protobuf trace requests. | No approved HTTPS collector, W3C parent-propagation proof, attribute-bound proof, or captured redaction assertions. |
| Multi-worker behavior | `PARTIAL_UNBOUND` | Two processes returned the tool list and shared a local volume. | Apple Container could not attach that native volume to two VMs; deployment-grade process and storage coordination remains untested. |

local_tls_proxy_observation: OBSERVED_UNBOUND

local_backup_restore_observation: OBSERVED_UNBOUND

local_scaling_rollback_observation: PARTIAL_UNBOUND

local_otlp_receipt_observation: OBSERVED_UNBOUND

local_multiworker_observation: PARTIAL_UNBOUND

## Production gate status

tls_edge: BLOCKED

backup_restore: BLOCKED

scaling_rollback_incident: BLOCKED

otlp: BLOCKED

multiworker: BLOCKED

public_acceptance: NOT_RUN

publication_status: BLOCKED

production_gate_status: BLOCKED

named_production_approver: NOT_ASSIGNED

immutable_registry_digest: NOT_AVAILABLE

## Staged DuckDB execution defect

The staged image statically registered and advertised DuckDB, but its build
installed `benchbox[mcp]` without the separate DuckDB extra. A read-only probe
of the exact image found no importable `duckdb` package, so adapter construction
failed with the missing-driver error. This is a packaging defect, not a static
registry or runtime-policy defect.

PR #1716 merged into `develop` as
`3ffa5ba0265e065805e28aab6f092682d3039f2a`. It adds the repository's
supported `duckdb>=1.0.0,<2.0.0` dependency to the MCP extra and real
synchronous and durable surface tests. No corrected immutable image has been
built or exercised from that merged revision. A new image must still be built,
published by immutable registry digest, and exercised through an actual DuckDB
benchmark before execution acceptance can pass.

## Required production evidence

- Build the corrected merged revision and publish it to the approved registry.
- Record the immutable registry digest and one matching readiness-evidence
  digest.
- Deploy behind the approved production TLS and identity edge.
- Prove the supported shared storage class across separate workers or hosts,
  including WAL-safe backup and clean restore.
- Verify HTTPS OTLP export, W3C parent propagation, bounded attributes, and
  redaction.
- Run the full pinned deployed-endpoint matrix, including DuckDB execution,
  tenant isolation, quotas, durable jobs, cancellation, artifacts, cache
  policy, scaling, rollback, dashboards, alerts, and incident diagnostics.
- Publish a redacted replayable transcript and obtain named production
  approval before changing any production gate above to `PASS` or `APPROVED`.
