# ADR: JOB Scale-Stress Benchmark Decision Framework

Date: 2026-06-30

Status: Accepted — `replicated_imdb` baseline recommended as the smallest next
prototype; first-class statistics-phase accounting deferred to a dependency TODO.

This is a decision framework, not an implementation. It decides *whether and how*
BenchBox should add a scaled JOB-derived workload for evaluating optimizer
behavior as correlated predicates and join graphs grow past statistics, sampling,
planning-time, memory, and distributed-execution thresholds. It concludes with a
go/no-go recommendation and names the smallest next prototype with verification
criteria. The companion licensing record is
`_project/decisions/joinorder-scale-stress-licensing-2026-06-30.md`; this file
does not use the licensing filename prefix.

## Benchmark question and non-goals

A scaled JOB-derived workload answers a *different* question from canonical JOB.
Canonical JOB evaluates optimizer/cardinality behavior on a fixed real correlated
dataset (canonical IMDb 2013, SF=1) and is comparable to the Leis et al. VLDB
2015 literature. A scaled JOB-derived workload instead evaluates how optimizers
degrade as data grows. The framework must keep these axes separate:

- **Canonical JOB comparability** — fixed dataset, fixed 113 queries, literature
  baseline. Not what scale-stress measures.
- **Physical scale stress** — spill, memory thresholds, distributed shuffle as
  bytes grow.
- **Statistics-maintenance stress** — cost and freshness of optimizer statistics
  as data is loaded, re-loaded, and grown incrementally.
- **Predicate selectivity drift** — how fixed literal predicates change
  selectivity as the database grows around them.
- **Optimizer search / planning-time limits** — join-order search blowup as the
  join graph widens.
- **Distributed skew and spill behavior** — partition skew under correlated keys.

Non-goals: scaled JOB-derived results are **not** canonical JOB results and must
never publish as canonical `joinorder` or claim literature comparability. Any
scale-up is labeled derived (`job_scale_stress`, `replicated_imdb`, etc.). The
evidence that this problem is real and distinct from the JOB paper's fixed-dataset
cardinality-estimation problem (engine docs on sampled/stale/partition statistics
limits, BenchBox-local large-scale observations, and optimizer/planning-time
literature) is collected separately from the original JOB cardinality-estimation
framing and motivates a distinct workload identity rather than re-using `joinorder`.

## Scale semantics

"Scale factor" for a JOB-derived workload is defined as **integer multiplication
of total IMDb row count across all 21 entity classes**, not bytes and not title
count alone. SF=N means each canonical table is replicated/expanded to
approximately N× its canonical row count with referential integrity preserved.
Bytes and per-query cardinality are *derived* reporting fields, not the scale
control, because byte size varies by engine encoding and per-query cardinality is
exactly what the workload measures.

Workload labels and their comparability rules:

| Label | Data origin | Comparable to canonical JOB? | Publication rule |
| --- | --- | --- | --- |
| canonical_imdb | Fixed IMDb 2013, SF=1 | Yes (this *is* canonical JOB) | Publishes as `joinorder` |
| replicated_imdb | Offset-replicated canonical | No | Derived; carries dataset_version + replica count |
| expanded_imdb | Profiled graph expansion | No | Derived; research-only until validated |
| parameterized_imdb | Queries sampled from scaled graph | No | Derived; separate leaderboard from fixed queries |
| synthetic_schema | Fully synthetic correlated generator | No | Derived; correlations are modeled, not real |

Every derived label must report data-generation strategy, dataset version,
generator version, seed, and stats protocol in result-bundle metadata. The
`canonical_imdb` label is never silently replaced by a derived mode.

## Statistics phase and measurements

The core research question includes statistics maintenance, so stats-build time
must be a **separate phase** between load and query: `load → statistics → query`.
Folding stats-build into load or query invalidates the measurement before it
starts (an engine with 30s auto-stats looks 30s slower at load *or* at
first-query — neither attribution is correct).

Per-engine statistics compatibility matrix (concrete numbers bound during
implementation):

| Engine | Has explicit ANALYZE? | Auto-stats on load? | Sampled mode? | Stats-phase attribution |
| --- | --- | --- | --- | --- |
| DuckDB | yes (ANALYZE) | yes (background) | n/a | zero wall-clock; `stats_mode: auto-on-load` |
| PostgreSQL | yes (ANALYZE) | no | yes (default_statistics_target) | explicit ANALYZE phase timed |
| ClickHouse | partial (per-table) | yes (on insert) | n/a | zero wall-clock; `stats_mode: auto-on-load` |
| StarRocks | yes (ANALYZE TABLE) | no | yes (sample size knob) | explicit ANALYZE phase timed |
| Spark | yes (ANALYZE TABLE) | no | yes | explicit ANALYZE phase timed |

For engines without an explicit ANALYZE, the stats-phase wall-clock is reported as
zero with `stats_mode: auto-on-load` recorded in result-bundle metadata so
attribution is unambiguous.

Measurement methodology (required):

- **Cache state**: each phase begins with documented cache state — drop caches
  before stats-build, no drop between stats-build and planning — so cold-vs-warm
  is explicit.
- **Per-engine knobs**: `default_statistics_target` (PostgreSQL), sample size
  (StarRocks), etc., documented per run.
- **Idempotence**: re-running ANALYZE on already-analyzed data must produce the
  same plan (sanity check).

First-class statistics-phase accounting is **not yet implemented**. The canonical
follow-up slug is `track2-joinorder-stats-phase` (seeded by
`joinorder-track2-groundwork` w2). Any implementation prototype must depend on
that TODO before coding rather than re-rolling a separate
`joinorder-statistics-phase-measurement.yaml`. The machine-checkable gate:

Stats phase gate: dependency:track2-joinorder-stats-phase

## Scale-up options

| Option | Correlation fidelity | Impl. cost | Validation oracle | Stats-stress value | User-mislead risk |
| --- | --- | --- | --- | --- | --- |
| Offset replication of canonical IMDb (`replicated_imdb`) | Real correlations preserved within each replica | Low | Canonical oracle × replica count | Medium (stale-stats axis, modest predicate drift) | Low if labeled |
| Predicate-preserving augmentation | Real backbone, synthetic tail | Medium | Partial (synthetic part unverifiable) | Medium | Medium |
| Profiled graph expansion (`expanded_imdb`) | Modeled, can destroy JOB signal | High | Weak | High if correct | High |
| Parameterized JOB-like generation (`parameterized_imdb`) | Real data, sampled predicates | Medium | Per-generated-query oracle needed | High | Medium |
| Newer real IMDb snapshot | Real, but not the JOB-paper dataset | Medium | None vs literature | Medium | High (looks canonical) |

Offset replication is the lowest-risk first step: it preserves real intra-replica
correlations, reuses the canonical oracle (reference cardinalities scale by the
replica count for the subset of queries whose predicates do not cross replica
boundaries), and exercises a stale-statistics axis without inventing correlations.
Its limitation — predicate selectivity drift is bounded because replicas are
disjoint — is acceptable for a baseline and is explicitly documented rather than
hidden. Offset replication is **not** chosen merely because it is easiest; it is
chosen because it answers the statistics-maintenance sub-question with a real
oracle while the higher-fidelity options (graph expansion, parameterized
generation) remain unvalidated.

## Validation gates for derived workloads

A derived workload ships only behind a validation gate stronger than existence
checks. Non-empty checks are insufficient: a workload can return rows and still be
silently wrong (queries-empty-by-construction, predicate-domain drift, broken
referential integrity). The gate must verify:

- FK integrity across all 21 tables, and per-table row counts.
- Predicate-domain frequencies and per-column null counts.
- Fixed-query result cardinalities and pre-aggregate match counts.
- Important join-subgraph cardinalities (not just final result cardinalities).
- A q-error profile wherever a reference estimator or engine plan output exists.
- Plan shape and planning-time summaries.

The q-error and cardinality checks are the load-bearing gates: a derived dataset
that preserves row counts but shifts cardinality distributions unevenly will pass
naive checks while destroying the JOB signal. Define these measurement gates
*before* building any generator.

## Fixed vs parameterized

The first scaled workload keeps the **fixed 113 JOB queries** and studies what
happens as the database grows around those fixed literals. This preserves the
clearest tie to canonical JOB semantics (the literals are the JOB literals) and
gives a real reference oracle. Parameterized JOB-like generation
(`parameterized_imdb`) — predicates sampled from the scaled graph — is a valuable
*separate* track but needs its own per-query oracle and must not be mixed into the
same leaderboard or cohort as the fixed queries. If both are eventually built,
they publish under separate result labels.

## Recommendation and prototype scope

Recommendation: replicated_imdb baseline only

Rationale: offset replication is the only option that (a) preserves real
correlations, (b) reuses the canonical oracle for validation, and (c) exposes a
genuine statistics-maintenance axis (stale stats after loading additional
replicas), all at low implementation cost and low user-mislead risk when labeled.
It explicitly rejects **profiled graph expansion** for the first prototype:
synthetic correlations can look plausible while destroying the very JOB signal the
benchmark exists to measure, and graph expansion has no independent validation
oracle yet. Newer-IMDb-snapshot is rejected for the baseline because it breaks
literature comparability while *looking* canonical.

Smallest next prototype and its verification criteria
(`_project/TODO/main/planning/joinorder-replicated-imdb-scale-prototype.yaml`,
currently quiescent — status "Not Started", no in-progress work units, so this
framework does not mutate it; the prototype owner wires the stats-phase dependency
at its next checkpoint once `track2-joinorder-stats-phase` exists):

- Offset-replicate canonical IMDb at SF=2 with consistent PK/FK offsetting.
- Validate via the canonical oracle scaled by replica count plus the full
  validation-gate list above (FK integrity, predicate-domain frequencies,
  cardinalities, q-error where available).
- Run the fixed 113 queries; report load, statistics, planning, and execution
  time as separate phases.
- Gate: prototype must depend on `track2-joinorder-stats-phase` before any
  statistics-phase wall-clock is claimed as publication-quality.

## CI cost & infrastructure

- **Estimated dataset size per tier**: `replicated_imdb` SF=2 ≈ 3 GB Parquet,
  SF=10 ≈ 15 GB. Beyond SF=10 the archive exceeds practical CI download budgets
  and is local/manual-only.
- **Cache strategy**: CI runner cache keyed on dataset_version + replica count,
  not fresh download per run. Bandwidth ≈ archive size × runner-count ×
  run-frequency; SF=2 at a few runs/day is bounded, SF=10 is cache-or-skip.
- **Download-failure handling**: retry with backoff (3 attempts), fall back to a
  cached prior dataset_version if the hosted Release is unreachable, and abort the
  cell (not the whole matrix) past the retry threshold.
- **Cost ceiling per matrix run**: the prototype runs DuckDB + PostgreSQL locally
  only (≈ no cloud cost); any cloud-engine matrix is deferred from the prototype
  with a documented rough $/run before it is enabled.

## Licensing posture for derived workloads

`replicated_imdb` is a deterministic transformation (offset replication) of the
canonical IMDb-2013 archive. The derived archive carries the source
`dataset_version` and inherits the canonical dataset's redistribution posture and
license review (`joinorder-canonical-data-licensing-2026-05-12`) unless the
transformation is judged material. Because offset replication does not add new
source data — only mechanically duplicates existing rows with offset keys — the
posture is treated as inherited-but-re-pinned rather than cleared anew. The full
posture, attribution, hosting model, and takedown contact for the derived form are
pinned in `_project/decisions/joinorder-scale-stress-licensing-2026-06-30.md`.
`parameterized_imdb` (queries only, no derived data archive) needs no new license
review.
