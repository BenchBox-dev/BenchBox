# ADR: Cross-benchmark power and throughput scores

- Status: Proposed
- Date: 2026-09-19
- Constrains: Future `BenchBox-Power` and `BenchBox-Throughput` methodology, score manifests, reference
  results, qualification runs, result identity, and Results Explorer score surfaces.

## Context

BenchBox reports benchmark-specific timings and official TPC metrics, but it does not have a single,
cross-benchmark measure of analytical SQL performance. A reader who wants to compare two exact system
configurations must interpret TPC-H, TPC-DS, SSB, ClickBench, Join Order Benchmark (JOB), TPC-H Skew,
TPC-Havoc, TPC-DS OBT, and primitive-query results separately.

This ADR defines the planned architecture for two synthetic scores:

- `BenchBox-Power@<size>` for one-session analytical query performance;
- `BenchBox-Throughput@<size>/C<concurrency>` for sustained concurrent analytical work.

`BenchBox-Throughput` is the canonical spelling. The earlier working name `BenchBox-Throughout` is not
used because it obscures that the metric measures throughput.

The scores are intended to synthesize the distinctive evidence in BenchBox's workload catalog without
pretending that every benchmark measures an independent property. They must also identify the exact
BenchBox version, database platform and version, hardware, operating system, deployment, tuning, dataset,
and execution policy that produced them.

This decision is proposed rather than accepted because the workload membership, weights, size vectors,
concurrency points, and reference machine still require empirical qualification. The architecture and
admission gates are the decision; the numerical constants below are pilot hypotheses.

## Research

### Geekbench scoring concepts

Geekbench is useful prior art because it turns heterogeneous workload measurements into a score that is
simple to compare while keeping the workload definitions and reference system versioned.

The [Geekbench 6 internals document](https://www.geekbench.com/doc/geekbench6-benchmark-internals.pdf)
describes these relevant properties:

1. Workloads model recognizable tasks and use representative datasets rather than one synthetic kernel.
2. Each workload is normalized to a fixed reference system. A score of 2,500 represents the reference;
   twice the score represents twice the performance.
3. Workload scores are combined geometrically inside a subsection. Geekbench 6 then combines its integer
   and floating-point subsection scores with a 65/35 weighted arithmetic mean.
4. Single-core and multi-core results are separate composites rather than one score with an undisclosed
   execution mode.
5. The runtime inserts a workload gap to reduce ordering and thermal effects.

Geekbench's evolution is as important as its formula:

- Geekbench 6 replaced the older “one separate task per core” multi-thread model with threads cooperating
  on a shared task. This changed the estimand from embarrassingly parallel capacity toward application-like
  coordination.
- [Geekbench 6.1](https://www.geekbench.com/blog/2023/06/geekbench-61/) lengthened the gap between
  workloads and changed implementations. Primate Labs states that the resulting 6.0 and 6.1 scores should
  not be compared. A methodology change therefore creates a compatibility boundary even inside a major
  benchmark generation.
- [Geekbench 7](https://www.geekbench.com/blog/2026/07/geekbench-7/) only includes a workload in its
  multi-core suite when the modeled real application is meaningfully multi-threaded. It also refreshes
  workload data and changes the reference CPU while retaining the “double the score means double the
  performance” interpretation.

The transferable concepts are normalization to a declared reference, representative workload families,
hierarchical aggregation, separate serial and parallel scores, explicit methodology versions, and
curated membership based on the behavior being modeled. BenchBox must not copy Geekbench mechanically:
database concurrency is independent sessions over shared state, not CPU threads over one in-process task,
and SQL workloads require correctness and dialect-equivalence gates before performance is meaningful.

### BenchBox prior art

This proposal extends existing BenchBox mechanisms rather than replacing them:

- `benchbox/core/throughput/runner.py` supplies a shared concurrent-stream executor for TPC-H and TPC-DS.
  The cross-benchmark runner should extend its outcome and containment contracts, not create an unrelated
  thread harness.
- `benchbox/core/results/` supplies result schemas, timing, environment identity, provenance, validation,
  and integrity checks. A score manifest should reference immutable result evidence through these
  contracts.
- `benchbox/core/expected_results/` supplies expected-result and digest mechanisms that can support score
  admission, but the new suite needs more than one exact-equality oracle.
- `docs/development/benchbox-results-platform-strategy.md` defines comparable result cohorts and deliberately
  avoids a weighted cross-context composite. The new scores are a new, explicitly versioned product
  surface; they do not reinterpret the Explorer's existing meta-leaderboard.
- `docs/development/adr/adr-client-link-locality-disclosure.md` requires client cloud and region disclosure
  plus a post-run statement-overhead probe. Score evidence inherits that contract. The score does not
  subtract network latency; comparisons disclose it and group like-with-like topology.
- `docs/blog/2026-05-18-joinorder-imdb-2013-dataset.md` records why public JOB results use the fixed IMDb
  2013 dataset at scale 1. This ADR preserves that dataset contract instead of inventing synthetic JOB
  sizes.
- The benchmark-specific TPC metrics remain available. `BenchBox-Power` and `BenchBox-Throughput` are not
  official TPC metrics and must never be labeled as such.

The score calculator, manifest, workload taxonomy, qualification policy, and reference vector are new
infrastructure. The existing runner and result components are extension points, not complete substitutes.

### Workload inventory findings

The current benchmark catalog contains candidates for the diversity needed by a useful composite,
including experimental workloads created to cover gaps in traditional suites. Whether those candidates
provide independent, non-vacuous coverage remains a pilot question rather than an established finding:

- TPC-H, TPC-DS, and SSB cover established decision-support shapes.
- ClickBench and JOB add independent query and data lineage. JOB specifically stresses join ordering and
  cardinality estimation over skewed, correlated real data.
- TPC-H Skew isolates distribution sensitivity.
- TPC-DS OBT changes the physical model while retaining analytical intent.
- TPC-Havoc changes SQL form while retaining TPC-H semantics, exposing optimizer sensitivity to syntax.
- Read Primitives and related experimental suites exercise functions and constructs that the standard
  benchmarks omit.

“Experimental” is a maturity label, not a reason to exclude a workload. These suites should be first-class
score candidates after they pass stricter correctness, portability, and non-vacuity gates.

The inventory also exposed qualification blockers:

- TPC-Havoc documents 220 variants, but `TPCHavocQueryManager.get_all_queries()` currently catches any
  generation exception and silently omits that variant. A registry count alone cannot establish the scored
  cohort.
- TPC-DS OBT currently identifies 89 convertible queries, while older catalog descriptions still describe
  a much smaller subset.
- Read Primitives has grown beyond older documented counts. Its full catalog is richer than the subset that
  runs without skips on every platform, so “portable everywhere” would remove much of the advanced SQL
  coverage the suite exists to provide.
- Some advanced-looking probes can be vacuous: JSON functions over plain text, ASOF joins over unique keys,
  one-element grouping sets, or fixed-bound windows can parse successfully without exercising the intended
  behavior.
- ClickBench has a fixed canonical dataset and JOB has a fixed canonical IMDb dataset. Neither fits a shared
  numeric scale-factor ladder.

Therefore the score cannot use declared query counts, benchmark names, or parse success as admission
evidence. It needs an explicit scored-query manifest with rendered SQL, data identity, capability coverage,
correctness evidence, and expected execution mode.

## Decision

### 1. What the scores estimate

The scores estimate end-to-end analytical SQL performance for one exact configuration. Timed work includes
planning, execution, and full result consumption through the BenchBox client. It excludes data generation,
data loading, schema creation, and warmup unless a future methodology version explicitly changes the
estimand.

The scores do not claim to measure transactional performance, data ingestion, metadata operations,
maintenance, vector search, geospatial analysis, AI inference, or total product quality. Those remain
separate results or future score families.

### 2. Score identity and names

Every published score carries a cohort key with at least:

- score-methodology major and minor version;
- score type (`power` or `throughput`) and score-specific member-manifest hash;
- capability profile;
- dataset-profile version and size label;
- concurrency for throughput;
- BenchBox version and source revision;
- benchmark/query manifest hash and rendered SQL hash;
- dataset manifest and state hashes;
- platform name, platform version, adapter identity, driver version, and SQL dialect/renderer version;
- dataset-generator and transformation-tool versions, source-object identities, row counts, and content
  hashes, including every pinned NYC Taxi slice;
- hardware identity: model, CPU, logical and physical cores where available, memory, storage, and relevant
  accelerators;
- operating system and architecture;
- deployment topology, client-to-platform locality, and the measured statement-overhead floor defined by
  the accepted locality ADR;
- tuning, resource limits, cache policy, warmup policy, repetition policy, result-consumption policy, and an
  attestation that identifies indexes, materialized structures, caches, or settings created specifically for
  the public scored manifest;
- the monotonic timing source and available timing-breakdown fields.

The compact display names are:

```text
BenchBox-Power@S
BenchBox-Throughput@S/C4
```

The display name is not the full comparison key. Interfaces must show the methodology version and exact
configuration alongside it. Results from different methodology major versions are not directly comparable.
A minor version may remain comparable only when qualification proves that scoring semantics, membership,
and reference values are unchanged. Power and Throughput have different scored member sets and are never
compared to each other merely because they share a size label. Remote and co-located runs remain valid
measurements of their declared configurations, but default comparisons must not hide material client-link
differences.

### 3. Size is a versioned workload vector

`S`, `M`, and `L` are named dataset profiles, not aliases for one universal scale factor. Each profile pins
the dataset contract for every member. A proposed pilot vector is:

| Workload family | S | M | L | Notes |
| --- | ---: | ---: | ---: | --- |
| TPC-H, TPC-Havoc, TPC-H Skew | SF1 | SF10 | SF100 | Shared lineage is controlled by block weights. |
| TPC-DS, TPC-DS OBT | SF1 | SF10 | SF100 | Final inclusion depends on runtime and storage qualification. |
| SSB | SF1 | SF10 | SF100 | Independent star-schema lineage. |
| ClickBench | Canonical | Canonical | Canonical | Fixed dataset; the profile records the same immutable identity. |
| JOB | IMDb 2013 | IMDb 2013 | IMDb 2013 | Power only; canonical dataset remains fixed at public SF1. |
| NYC Taxi | Pinned small slice | Pinned medium slice | Pinned large slice | Exact source objects and rows must be hashed. |
| Advanced fixtures | Small | Medium | Large | Event-history, nested-value, statistical, tie, and null fixtures. |

The labels do not promise equal bytes across families. They promise one immutable, documented workload
vector with a stated resource envelope. Changing any member dataset or scale creates a new dataset-profile
version.

Before freezing a profile, a versioned qualification policy declares the numerical resource, correctness,
variance, thermal, client-headroom, and timeout thresholds without seeing the qualification results.
Qualification then records generation time, load time, peak resident memory,
database size, temporary storage, spill, client memory, query runtime, timeout rate, and run-to-run variance.
A profile is rejected if it does not fit its stated resource envelope with headroom.

### 4. Capability profiles and SQL coverage

Two capability profiles prevent the least-capable platform from silently defining the benchmark:

- `analytics-core-v1` covers scans, filters, joins, correlated and uncorrelated subqueries, aggregation,
  sorting, Top-N, common table expressions, set operations, date/time operations, string operations, and
  basic window functions.
- `analytics-full-v1` adds advanced window frames and ranking, applied analytical sequences, statistical and
  approximate aggregates with accuracy checks, cube/rollup/grouping sets, pivot/unpivot, semi-structured
  data over native complex values, temporal and true ASOF joins, regular expressions and collation, lateral
  operations, recursive CTEs, and richer set semantics. Geospatial and `MATCH_RECOGNIZE` may be separately
  named extensions until enough platforms support comparable semantics.

Window coverage must include partitioned ranking with ties and nulls, moving and cumulative frames,
`ROWS` versus `RANGE`, offset functions, named windows, frame exclusion where supported, and multi-stage
analyses in which a window result feeds another relational operation. A query that only proves syntax is
not sufficient coverage.

Every scored query maps to one or more capability leaves and one source-lineage group. Companion fixtures
must make the target behavior observable:

- event history with duplicate timestamps and late arrivals for temporal work;
- nested arrays, structs, and JSON values stored in native types for semi-structured work;
- controlled distributions with known moments and quantiles for statistical functions;
- deliberate ties, nulls, and irregular intervals for windows;
- non-unique, time-varying keys for ASOF joins.

A non-vacuity test must fail when the distinguishing construct is removed or replaced with a simpler
operation. Passing SQL translation is necessary but not sufficient.

The capability matrix must resolve every proposed leaf before freeze: provide a deterministic fixture and
oracle, exclude it with a versioned rationale and reallocated weight, or move it to a separately named
extension. An uncovered leaf cannot remain an implicit zero-weight promise in Core or Full.

### 5. Workload blocks and candidate weights

The composite uses capability and source-lineage blocks so adding many variants of one query cannot buy
more influence. The pilot allocation is:

| Block | Candidate weight | Candidate members | Distinct contribution |
| --- | ---: | --- | --- |
| Standard decision support | 25% | TPC-H, TPC-DS, SSB | Established analytical shapes and broad comparability |
| Independent real-data analytics | 25% | ClickBench, JOB, NYC Taxi | Independent schemas, queries, and distributions |
| Syntax and advanced analytics | 20% | TPC-Havoc panel, qualified advanced-function panel | SQL-form robustness and missing language coverage |
| Distribution robustness | 15% | TPC-H Skew | Sensitivity to skew and selectivity errors |
| Physical-model robustness | 15% | TPC-DS OBT | Behavior under denormalized storage and different access paths |

These block weights are hypotheses, not a complete allocation. The capability-matrix work must publish
explicit weights within each block before a score manifest is frozen. Weight is assigned to capability
leaves and lineage allocations, not inferred from query count. Adding a duplicate-capability query therefore
does not create weight.

The pilot must test alternative allocations against multiple systems and holdout workloads. The frozen
weights must satisfy these guardrails over the effective nested weights after summing a lineage across all
blocks:

- no individual benchmark contributes more than 15% of a headline score;
- no shared source lineage contributes more than 40%;
- independent real-data workloads contribute at least 25%;
- advanced SQL capabilities contribute at least 15%;
- duplicating a query or syntactic variant does not change block weight.

The scored TPC-Havoc member is a constrained panel selected for semantic equivalence, transformation-family
coverage, plan or runtime differentiation, platform viability, and a fixed runtime budget. The complete
220-variant corpus remains an optional diagnostic extension. JOB is included in Power but not in the
default Throughput score because it models optimizer stress over one fixed dataset more directly than a
typical concurrent user mix. It may appear in an explicitly named plan-contention extension.

### 6. Correctness and admission

No timing contributes to a score unless the query and run pass their declared oracle. The score manifest
supports:

- exact result comparison;
- ordered or unordered comparison with declared row identity;
- numeric tolerance with absolute and relative bounds;
- approximation bounds and accuracy floors for approximate functions;
- valid-result sets when the SQL standard permits multiple answers;
- semantic equivalence to a canonical query, including TPC-Havoc variants.

Missing, skipped, timed-out, cancelled, translation-failed, or incorrect queries make the applicable block
and headline score invalid. The calculator never redistributes missing weight. It emits structured
diagnostics so capability support can be distinguished from infrastructure failure.

Every expected atom records one of `passed`, `failed_correctness`, `skipped_unsupported`,
`skipped_infrastructure`, `timed_out`, `cancelled`, or `translation_failed`. Only `passed` is scoreable. An
unsupported capability prevents that configuration from receiving the affected named profile; it does not
remove the atom or change the denominator. The manifest separately records every excluded candidate with a
reason such as unsupported, vacuous, outside the runtime budget, or duplicate coverage. Undeclared skips and
differences between declared, generated, runnable, and scored sets fail qualification.

Qualification freezes the exact member set. Registry counts, generated counts, and documentation counts
are checked against the manifest, but none is used as a scoring denominator by itself.

### 7. Power protocol

Power runs one scored query at a time with one client session and no deliberate concurrent workload. The
query order and parameter streams are deterministic and versioned. The protocol includes full result
consumption and records planning/execution/client timing boundaries when the platform exposes them, while
the score uses the end-to-end elapsed time.

Warmup and cache policy are explicit. A pilot should compare cold, prepared-warm, and steady-state policies;
the first public methodology must choose one as scored and may publish the others as diagnostics. A fixed
gap may be introduced when qualification shows that heat or resource carry-over materially biases later
queries, following Geekbench's treatment of workload-order effects.

The selected cache state must have a platform-specific, replayable procedure and verification evidence. If
a platform cannot control or verify a cold state, it may qualify only for a methodology that declares the
achievable state, such as `warm_only`; it must not label an uncontrolled run as cold. The process/session
lifecycle and any cache-control hook are part of the cohort evidence.

A public score cannot be selected from one unusually fast run. The pilot starts with three complete,
independently measured repetitions for candidate results. It aggregates each atomic measure by the median
before normalization and publishes the dispersion and every constituent run. The frozen methodology may
raise that minimum when measured variance requires it. Each repetition starts from the declared data and
cache state and rotates the deterministic query schedule so one position does not receive a permanent
advantage.

The predeclared scored set contains at least three complete repetitions. Every repetition must contain every
required atom. A failed repetition remains published evidence and invalidates that submission; it cannot be
discarded while faster repetitions are retained. Exploratory runs are labeled separately. For a valid scored
set, the calculator takes each atom's median across the complete repetitions and publishes all raw values
plus the methodology's declared dispersion statistics.

### 8. Throughput protocol and concurrency

Throughput is not “Power with more threads.” It models multiple independent analytical sessions sharing a
platform and dataset.

Version 1 uses a finite-batch protocol:

1. Start `C` independent sessions.
2. Give each session a deterministic, versioned permutation and parameter stream.
3. Permit one outstanding query per session.
4. Start the measured interval when all sessions are ready and the first work is released.
5. Run an integer number of complete scored cycles per session; do not stop in a way that favors short
   queries.
6. Consume every result fully.
7. End only when all admitted work completes; include in-flight work, errors, and tail latency in the
   result.

The default mix includes TPC-H, TPC-DS, SSB, canonical ClickBench, TPC-H Skew, TPC-DS OBT, and a bounded
advanced-function mix after admission. Full TPC-Havoc and JOB remain Power-only by default. Platform-native
TPC throughput and composite metrics continue to be reported separately.

Qualification measures the ladder `{1, 2, 4, 8, 16}` and adds `32` for server-class profiles where feasible.
The public result should retain the curve. Initial display-point hypotheses are `S/C4`, `M/C8`, and `L/C16`,
but they are not frozen until the pilot identifies saturation, stability, memory pressure, and platform
coverage. A platform must not silently reduce `C`; a lower supported point is a different score name.

Each run records active interval, completed work, queries per second, per-session fairness, P50/P95/P99
latency, timeout/cancellation state, client CPU and memory, platform utilization where available, cache
policy, and pool/session configuration. The existing concurrent-stream executor is the starting point, but
the implementation must preserve one real database session per logical stream and contain outstanding work
after timeout before it can support the score.

Containment means more than returning from a Python future. A scored implementation must provide a
platform-supported statement or session cancellation boundary, wait through a bounded drain barrier, and
prove that no abandoned query can issue work after the deadline or overlap the next repetition. If it cannot
prove termination, the repetition is invalid and its connection, pool, or execution context is quarantined
from later scored work. Process isolation may be used where cooperative cancellation cannot meet this
contract. Detect-and-invalidate without a successful drain is safe for the current result but can still
contaminate later work, so the executor must not reuse that environment for another scored repetition.

Throughput uses the same complete-repetition rule as Power. A repetition with an incomplete stream or cycle
is invalid and cannot be replaced selectively. A later attempt is a new submission that reruns the full
predeclared repetition set under the same manifest and retains the failed attempt as evidence.

A concurrency point is also invalid when the load generator breaches predeclared client CPU, memory, or
event-loop headroom. Such a point is labeled client-limited rather than platform-limited and cannot become
the public display point.

### 9. Normalization and aggregation

Each atomic measurement becomes a dimensionless ratio against the matching reference measurement:

```text
power_ratio_i = reference_elapsed_i / candidate_elapsed_i
throughput_ratio_i = candidate_completed_work_per_second_i /
                     reference_completed_work_per_second_i
```

For throughput, one atomic measurement is a complete workload-family batch at one declared concurrency.
Completed work per second counts only a fixed manifest's successful queries over the full active interval;
an incomplete cycle invalidates the atom instead of changing its denominator.

For atomic measures where higher is better, the ratio direction follows the throughput form. Accuracy is an
admission gate, not a performance multiplier, unless a future methodology explicitly defines an
accuracy-performance score.

Within a block, use the weighted geometric mean:

```text
B_k = exp(sum_i(w_i * ln(r_i)) / sum_i(w_i))
```

The headline remains geometric across blocks:

```text
BenchBox score = 1000 * exp(sum_k(W_k * ln(B_k)) / sum_k(W_k))
```

The reference configuration therefore scores 1,000. A score of 2,000 means twice the aggregate performance
under that exact methodology and profile; it does not mean twice the performance for every query.

BenchBox does not copy Geekbench 6's final weighted arithmetic step. Keeping the hierarchy geometric avoids
one exceptional block dominating the composite and preserves ratio-scale properties. Paired-query ratios,
tail latency, and robustness deltas remain diagnostics rather than hidden additions to the headline.

The calculator must prove these invariants with golden fixtures:

- the reference vector scores exactly 1,000 within declared rounding;
- multiplying every candidate atomic performance value by `x` multiplies the score by `x`;
- duplicating a query without changing declared weights does not change the score;
- changing query enumeration order does not change the score;
- a missing or incorrect required result cannot increase a score and does not redistribute weight;
- candidate A ranks above B independently of which qualified physical reference supplies an equivalent
  normalized reference vector, where equivalent vectors are scalar multiples;
- a proportional alternative reference preserves ranking, while a non-proportional vector is rejected as
  non-equivalent and requires recalibration evidence or a methodology-major change;
- replaying one immutable manifest and evidence bundle produces the same score.

### 10. Reference configuration

A Mac mini with Apple M4 and 16 GB RAM running DuckDB at the M profile is the first reference candidate,
not the predeclared reference. The frozen reference must additionally identify exact storage, macOS build,
DuckDB version and build, BenchBox revision, adapter and driver versions, power mode, background-service
policy, tuning, memory and thread limits, client runtime, and every dataset/score manifest hash.

Qualification has three stages:

1. A qualification-policy artifact freezes numerical correctness, timeout, variance, resource-headroom,
   thermal/power-mode, background-service, locality, and client-saturation thresholds before measurements.
2. Three exploratory runs per profile and concurrency point identify infeasible datasets, spill, thermal
   drift, timeouts, and high-variance members.
3. After the methodology candidate is frozen, five fresh end-to-end runs produce the reference vector and
   confidence report. Each atomic reference value is the median of those five runs. The reference is
   accepted only if every required query is correct, no resource envelope is breached, and per-block
   variance meets thresholds defined before the run.

The M4/16 GB candidate is acceptable only for profiles it can execute with operational headroom. If it
cannot qualify M or L, BenchBox may use a different reference configuration for that profile. The profile's
reference identity is immutable within a methodology major version; changing it requires either a
mathematically equivalent recalibration with published proof or a new major version.

The pilot must evaluate at least one embedded and one client-server reference candidate and report ranking
and sensitivity effects before selecting a physical reference. A replacement physical unit must repeat
qualification; matching a model name is not sufficient evidence of equivalence.

### 11. Planned architecture

Implementation proceeds in separable layers:

1. **Methodology assets.** Versioned capability taxonomy, workload/dataset profile, scored-query manifest,
   oracle declarations, weights, and concurrency policy.
2. **Replayable calculator.** A pure calculator consumes a frozen manifest, reference vector, and admitted
   result evidence. It does not run benchmarks or read mutable registries.
3. **Evidence and identity.** Result bundles record the full score cohort key, rendered SQL, parameters,
   order, session schedule, data state, correctness outcomes, and workload-level measurements.
4. **Execution orchestration.** Power and throughput runners reuse the core run service, timing utilities,
   result contracts, and throughput executor after required session and timeout semantics are verified.
5. **Qualification tools.** Resource/variance reports select feasible profiles, concurrency points,
   workload panels, and weights before any public methodology is accepted.
6. **Publication.** A distinct Results Explorer surface shows headline scores, block scores, workload detail,
   correctness, variance, concurrency curves, reference identity, and methodology version. Existing
   cross-benchmark ranking data is not silently converted into a BenchBox score.

Publication is mechanically gated. A ranked bundle must identify a frozen methodology major, a qualified
reference-vector ID, and the exact frozen manifest hash. Development and pilot bundles remain provisional
and unranked; CI and ingestion reject any bundle whose identities do not match the qualified set.

## Review findings incorporated

Adversarial reviews changed the proposal in these material ways:

- benchmark-count weighting was replaced with capability and lineage blocks;
- experimental benchmarks became first-class candidates with stronger admission gates;
- a portable no-skip query core was rejected as the only score because it discards advanced SQL coverage;
- fixed canonical datasets and scalable synthetic datasets were separated into versioned size vectors;
- concurrency became an explicit measured dimension, with a ladder and published curve rather than one
  asserted constant;
- advanced windows, applied analytics, complex types, approximate accuracy, temporal behavior, and
  non-vacuity fixtures were added to the qualification contract;
- JOB and full TPC-Havoc were removed from the default throughput mix while remaining important Power or
  diagnostic workloads;
- a fully geometric hierarchy replaced mixed arithmetic/geometric aggregation;
- the M4/16 GB example became a reference candidate subject to resource and variance qualification.

Two challenges were rejected. First, experimental workloads are not excluded merely because they are
experimental; their purpose is directly relevant and admission evidence addresses their maturity. Second,
all benchmarks do not receive equal top-level weight, because TPC-H, TPC-Havoc, and TPC-H Skew share data
and query ancestry and would otherwise dominate independent evidence.

### External review adjudication

Claude Sonnet and Muse independently reviewed this proposed ADR and its tracker sequence. Each reported
finding was resolved as follows. `NARROW` means the underlying risk was accepted but the proposed remedy was
made platform-neutral or aligned with the score's atomic model.

| Reviewer finding | Disposition | Resolution |
| --- | --- | --- |
| Muse F-CRIT-001: ambiguous skip and failure states | ACCEPT | The manifest now has explicit evidence states; only `passed` scores, and unsupported required work invalidates the named profile. |
| Muse F-CRIT-002: timed-out threads can leak work | NARROW | Scored runs require cancellation plus a drain barrier or isolation; a failed drain quarantines the execution context. No one database-specific timeout mechanism is mandated. |
| Muse F-CRIT-003: fixture and non-vacuity work was under-specified | ACCEPT | Fixture, oracle-engine, and TPC-Havoc equivalence work are separate tasks, and the manifest depends on all three. |
| Muse F-CRIT-004: reference thresholds could be selected after seeing results | ACCEPT | A separate qualification-policy task freezes numerical gates before pilot measurements. |
| Muse F-REQ-005: block weights could exceed the TPC-H lineage cap | NARROW | Effective lineage weights are summed across blocks and must be demonstrated before manifest freeze; the provisional top-level block percentages need not be discarded yet. |
| Muse F-REQ-006: reference-independent ranking was too broad | ACCEPT | Equivalence is limited to scalar-multiple vectors; a non-proportional vector must be rejected or cause a major-version recalibration. |
| Muse F-REQ-007: Power and Throughput can have different members at the same size | NARROW | Score type and its member-manifest hash are cohort identity; membership belongs in the score manifest rather than the dataset profile. |
| Muse F-REQ-008: cache state was not reproducible | ACCEPT | Each platform needs a recorded, verified cache-state procedure; otherwise it can qualify only for an honestly named achievable state. |
| Muse F-REQ-009: repetition aggregation allowed partial interpretation | NARROW | Every predeclared repetition must be complete and failures cannot be discarded. Atomic measures remain queries for Power and complete family batches for Throughput, rather than redefining an atom as the whole suite. |
| Muse F-REQ-010: missing TODO dependency edges | NARROW | Manifest schema now depends on the oracle/fixture/equivalence tasks. A direct multi-system-to-oracle edge is unnecessary because both runners and the manifest provide that dependency transitively. |
| Muse F-REQ-011: publication ordering lacked a mechanical gate | ACCEPT | Ranked publication must verify the frozen methodology, qualified reference, and frozen manifest hashes. |
| Muse F-REQ-012: generator, data-slice, renderer, and clock provenance gaps | NARROW | Generator/tool versions, post-translation SQL, source objects, rows, hashes, and timing source are recorded. BenchBox revision already binds the timing implementation, so the clock alias is evidence rather than a separate comparison dimension. |
| Muse F-REQ-013: runnable and scored sets were conflated | ACCEPT | The inventory now defines admitted and excluded sets, reason codes, and fail-closed skip drift. |
| Muse F-REQ-014: unsupported Full-profile leaves could block forever | ACCEPT | Every leaf must gain a fixture, be explicitly removed with weight reallocation, or move to a named extension before freeze. |
| Muse F-REQ-015: “materially different systems” was undefined | ACCEPT | The pilot requires embedded, client-server, and distributed or managed-warehouse execution archetypes, with exceptions requiring evidence. |
| Muse F-NIT-016: timing boundaries were not auditable | ACCEPT | Monotonic total time is required; optional planning, execution, and fetch components and non-overlapping setup/scored phases are evidence. |
| Muse F-CONS-017: query counts could still influence within-block weight | ACCEPT | Leaf and lineage weights are explicit; duplicate-capability queries cannot create weight. |
| Muse F-CONS-018: the client could be the throughput bottleneck | ACCEPT | Client-headroom thresholds are preregistered and client-limited points cannot become headlines. |
| Claude ADR-SCORE-01: lineage arithmetic was absent | ACCEPT | The capability-matrix task must publish the complete effective-weight audit before manifest work. |
| Claude ADR-SCORE-02: thread containment was unachievable as written | NARROW | The contract permits process isolation or platform cancellation, but always requires a bounded drain and quarantine on failure. |
| Claude ADR-SCORE-03: accepted locality policy was omitted | ACCEPT | The ADR now inherits the locality ADR, overhead probe, disclosure, and comparison behavior. |
| Claude ADR-SCORE-04: reference-equivalence test could be vacuous | NARROW | Golden tests require a proportional alternative that preserves order and a non-proportional vector that is rejected; two arbitrary physical references are not assumed equivalent. |
| Claude ADR-SCORE-05: manifest could precede oracle design | ACCEPT | The dependency is reversed so the manifest consumes the completed contracts. |
| Claude ADR-SCORE-06: the advanced-oracle task was overloaded | ACCEPT | It is split into oracle-engine, fixture/non-vacuity, and TPC-Havoc-equivalence items. |
| Claude ADR-SCORE-07: public-manifest-specific tuning was undisclosed | ACCEPT | The cohort key gains a benchmark-specialization attestation, and freeze/publication policy must label and filter such results. |
| Claude ADR-SCORE-08: an embedded reference may bias Throughput | ACCEPT | Qualification compares embedded and client-server reference candidates and reports rank sensitivity before selection. |
| Claude ADR-SCORE-09: Power should ship independently | REBUT | Version 1 is intentionally a coherent two-metric methodology with shared identities and gates. Splitting release milestones would permit a partial product under the same version before the requested concurrency metric is sound. |
| Claude ADR-SCORE-10: `benchbox/core/manifest/` does not exist | REBUT | The exact reviewed revision contains that package, including `models.py`, `io.py`, and `io_specs.yaml`; the tracker link is valid. |

Muse's additional cost, energy, tenancy, and data-freshness concerns do not become hidden score dimensions.
Cost and energy may be published as diagnostics; isolation and quota policy belong to execution qualification;
and fixed datasets are deliberately immutable for reproducibility rather than freshness claims. Its cross-engine
null, NaN, timestamp, collation, and complex-value semantics concern is accepted into the oracle contract.
Claude's hardware-unit continuity and shared-host resource-accounting concerns are accepted into reference
qualification and topology evidence. Both reviewers' suggestion to make the diagnostic surface primary is
accepted in presentation—the Explorer must show blocks and evidence next to the headline—but not as a reason
to remove the two headline metrics requested here. Holdout and sensitivity gates test whether those headlines
add stable information before publication.

## Alternatives rejected

### One universal numeric scale factor

Rejected because ClickBench and JOB have fixed canonical datasets, while scale factors from different
specifications do not imply equal bytes, complexity, or resource demand. Versioned `S`, `M`, and `L`
vectors are more honest.

### Hide concurrency behind `@size`

Rejected because throughput changes materially with session count and saturation. `C` is part of the score
name and immutable cohort identity.

### Weight every benchmark or query equally

Rejected because correlated suites and large variant catalogs would dominate by enumeration. Capability
and lineage weights preserve diversity without rewarding duplication.

### Score only queries supported by every platform

Rejected as the sole headline because it lets the least-capable implementation remove the window,
semi-structured, statistical, temporal, and advanced analytical features the experimental benchmarks were
created to cover. Named Core and Full profiles make support explicit.

### Require every Power workload in Throughput

Rejected because some workloads model optimizer robustness or exhaustive syntax variation rather than a
realistic concurrent session. Throughput membership follows modeled concurrent use, as Geekbench 7 limits
multi-core membership to workloads whose applications are meaningfully multi-threaded.

### Use paired-query robustness penalties in the headline

Rejected for version 1. TPC-H versus TPC-Havoc and normalized versus skewed pairs are valuable diagnostics,
but an added penalty is difficult to interpret and can double-count shared lineage. Admit representative
members into weighted blocks and publish paired deltas separately.

### Freeze the M4/16 GB reference before qualification

Rejected because a convenient machine is not automatically a stable reference for all profiles. Resource,
correctness, and variance evidence must determine whether it qualifies.

### Reuse the Explorer meta-leaderboard as the score

Rejected because rank aggregation does not preserve a “twice the score means twice the performance”
interpretation, and existing cohorts do not carry the scored manifest and correctness contract.

## Consequences

Positive consequences:

- Users get two understandable, ratio-scaled summary metrics while retaining block and query evidence.
- Concurrency, methodology, software, hardware, and data identity become explicit comparison dimensions.
- Experimental workloads contribute the syntax, function, skew, and physical-model diversity they were
  designed to provide.
- Correctness, capability, and non-vacuity gates prevent fast wrong answers or trivial probes from scoring.
- The pure calculator can be tested and audited before the expensive orchestration exists.

Costs and limitations:

- Qualification requires substantial multi-system and multi-profile execution before publication.
- Some platforms will have a Core score but no Full score; that is an honest capability outcome.
- Fixed datasets mean `S`, `M`, and `L` are workload profiles, not progressively larger forms of every
  member.
- `Power` means single-session query performance, not electrical power. Energy, monetary cost, and carbon
  estimates may accompany a result but are not part of either version 1 headline.
- A platform without reliable cancellation may need process isolation or may be ineligible for a Throughput
  score. A detected timeout protects the current score only after the environment drains; otherwise later
  repetitions must use a new, uncontaminated execution context.
- A composite hides variation. Public surfaces must show blocks, query distributions, correctness, and
  concurrency curves next to the headline.
- Methodology changes can create non-comparable score generations. BenchBox must version and communicate
  those boundaries instead of backfilling old results under new rules.

## Acceptance gates for methodology version 1

This ADR may move from Proposed to Accepted only when:

1. Catalog, documentation, generated, runnable, excluded, and scored-query sets are reconciled for every
   candidate workload, with no undeclared skip path.
2. The Core and Full capability matrices have no unowned coverage gaps, and each scored capability has a
   non-vacuous fixture or workload.
3. Every scored query has a passing oracle on the qualification platforms.
4. The calculator passes its algebraic and replay invariants.
5. At least three materially different database systems complete the pilot—covering embedded,
   client-server, and distributed or managed-warehouse execution—so weights are not tuned to DuckDB or one
   deployment archetype alone.
6. Holdout analysis shows that the headline tracks independent workload performance better than simpler
   alternatives and does not collapse into one lineage or one query family.
7. Size-profile resource envelopes and final concurrency points are supported by measured data.
8. The reference candidate passes five fresh qualification runs with the predeclared variance and resource
   thresholds.
9. The result schema and Explorer disclose the complete cohort key, invalid/missing state, blocks,
   concurrency curves, and reference identity.
10. Publication mechanically rejects a non-frozen methodology, unqualified reference, manifest mismatch,
    or undisclosed benchmark-specific tuning; documentation states that these are BenchBox synthetic
    metrics, not official TPC results.

## Implementation ownership

The tracker sequence rooted at `benchbox-score-workload-contracts` owns implementation and qualification.
No task may publish a headline score before the methodology-freeze item has satisfied every acceptance gate
above.

| Order | Tracker item | Depends on |
| ---: | --- | --- |
| 1 | `benchbox-score-workload-contracts` | — |
| 2 | `benchbox-score-capability-matrix` | Workload contracts |
| 3 | `benchbox-score-advanced-oracles` | Capability matrix |
| 4 | `benchbox-score-advanced-fixtures` | Capability matrix |
| 5 | `benchbox-score-tpchavoc-equivalence` | Capability matrix and oracle engine |
| 6 | `benchbox-score-manifest-schema` | Oracle engine, advanced fixtures, and TPC-Havoc equivalence |
| 7 | `benchbox-score-qualification-policy` | Manifest schema |
| 8 | `benchbox-score-calculator` | Manifest schema |
| 9 | `benchbox-score-power-runner` | Manifest schema |
| 10 | `benchbox-score-throughput-runner` | Manifest schema |
| 11 | `benchbox-score-size-profile-pilot` | Power runner and qualification policy |
| 12 | `benchbox-score-concurrency-pilot` | Throughput runner, size-profile pilot, and qualification policy |
| 13 | `benchbox-score-multisystem-pilot` | Calculator, both runners, and both profile pilots |
| 14 | `benchbox-score-methodology-freeze` | Multi-system pilot |
| 15 | `benchbox-score-explorer-publication` | Methodology freeze |
