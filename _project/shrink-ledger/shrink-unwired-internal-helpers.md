---
iteration: shrink-unwired-internal-helpers
date: 2026-05-25
surface: unwired internal helper modules maintained only by tests and stale contributor docs
branch: chore/shrink-cli-private-helper-followup
pr:
raw_cloc_delta: 562
credited_reduction: 562
uncredited_relocation: 0
repair_only_delta: 0
generated_python_delta: 0
moved_content: none
decision_gate: conservative default; dead internal helper deletion only, no benchmark/platform/public-contract surface removed
verification: targeted checks and pr-preflight passed
---

## Thesis

Shrink iteration. Remove four maintained Python helper modules that are not wired
into runtime code, package exports, public-contract docs, benchmark registries,
query registries, platform registries, or CLI surfaces:

- `benchbox/utils/lazy_loader.py`
- `benchbox/core/platform_config_utils.py`
- `benchbox/core/tpcdi/worker_pool_examples.py`
- `benchbox/core/tpcds/dist_parser.py`

The candidate surface is coherent by risk: these are internal helpers whose
only exact imports are tests. `docs/development/import-patterns.md` still
describes the old shared `LazyLoader` design, but current `benchbox/__init__.py`
uses inline `_BenchmarkSpec`, `_BENCHMARK_REGISTRY`, `_load_benchmark_class`,
and `_clear_lazy_cache` helpers. Updating that contributor doc is uncredited
cleanup needed to avoid stale orientation.

Baseline at slice start:

- `make shrink-rollup`: 10,142 merged credited lines; 1,858 remaining to the
  committed 12,000 floor.
- `cloc --include-lang=Python benchbox/`: 196,956 Python code lines.
- Candidate production Python cloc: 562 code lines.

Expected credit: 562 maintained-Python lines. Test removals, docs updates, and
project-config cleanup are uncredited and exist only because the production
modules disappear.

Moved-content classification: none. This deletes dead maintained Python logic;
no Python logic is moved to data, generated Python, strings, docs, YAML, SQL, or
fixtures.

## Guardrail evidence

- Exact import sweep before editing found references only from tests:
  `tests/unit/tpcds/test_dist_parser.py`,
  `tests/unit/core/test_tpcds_dist_parser.py`,
  `tests/unit/core/test_platform_config_utils.py`,
  `tests/unit/utils/test_lazy_loader.py`, and
  `tests/unit/core/tpcdi/test_worker_pool_pipeline_sources.py`.
- Public-contract/reference sweep found no hits in
  `docs/reference/public-contracts.md`,
  `docs/reference/backward-compatibility.md`,
  `docs/reference/api-reference.md`, or `docs/reference/cli`.
- Package export checks found no `__init__.py` re-export for the removed
  modules.
- Open develop PR overlap check found only #626, an auto-revert touching
  JoinOrder, with no overlap.
- No registry, query, generated-callable, benchmark-semantics, SQL, import-time
  I/O, or dynamic-symbol surface is changed.

## Verification

Completed before PR preflight:

- `rg -n "from benchbox\\.utils\\.lazy_loader|import benchbox\\.utils\\.lazy_loader|from benchbox\\.core\\.platform_config_utils|import benchbox\\.core\\.platform_config_utils|from benchbox\\.core\\.tpcdi\\.worker_pool_examples|import benchbox\\.core\\.tpcdi\\.worker_pool_examples|from benchbox\\.core\\.tpcds\\.dist_parser|import benchbox\\.core\\.tpcds\\.dist_parser" benchbox tests docs pyproject.toml scripts .github -g '*.py' -g '*.md' -g '*.yaml' -g '*.toml'` -> no live references.
- `rg -n "lazy_loader|LazyLoader|LazyImportSpec|platform_config_utils|worker_pool_examples|dist_parser|TPCDSDistribution|TPCDSDistributionParser|SimpleWorkerPoolManager|normalize_warehouse_size" benchbox tests docs pyproject.toml scripts .github -g '*.py' -g '*.md' -g '*.yaml' -g '*.toml'` -> no live references.
- Import smoke for `benchbox`, `benchbox.utils`, `benchbox.core.tpcdi`,
  `benchbox.core.tpcds`, and `benchbox.core.tpcds.dataframe_queries` -> pass.
- `uv run -- python -m pytest -n 0 tests/unit/core/tpcdi/test_worker_pool_pipeline_sources.py tests/unit/test_init.py tests/unit/test_lazy_modules_fast.py tests/unit/core/tpcds/test_tpcds_dataframe_queries.py -q` -> 59 passed.
- `uv run -- ruff check tests/unit/core/tpcdi/test_worker_pool_pipeline_sources.py` -> pass.
- `uv run -- ruff format --check tests/unit/core/tpcdi/test_worker_pool_pipeline_sources.py` -> pass.
- `uv run -- python -m compileall -q benchbox tests` -> pass.
- `git diff --check` -> pass.
- `make shrink-rollup` -> merged ledger remains 10,142 credited lines; branch-local fragment will not count until merge.
- `cloc --include-lang=Python benchbox/ --csv --quiet` -> 916 Python files, 196,394 code lines.
- `uv run -- python scripts/check_complexity.py` -> pass; 0 failures above max complexity 20.
- `make pr-preflight > /tmp/shrink-unwired-internal-helpers-pr-preflight.log 2>&1` -> pass; 22,623 passed, 5 skipped, 47 warnings, 4 subtests passed.

## Residual risk

Low but nonzero: external code could have imported these undocumented internal
modules directly. The documented public-contract and package-export surfaces do
not include them, and no BenchBox runtime path imports them.

## Next target

Continue looking for credited dead-code or true-dedup slices that can close the
remaining distance to the 12,000-line committed floor without product-surface
deletion or benchmark/platform removal.
