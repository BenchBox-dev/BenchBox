# ADR: Track-2 JOB Scaling Direction — sampled-from-real first

Date: 2026-07-04

Status: Accepted (project-owner decision, 2026-07-04). Supersedes the
recommendation section of
`_project/decisions/joinorder-scale-stress-decision-2026-06-30.md`; the rest of
that framework (options analysis, validation gates, fixed-vs-parameterized,
CI-cost model) remains in force.

## Decision

Track 2 pursues **one** scaling direction first: **sampled-from-real**
(Option B in `_project/design/track2-joinorder-scaling-strategy.md` —
title-stratified downsampling of the canonical IMDb-2013 archive with
referential-integrity preservation).

`replicated_imdb` (offset replication, the 2026-06-30 framework's pick) is
**deferred, not rejected**: its prototype seed
(`_project/TODO/main/planning/joinorder-replicated-imdb-scale-prototype.yaml`)
stays gated and must not start unless a future decision re-approves an upward
axis. The two directions are not pursued as parallel tracks; a second track
requires its own decision note. Option E (stats-only at SF=1) remains the
correctness fallback if the sampling axis cannot be validated.

## Why sampled-from-real

The two documents disagreed because they answered different research questions.
The question Track 2 is actually chartered on — recorded in
`_project/design/track2-joinorder-stats-as-phase.md` ("Track 2's research
question is the interplay of statistics maintenance and predicate selectivity")
— is served by an axis on which per-predicate selectivities and correlations
genuinely move between scale points. Title-stratified sampling provides that:
each sample point has different predicate-match counts, different join-fanout
distributions, and a real opportunity for the optimizer to mis-estimate.

Offset replication cannot provide it. Because replicas are value-identical and
disjoint, per-predicate selectivity is scale-invariant by construction; the
only staleness a stats-maintenance phase can expose on replicated data is a
uniform ×N row-count miss. That is a real but degenerate signal — it does not
exercise the correlated/skewed mis-estimation behavior the research question
targets. (This resolves the tension inside the 2026-06-30 note, which conceded
"predicate selectivity drift is bounded because replicas are disjoint" while
still describing the axis as "a genuine statistics-maintenance axis".)

Replication's remaining advantage — the canonical final-result oracle is
replica-invariant (the 113 scalar `MIN` results are unchanged), so validation
is nearly free — is an argument about implementation cost, not about the
research question. It is why replication stays on the shelf rather than being
rejected: if a genuine "larger-than-SF=1" question is chartered later
(distributed-execution thresholds, memory cliffs), replication is still the
lowest-risk upward path.

## Accepted costs

- **Per-sample-point oracle regeneration.** Sampled data changes query results,
  so each published sample point needs its own reference oracle computed with
  the existing PostgreSQL pipeline (the `reference_cardinalities.json`
  precedent, including known-zero tracking — downsampling will push more of the
  113 queries to zero underlying rows at small fractions, and each sample
  point's known-zero set must be recorded rather than assumed).
- **The 2026-06-30 framework's validation gates apply unchanged** (FK
  integrity, predicate-domain frequencies, join-subgraph cardinalities,
  q-error where available). Sampling makes these gates *more* load-bearing
  than replication would, since there is no replica-invariance shortcut.
- **Stats-phase dependency carries over.** The sampling track inherits the same
  gate: no publication-quality statistics-maintenance claims before
  `track2-joinorder-stats-phase` lands.

## Licensing

A sampled derived archive is, like replication, an alteration of the canonical
data. The risk-parity reasoning in
`_project/decisions/joinorder-scale-stress-licensing-2026-06-30.md` (as
reworded on 2026-07-04 to engage the upstream "must not be altered" term
directly) applies a fortiori: sampling removes rows and adds no new expressive
content, so it inherits the canonical archive's accepted redistribution posture
under the same explicitly-argued judgement. Any *hosted* sampled archive
re-pins attribution, provenance (source `dataset_version`, sampling fraction,
seed), and takedown routing through the same process before publication; a
BYO/local-generation path needs no hosted asset.

## Consequences

- `_project/TODO/main/planning/track2-joinorder-scaling-strategy.yaml` is the
  implementation vehicle for the sampled-from-real axis when Track 2 is picked
  up; its design source is the scaling-strategy groundwork doc, whose
  "divergence to reconcile" section now records this resolution.
- The `joinorder-replicated-imdb-scale-prototype` verification gate
  (`grep '^Recommendation: (replicated_imdb baseline|staged combination)'`
  over `joinorder-scale-stress-decision-*.md`) intentionally no longer passes:
  the 2026-06-30 note's recommendation line is marked superseded, so the
  prototype stays blocked exactly as its own w1 guardrail requires.
- Result labeling rules from the framework are unchanged: sampled datasets
  publish as a derived, explicitly-labeled workload (`sampled_imdb` or the
  name the implementation TODO fixes), never as canonical JOB, and are not
  comparable to the JOB literature.
