---
iteration: shrink-cli-private-dead-scaffolding
date: 2026-05-25
surface: legacy CLI helper facades with no production references
branch: chore/shrink-cli-private-dead-scaffolding
pr:
raw_cloc_delta: 603
credited_reduction: 603
uncredited_relocation: 0
repair_only_delta: -12
generated_python_delta: 0
moved_content: logic
decision_gate: conservative default; remove only non-exported, undocumented, production-unreferenced helper surfaces
verification:
  - make shrink-rollup
  - cloc --include-lang=Python benchbox/
  - cloc --include-lang=Python --by-file benchbox/cli/execution.py benchbox/cli/validation.py benchbox/cli/config.py
  - rg reference checks for removed CLI helper symbols/modules
  - make duplicate-check-json
  - uv run -- ruff check benchbox/cli/config.py benchbox/core/catalog_schema.py benchbox/sql_compat/baseline_tool.py benchbox/sql_compat/inventory.py benchbox/utils/printing.py tests/unit/cli/test_config_coverage.py
  - uv run -- python -m compileall -q benchbox/utils benchbox/cli benchbox/core benchbox/sql_compat
  - uv run -- python -m pytest tests/unit/cli/test_output_control_static.py tests/unit/cli/test_config_coverage.py tests/unit/cli/test_execution_pipeline.py tests/unit/cli/test_cli_benchmark_boundaries.py tests/unit/cli/test_benchmark_selection.py tests/unit/cli/test_benchmark_manager_behavioral.py -q -n 0
  - uv run -- python -m pytest tests/unit/cli -q -n 0
  - uv run -- python -m pytest tests/uat/test_no_cli_surface_drift.py -q -n 0
  - make pr-preflight
---
## Thesis

Shrink iteration targeting dead CLI helper scaffolding, not command behavior. The slice removes:

- `benchbox/cli/execution.py` (`BenchmarkExecutor`), a legacy facade around `execution_pipeline.py`.
- `benchbox/cli/validation.py` (`ValidationDisplay` and `CLIValidationRunner`), a standalone presentation runner for core validation.
- `benchbox/cli/config.py::ExampleArgumentParser`, an example-parser helper that is not used by shipped examples or CLI commands.

The target files contain 1,269 maintained-Python code lines before editing. The removed surfaces have no production imports, are not exported by `benchbox.cli.__all__`, and are absent from `docs/reference/public-contracts.md`. Final credited reduction is 603 maintained-Python lines after subtracting the narrow output-control repair required to keep the verification gate green while preserving stderr behavior. Tests removed in this slice are uncredited and exist only to exercise the deleted dead helper surfaces.

## Guardrail evidence

- Current rollup before editing: cumulative merged credited reduction 2,655; remaining to 12,000 floor 9,345; remaining to stretch 16,345; raw cloc delta sanity 1,507.
- Current raw maintained-Python size: `cloc --include-lang=Python benchbox/` reports 204,352 Python code lines.
- Target surface size: `cloc --include-lang=Python --by-file benchbox/cli/execution.py benchbox/cli/validation.py benchbox/cli/config.py` reports 1,269 Python code lines.
- Final raw maintained-Python size: `cloc --include-lang=Python benchbox/` reports 203,749 Python code lines, a 603-line net reduction from the 204,352-line slice baseline.
- During the broader CLI test sweep, the static output-control guard found pre-existing raw `print()` violations in `benchbox/core/catalog_schema.py`, `benchbox/sql_compat/baseline_tool.py`, and `benchbox/sql_compat/inventory.py`. The slice uses the smallest policy-compliant repair: migrate those calls to `benchbox.utils.printing.emit()` instead of adding pending-migration exceptions. Because some calls originally wrote to stderr, `emit()` now accepts `stderr=True` to preserve stream behavior. The net 12-line cost is included in the 603-line credited reduction and recorded as `repair_only_delta: -12`.
- `tests/uat/test_no_cli_surface_drift.py` initially failed the broad preflight because this branch intentionally changes private non-command CLI modules. The repair adds `benchbox/cli/config.py`, `benchbox/cli/execution.py`, and `benchbox/cli/validation.py` to the existing internal-file allowlist; the Click decorator/signature drift checks still apply to command modules.
- Production reference checks:
  - `rg "BenchmarkExecutor|benchbox\\.cli\\.execution|from benchbox.cli.execution|import benchbox.cli.execution" benchbox docs/reference README.md pyproject.toml` found no production or public-contract references.
  - `rg "ValidationDisplay|CLIValidationRunner|benchbox\\.cli\\.validation|from benchbox.cli.validation|import benchbox.cli.validation" benchbox docs/reference README.md pyproject.toml` found only the definitions inside `benchbox/cli/validation.py`.
  - `rg "ExampleArgumentParser" benchbox docs/reference README.md pyproject.toml` found only the definition inside `benchbox/cli/config.py`.
- Test/archive/design references were identified separately and are not production call sites:
  - `tests/unit/cli/test_cli_execution.py`
  - `tests/unit/cli/test_cli_validation.py`
  - `tests/unit/cli/test_example_argument_parser.py`
  - `tests/unit/cli/test_config_coverage.py`
  - `docs/design/structure.md`
  - `_project/_archive/PROJECT_DONE.yaml`

## Verification

- `make shrink-rollup`: 10 merged fragments; cumulative merged credited reduction 2,655; remaining to 12,000 floor 9,345; raw cloc delta sanity 1,507.
- `cloc --include-lang=Python benchbox/`: 929 files, 203,749 Python code lines after edits.
- `cloc --include-lang=Python --by-file benchbox/cli/execution.py benchbox/cli/validation.py benchbox/cli/config.py`: `config.py` now has 654 code lines; deleted files are absent. Net runtime reduction from slice baseline after the output-control repair is 603 lines.
- Removed-symbol reference check:
  `rg -n "BenchmarkExecutor|ValidationDisplay|CLIValidationRunner|ExampleArgumentParser|benchbox\\.cli\\.execution\\b|benchbox\\.cli\\.validation\\b|from benchbox\\.cli import execution\\b|from benchbox\\.cli import validation\\b" benchbox tests docs README.md pyproject.toml`: no matches.
- `make duplicate-check-json`: pass; summary reported 277 groups, 360 duplicate instances, 6,183 duplicated lines.
- `uv run -- ruff check benchbox/cli/config.py benchbox/core/catalog_schema.py benchbox/sql_compat/baseline_tool.py benchbox/sql_compat/inventory.py benchbox/utils/printing.py tests/unit/cli/test_config_coverage.py`: pass.
- `uv run -- python -m compileall -q benchbox/utils benchbox/cli benchbox/core benchbox/sql_compat`: pass.
- `uv run -- python -m pytest tests/unit/cli/test_output_control_static.py tests/unit/cli/test_config_coverage.py tests/unit/cli/test_execution_pipeline.py tests/unit/cli/test_cli_benchmark_boundaries.py tests/unit/cli/test_benchmark_selection.py tests/unit/cli/test_benchmark_manager_behavioral.py -q -n 0`: 99 passed.
- `uv run -- python -m pytest tests/unit/cli -q -n 0`: 1,419 passed, 15 deselected.
- `uv run -- python -m pytest tests/uat/test_no_cli_surface_drift.py -q -n 0`: 5 passed.
- `make pr-preflight`: pass; `ci-lint` passed and fast tests reported 22,961 passed, 5 skipped, 47 warnings, and 4 subtests passed.

## Residual risk

The only meaningful risk is an external user importing these undocumented helper classes directly. They are not in the recorded public contract map and have no in-repo production consumers; preserving them would keep test-only scaffolding as maintained runtime code.

## Next target

After this slice lands, re-run `make shrink-rollup` and duplicate/dead-code checks from the new `develop` baseline. Do not count this slice until the PR merges.
