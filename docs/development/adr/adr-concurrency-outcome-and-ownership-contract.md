# ADR: Concurrency Outcome and Resource-Ownership Contract

**Status**: Accepted
**Date**: 2026-09-19
**Scope**: `concurrency-outcome-and-ownership-contract` (prerequisite for the 10-item concurrency batch)

## Context

BenchBox has several concurrent execution paths with narrower, disagreeing status vocabularies:

| Surface | Observed status model | Problem |
|---|---|---|
| `benchbox/core/throughput/runner.py` (`StreamRunner`) | `streams_executed` / `streams_successful` / `errors`; timeout via `as_completed(pending, timeout=...)`; opt-in cooperative cancel (`cancel_on_timeout`, `_stream_cancel_events`); `shutdown(wait=False, cancel_futures=True)` | Timeout returns bounded but leaked worker threads keep running; timeout text does not expose owned resources or cleanup state for phase boundaries |
| `benchbox/core/tpcdi/benchmark.py` enhanced pipeline + `etl/parallel_batch_processor.py` | Scheduler stats `success` / `tasks_completed` / `tasks_failed`; wrapper `_run_parallel_batch_processing` sets `success = tasks_failed == 0`; `run_enhanced_etl_pipeline` reports overall `success = core_success` with advanced phases optional | Scheduler-level failure collapses into apparent success; explicitly requested phases treated as optional |
| `benchbox/core/expected_results/registry.py` + `tpcds_results.py` | Single-flight via `_loading` dict + `threading.Event` (waiter waits up to 30 s); module-global validation-mode overrides (`_query_validation_mode_override`, `_config_validation_mode_override`, env var); cache key is benchmark + scale factor | Publication/signal ordering and policy-independent caching are not contractually pinned; a run's policy can leak into cached answers |
| `benchbox/utils/execution_manager.py` | `PowerRunExecutor`, `ConcurrentQueryExecutor` beside canonical `StreamRunner` and benchmark power harnesses; `success` bool + `errors` list shapes; timeout via `run_with_timeout` | The two utilities are quarantined, publicly re-exported compatibility classes; `StreamRunner` is the canonical production concurrent-stream executor |
| `benchbox/mcp/jobs.py` (`DurableJobRepository`) | Row states `queued` / `running` / `publishing` / `completed` / `failed` / `cancelled`; `lease_owner` / `lease_expires_at` / `lease_version` / `lease_generation`; `claim` / `renew` / `begin_publication` / `complete` / `fail_attempt` / `cancel` / `claim_expired` | Lease expiry can requeue while the old attempt still executes database work, duplicating effects |
| Result serializers (`benchbox/core/results/metrics.py`, throughput `compute_metrics`) | `Throughput@Size`, `Power@Size`, `Qph` derived from completed streams | Partial/timeout results must never export a numeric sentinel as a valid measurement |

## Decision

Adopt one shared outcome vocabulary where the semantics are real, plus explicit adapters
where a surface is narrower. No second orchestration framework is introduced; existing narrow
state machines are extended by the owning follow-up items.

### 1. Shared outcome vocabulary

| Outcome | Terminal? | Meaning | May carry valid benchmark metrics? |
|---|---|---|---|
| `completed` | Yes | All requested work finished and its result was observed | Yes — the only outcome that may carry `Throughput@Size`, `Power@Size`, `Qph` |
| `failed` | Yes | Work finished with an error, including scheduler-reported failure and explicitly requested phases with no executable work | No |
| `timed_out` | Non-terminal w.r.t. work | The caller's bounded wait expired; says nothing about whether work stopped | No |
| `cancel_requested` | No | Cancellation was asked for but not yet confirmed effective | No |
| `outstanding_work` | No | Previously timed-out/cancelled/lease-lost work may still be executing and owning resources | No |
| `publishing` | No | A result artifact is being durably committed (`begin_publication` point in MCP; serializer write elsewhere) | No |
| `unknown` | No | Ownership or termination cannot currently be proven (e.g., worker crash, lease loss without confirmation) | No |
| `incomplete` | Yes | An explicitly requested phase had no executable or fully observed work, so the requested operation did not complete | No |
| `cancelled` (durable jobs only) | Yes | Cancellation took effect before the publication commit point | No |

Adapters: in-process runners map their local booleans onto this vocabulary at the publication
boundary (`StreamRunner` timeouts surface as `timed_out` + `outstanding_work` while workers live;
TPC-DI phases surface `failed` or `incomplete` as defined above; MCP rows keep their stored states but must expose the
shared outcome alongside row state wherever a second worker may act).

### 2. Ownership: one owner per transition

| Producer → consumer | Cancellation owner | Resource cleanup owner | Final-status publication owner |
|---|---|---|---|
| `StreamRunner.execute` → spec harnesses (`tpch`/`tpcds` `throughput_test`, `official_benchmark`) | Calling run, via cooperative cancel events where enabled | Stream owner until observed termination; combined runner must not close/reuse shared connections meanwhile | `compute_metrics` + spec `run()`; only `completed` may set a nonzero score |
| TPC-DI scheduler (`ParallelBatchProcessor`) → `_run_parallel_batch_processing` → `run_enhanced_etl_pipeline` → serialized pipeline result | Pipeline run; must propagate scheduler `success=false` and reject synthetic/non-executable work before mutation | Pipeline run; no downstream mutation after rejection | Pipeline run; overall success requires every explicitly requested phase |
| Expected-results provider → `ExpectedResultsRegistry` single-flight → waiting runs | N/A (loading is not cancellable work) | Registry lock holder; waiter never interprets in-progress load as absence | Loader, while holding the synchronization boundary, before signaling waiters; cached entries must be policy-neutral or include validation policy in their identity |
| `execution_manager` utilities → callers | Each utility's documented timeout path; no utility implies termination of another's work | Utility that submitted the work | `StreamRunner` is canonical for production concurrent streams. `PowerRunExecutor` and `ConcurrentQueryExecutor` remain quarantined compatibility classes; future removal or behavior change must preserve or version their public surface |
| MCP worker attempt → `DurableJobRepository` row → replacement worker / operator | Owning worker while its lease is valid; cross-process cancel must reach the owner (native adapter interruption where supported) | Owning attempt until termination is proven or ownership transfers under the fenced retry contract | Only the current fenced owner, before/after the `begin_publication` commit point per the fencing rules |

### 3. Bounded response is not termination

A returned timeout expires the caller's wait only. Python cannot forcibly stop a running thread,
cooperative events act only between queries, and row-state changes do not stop database work.
Therefore a `timed_out` return, a `cancel_futures=True` shutdown, a `cancel_requested` flag, or a
lease-expiry requeue must never be read as proof that work stopped.

### 4. Phase and resource containment

While `outstanding_work` or `unknown` holds for work that owned shared resources:

- no maintenance, later measured phase, or teardown may start;
- affected shared resources (connections, engines, artifacts under publication) may not be
  reused or closed by another phase or worker.

The prohibition lifts only on observed evidence: worker termination (future done/joined),
adapter-native cancellation confirmation, or a fenced ownership transfer that quarantines
capacity until termination is proven. Unsupported adapters stay safe through containment and
fail-closed status, never through assumed cancellation.

### 5. Metric validity

Only `completed` outcomes may export valid `Throughput@Size`, `Power@Size`, or composite metrics.
All other outcomes must omit those metrics from public artifacts or mark them explicitly invalid;
a numeric sentinel (e.g., `0.0`) must never read as a valid measurement.

### 6. Prohibited claims

No implementation may claim universal cancellation, exactly-once execution, or production
readiness unless this contract and its proving tests establish that property. In particular,
external MCP production acceptance stays operator-owned under
`docs/operations/mcp-production-readiness.md`; local durable-job hardening does not certify it.

## Reconciliation

This ADR constrains but does not supersede: the throughput runner's bounded-timeout design, the
canonical TPC-DI ETL path, the expected-results registry cache, the execution-manager utilities,
the durable-job lease design, or completed work (`concurrency-executor-consolidation`,
`universal-validation-mode-system-architectural-refactor`, TPC-DI phase-3 items). The ten
follow-up batch items own their surfaces:

- truthful TPC-DI parallel outcomes, expected-results single-flight/run policy, throughput
  outstanding-work containment, deterministic TPC-DI generation, adapter session capability,
  enhanced-parallel support decision, public-API semantic reconciliation, MCP ownership fencing,
  durable admission/fairness, and the final proof matrix.

## Consequences

- Follow-up items extend existing state machines with the outcomes, owners, and containment
  rules above instead of inventing parallel ones.
- The proof-matrix item verifies each invariant at the lowest layer capable of falsifying it;
  mock-based success cannot certify real cancellation or session equivalence.
