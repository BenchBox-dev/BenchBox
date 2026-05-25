---
iteration: shrink-dead-tuning-validation
date: 2026-05-25
surface: legacy core tuning validation helper
branch: chore/shrink-dead-tuning-validation
pr:
raw_cloc_delta: 454
credited_reduction: 454
uncredited_relocation: 0
repair_only_delta: 0
generated_python_delta: 0
moved_content: none
decision_gate: conservative default; internal helper deletion only, no benchmark/platform/public-contract surface removed
verification: targeted pytest, import smoke, reference sweep, ruff, compileall, complexity, diff-check, shrink-rollup, cloc, pr-preflight
---

## Thesis

Shrink iteration using the smaller-subsystem exception. Remove the legacy
`benchbox/core/tuning/validation.py` helper and its YAML specs because the
fresh reference sweep shows no runtime users: references are limited to the
module itself, the `benchbox.core.tuning` package convenience exports, and the
module's dedicated unit test.

The named subsystem is the legacy core tuning validation helper: 436 Python
code lines in `validation.py`, plus package export cleanup. It is under 1,000
Python code lines, and the expected maintained-Python reduction is about 454
lines, satisfying the smaller-subsystem gate of at least 250 credited lines
and at least 10% of the named subsystem.

Baseline at slice start:

- `make shrink-rollup`: 10,956 merged credited lines; 1,044 remaining to the
  committed 12,000 floor.
- `cloc --include-lang=Python benchbox/`: 916 Python files, 196,142 code lines.
- Open `develop` PRs at refresh:
  - #657 `chore/shrink-dead-analysis-helpers`: touches `benchbox/core/analysis`
    and its fragment only.
  - #658 `chore/benchmark-visibility-invariants`: touches benchmark visibility
    docs/tests only.
- No open PR overlaps `benchbox/core/tuning`.

Expected credit: 454 maintained-Python lines. The unit test and YAML spec file
are uncredited cleanup because their production consumer disappears.

Moved-content classification: none. This deletes unwired maintained Python
logic and its private data file; no Python logic moves to data, generated
Python, strings, docs, YAML, SQL, or fixtures.

## Guardrail evidence

- Public-reference sweep found tuning documentation imports
  `benchbox.core.tuning.interface`, not `benchbox.core.tuning.validation` or the
  package-level validation convenience exports.
- The active platform/runtime tuning paths use
  `benchbox/platforms/base/tuning_config.py`, `benchbox/core/tuning/metadata.py`,
  and `benchbox.core.dataframe.tuning.validation`, not this helper.
- Removing the package-level validation imports also removes an existing
  import-time YAML read from plain `import benchbox.core.tuning`.
- No registry, query, generated-callable, benchmark-semantics, SQL,
  dynamic-symbol, benchmark, or platform surface is changed.

## Verification

- Whole-tree reference sweep for removed symbols/modules:
  `rg -n "benchbox\\.core\\.tuning\\.validation|from benchbox\\.core\\.tuning import .*validate_|from benchbox\\.core\\.tuning import .*Validation(Issue|Level|Result)|validate_columns_exist|validate_column_types|detect_tuning_conflicts|validate_benchmark_tunings|validate_constraint_consistency" benchbox tests docs README.md pyproject.toml scripts _project/scripts`
  -> no hits.
- Public-reference sweep for core tuning docs/contracts:
  `rg -n "benchbox\\.core\\.tuning|core/tuning|tuning\\.validation|validation_specs" docs/reference/public-contracts.md docs/reference/backward-compatibility.md docs/reference/api-reference.md docs/reference/python-api docs/development README.md pyproject.toml`
  -> public tuning docs reference `benchbox.core.tuning.interface`, not the
  removed validation helper.
- Import smoke for `benchbox.core.tuning`, `benchbox.core.tuning.interface`,
  `benchbox.core.tuning.metadata`, `benchbox.core.tuning.ddl_generator`,
  `benchbox.cli.config`, `benchbox.platforms.base.tuning_config`, and
  `benchbox.core.dataframe.tuning.validation` -> pass.
- `uv run -- python -m pytest -n 0 tests/unit/core/tuning/test_tuning_metadata.py tests/unit/core/tuning/test_tuning_config.py tests/unit/core/tuning/test_ddl_generator.py tests/unit/cli/test_cli_config.py tests/unit/cli/test_tuning_runtime.py tests/unit/cli/commands/test_tuning_group_cli.py tests/unit/platforms/test_base_adapter_database_management.py -q`
  -> 181 passed.
- `uv run -- python -m compileall -q benchbox tests` -> pass.
- `git diff --check` -> pass.
- `uv run -- ruff check benchbox/core/tuning/__init__.py benchbox/core/tuning/interface.py benchbox/core/tuning/metadata.py benchbox/platforms/base/tuning_config.py benchbox/core/dataframe/tuning/validation.py`
  -> pass.
- `uv run -- python scripts/check_complexity.py` -> pass; 0 failures above
  max complexity 20.
- `cloc --include-lang=Python benchbox/ --csv --quiet` -> 915 Python files,
  195,688 code lines.
- `make shrink-rollup` -> merged ledger remains 10,956 credited lines; branch
  fragment will not count until merge.

- `make pr-preflight > /tmp/shrink-dead-tuning-validation-pr-preflight.log 2>&1`
  -> pass; `ci-lint` passed and the fast gate reported 22,645 passed, 5
  skipped, 47 warnings, and 4 subtests passed.

## Residual risk

Low but nonzero: external code could import the undocumented
`benchbox.core.tuning.validation` module or package-level validation helpers.
The public Python API docs and public-contract map do not list those helpers,
and no BenchBox runtime path imports them.

## Next target

If this PR and #657 both merge, the campaign should cross the 12,000-line
committed floor. Continue only within the safe autonomous reservoir, and stop
for human review if further qualifying slices are not evident.
