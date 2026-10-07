# ADR: DuckLake Maturity, Publishability, and Compaction Bias

```{tags} platform, governance, results
```

## Status

Accepted (2026-07-30). Each decision below is independently reversible and states what evidence would reverse it.

**Updated 2026-07-30: DuckLake is now `beta`.** Every criterion of the beta exit
decision below is met: TPC-H SF=1 runs on all four deployment modes each passed data validation, and
`support_status` in `platform_registry.py` was changed to `beta`.

Those runs also tested the reproducibility question the remote-backed results
decision left open. That decision stands. Remote-backed modes were not materially
irreproducible: their run-to-run coefficient of variation was 2-9%, lower
than the 13% seen in `local` mode. The measurements refute "remote-backed is
irreproducible" but are not precise enough to publish as reproducibility
characteristics.

## Date

2026-07-30

## Context

The DuckLake adapter shipped as `support_status: experimental`, which left
three policy questions open:

- What concretely moves DuckLake from `experimental` to `beta`?
- May results from a remote-backed DuckLake run (PostgreSQL catalog
  and/or S3 `DATA_PATH`) be published, and are they ranking-eligible?
- Does the absence of DuckLake compaction/inlining bias cross-engine
  comparisons, and should that be instrumented or documented?

Nothing in the repository answered any of them. `support_status` values are
enumerated in
[`new-platform-acceptance-checklist.md`](../new-platform-acceptance-checklist.md)
but no transition criteria exist between them; the provenance vocabulary in
`benchbox/core/results/provenance.py` classifies results by *who ran them*, not
by *what infrastructure produced them*.

---

## Decision: experimental to beta exit criterion

DuckLake moves to `beta` when **all** of the following hold, and not before:

1. The non-live classes of `tests/integration/test_ducklake_integration.py` run
   in a lane on every PR. *(Met.)*
2. Both live classes - PostgreSQL catalog and S3 `DATA_PATH` - have been run
   green against real infrastructure at least once per minor release, with the
   run recorded. *(First met 2026-07-30: PostgreSQL 18.4 and
   a real S3 bucket.)*
3. A full TPC-H SF>=1 run completes on each of the four deployment modes with
   results validated by the standard correctness gate - not just the SF=0.01
   smoke coverage that exists today. *(Met as of 2026-07-30.)*
4. Catalog reuse and `--force` are verified against a server-side catalog, not
   only a local file. *(Met 2026-07-30; that verification found and fixed a real
   defect where `--force` left orphaned Parquet.)*
5. No known-wrong-results defect is open against the adapter.

**Basis.** Criteria 1-2 and 4 encode failure modes the adapter actually had: coverage that existed but ran nowhere, and reuse/force semantics that
were never exercised against the backend they were written for. Criterion 3
was closed by the recorded SF=1 runs across all four deployment modes.

**What would reverse this.** If `beta` acquires a repo-wide definition that
conflicts with these, that definition wins and this section should be deleted
rather than reconciled.

---

## Decision: remote-backed results are publishable, and ranking-eligible, but must record their backing

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
them to `browse-only`. The SF=1 runs required by beta criterion 3 measured this
and did not find it (see Status).

---

## Decision: document the compaction bias; do not instrument yet

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

- The beta criteria are met; DuckLake is now `beta`. Future demotion would
  require new evidence against the reversal conditions above.
- Remote-backed publication requires that catalog backend and storage location
  reach result metadata. The registry models these as independent axes (four
  deployment modes), and each DuckLake result records both in
  `platform_storage`. Comparisons must group by them.
- The compaction decision adds a caveat to the DuckLake platform guide. Any future published
  DuckLake comparison should link it.
