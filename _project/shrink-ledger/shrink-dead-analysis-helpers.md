---
iteration: shrink-dead-analysis-helpers
date: 2026-05-25
surface: unwired core analysis insight and alternate-ranking helpers
branch: chore/shrink-dead-analysis-helpers
pr:
raw_cloc_delta: 680
credited_reduction: 680
uncredited_relocation: 0
repair_only_delta: 0
generated_python_delta: 0
moved_content: none
decision_gate: conservative default; internal unwired helper deletion only, no benchmark/platform/public-contract surface removed
verification: targeted pytest, import smoke, reference sweep, ruff, compileall, complexity, diff-check, shrink-rollup, cloc, pr-preflight
---

## Thesis

Shrink iteration. Remove `benchbox/core/analysis/insights.py` and
`benchbox/core/analysis/ranking.py`, which are maintained Python helper modules
for narrative generation and an alternate ranking engine that are not wired into
runtime CLI, MCP, result-export, result-database, benchmark, platform, query, or
registry paths.

The coherent surface is the unwired tail of `benchbox.core.analysis`: keep
`comparison.py`, `models.py`, and `statistics.py` because checked scripts still
import `PlatformComparison` and `comparison.py` depends on the shared models and
statistics helpers. Remove only the two modules whose exact non-self references
are their unit tests and the package-level convenience exports.

Baseline at slice start:

- `make shrink-rollup`: 10,956 merged credited lines; 1,044 remaining to the
  committed 12,000 floor.
- `cloc --include-lang=Python benchbox/`: 916 Python files, 196,142 code lines.
- Candidate production Python cloc: 680 code lines
  (`insights.py` 325, `ranking.py` 329, package-export cleanup 26).
- No open PRs target `develop` at slice refresh, and local `HEAD` matches
  `origin/develop` before edits are committed.

Expected credit: 680 maintained-Python lines. Test removals and package export
cleanup are uncredited and exist only because the production modules disappear.

Moved-content classification: none. This deletes unwired maintained Python
logic; no Python logic is moved to data, generated Python, strings, docs, YAML,
SQL, or fixtures.

## Guardrail evidence

- Runtime/reference sweep found active `PlatformComparison` consumers only in
  `scripts/benchmark_mooncake_migration.py` and `scripts/compare_pg_duckdb.py`;
  those use `benchbox.core.analysis.comparison`, which remains.
- CLI/MCP result analysis paths use `benchbox.core.results.exporter`,
  `benchbox.core.results.database`, and `benchbox/mcp/tools/analytics.py`, not
  the removed modules.
- Public-contract/reference sweep found no hits for `benchbox.core.analysis`,
  `InsightGenerator`, `PlatformRanker`, `RankingStrategy`, or the analysis
  `rank_platforms` helper in `docs/reference/public-contracts.md`,
  `docs/reference/backward-compatibility.md`, `docs/reference/api-reference.md`,
  `docs/reference/python-api`, `README.md`, or `pyproject.toml`.
- No registry, query, generated-callable, benchmark-semantics, SQL, import-time
  I/O, dynamic-symbol, benchmark, or platform surface is changed.

## Verification

- Whole-tree reference check for removed symbols/modules:
  `rg -n "benchbox\\.core\\.analysis\\.insights|benchbox\\.core\\.analysis\\.ranking|from benchbox\\.core\\.analysis import .*Insight|from benchbox\\.core\\.analysis import .*Rank|from benchbox\\.core\\.analysis\\.insights|from benchbox\\.core\\.analysis\\.ranking|InsightGenerator|InsightConfig|InsightReport|PlatformRanker|RankingStrategy|RankingWeights|RankingResult|generate_blog_snippet|generate_comparison_narrative" benchbox tests docs README.md pyproject.toml scripts .github _project/scripts`
  -> no hits.
- Import smoke for `benchbox.core.analysis`, `benchbox.core.analysis.comparison`,
  `benchbox.core.analysis.statistics`, `benchbox.core.comparison`,
  `benchbox.mcp.tools.analytics`, `scripts.compare_pg_duckdb`, and
  `scripts.benchmark_mooncake_migration` -> pass.
- `uv run -- python -m pytest -n 0 tests/unit/core/analysis/test_analysis_comparison.py tests/unit/core/analysis/test_statistics.py tests/unit/cli/test_compare_command.py tests/unit/mcp/test_analytics_tools.py -q`
  -> 106 passed.
- `cloc --include-lang=Python benchbox/ --csv --quiet` -> 914 Python files,
  195,462 code lines.
- `uv run -- python -m compileall -q benchbox tests` -> pass.
- `git diff --check` -> pass.
- `uv run -- python scripts/check_complexity.py` -> pass; 0 failures above
  max complexity 20.
- `uv run -- ruff check benchbox/core/analysis/__init__.py tests/unit/core/analysis/test_analysis_comparison.py tests/unit/core/analysis/test_statistics.py scripts/compare_pg_duckdb.py scripts/benchmark_mooncake_migration.py`
  -> pass.
- `make shrink-rollup` -> merged ledger remains 10,956 credited lines; branch
  fragment will not count until merge.
- `gh pr list --base develop --state open --json number,title,headRefName,baseRefName,state,mergeStateStatus,files`
  -> no open `develop` PRs.

- `make pr-preflight > /tmp/shrink-dead-analysis-pr-preflight.log 2>&1`
  -> pass; `ci-lint` passed and the fast gate reported 22,648 passed, 5
  skipped, 47 warnings, and 4 subtests passed.

## Residual risk

Low but nonzero: external code could have imported the undocumented internal
helper modules directly. The public-contract map and reference docs do not
include them, and no BenchBox runtime path imports them.

## Next target

Continue searching for credited dead-code or true-dedup slices after this PR;
this branch still leaves the campaign short of the 12,000-line committed floor
until merged and followed by another safe slice.
