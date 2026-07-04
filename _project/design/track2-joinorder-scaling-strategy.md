# Track-2 JOB Scaling-Strategy Options

Status: Design exploration (Track-2 groundwork). Recommends a leading candidate
but does **not** lock in. Final selection happens at Track-2 kickoff.

Context: Track 1 restores `joinorder` as canonical IMDb 2013 (SF=1). Track 2
asks "scaled JOB — *scaled how?*". This doc enumerates the candidate scaling
strategies, scores each against five dimensions, and names one leading candidate
with reasoning. It is plan-deepening before the work is picked up; a multi-option
"we'll see" outcome is not acceptable, so a single candidate is defended below.

Companion docs: the phase-model gap is surveyed in
`track2-joinorder-stats-as-phase.md`; a parallel *decision framework* with a
slightly different option framing lives in
`_project/decisions/joinorder-scale-stress-decision-2026-06-30.md`. The two are
reconciled at the end of this doc.

## Scoring dimensions

Every option is scored against the same five dimensions:

1. **Real-data fidelity** — does it preserve the real IMDb correlations and skew
   that are the actual JOB signal?
2. **Scalability axis** — does it provide a controllable axis of dataset sizes?
3. **License posture** — does it stay within the canonical dataset's already
   reviewed redistribution posture, or open new licensing questions?
4. **Implementation complexity** — generator, validation oracle, and packaging
   cost.
5. **JOB-literature comparability** — can results still be related to the
   Leis et al. JOB literature, or do they diverge?

## Options

### Option A — Correlated synthetic generator

Extend the synthetic generator with Zipf / power-law / cross-table correlations
(a new `joinorder_synthetic` mode, or a new `joinorder_correlated` benchmark).

- Real-data fidelity: **low** — correlations are modeled guesses, not the real
  IMDb correlations JOB measures.
- Scalability axis: **excellent** — arbitrary scale by construction.
- License posture: **clean** — fully synthetic, no IMDb redistribution.
- Implementation complexity: **high** — correlation model design + validation.
- JOB-literature comparability: **none** — different data, different answers.

### Option B — Sampled-from-real (downsample canonical)

Take a fraction of canonical IMDb 2013 preserving full referential integrity
(e.g. title-stratified sampling that keeps each sampled title's full join
subgraph).

- Real-data fidelity: **high** — real correlations preserved within the sample.
- Scalability axis: **good (downward)** — a controllable multi-point axis below
  SF=1; combinable with replication for an upward axis.
- License posture: **clean (inherited)** — a strict subset of the already
  reviewed canonical archive; no new source data.
- Implementation complexity: **low–medium** — sampling + integrity closure +
  oracle re-derivation on the subset.
- JOB-literature comparability: **partial** — same dataset lineage and same
  fixed queries; cardinalities differ from the published SF=1 numbers but the
  signal is the same kind.

### Option C — Real with multiple snapshots (current IMDb)

Use `datasets.imdbws.com` (post-2017 format) with different snapshot dates as the
scale axis.

- Real-data fidelity: **high** — real, naturally growing data.
- Scalability axis: **good** — snapshot dates give a real growth axis.
- License posture: **new review required** — different upstream artifact and
  terms from the JOB-paper Dataverse deposit.
- Implementation complexity: **high** — schema differs from JOB 2013; queries
  and oracle must be re-derived per snapshot.
- JOB-literature comparability: **none** — not the JOB-paper dataset, so results
  diverge from the literature.

### Option D — Real with augmentation (canonical + synthetic additions)

Start from canonical IMDb 2013 and layer synthetic correlated rows on top.

- Real-data fidelity: **mixed** — real backbone, synthetic tail; the synthetic
  part is still a guess that can dilute the signal.
- Scalability axis: **good (upward)** — augment to arbitrary size.
- License posture: **inherited + new** — canonical posture for the backbone, new
  questions for the synthesized additions.
- Implementation complexity: **high** — must blend without breaking correlations
  or referential integrity; partial oracle only.
- JOB-literature comparability: **weak** — fixed queries run, but augmented
  cardinalities are no longer the JOB cardinalities.

### Option E — Skip scaling; stats-maintenance interplay at SF=1 only

Reframe Track 2 from "scaled JOB" to "stats-maintenance JOB" at canonical scale:
study statistics freshness/sampling interplay on fixed SF=1 data.

- Real-data fidelity: **maximal** — unmodified canonical data.
- Scalability axis: **none** — loses the scaling axis entirely.
- License posture: **clean (inherited)** — canonical archive unchanged.
- Implementation complexity: **lowest** — no generator; only the statistics
  phase (see `track2-joinorder-stats-as-phase.md`).
- JOB-literature comparability: **full** — it *is* canonical JOB plus a stats
  protocol.

## Decision matrix

| Option | Real-data fidelity | Scalability axis | License posture | Impl. complexity | JOB comparability |
| --- | --- | --- | --- | --- | --- |
| A correlated synthetic | Low | Excellent | Clean | High | None |
| B sampled-from-real | High | Good (down) | Clean (inherited) | Low–Medium | Partial |
| C multi-snapshot real | High | Good | New review | High | None |
| D real + augmentation | Mixed | Good (up) | Inherited + new | High | Weak |
| E stats-only at SF=1 | Maximal | None | Clean (inherited) | Lowest | Full |

## Leading candidate

**Leading candidate: Option B — sampled-from-real with title-stratified
referential-integrity preservation.**

Reasoning tied to the five dimensions: the JOB signal *is* the real IMDb
correlation structure, so any option that scores low on real-data fidelity (A) or
weak/mixed (D) risks destroying the very thing the benchmark measures — this
eliminates A and D for a first move. Option C scores well on fidelity and scale
but fails license posture (new upstream artifact and review) and JOB
comparability (different dataset), making it a poor *first* step. That leaves B
and E, both of which are license-clean and high-fidelity. E is the simplest but
sacrifices the scaling axis entirely; B keeps a controllable axis while preserving
real correlations and the lowest implementation cost among the scale-capable
options. Title-stratified sampling (keep each sampled title's full join subgraph)
is what makes B's fidelity hold up: it preserves per-title correlation structure
rather than sampling rows independently, which would shear the joins.

This is a recommendation, not a lock-in.

> **Resolved (2026-07-04):** the divergence described below was reconciled by
> project-owner decision in
> `_project/decisions/joinorder-track2-scaling-direction-2026-07-04.md`:
> Track 2 pursues **Option B (sampled-from-real)** as its single scaling
> direction; `replicated_imdb` is deferred (its prototype seed stays gated),
> and the two directions are not run as parallel tracks. The paragraph below
> is kept as the record of why the reconciliation was needed.

A genuine divergence to reconcile at kickoff: the separate scale-stress
*decision framework*
(`_project/decisions/joinorder-scale-stress-decision-2026-06-30.md`) reaches a
**different** leading candidate — `replicated_imdb` (offset replication, an
*upward* baseline) — under a different framing. That doc evaluates only
scale-*up* strategies (replication, expansion, parameterized generation,
synthetic, augmentation) and does **not** consider downsampling at all; its
question is optimizer degradation as data grows. This groundwork doc, framed
around preserving the JOB correlation signal with the lowest-risk *scaling axis*,
leads with Option B (downward sampling). These are not the same recommendation,
and they are not automatically complementary: they reflect two different research
questions (multi-point fidelity vs upward stress). Track-2 kickoff must pick the
framing first — does the research question require *larger-than-SF=1* data (favor
replication) or a controllable, maximal-fidelity multi-point axis (favor
sampling)? — and only then select the strategy. Both candidates are license-clean
and oracle-reusable, and Option B composes with offset replication if kickoff
decides it wants both directions. Option E remains the correctness fallback if a
defensible scaling axis cannot be validated.
