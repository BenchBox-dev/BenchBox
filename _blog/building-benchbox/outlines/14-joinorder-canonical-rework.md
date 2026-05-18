---
title: "Reworking JoinOrder around the IMDb 2013 dataset"
series: building-benchbox
post_number: 14
type: architecture-design
tags: [benchbox, joinorder, job, imdb, provenance, benchmark-data]
status: OUTLINE
---

# Outline: JoinOrder benchmark, IMDb 2013 reworking

---

## Recommendation

This should be the most technical post in the v0.3.0 set, but its lead is not "canonical data."
Define "canonical" early: in this post, it means the fixed IMDb 2013 dataset and 113-query JOB
workload used by the benchmark papers, not any schema-compatible or generated approximation. The
lead is that GitHub issue #289, filed by community member @partychicken on 2026-05-09, surfaced a
fundamental JoinOrder benchmark problem, and BenchBox fixed the benchmark contract along the lines
they proposed. The reader-facing claim is:

> A community report (GitHub #289) exposed that BenchBox's JoinOrder benchmark was not
> measuring the workload the Join Order Benchmark was designed to expose. We fixed that, along the
> lines the reporter proposed, by making public `joinorder` mean the IMDb 2013 JOB dataset
> at a single fixed scale, not generated test data.

Do not turn this into a legal essay. The redistribution decision matters, but the core engineering
story is the move from generated smoke-test data to manifest-backed, verified, comparable
benchmark data.

Keep the published version focused on the data cutover. The outline has enough evidence for a
2,000-2,400 word post; if the draft grows longer, cut archive-build mechanics before cutting the
sections on comparability, no-small-scale tradeoffs, or provenance.

---

## Audience

- Query optimizer and database engineers who recognize the Join Order Benchmark.
- BenchBox users who previously ran `joinorder` and need to understand the breaking change.
- Benchmark maintainers dealing with real-world datasets, provenance, archives, and reproducibility.

---

## Thesis

Synthetic JoinOrder-shaped data was convenient for tests, but it was not the Join Order Benchmark
users expected. v0.3.0 fixes that user-raised benchmark contract bug: `joinorder` now means full
IMDb 2013 JOB at SF=1, synthetic data moves internal, and result identity/provenance
plumbing makes the cutover auditable.

---

## Evidence Matrix

| Claim | Evidence to cite | Notes |
| --- | --- | --- |
| The change was triggered by GitHub issue #289, filed by @partychicken on 2026-05-09 | `gh issue view 289`; archive a snapshot in the research folder before publishing in case the issue is later edited or deleted | This is the lead; name the reporter and link the issue |
| The reporter's argument was grounded in the JOB paper's stated motivation | Leis et al. 2015, PVLDB 9(3): 204-215; Leis et al. 2018, VLDB Journal 27(5): 643-668 | Cite both papers in the post's references; the reporter cited them explicitly |
| The reporter's proposed fix was "remove/disable the scaling capability [...] reference and ingest the original frozen IMDB dataset" | Issue #289 body, "Describe the solution you'd like" section | Quote the reporter directly when introducing how the implementation maps to the request |
| Public `joinorder` now accepts only scale 1 IMDb 2013 data | `CHANGELOG.md:12`, `benchbox/core/joinorder/benchmark.py:63`, `docs/reference/api-reference.md:239` | Use as the breaking-change anchor |
| The old generated benchmark is no longer the released `joinorder` benchmark | `CHANGELOG.md:16`, `benchbox/core/joinorder/benchmark.py:36`, `tests/unit/core/test_registry_surface_field.py:97` | Important for upgrade guidance |
| The IMDb 2013 archive is manifest-backed | `benchbox/core/joinorder/data_manifest.toml:1`, `benchbox/core/joinorder/data_manifest.toml:7` | Include version, manifest hash, archive hash |
| The data is a 21-table Parquet archive | `_project/joinorder/release-notes.md:11`, `README.md:916` | Mention the 21-table JOB schema |
| Row counts and table hashes are recorded | `_project/joinorder/release-notes.md:13`, `benchbox/core/joinorder/data_manifest.toml:20` | Avoid listing all tables in prose |
| All 113 JOB SQL queries are embedded | `CHANGELOG.md:25`, `benchbox/core/joinorder/queries.py:3`, `tests/unit/core/joinorder/test_query_coverage.py:17` | This is the main capability claim |
| DataFrame coverage exists for all 113 query IDs | `benchbox/core/joinorder/dataframe_queries.py:3`, `tests/unit/core/joinorder/test_dataframe_query_capabilities.py:86` | Draft carefully: implementation coverage is not the same as every platform being equally comparable |
| No small comparable public JOB workload ships in Step 1 | `_project/decisions/joinorder-small-workload-2026-05-12.md:14`, `_project/decisions/joinorder-small-workload-2026-05-12.md:35` | This deserves a transparent limitation section |
| Redistribution risk is accepted, not declared solved | `_project/decisions/joinorder-canonical-data-licensing-2026-05-12.md:20`, `_project/decisions/joinorder-canonical-data-licensing-2026-05-12.md:65` | Keep wording precise |

---

## Proposed Structure

### 1. Opening: what changed and why it is breaking (~250 words)

Lead with the report and the user-visible change:

- On 2026-05-09, @partychicken filed GitHub issue #289 arguing that BenchBox's public JoinOrder
  path used uniformly random synthetic data and therefore did not exercise the benchmark the JOB
  paper actually defines. Name the reporter and link the issue near the top of the section.
- Before: public `joinorder` was synthetic, scaled, and useful for smoke testing.
- After: public `joinorder` is IMDb 2013 JOB and accepts only `--scale 1`.
- The old generator is still useful as `joinorder_synthetic`, but it is not comparable JOB data.

Draft a compact TL;DR with these exact points:

- `joinorder` now downloads and verifies the JOB Parquet archive on first use.
- All 113 JOB SQL queries are available.
- Results carry dataset identity fields when backed by the data manifest.
- There is no public small comparable JOB scale in this step.
- Old v0.2.x `joinorder` results were synthetic and are not comparable to the new IMDb-backed path;
  do not aggregate the two.

### 2. What the reporter argued (~300 words)

Summarize @partychicken's case in their terms before adding our own framing. The argument has
three moves:

- **The JOB paper picked IMDb deliberately.** Leis et al. (PVLDB 2015, "How Good Are Query
  Optimizers, Really?") chose IMDb because real-world data has strong correlations, skew, and
  non-uniform distributions that systematically mislead traditional cardinality estimators. JOB's
  whole purpose is to expose that.
- **Uniform random data trivializes the benchmark.** Independence assumptions become accidentally
  accurate; join-order selection becomes easy because the optimizer's simple statistical model
  happens to match the data; the benchmark stops differentiating a naive optimizer from a
  sophisticated one.
- **The reporter's verdict.** "Testing JOB with current BenchBox will lead to a wrong result."

Acknowledge that synthetic data was useful for schema loaders, query wiring, and platform smoke
tests. The bug was not that the code was wrong; it was that the benchmark contract said
"JoinOrder" while shipping data that erased the property JOB was designed to test.

Quote the reporter once, briefly, on the cardinality-estimation mechanism, then close the section
with a neutral sentence in BenchBox voice:

> The synthetic workload was useful for testing. It was not comparable JOB.

### 2a. How we integrated the request (~200 words)

The reporter proposed a specific fix:

> remove/disable the scaling capability for the JOB workload [...] reference and ingest the
> original frozen IMDB dataset.

That is essentially the shape of the v0.3.0 change. Map their request to the implementation in one
short table so credit is concrete:

| What @partychicken asked for | What v0.3.0 shipped |
| --- | --- |
| Remove/disable scaling for JOB | Public `joinorder` accepts only `--scale 1`; old scaled path moves to internal `joinorder_synthetic` |
| Reference the original frozen IMDb dataset | IMDb 2013 archive sourced from Harvard Dataverse DOI `10.7910/DVN/2QYZBT`, parsed into the 21-table JOB schema |
| Ensure faithfulness to JOB's original intent | All 113 JOB SQL queries embedded; reference cardinality checks and predicate oracles |

Be explicit that there are places where the implementation went further than the report asked
(dataset identity fields in result bundles, archive hashing, manifest-backed provenance) and one
place where it deliberately did less (no public small-scale variant in this step, see §5).

### 3. What the reference dataset means in BenchBox (~350 words)

Concrete details:

- Source lineage:
  - Harvard Dataverse DOI `10.7910/DVN/2QYZBT`
  - file `imdb_pg11`
  - May 2013 IMDb list-file data parsed into the JOB 21-table schema
- BenchBox archive:
  - `joinorder-imdb-2013-v1.tar.zst`
  - Parquet table files
  - transport archive SHA256
  - logical dataset hash
  - manifest hash
- Runtime behavior:
  - first run fetches and verifies data
  - archive extraction rejects unsafe paths

Avoid turning this into a table dump. Include one sentence with the scale of the data, for example
`cast_info` at 36,244,344 rows, then point readers to the manifest for the full table list.

### 4. Query coverage and correctness checks (~350 words)

Cover the query side:

- Embedded 113 SQL queries from the pinned JOB query set.
- Query manager exposes IDs like `1a`, `2b`, etc.
- Reference cardinality checks and tiny-fixture predicate oracles guard query semantics.
- DataFrame implementations now cover the same 113 query IDs, but the post should distinguish:
  - query ID coverage
  - platform capability
  - result comparability

Drafting note: avoid saying "all DataFrame platforms run full JOB comparably" unless release tests
prove that exact statement.

### 5. The honest tradeoff: no small public scale yet (~300 words)

This is a strength of the post if written plainly.

- A useful `JOB-light` is not just "take fewer rows."
- A meaningful subset needs correlated data, reference cardinalities, a data-delivery contract,
  and labels that prevent readers from comparing it to full JOB.
- The tiny fixture remains test evidence, not a public measurement workload.
- Users who need the public benchmark should run SF=1; users who need unrelated smoke coverage can
  rely on internal/dev paths, but those results should not be published as JOB.

### 6. Provenance and redistribution: what we documented (~250 words)

Be precise and restrained.

- BenchBox documents Dataverse DOI, IMDb attribution, data archive hash, manifest hash, and dataset
  version.
- The project accepted residual redistribution risk for the default GitHub Release asset because
  direct Dataverse restore/conversion is much worse as a first-run path.
- Do not claim legal certainty.
- Mention possible future hardening:
  - written permission
  - direct Dataverse fetch and local conversion
  - bring-your-own Dataverse path for stricter environments

### 7. Try it yourself (~150 words)

Command:

```bash
uv add "benchbox[duckdb]"
uv run benchbox run --platform duckdb --benchmark joinorder --scale 1
```

Add:

- First run downloads and verifies the JOB archive.
- Mention `queries_dir` if users want custom query files, but keep the default embedded 113 queries
  as the main path.

---

## Alternatives Rejected

| Alternative | Why not |
| --- | --- |
| Keep synthetic as public `joinorder` | Convenient, but not comparable to JOB |
| Add public `joinorder --scale 0.01` immediately | Creates a fake sense of comparability unless the subset is designed, validated, and labeled |
| Make users fetch Dataverse and convert locally on first run | Stronger redistribution separation, but much worse first-run UX for the default path |
| Hide the legal/provenance wrinkle | Undermines trust; the honest position is documented risk acceptance plus future hardening |

---

## Drafting Risks

| Risk | Mitigation |
| --- | --- |
| Accidentally giving legal advice | Say "engineering release-risk decision"; cite ADR; avoid "cleared" |
| Overclaiming DataFrame comparability | Separate implemented query IDs from platform execution guarantees |
| Making the breaking change sound punitive | Explain why comparability requires the full IMDb 2013 data contract |
| Overloading readers with hashes | Show the identity fields once, then point to the manifest |
| Taking credit for the reporter's diagnosis | Quote @partychicken's argument directly in §2; map their proposal to the implementation in §2a; do not paraphrase their case in BenchBox voice and present it as our own framing |
| Implying the reporter signed off on the implementation | Be clear that the post describes what BenchBox shipped; the reporter raised the problem and proposed a direction, they did not review or approve v0.3.0 |

---

## Follow-Up Research Before Draft

- Confirm issue #289 is still the primary reference link at publish time; archive the issue body
  (and any comments) to `_blog/building-benchbox/research/14-joinorder/issue-289-snapshot.md` so the
  post survives later edits or deletion.
- Check whether @partychicken would like to be credited by GitHub handle or by name; default to the
  GitHub handle until the reporter says otherwise.
- Confirm final archive URL and hashes in the v0.3.0 release branch.
- Check whether `DATA-LICENSE.md` has final user-facing wording and cite it directly.
- Confirm the published docs page for JoinOrder reflects the no-small-scale limitation.
- Verify the Leis et al. 2015 and 2018 citation details (page numbers, DOIs) before adding to the
  references section.
