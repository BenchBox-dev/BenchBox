---
iteration: shrink-campaign-pr-audit-followups
date: 2026-05-26
surface: shrink campaign audit follow-up repairs
branch: fix/shrink-campaign-pr-audit
pr: 675
raw_cloc_delta: -60
credited_reduction: 0
uncredited_relocation: 0
repair_only_delta: -60
generated_python_delta: 0
moved_content: none
decision_gate: conservative default
verification:
  - gh pr list --repo joeharris76/BenchBox --state merged --base develop --limit 200 --json number,title,mergedAt,headRefName,url
  - make shrink-rollup
  - cloc --include-lang=Python benchbox/
  - uv run -- ruff check benchbox/core/dataframe/query.py benchbox/core/read_primitives/dataframe_queries.py benchbox/core/tpcds/dataframe_queries/__init__.py benchbox/core/tpcds/dataframe_queries/registry.py benchbox/core/tpcds/dataframe_queries/queries.py benchbox/core/tuning/coverage.py tests/unit/core/test_registry_lazy_load.py tests/uat/test_tuning_coverage.py tests/uat/test_no_cli_surface_drift.py tests/unit/cli/test_cli_package_exports.py
  - uv run -- ty check benchbox/core/dataframe/query.py benchbox/core/read_primitives/dataframe_queries.py benchbox/core/tpcds/dataframe_queries/__init__.py benchbox/core/tpcds/dataframe_queries/registry.py benchbox/core/tpcds/dataframe_queries/queries.py benchbox/core/tuning/coverage.py tests/uat/test_tuning_coverage.py tests/unit/cli/test_cli_package_exports.py
  - uv run -- python -m pytest tests/unit/cli/test_cli_package_exports.py tests/unit/core/test_registry_lazy_load.py tests/unit/core/test_dataframe_generated_impl_registry.py tests/unit/core/tpcds/test_tpcds_dataframe_queries.py tests/unit/benchmarks/test_read_primitives_dataframe_queries.py tests/uat/test_tuning_coverage.py tests/uat/test_no_cli_surface_drift.py -q -n 0
  - uv run -- python -m pytest tests/unit/core/read_primitives/test_read_primitives_dataframe.py -q -n 0
  - make catalog-schema-check
  - make compat-docs-check
  - make pr-preflight
---

## Thesis

Audit follow-up for the merged shrink campaign PR set. This PR intentionally
claims zero shrink credit: it fixes regressions and stale guardrail metadata
found while reviewing the completed shrink PRs, and it records the 60-line
repair cost explicitly instead of treating the work as a new shrink thesis.

The audit regenerated the current merged shrink PR set from GitHub and reviewed
102 merged shrink PRs in ascending PR-number order, including the seeded PR set
and any shrink PRs merged since that seed. PR #581 exceeded the GitHub PR diff
API limit, so its squash merge commit diff was used as the local review
artifact.

## Findings Fixed

- PRs that deleted `benchbox/cli/execution.py` and
  `benchbox/cli/validation.py` left those paths in the CLI-surface drift
  allowlist. The stale allowlist entries are removed so the UAT guard now
  reflects the current package surface.
- The TPC-DI transformations deletion left stale references in Ruff per-file
  ignores and coverage omit configuration. Those dead config paths are removed.
- The shrink campaign left import-time metadata reads in DataFrame query
  registries and tuning coverage. Read Primitives and TPC-DS DataFrame query
  metadata now load through a lazy registry, and tuning coverage loads
  `coverage.yaml` only when backlog data is needed.
- The tuning import constants are now checked against the YAML source when the
  YAML is explicitly loaded, preserving the no-import-I/O guardrail without
  creating an untested duplicate source of truth.

## Guardrail Evidence

- Iteration type: guardrail repair.
- Moved-content classification: none. No Python logic was relocated into data,
  generated Python, SQL, YAML, or benchmark data.
- Decision-gate status: conservative default. The lazy metadata changes follow
  the existing runtime-load pattern ratified by the catalog-source ADR; this PR
  does not approve a new catalog or code-generation pattern.
- Ledger classification: zero credited reduction, `raw_cloc_delta: -60`, and
  `repair_only_delta: -60`, based on `cloc --include-lang=Python benchbox/`
  increasing from 195079 to 195139 maintained Python code lines.
- Deleted-path sweep: exact references to shrink-deleted Python paths are gone
  from current package code, tests, docs, and `pyproject.toml`. Archived
  `_project/DONE` provenance and the 2026-04-30 path-filter evidence note still
  mention historical paths and were left as historical records, not active
  guardrails.
- Import-time I/O sweep: an AST scan over shrink-touched `benchbox/**/*.py`
  reports zero module-level `open`, `read_text`, `read_bytes`, or
  `yaml.safe_load(Path(...).read_text(...))` candidates after the repair.

## Verification

- `make shrink-rollup`: 27 local fragments including this PR body, 12090
  cumulative credited reduction, 0 remaining to the committed floor.
- `cloc --include-lang=Python benchbox/`: 913 Python files and 195139 code
  lines after repairs.
- `uv run -- ruff check ...`: pass for all touched runtime and test files.
- `uv run -- ty check ...`: pass for touched runtime files and tuning tests.
- `uv run -- python -m pytest tests/unit/cli/test_cli_package_exports.py tests/unit/core/test_registry_lazy_load.py tests/unit/core/test_dataframe_generated_impl_registry.py tests/unit/core/tpcds/test_tpcds_dataframe_queries.py tests/unit/benchmarks/test_read_primitives_dataframe_queries.py tests/uat/test_tuning_coverage.py tests/uat/test_no_cli_surface_drift.py -q -n 0`:
  pass, 98 tests.
- `uv run -- python -m pytest tests/unit/core/read_primitives/test_read_primitives_dataframe.py -q -n 0`:
  pass, 383 tests.
- `make catalog-schema-check`: pass.
- `make compat-docs-check`: pass.
- `make pr-preflight`: pass; CI lint passed and the fast lane reported 22692
  passed, 5 skipped, 42 warnings, and 4 subtests passed.

## Blind-Spot Follow-up Audit

After the first correction PR was opened, a second pass covered the main
blind spots from the review process:

- PR-set completeness: regenerated the merged shrink PR query and compared it
  with the seeded list. Both sets contain 102 PRs, with no `query_minus_seed`
  or `seed_minus_query` differences. The 26 ledger-backed PRs are all present
  in that merged shrink PR set.
- Ledger recomputation: recomputed `cloc --include-lang=Python benchbox/` at
  each `origin/develop` ledger fragment's introducing squash commit and its
  parent. All 26 fragments were classified `ok`; credited reduction sums to
  12090. The raw parent-to-commit reduction sums to 12078 because PR #630 is a
  zero-credit repair that intentionally added 12 maintained Python lines.
- Package artifact smoke: `uv build --out-dir /tmp/shrink-campaign-pr-audit-dist`
  produced both wheel and sdist. The sdist contains the moved query/catalog
  resources, and an isolated installed-wheel smoke confirmed those resources
  are accessible via `importlib.resources`.
- Installed-wheel API smoke: from outside the checkout, the wheel exposes
  `TPCDS_DATAFRAME_QUERIES` through `benchbox.__all__` as `QueryRegistry`, and
  lazy registry loading keeps miss counts at 0 before first access and 1 after
  `len()` for both Read Primitives and TPC-DS.
- Runtime query semantics: `uv run -- python -m pytest
  tests/integration/validation/test_read_primitives_variant_parity.py -q -n 0`
  passed 44 integration parity tests against the DuckDB SF=0.01 reference
  surface.
- Follow-up branch gate: after PR #675 merged, this evidence-only update was
  replayed onto current `origin/develop`; `make pr-preflight` passed with
  22716 passed, 5 skipped, 42 warnings, and 4 subtests.

## Residual Risk

The branch is deliberately repair-only and increases maintained Python by 60
lines. The remaining risk is limited to lazy-load timing: first registry access
now performs metadata file reads that previously happened at import time. The
existing query registry and benchmark tests cover query IDs, callable identity,
package data inclusion, and DataFrame behavior after first access.
