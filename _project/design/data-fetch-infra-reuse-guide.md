# Data-fetch infrastructure reuse guide (stub)

This file is the cross-TODO contract surface for
`benchbox/core/data_fetch/`. Foundation creates this stub; cutover
and Track-2 groundwork fill in the sections each owns.

## DATA-LICENSE.md template

OWNED BY: joinorder-canonical-cutover w13. Filled in when cutover
authors `benchbox/core/joinorder/DATA-LICENSE.md` and lifts its
shape into a reusable template here.

Required shape for real-data benchmarks:

1. Dataset provenance: name the upstream archive, DOI or durable URL,
   source snapshot date, conversion/parsing path, and final BenchBox
   storage format.
2. Upstream attribution: include any attribution text supplied by the
   source project verbatim.
3. Scope clause: state the research or benchmark-only usage intent.
4. Redistribution disclaimer: BenchBox redistributes a derivative form
   for reproducibility, claims no ownership over upstream data, and will
   honor takedown requests.
5. Takedown contact: include a real reachable address; no placeholders
   are allowed before publishing a release asset.

## When to use

Reach for the data-fetch infrastructure when all three hold:

- **Real-data benchmark with a stable upstream source** — the data comes from a
  durable, citable origin (a DOI, an archived snapshot URL) rather than being
  synthesized at runtime. JoinOrder (canonical IMDb 2013) is the reference
  instance; ClickBench, Wikipedia pageviews, and GitHub Archive are the obvious
  next consumers.
- **Dataset too large to commit to git (~50 MB+)** — committing it would bloat
  the repo; instead it is fetched on demand and verified.
- **Provenance / license attribution matters** — the source carries terms or
  attribution that must travel with every redistribution (see the
  `## DATA-LICENSE.md template` section).

Do **not** use it for synthetic benchmarks (TPC-H, TPC-DS, write_primitives),
which generate data deterministically and need no upstream fetch. The
infrastructure is a manifest-driven verification step layered on top of
BenchBox's existing datagen path convention — `resolve_benchmark_runs_dir()`
(`benchbox/utils/path_utils.py:31`) and the run config's
`get_datagen_path(benchmark, sf)` (`benchbox/cli/config.py:953`) — not a
separate storage root with its own location policy.

## Step-by-step: instantiating for a new benchmark

Using a hypothetical `clickbench` benchmark as the worked example:

a. **Decide the canonical source.** Pin a DOI or an archived snapshot URL — a
   durable, reproducible origin, not a live mutable endpoint. Record the source
   snapshot date.

b. **Build an offline conversion pipeline.** Add
   `_project/scripts/build_clickbench_data.py` that downloads the source,
   converts it to per-table Parquet, and is rerunnable from scratch. Keep it
   offline/one-shot — it produces the archive, it is not on the benchmark hot
   path.

c. **Compute reference cardinalities via an independent oracle.** Run the query
   set against a *different* engine than the one being benchmarked (PostgreSQL
   for SQL workloads) to get trustworthy expected cardinalities. Never derive the
   oracle from the same engine that will later be measured.

d. **Package the archive.** Per-table Parquet + `manifest.toml` + SHA256
   checksums + `DATA-LICENSE.md` + reference cardinalities, as one versioned
   tarball.

e. **Stage as a DRAFT GitHub Release.** Upload the archive as a draft asset;
   publish (promote) only after UAT confirms the fetch + load + validation path.

f. **Add `data_manifest.toml`** in `benchbox/core/clickbench/`, mirroring
   `benchbox/core/joinorder/data_manifest.toml` (it carries `dataset_version`,
   the archive URL, `archive_sha256`, `manifest_hash`, `data_archive_hash`, and
   the license file reference — see `benchbox/core/data_fetch/manifest.py:106`).

g. **Wire the benchmark to the datagen path convention.** Resolve the output
   directory with `get_datagen_path(benchmark, sf)` and fetch into it via
   `fetch_data(..., output_dir=...)` from `benchmark.py`. Do not invent a new
   storage location.

h. **Add `DATA-LICENSE.md`**, using joinorder's as the template (its shape is
   pinned in the `## DATA-LICENSE.md template` section of this guide).

i. **Add a per-benchmark CHANGELOG entry** recording the dataset version and
   provenance.

## Common pitfalls (from joinorder Step 1)

Each of these bit the joinorder Step-1 effort and has a concrete guard:

- **Encoding round-trip gates.** Unicode NFC/NFD normalization can silently
  rewrite string keys during conversion, breaking joins and predicate matches.
  Add an explicit encoding round-trip gate that fails the build if a column's
  bytes change under normalization.
- **Predicate-domain validation.** A converted dataset can pass row-count and
  non-empty checks yet return empty results for every query because predicate
  literal values no longer exist in the data (queries-empty-by-construction).
  Validate that each query's predicate domain is actually present.
- **Reference cardinalities via an independent oracle.** Computing expected
  cardinalities with the same engine that will be benchmarked launders that
  engine's bugs into the "ground truth." Use a separate oracle (PostgreSQL).
- **DRAFT-then-promote the GitHub Release.** Publishing the release asset before
  UAT means a broken archive is already the public default. Stage as DRAFT,
  promote only after the fetch + load + validation path is confirmed.

## Infrastructure components reused

A new benchmark inherits all of these rather than rebuilding them:

- **Existing datagen path convention** — `resolve_benchmark_runs_dir()` +
  `get_datagen_path(benchmark, sf)` resolve under
  `BENCHBOX_OUTPUT_DIR` / `benchmark_runs/datagen/<benchmark>_<sf>/`. The
  fetched data lands on the same path every other benchmark uses; there is no
  benchmark-specific storage root.
- **`benchbox.core.data_fetch`** — manifest parsing (`manifest.py`), the
  downloader (`downloader.py`), the manager (`manager.py`), typed errors
  (`errors.py`), concurrency control (`locking.py`), and SHA256 verification of
  both the archive (`archive_sha256`) and the aggregate per-table data
  (`data_archive_hash`).
- **`benchmark_registry` surface field** — marks the benchmark public vs
  internal so it appears (or not) in the public benchmark list.
- **`bundle_publisher` `dataset_version`** — the result-bundle records the
  `dataset_version` it ran against (`benchbox/core/results/models.py:383`,
  `benchbox/core/publishing/store.py`), so results are traceable to an exact
  dataset.
- **`scale_factor` enforcement gate** — the shared SF validation rejects
  unsupported scale factors before any fetch or load begins.
