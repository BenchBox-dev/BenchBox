# Concurrency Contract Proof Matrix

This matrix binds each concurrency claim to the lowest repository layer that can
falsify it. It does not certify live adapter behavior or an external MCP
deployment. Those claims require the operator-controlled UAT and production
evidence named below.

## Repository evidence

| Invariant | Producer to consumer | Failure injection | Proving evidence |
|---|---|---|---|
| Expected-result publication is single-flight and validation policy is run-local | expected-results provider to TPC runner | concurrent exact, loose, skip, and disabled runs | `tests/unit/core/expected_results/test_singleflight_run_policy.py` |
| Failed or incomplete throughput work cannot publish a valid score | stream runner to official result | failed dictionary and object results carrying misleading metrics | `tests/unit/core/test_tpc_reporting_execution.py`, `tests/unit/core/throughput/test_containment.py` |
| A throughput adapter is admitted only from the canonical manifest capability | platform manifest to stream admission | undeclared adapter and unsupported manifest entry | `tests/unit/platforms/test_throughput_session_capability_sweep.py`, `tests/unit/platforms/throughput_session_capability_snapshot.json` |
| Requested TPC-DI phases fail the aggregate outcome when any phase fails | phase result to enhanced pipeline result | failed data, SCD, and incremental phases | `tests/integration/test_tpcdi_phase3_benchmark.py` |
| TPC-DI generation is repeatable for one seed across repeated requests | generation request to fact files | reuse one generator after its nested RNG has advanced | `tests/unit/test_tpcdi_phase1.py` |
| BigQuery TPC-DI relative dates use valid interval syntax | SQLite query source to BigQuery execution | AQ7 `DATE('now', '-90 days')` rewrite and parse | `tests/unit/platforms/test_bigquery_adapter.py` |
| Only the current MCP owner may publish or complete | durable attempt to result row and artifact | stale owner after lease fencing | `tests/unit/mcp/test_durable_jobs.py`, `tests/integration/mcp/test_durable_jobs.py` |
| Cancellation or lease loss never proves database work stopped | durable attempt to admission capacity | cancellation plus expired lease while the executor remains blocked | `tests/integration/mcp/test_durable_jobs.py` |
| Unknown work retains capacity until a durable quiescence attestation | recovery and retention to replacement claim | retention expiry before and after worker quiescence | `tests/unit/mcp/test_durable_jobs.py`, `tests/integration/mcp/test_durable_jobs.py` |
| Durable queue and running caps survive concurrent processes | submit and claim transactions to shared SQLite state | competing principals and processes at global and per-principal limits | `tests/unit/mcp/test_durable_jobs.py`, `tests/integration/mcp/test_durable_jobs.py` |
| Fairness and per-principal FIFO do not depend on wall-clock order | durable enqueue and service sequences to claim selection | wall-clock rollback between submissions and claims | `tests/unit/mcp/test_durable_jobs.py` |
| Capacity reporting does not expose another tenant's job identity | durable capacity state to MCP caller | two authenticated principals with quarantined work | `tests/integration/mcp/test_durable_jobs.py` |

The concurrency tests use events, fenced row transitions, database-owned
sequences, or separate processes as synchronization oracles. Sleeps may bound a
test, but a sleep alone is not evidence that work stopped or that ownership
changed.

## Adapter evidence

The platform manifest is the single declaration source for stream capability.
Repository tests establish the contract wiring and focused behavior for the
adapters with existing session implementations. They do not establish live
service equivalence for every platform.

- Shared-cursor support is declared only for the established embedded or
  Spark-style implementations pinned by the capability snapshot.
- Independent-session support is declared only where an adapter already has a
  tested `new_stream_connection` implementation or inherits one from its wire
  family.
- All other manifest adapters are `unsupported` until adapter-specific tests or
  UAT prove database, catalog, schema, credentials, settings, overlap, and
  cleanup equivalence.
- No adapter in this surface currently claims native mid-query cancellation.

Live container and cloud evidence belongs to `docs/operations/uat-framework.md`.
An unsupported classification is a safe product limit, not proof that the
platform can never support throughput.

## Hosted CI and external acceptance

Hosted CI for this remediation is recorded on its PR and is not pre-certified
by this document. A local pass and a required-CI pass remain separate evidence.

External MCP production acceptance remains operator-owned under
`docs/operations/mcp-production-readiness.md` and its evidence record. Local
durable-job tests do not certify TLS termination, deployment, rollback,
operator response, or a production database adapter.

## Known fail-closed boundary

If an MCP worker dies after losing its lease and before it can attest
quiescence, the unknown attempt continues to consume durable capacity. BenchBox
does not release that fence merely because retention time elapsed. A future
operator recovery mechanism must obtain explicit termination evidence before it
can release capacity; until then, manual resubmission is unsafe.
