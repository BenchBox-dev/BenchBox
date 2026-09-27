# Cross-surface scope boundary and release-branch posture

Date: 2026-09-27

Status: Accepted.

## Scope boundary

Cross-surface gates (`benchbox/core/equivalence/cross_surface.py`, `GATES`)
cover benchmarks that ship both a SQL surface and a static `QueryRegistry`
DataFrame surface. That is transcription and regression verification against
DuckDB SQL references at a bounded equivalence scale: the two surfaces are
authored from the same understanding by the same person, so the gate catches
transcription drift, not shared conceptual errors, and its signal holds only
at the gated scale (see the module docstring and
`_project/analysis/cross-surface-oracle-independence.md` for per-benchmark
provenance).

Out of scope for the cross-surface gate, by construction:

- Operation-pipeline benchmarks with no DataFrame query surface route to the
  w2 fallback oracle (differential second-engine check or curated
  expected-results subset), not to a cross-surface builder:
  `write_primitives`, `metadata_primitives`, `transaction_primitives`,
  `tpcdi` (see `_project/analysis/cross-surface-applicability.md`).
- `ai_primitives` and `vector_search` stay `supports_dataframe: false` in
  `benchmark_registry.yaml` and are likewise single-surface benchmarks
  needing a fallback oracle, not cross-surface members.

Building the w2 fallback oracle itself is explicitly out of scope here; this
record only routes the benchmarks to it so they are not silently unguarded.

## Release-branch posture

`test.yml` runs only the bounded `test-correctness-gate` on release-bound
pull requests; the per-benchmark cross-surface suite runs in `pr.yml` on
`develop`. Release PRs therefore rely on develop-time squash-merge
enforcement: every change entering `develop` passes the blocking
correctness-gate suite (including all `GATES` cross-surface reports) before
it can ride a release. Adding the cross-surface suite to `test.yml` is a
separate, explicitly approved CI change if it is ever wanted; until then,
release coverage is by inheritance, not by omission.
