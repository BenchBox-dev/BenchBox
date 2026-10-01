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

Which dual-surface benchmarks are enforced (`GATES`) or staged
(`STAGED_GATES`) changes as burn-downs finish, so this record does not list
them; `cross_surface.py` and `_project/analysis/oracle-coverage-map.md` are the
authority. Out of scope for the cross-surface gate, by construction:

- Operation-pipeline benchmarks with no DataFrame query surface need a
  different oracle (a differential second-engine check or a curated
  expected-results subset), not a cross-surface builder: `write_primitives`,
  `metadata_primitives`, `transaction_primitives`, `tpcdi` (see
  `_project/analysis/cross-surface-applicability.md`). That oracle does not
  exist yet, so until it does these benchmarks have no cross-surface
  protection; this record does not provide it.
- `joinorder` stays outside `GATES`: it accepts only the canonical IMDb data at
  `scale_factor=1.0`, which is not a bounded routine-PR cell. The
  `joinorder_synthetic` CI-enforced gate covers scaled smoke-test data for the
  JoinOrder family in the meantime. A divergence that appears only on the
  canonical IMDb distributions is not caught by any cross-surface gate.
- `tpcds_obt` has an abandoned correspondence (OBT-native Q1..Q17 versus
  TPC-DS numbered SQL IDs), ruled out without renumbering one side.
- `ai_primitives` and `vector_search` stay `supports_dataframe: false` in
  `benchmark_registry.yaml` and are single-surface benchmarks that need the
  same non-cross-surface oracle.

## Release-branch posture

`ci.yml` has no branch filter on `pull_request`, so a pull request opened
against `release` runs the same path-aware unit checks as one against
`develop`, including the blocking correctness-gate suite and its `GATES`
cross-surface reports when the touched paths select them. `test.yml`
additionally runs the bounded `test-correctness-gate` on release-bound pull
requests. The `release` ruleset rejects direct pushes, so every change reaches
it through a pull request. Adding the full cross-surface suite to `test.yml` is
a separate, explicitly approved CI change if it is ever wanted.
