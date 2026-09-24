# Browser-test fixture sources

Deterministic input corpus for the results-explorer browser-functional
test suite. The generator script
`results-explorer/scripts/generate-browser-fixtures.mjs` copies files
from here into `../.generated/source/`, applies controlled metadata
variants, and then runs
`uv run -- python _project/scripts/explorer_publish.py build` to produce
`../.generated/data/results.duckdb` plus the companion bundle copies.

The curated public corpus under `results-explorer/public/data/` and the
source corpus under `results-data/bundles/` are never touched during a
test run. See `docs/development/browser-test-architecture.md` for the
full rationale.

## Why these specific bundles

- **TPC-H SF 0.01 across DuckDB / DataFusion / Polars / Pandas** - gives a
  valid ≥4-platform compare cohort at a single `benchmark × scale_factor`
  key, which is required for the compare-happy-path and honesty-control
  tests.
- **Star-schema SF 0.01 DuckDB** - provides a second `benchmark` so the
  compare-invalid benchmark-mismatch hard-block test can reference a
  real bundle rather than a synthesised stub.

The Pandas input is a byte-for-byte copy of the immutable internal corpus
bundle named in `provenance/tpch-pandas-sf0.01-20260826-8bde2222.source.manifest.json`.
The generator verifies both hashes before use. Its source is a `power` run;
the standard-phase Pandas row is generated under `synthetic/` with run ID
`8bde2222-fixture-standard`. It is therefore fixture-only, not relabelled
contributed evidence.

## Generator-derived honesty coverage

The generator also synthesises additive variants from these sources
(never written back here):

- **Trust labels** - `maintainer-run` (verbatim sources),
  `community-submission` (DuckDB under `community/` with a submission
  manifest), and `vendor-supplied` (Pandas under `vendor/`).
- **Tuned / notuned pairs** - DuckDB and Pandas each have a tuned sibling
  (`config.tuning_mode="tuned"` plus a `.tuning.json` sidecar) so at least
  two platforms in the ≥4-platform cohort exercise both modes.

## Adding new sources

Prefer reusing existing curated bundles from
`results-explorer/public/data/bundles/` or `results-data/bundles/` rather
than committing new fixtures. If a variant cannot be expressed by copying
an existing bundle plus a sidecar or metadata mutation, that's a signal
the explorer pipeline needs the capability - raise the question before
growing this directory.
