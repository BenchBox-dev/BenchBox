# Cross-surface scope boundary and release-branch posture

Date: 2026-09-27

Status: Accepted.

## Scope boundary

Cross-surface gates (`benchbox/core/equivalence/cross_surface.py`, `GATES`)
cover benchmarks that ship both a SQL surface and a static `QueryRegistry`
DataFrame surface. That is transcription and regression verification against
DuckDB SQL references at a bounded equivalence scale: the two surfaces are
authored from the same understanding by the same person (how separately they
were handwritten varies by benchmark, as each gate's `surface_independence`
records), so the gate catches transcription drift, not shared conceptual
errors, and its signal holds only at the gated scale (see the module docstring and
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
  TPC-DS numbered SQL IDs), ruled out without renumbering one side. The
  comment above `STAGED_GATES` in `cross_surface.py` still lists `tpcds_obt`
  among the next gateable benchmarks; it predates this decision and is
  stale.
- `ai_primitives` and `vector_search` stay `supports_dataframe: false` in
  `benchmark_registry.yaml` and are single-surface benchmarks that need the
  same non-cross-surface oracle.

## Release-branch posture

Cross-surface enforcement is a develop-time gate. It is not a release-time
gate.

`ci.yml` has no branch filter on `pull_request`, so a pull request opened
against `release` triggers the same workflow as one against `develop`, but the
`release` ruleset does not require its results. The required checks are
`validate-base` and `release-required-result`
(`docs/operations/repo-admin-settings.md`). `release-required-result`
aggregates `test.yml`, which runs the bounded `test-correctness-gate`
(`make test-correctness-gate`, a strict expected-results run of TPC-H on
DuckDB over the gated query ids in `CORRECTNESS_GATE_QUERY_IDS`) and does not
include `ci.yml`'s `core` unit or its `GATES` cross-surface reports. Those reports can run on a release pull request,
but nothing makes them merge-blocking there.

The `release` ruleset rejects direct pushes, so every change reaches it through
a pull request. Making cross-surface coverage a release requirement would be a
separate, explicitly approved change to `test.yml` or the ruleset.

Known limitation: release curation (`make release-cut`) removes
`_project/scripts/todo_state_contract_check.py`, while `ci.yml` runs it on every
pull request without a condition. As written, that step cannot succeed on a
curated release tree, so `ci.yml` results on release pull requests are not a
usable signal until the two are reconciled. This record does not change either.
