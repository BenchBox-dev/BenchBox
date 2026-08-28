# ADR: DuckLake Maturity, Publishability, Review Path, and Compaction Bias

```{tags} platform, governance, results
```

## Status

Accepted (2026-07-30). Resolves work units w11-w14 of the
`ducklake-post-merge-review-followups` tracker item. Each decision below is
independently reversible and states what evidence would reverse it.

**Updated 2026-07-30: DuckLake is now `beta`.** Every w11 criterion is met -
criterion 3 was satisfied by TPC-H SF=1 runs on all four deployment modes, each
passing data validation. `support_status` was flipped in
`platform_registry.py` accordingly. Measured Power@Size, and the run-to-run
reproducibility that decision w12 asked to revisit once scale runs existed:

| deployment mode | Power@Size (mean) | CV | runs |
|---|---|---|---|
| `local` | 89,717 | 12.9% | 5 |
| `local_catalog_s3` | 74,760 | 2.2% | 3 |
| `postgres_catalog` | 77,919 | 8.7% | 3 |
| `postgres_catalog_s3` | 64,955 | 5.1% | 5 |

**Decision w12 is confirmed, not revised.** It said remote-backed results would
warrant demotion only if they proved *materially irreproducible* rather than
merely slower. They did not: the remote-backed modes were the more consistent
ones, and `local` showed the widest spread of all.

That local spread is a caveat about the measurement, not a finding about
DuckLake. It is bimodal - ~98k on the first run, ~77k on later repeats - which
is a systematic first-run-versus-later split rather than random variance, and
almost certainly host contention from concurrent work on the measuring machine.
**Re-measure on a quiet host before treating these CVs as authoritative.** They
are strong enough to refute "remote-backed is irreproducible" and not strong
enough to publish as reproducibility characteristics.

## Date

2026-07-30

## Context

The DuckLake adapter shipped as `support_status: experimental` and its post-merge
review raised four questions that the code changes in that review deliberately
did not answer, because they are policy rather than defects:

- **w11** - what concretely moves DuckLake from `experimental` to `beta`?
- **w12** - may results from a remote-backed DuckLake run (PostgreSQL catalog
  and/or S3 `DATA_PATH`) be published, and are they ranking-eligible?
- **w13** - should platform adapters that produce publishable numbers be a
  CODEOWNERS owner-review path?
- **w14** - does the absence of DuckLake compaction/inlining bias cross-engine
  comparisons, and should that be instrumented or documented?

Nothing in the repository answered any of them. `support_status` values are
enumerated in
[`new-platform-acceptance-checklist.md`](../new-platform-acceptance-checklist.md)
but no transition criteria exist between them; the provenance vocabulary in
`benchbox/core/results/provenance.py` classifies results by *who ran them*, not
by *what infrastructure produced them*.

---

## Decision w11: experimental -> beta exit criterion

DuckLake moves to `beta` when **all** of the following hold, and not before:

1. The non-live classes of `tests/integration/test_ducklake_integration.py` run
   in a lane on every PR. *(Met as of #1357.)*
2. Both live classes - PostgreSQL catalog and S3 `DATA_PATH` - have been run
   green against real infrastructure at least once per minor release, with the
   run recorded on the tracker item. *(First met 2026-07-30: PostgreSQL 18.4 and
   a real S3 bucket.)*
3. A full TPC-H SF>=1 run completes on each of the four deployment modes with
   results validated by the standard correctness gate - not just the SF=0.01
   smoke coverage that exists today. *(Met as of 2026-07-30.)*
4. Catalog reuse and `--force` are verified against a server-side catalog, not
   only a local file. *(Met 2026-07-30; that verification found and fixed a real
   defect where `--force` left orphaned Parquet.)*
5. No known-wrong-results defect is open against the adapter.

**Basis.** Criteria 1-2 and 4 encode the failure modes this review actually
found: coverage that existed but ran nowhere, and reuse/force semantics that
were never exercised against the backend they were written for. Criterion 3
was closed by the recorded SF=1 runs across all four deployment modes.

**What would reverse this.** If `beta` acquires a repo-wide definition that
conflicts with these, that definition wins and this section should be deleted
rather than reconciled.

---

## Decision w12: remote-backed results are publishable, and ranking-eligible, but must record their backing

Runs with a PostgreSQL catalog and/or S3 `DATA_PATH` are **publishable** under
the same trust labels as any other run, and are **not** demoted in ranking.

They must, however, carry their catalog backend and storage location in result
metadata, and comparisons must not silently mix backings.

**Basis.** The existing model in `provenance.py` maps *source* to trust label
(`internal` -> `maintainer-run` -> `public-curated` -> ranking-eligible). It
deliberately says nothing about infrastructure, and inventing an
infrastructure-based demotion here would fork that model for one platform. The
honest framing is that DuckLake's catalog backend and storage location are
**part of the configuration under test**, exactly like a tuning profile or a
scale factor - not a defect in the run.

The real hazard is not publication, it is *comparison*: a DuckLake-on-S3 number
partly measures object-store latency, so ranking it against DuckLake-on-local-
disk as though they were the same system is the error. That is a
comparison-grouping concern, addressed by recording the backing, not by
suppressing the result.

**What would reverse this.** Evidence that remote-backed numbers are materially
irreproducible run-to-run (rather than merely slower) would justify demoting
them to `browse-only`. Measuring that requires criterion w11.3 above, so this
decision should be revisited when scale runs exist.

---

## Decision w13: no. Platform adapters do not become a CODEOWNERS path

**Basis.** This one is decided by what CODEOWNERS currently *does* in this repo,
which is not what the question assumes. Per `.github/CODEOWNERS` and
[`repo-admin-settings.md`](../../operations/repo-admin-settings.md), code-owner
approval enforcement was **retired on 2026-07-18** - the sole owner authors every
PR and GitHub forbids self-approval. The file's two live roles are:

1. mirroring `SOUNDNESS_PREFIXES` in
   `_project/scripts/auto_merge_soundness_paths.py`, which **withholds
   auto-merge**; and
2. routing review requests.

So adding `benchbox/platforms/**` would not add a human review gate. It would
withhold auto-merge from every platform PR - and the platform tree is the
highest-churn area in the repo. That is a real cost for no review benefit.

The soundness set is scoped to code that decides whether a result is *correct*
(validators, equivalence, plan parsers, expected-results, `result_capture.py`).
A platform adapter produces numbers but does not adjudicate them; the
correctness gate does, and that gate is already owner-reviewed. The existing
boundary is principled and DuckLake gives no reason to move it.

**What would reverse this.** Reinstating enforced code-owner approval (a second
maintainer joining) changes the premise entirely and this should be re-decided
then.

---

## Decision w14: document the bias; do not instrument yet

BenchBox never invokes DuckLake's compaction or inlining maintenance
(`ducklake_merge_adjacent_files`, inlining) - verified by inspection of the
adapter and core. Measured behaviour: **5 separate `INSERT`s produce 5 Parquet
files**, and nothing merges them.

The bias is therefore real, and its **direction is against DuckLake**: scans hit
more, smaller files than a compacted deployment would, so BenchBox's DuckLake
numbers are a floor, not a ceiling. This is documented in the platform guide
rather than instrumented.

**Basis.** Instrumenting means either invoking compaction (changing what is
measured, and requiring a policy on whether maintenance time counts toward the
run) or reporting file-count/size distributions per run (new result-schema
surface). Both are larger than the ambiguity they resolve, and the ambiguity is
one-directional - a reader who knows DuckLake numbers are un-compacted can
reason about the gap, whereas a reader who does not know may over-read a
DuckLake loss.

Load path shape matters here: bulk loading via few large inserts produces few
large files and little bias, whereas row-wise loading produces many small ones.
Documenting the mechanism lets a reader assess their own configuration.

**What would reverse this.** A measured cross-engine comparison where DuckLake's
un-compacted file layout accounts for a decisive share of the gap would justify
either invoking compaction as part of the load phase or reporting the file
layout in results metadata.

---

## Consequences

- w11's criteria are met; DuckLake is now `beta`. Future demotion would require
  new evidence against the reversal conditions above.
- w12 requires that catalog backend and storage location reach result metadata.
  The registry already models these as independent axes (four deployment modes
  as of the w10 fix), so the vocabulary exists; wiring it into result metadata
  and comparison grouping is follow-up work, not covered here.
- w13 leaves `SOUNDNESS_PREFIXES` and CODEOWNERS unchanged - and they must stay
  in lockstep, pinned by
  `tests/unit/test_auto_merge_soundness_paths.py::test_codeowners_covers_soundness_paths`.
- w14 adds a caveat to the DuckLake platform guide. Any future published
  DuckLake comparison should link it.
