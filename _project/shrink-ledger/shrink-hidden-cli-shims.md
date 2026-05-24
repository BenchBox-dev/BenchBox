---
iteration: shrink-hidden-cli-shims
date: 2026-05-24
surface: hidden deprecated CLI compatibility shims
branch: chore/shrink-hidden-cli-shims
pr:
raw_cloc_delta: 252
credited_reduction: 252
uncredited_relocation: 0
repair_only_delta: 0
generated_python_delta: 0
moved_content: logic
decision_gate: conservative default
verification:
  - make shrink-rollup
  - cloc --include-lang=Python benchbox/
  - cloc --include-lang=Python benchbox/cli/commands/compare_dataframes.py benchbox/cli/commands/df_tuning.py benchbox/cli/commands/compare_plans.py benchbox/cli/commands/run_official.py benchbox/cli/commands/tuning.py benchbox/cli/commands/calculate_qphh.py --by-file
  - uv run -- ruff check benchbox/cli/commands/calculate_qphh.py benchbox/cli/commands/compare_dataframes.py benchbox/cli/commands/df_tuning.py benchbox/cli/commands/compare_plans.py benchbox/cli/commands/run_official.py benchbox/cli/commands/tuning.py tests/unit/cli/test_onboarding_df_tuning_behavioral.py tests/unit/cli/commands/test_cli_tuning.py tests/unit/cli/commands/test_compare_plans_coverage.py tests/unit/cli/commands/test_compare_dataframes_coverage.py tests/unit/cli/test_compare_command.py tests/unit/cli/test_new_commands.py tests/unit/test_cli_documentation.py tests/unit/test_patch_safety.py tests/uat/test_no_cli_surface_drift.py
  - uv run -- python -m pytest tests/unit/cli/test_onboarding_df_tuning_behavioral.py tests/unit/cli/commands/test_cli_tuning.py tests/unit/cli/commands/test_compare_plans_coverage.py tests/unit/cli/commands/test_compare_dataframes_coverage.py tests/unit/cli/test_compare_command.py tests/unit/cli/test_new_commands.py tests/unit/test_cli_documentation.py tests/unit/test_patch_safety.py tests/uat/test_no_cli_surface_drift.py -q -n 0
  - uv run -- benchbox compare-dataframes --list-platforms
  - uv run -- benchbox df-tuning list-platforms
  - uv run -- benchbox run-official tpch --platform duckdb --scale 0.5 --phases power
  - uv run -- python - <<'PY' ... # manual hidden CLI fingerprint
  - make pr-preflight
---

## Thesis

Shrink iteration under the smaller-subsystem exception. The hidden deprecated CLI
compatibility shim subsystem is 802 Python code lines:

- `benchbox/cli/commands/compare_dataframes.py`: 224
- `benchbox/cli/commands/compare_plans.py`: 284
- `benchbox/cli/commands/df_tuning.py`: 179
- `benchbox/cli/commands/run_official.py`: 72
- `benchbox/cli/commands/tuning.py`: 22
- `benchbox/cli/commands/calculate_qphh.py`: 21

The slice preserves the hidden command names, option surfaces, registration,
and deprecation warnings, but collapses compatibility-only implementation
copies onto maintained command paths or tighter local helpers:

- `compare-dataframes` keeps its legacy options, data-dir validation,
  DataFrame and SQL-vs-DataFrame execution paths, output modes, and chart
  behavior while removing duplicated formatting scaffolding.
- `df-tuning` keeps its legacy command group and subcommands, but delegates to
  the maintained `tuning` callbacks and reuses the maintained profile helper.
- `compare-plans` keeps the hidden command and helper behavior but compacts
  duplicated private output plumbing.
- `run-official` keeps the TPC guardrails and delegates directly to
  `benchbox run --official` without separate argument builder helpers.
- `create-sample-tuning` keeps its hidden command and help text but delegates to
  `tuning init`.
- `calculate-qphh` keeps its command surface and delegates directly to the
  maintained metrics implementation without a temporary result variable.

Credited reduction is 252 maintained-Python lines: 802 Python cloc before the
slice, 550 after. No command is removed, no deprecated/beta-public surface is
retired, and no benchmark, platform, query, result schema, or docs surface is
deleted.

## Guardrail Evidence

- Iteration type: shrink iteration, smaller-subsystem exception.
- Subsystem: hidden deprecated CLI compatibility shims; total subsystem size is
  802 Python cloc, below the 1,000-line smaller-subsystem cap.
- Minimum gate: remove at least 250 credited Python lines and at least 10% of
  the subsystem. If the final cloc delta is below that, this branch must stop or
  be reclassified before PR open.
- Moved-content classification: logic consolidation only. No Python-to-data
  relocation, generated Python, SQL/query movement, or catalog migration.
- Decision-gate status: conservative default. The slice does not approve
  deprecated command removal; it preserves the compatibility surface.
- Open PR overlap: PR #616 merged before selection; `git diff
  origin/develop...HEAD` is empty before edits. `gh pr list --state open
  --base develop --json number,title,headRefName,mergeStateStatus --limit 20`
  returned `[]`.
- Behavior preservation plan: Click option decorators and command names remain
  in place. Existing hidden-command tests must pass, plus the CLI surface drift
  guard for hidden compatibility files.
- Fingerprint scope: command registry/callable fingerprints were captured for
  `compare-dataframes`, `compare-plans`, `run-official`,
  `create-sample-tuning`, `df-tuning`, and `calculate-qphh`. No query,
  benchmark registry, platform registry, or generated-callable surface changed.

## Verification

- `make shrink-rollup` before edits: cumulative merged credited reduction 0;
  remaining floor 12000, stretch 19000.
- `cloc --include-lang=Python benchbox/`: 206,602 Python code lines after the
  slice, down from the 206,854 pre-edit sanity measurement on this branch.
- Hidden shim subsystem cloc: 550 code lines after the slice, down from 802
  before the slice.
- `uv run -- ruff check benchbox/cli/commands/calculate_qphh.py benchbox/cli/commands/compare_dataframes.py benchbox/cli/commands/df_tuning.py benchbox/cli/commands/compare_plans.py benchbox/cli/commands/run_official.py benchbox/cli/commands/tuning.py tests/unit/cli/test_onboarding_df_tuning_behavioral.py tests/unit/cli/commands/test_cli_tuning.py tests/unit/cli/commands/test_compare_plans_coverage.py tests/unit/cli/commands/test_compare_dataframes_coverage.py tests/unit/cli/test_compare_command.py tests/unit/cli/test_new_commands.py tests/unit/test_cli_documentation.py tests/unit/test_patch_safety.py tests/uat/test_no_cli_surface_drift.py`
- `uv run -- python -m pytest tests/unit/cli/test_onboarding_df_tuning_behavioral.py tests/unit/cli/commands/test_cli_tuning.py tests/unit/cli/commands/test_compare_plans_coverage.py tests/unit/cli/commands/test_compare_dataframes_coverage.py tests/unit/cli/test_compare_command.py tests/unit/cli/test_new_commands.py tests/unit/test_cli_documentation.py tests/unit/test_patch_safety.py tests/uat/test_no_cli_surface_drift.py -q -n 0`: 155 passed.
- `uv run -- benchbox compare-dataframes --list-platforms`: passed.
- `uv run -- benchbox df-tuning list-platforms`: passed.
- `uv run -- benchbox run-official tpch --platform duckdb --scale 0.5 --phases power`: exited 1 with the expected TPC scale validation and Click deprecation signal.
- Manual hidden CLI fingerprint captured command names, hidden/deprecated flags,
  callback names, options, required flags, and defaults for the touched hidden
  commands.
- `make pr-preflight`: passed; broad fast suite reported 22,775 passed,
  5 skipped, 47 warnings, and 4 subtests passed.

## Residual Risk

The touched commands are hidden/deprecated compatibility paths, so exact
cosmetic output can differ where they now share maintained command callbacks.
The option surfaces, hidden registration, deprecation signals, validation
guards, and execution semantics are preserved; targeted tests and smokes cover
the command paths.

## Next Target

If this lands with credit, continue with another true-dedup slice in CLI/result
plumbing or platform adapter boilerplate. If it misses the smaller-subsystem
threshold, reject this slice and return to high-yield surfaces instead of
opening a below-threshold PR.
