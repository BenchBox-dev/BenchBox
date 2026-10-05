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
| A failed TPC-DI file transform fails the ETL run and names the failed files, sequentially and in parallel | per-file transform to `run_etl_pipeline` result and batch status | one unreadable source file among healthy files; every file failing in parallel | `tests/unit/tpcdi/test_transform_outcomes.py` |
| An enhanced TPC-DI data phase with a missing processor or no input files is not reported as success | processor and generated-file inventory to phase result | no connection-bound processors; empty file lists | `tests/unit/tpcdi/test_transform_outcomes.py` |
| A later phase cannot start while throughput workers may still run | stream runner outstanding state to phase-boundary gate and combined sequencers | timed-out running stream; maintenance requested after it | `tests/unit/core/throughput/test_containment.py` (`TestOutstandingOwnershipState`, `TestPhaseBoundaryGate`, `TestOfficialBenchmarkContainment`, `TestCombinedSequencerContainment`) |
| Termination is observed from worker futures, never assumed | retained futures to boundary release | running future released mid-wait; no observable handles | `tests/unit/core/throughput/test_containment.py` (`TestAwaitQuiescence`) |
| Contained work blocks reuse of the measurement connection for post-measurement probes | adapter containment flag to plan capture and link probe | worker still running when the bounded cleanup wait expires | `tests/unit/platforms/test_base_adapter.py` (`TestDeferredConnectionClose`) |
| The measurement connection closes only after contained workers end | adapter close path to retained worker futures, after result capture has consumed the throughput result | blocked worker released after the close request | `tests/unit/platforms/test_base_adapter.py` (`TestDeferredConnectionClose`) |
| Independent-connection adapters give each stream its own session; shared-cursor adapters share one by declaration | adapter capability to stream connection factory | temp-table and session-setting leakage across streams; undeclared override | `tests/integration/test_throughput_session_isolation.py` |
| TPC-DI generation is repeatable for one seed across repeated requests | generation request to fact files | reuse one generator after its nested RNG has advanced | `tests/unit/test_tpcdi_phase1.py` |
| BigQuery TPC-DI relative dates use valid interval syntax | SQLite query source to BigQuery execution | AQ7 `DATE('now', '-90 days')` rewrite and parse | `tests/unit/platforms/test_bigquery_adapter.py` |
| Only the current MCP owner may publish or complete | durable attempt to result row and artifact | stale owner after lease fencing | `tests/unit/mcp/test_durable_jobs.py`, `tests/integration/mcp/test_durable_jobs.py` |
| Cancellation or lease loss never proves database work stopped | durable attempt to admission capacity | cancellation plus expired lease while the executor remains blocked | `tests/integration/mcp/test_durable_jobs.py` |
| Unknown work retains capacity until a durable quiescence attestation | recovery and retention to replacement claim | retention expiry before and after worker quiescence | `tests/unit/mcp/test_durable_jobs.py`, `tests/integration/mcp/test_durable_jobs.py` |
| Durable global and per-principal running caps hold across concurrent processes | claim transaction to shared SQLite state | two spawned processes claiming at a cap of one, globally and for one principal | `tests/integration/mcp/test_durable_jobs.py` (`test_multiprocess_claims_respect_global_running_limit`, `test_multiprocess_claims_respect_per_principal_running_limit`) |
| Durable queue bounds hold across repository handles | submit and retry transactions to shared SQLite state | global and per-principal queue limits, each through separate repository handles in one process; not proven across processes | `tests/unit/mcp/test_durable_jobs.py` |
| A durable job stores and exposes a shared outcome derived from its result | result payload to job row and status tool | failed queries, failed phases, failed validation, no result, rejected request, quarantined outstanding work | `tests/unit/mcp/test_durable_jobs.py` (`test_job_stores_and_exposes_shared_outcome_derived_from_result`, `test_public_outcome_reports_non_terminal_and_quarantined_states`, `test_recovered_published_artifact_keeps_its_derived_outcome`) |
| Outstanding throughput work is detected from the real result export shape and from the result object when both exports fail | result export to job worker | `phases.throughput_test.outstanding_work` payload; exporter and payload builder both failing | `tests/unit/mcp/test_run_response_outstanding_work.py` |
| Leaked throughput work releases its capacity only when its futures finish | stream runner futures to worker attestation to claim admission | blocked stream future released after the job was quarantined; no observable handles | `tests/unit/mcp/test_durable_jobs.py` (`test_leaked_throughput_work_attests_quiescence_when_its_futures_finish`, `test_leaked_work_without_observable_handles_stays_quarantined`, `test_leaked_work_quarantines_even_when_the_executor_raises_or_the_response_hides_it`, `test_quiescence_attestation_is_retried_and_logged_when_the_store_fails`) |
| Recovery never deletes the staging directory of a fenced attempt that may still write | recovery fence to staging directory | expired lease with a live writer; purge before and after quiescence | `tests/unit/mcp/test_durable_jobs.py` (`test_recovery_leaves_fenced_attempt_staging_until_quiescence_and_purge`) |
| The load-testing executor bounds its waits, stops abandoned streams between queries, reports them as outstanding, and times durations and latencies on the monotonic clock | stream futures to run result | stream blocked past the drain bound; query over its timeout; wall clock stepping backwards; non-positive timeout | `tests/unit/core/load_testing/test_executor.py` (`TestExecutorBoundedWaitsAndClocks`, `TestExecutorLatencyAndAbandonedStreams`) |
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

An unknown attempt consumes durable capacity until its displaced worker attests
quiescence. Three cases never attest, and BenchBox does not release the fence
merely because retention time elapsed:

- The worker process dies after losing its lease and before it can attest.
- The worker process restarts or exits while leaked futures are still running.
  The attesting thread dies with the process and nothing else observes the
  futures.
- The job returned a result that reports outstanding throughput work and the
  worker holds no futures for it, for example a custom executor that does not
  go through `StreamRunner`.

A worker that did observe the leaked futures, on a normal return or after the
executor raised, attests from a background thread once they all finish, then
removes the attempt's staging directory. Attestation is retried with backoff
and failures are logged. Until then each such job holds one running slot for its principal and one global
slot. No operator release path exists. A future one must obtain explicit
termination evidence before it can release capacity; until then, manual
resubmission is unsafe.

Staging directories of fenced attempts are not deleted at recovery. The
displaced worker removes its own directory when it finishes, and the
retention purge removes any leftover once the job is terminal.

## Load-testing executor limit

An abandoned load-testing stream stops only between queries. A query that never
returns keeps its worker thread alive, and the standard library joins pool
threads at interpreter exit, so a hung query can still delay process exit. The
run result lists such streams in `outstanding_stream_ids` with
`cleanup_state` set to `outstanding`.

## Job outcome for rows written before the outcome field

Job rows written before the `outcome` column existed have no stored outcome.
For a completed row with a retained artifact the status tool derives the
outcome from that artifact. Rows without an artifact report a null outcome.
