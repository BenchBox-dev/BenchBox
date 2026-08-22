# MCP MVP evidence boundary and deferred production observations

This record preserves observations from a controlled local Apple Container
exercise. It is historical diagnostic evidence, not release acceptance and not
production acceptance. None of the observations below is bound by one
replayable transcript to the same readiness digest, image digest, source
revision, and timestamp.

MVP modernization and external production publication are separate claims.
Only a current DuckDB package/execution proof and current pinned protocol
conformance block the MCP MVP release. Every external deployment, operations,
and approval action in this record is deferred until post-release. The future
non-loopback publication path remains fail-closed while deferred.

## Identity and immutable inputs

deployment_revision: 96d1b040724c19d182792c99aaf3b960e5ad503e

deployment_target: local Apple Container staging on joe-mac-mini.local

operator: Joe Harris (joe@joe-mac-mini.local)

evidence_owner: Joe Harris

local_staging_authorization: user-authorized local exercise on 2026-08-13

record_updated_at: 2026-08-22T19:40:03Z

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

## Claim status

mvp_modernization_scope: LOCAL_STDIO_AND_LOOPBACK_HTTP

mvp_duckdb_execution: NEEDS_CURRENT_EVIDENCE

mvp_protocol_conformance: NEEDS_CURRENT_EVIDENCE

external_acceptance_schedule: DEFERRED_POST_RELEASE

tls_edge: DEFERRED_POST_RELEASE

backup_restore: DEFERRED_POST_RELEASE

scaling_rollback_incident: DEFERRED_POST_RELEASE

otlp: DEFERRED_POST_RELEASE

multiworker: DEFERRED_POST_RELEASE

public_acceptance: DEFERRED_POST_RELEASE

publication_status: DEFERRED_POST_RELEASE

production_gate_status: DEFERRED_POST_RELEASE

named_production_approver: NOT_ASSIGNED

immutable_registry_digest: NOT_AVAILABLE

`DEFERRED_POST_RELEASE` is not `PASS` or `APPROVED`. It prevents accidental
shared-endpoint publication without presenting post-release operational work as
a blocker to the local MCP MVP.

## MVP blocker 1: DuckDB package and execution proof

The staged image statically registered and advertised DuckDB, but its build
installed `benchbox[mcp]` without the separate DuckDB extra. A read-only probe
of the exact image found no importable `duckdb` package, so adapter construction
failed with the missing-driver error. This is a packaging defect, not a static
registry or runtime-policy defect.

PR #1716 merged into `develop` as
`3ffa5ba0265e065805e28aab6f092682d3039f2a`. It adds the repository's
supported `duckdb>=1.0.0,<2.0.0` dependency to the MCP extra and synchronous and
durable surface regression tests. The implementation defect is corrected; the
remaining MVP blocker is a current release-artifact proof, not an external
image-publication exercise.

The release operator should build the wheel, install that wheel with `[mcp]` in
a clean environment, confirm `duckdb` imports, and invoke a small real TPC-H
DuckDB run through local MCP `run_benchmark`. Record the source revision, wheel
digest, command, timestamp, and redacted result. No registry, TLS edge, or
production approver is required for this proof.

## MVP blocker 2: current protocol conformance

Run the exact pinned verifier documented in
[the conformance baseline](mcp-conformance-baseline.md):

```bash
uv run -- python scripts/verify_mcp_conformance.py \
  --protocol-version 2026-07-28
```

Retain its redacted output with the source revision and timestamp. Resolve every
unexpected failure or warning; only the two individually named fixture
non-applicabilities in the baseline are allowed. This loopback protocol and
Inspector proof requires no external deployment.

## Deferred post-release production evidence

The following work is deliberately unscheduled until after the MVP release:

- select an approved external HTTPS target, operator, approver, and registry;
- publish an immutable image and bind it to a readiness-evidence digest;
- deploy behind the approved production TLS and identity edge;
- prove shared storage, WAL-safe backup/restore, and separate-worker or
  multi-host behavior;
- verify HTTPS OTLP export, W3C propagation, bounded attributes, and redaction;
- exercise deployed tenant isolation, quotas, durable jobs, cancellation,
  artifacts, cache policy, scaling, rollback, dashboards, alerts, and incident
  diagnostics; and
- publish one replayable redacted production transcript and obtain named
  approval.

When this work resumes, every item must pass before changing a production field
to `PASS` or `APPROVED`. Until then, these fields constrain only future
non-loopback publication and must not be cited as MVP release blockers.
