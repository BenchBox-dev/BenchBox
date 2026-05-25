---
iteration: shrink-cli-display-dead-helpers
date: 2026-05-25
surface: unused CLI display helper methods
branch: chore/shrink-cli-display-dead-helpers
pr:
raw_cloc_delta: 306
credited_reduction: 306
uncredited_relocation: 0
repair_only_delta: 0
generated_python_delta: 0
moved_content: logic
decision_gate: conservative default; remove only undocumented, production-unreferenced CLI display helper methods while preserving the system-profile display path
verification:
  - make shrink-rollup
  - cloc --include-lang=Python benchbox/
  - cloc --include-lang=Python --by-file benchbox/cli/display.py benchbox/cli/system.py tests/unit/cli/test_display.py tests/unit/cli/test_system_profiler.py
  - rg reference checks for removed display helpers
  - uv run -- ruff check benchbox/cli/display.py benchbox/cli/system.py tests/unit/cli/test_display.py tests/unit/cli/test_system_profiler.py
  - uv run -- python -m compileall -q benchbox/cli
  - uv run -- python -m pytest tests/unit/cli/test_system_profiler.py tests/unit/cli/test_display.py -q -n 0
  - uv run -- python -m pytest tests/unit/cli/test_cli_startup_imports.py tests/unit/cli/test_cli_dryrun.py::TestDryRunDisplayConfigurationSummary tests/unit/cli/test_system_profiler.py tests/unit/cli/test_display.py -q -n 0
  - uv run -- python -m pytest tests/unit/cli -q -n 0
  - uv run -- python -m pytest tests/uat/test_no_cli_surface_drift.py -q -n 0
  - make pr-preflight
---

## Thesis

Shrink iteration using the smaller-subsystem exception. The target is `benchbox/cli/display.py`, a 341-code-line internal CLI display helper module. Production references resolve to the system profiler path only: `benchbox.cli.system.SystemProfiler.display_profile()` imports `create_display_manager()` and calls `StandardDisplays.show_system_profile()`.

The slice removes the remaining undocumented display helpers that have no production call sites: benchmark configuration display, database configuration display, benchmark-result display, query-result display, dry-run summary display, generic progress/error/success helpers, and their top-level convenience wrappers. The final credited reduction is 306 maintained-Python lines from a subsystem under 1,000 code lines, with no Python-to-data movement and no command/option deletion.

## Guardrail evidence

- Current rollup before editing: cumulative merged credited reduction 9,836; remaining to the 12,000 floor 2,164; raw cloc delta sanity 7,396.
- Current raw maintained-Python size: `cloc --include-lang=Python benchbox/` reports 197,262 Python code lines.
- Target surface size: `cloc --include-lang=Python --by-file benchbox/cli/display.py benchbox/cli/system.py tests/unit/cli/test_display.py tests/unit/cli/test_system_profiler.py` reports `benchbox/cli/display.py` at 341 code lines and `benchbox/cli/system.py` at 30 code lines.
- Reference scan found the production dependency on `benchbox/cli/display.py` in `benchbox/cli/system.py`; tests and `_project` archive records cover the unused helper methods but are not production call sites.
- Final raw maintained-Python size: `cloc --include-lang=Python benchbox/` reports 196,956 Python code lines, down 306 from the 197,262-line slice baseline.
- Final target surface size: `benchbox/cli/display.py` reports 35 code lines; `benchbox/cli/system.py` remains 30 code lines.
- The first `make pr-preflight` run failed only the CLI surface-drift UAT guard because `benchbox/cli/display.py` was not in the private-CLI allowlist. The repair adds that internal helper module to `ALLOWED_INTERNAL_CLI_FILES`; the guard still checks Click decorators/signatures for command modules.

## Verification

- `make shrink-rollup`: 21 merged fragments; cumulative merged credited reduction 9,836; remaining to 12,000 floor 2,164; raw cloc delta sanity 7,396.
- `cloc --include-lang=Python benchbox/`: 920 files, 196,956 Python code lines after edits.
- `cloc --include-lang=Python --by-file benchbox/cli/display.py benchbox/cli/system.py tests/unit/cli/test_display.py tests/unit/cli/test_system_profiler.py`: `benchbox/cli/display.py` now has 35 code lines; `benchbox/cli/system.py` remains 30.
- Removed-symbol reference check:
  `rg -n "\b(DisplayConfig|show_banner|show_benchmark_config|show_database_config|show_query_results|show_benchmark_result|show_dry_run_summary|show_progress_with_context|show_error_summary|show_success_message|show_benchmark_summary|show_configuration_summary)\b" benchbox tests docs _project pyproject.toml README.md`: no matches.
- `uv run -- ruff check benchbox/cli/display.py benchbox/cli/system.py tests/unit/cli/test_display.py tests/unit/cli/test_system_profiler.py`: pass.
- `uv run -- python -m compileall -q benchbox/cli`: pass.
- `uv run -- python -m pytest tests/unit/cli/test_system_profiler.py tests/unit/cli/test_display.py -q -n 0`: 8 passed.
- `uv run -- python -m pytest tests/unit/cli/test_cli_startup_imports.py tests/unit/cli/test_cli_dryrun.py::TestDryRunDisplayConfigurationSummary tests/unit/cli/test_system_profiler.py tests/unit/cli/test_display.py -q -n 0`: 18 passed.
- `uv run -- python -m pytest tests/unit/cli -q -n 0`: 1,407 passed, 15 deselected.
- `uv run -- python -m pytest tests/uat/test_no_cli_surface_drift.py -q -n 0`: 5 passed.
- Manual production-path smoke:
  `uv run -- python - <<'PY' ... SystemProfiler().display_profile(profile, detailed=True) ... PY`: printed the system profile and `system-display-ok`.
- `make pr-preflight`: pass; fast tests reported 22,735 passed, 5 skipped, 47 warnings, and 4 subtests passed.

## Residual risk

The residual risk is external direct imports of undocumented `benchbox.cli.display` helper methods. They are not listed in `docs/reference/public-contracts.md`; the public CLI contract is command and option behavior, which this slice should not change.

## Next target

After this slice lands, re-run `make shrink-rollup` and continue searching for autonomous-safe dead helper or proven-dedup surfaces outside open PR paths.
