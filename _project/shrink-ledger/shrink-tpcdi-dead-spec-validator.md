---
iteration: shrink-tpcdi-dead-spec-validator
date: 2026-05-25
surface: unreferenced TPC-DI specification validator module
branch: chore/shrink-tpcdi-dead-spec-validator
pr:
raw_cloc_delta: 864
credited_reduction: 864
uncredited_relocation: 0
repair_only_delta: 0
generated_python_delta: 0
moved_content: none
decision_gate: conservative default; delete only unexported, undocumented, production-unreferenced validation helper code
verification:
  - make shrink-rollup
  - cloc --include-lang=Python benchbox/
  - cloc --by-file --include-lang=Python benchbox/core/tpcdi/specification_validator.py tests/unit/tpcdi/test_specification_validator.py tests/integration/test_phase4_validation_integration.py
  - rg reference check for removed validator module/symbols
  - uv run -- ruff check benchbox/core/tpcdi tests/unit/tpcdi tests/integration
  - uv run -- python -m compileall -q benchbox/core/tpcdi
  - uv run -- python -m pytest tests/unit/tpcdi -q -n 0
  - uv run -- python -m pytest tests/test_tpcdi.py tests/integration/test_tpcdi_full_benchmark.py -q -n 0
  - make pr-preflight
---
## Thesis

Shrink iteration targeting a dead TPC-DI validation helper, not benchmark behavior. The slice removes
`benchbox/core/tpcdi/specification_validator.py`, a 864-line maintained-Python module that is not imported by
runtime TPC-DI code, not exported by `benchbox.core.tpcdi.__all__`, and absent from public-contract docs.

The only in-repo consumers found are tests dedicated to that module:

- `tests/unit/tpcdi/test_specification_validator.py`
- `tests/integration/test_phase4_validation_integration.py`

Those tests are deleted as verification scaffolding for the removed dead module and are not credited. Expected credited
reduction is 864 maintained-Python lines.

## Guardrail Evidence

- Current rollup after rebasing onto merged PR #632: cumulative merged credited reduction 3,258; remaining to 12,000 floor 8,742; remaining to stretch 15,742; raw cloc delta sanity 2,110.
- Current raw maintained-Python size after rebasing onto merged PR #632: `cloc --include-lang=Python benchbox/` reports 203,749 Python code lines before this slice and 202,885 after this slice.
- Target runtime size: `cloc --by-file --include-lang=Python benchbox/core/tpcdi/specification_validator.py tests/unit/tpcdi/test_specification_validator.py tests/integration/test_phase4_validation_integration.py` reports 864 Python code lines in the runtime module, 356 in unit tests, and 299 in integration tests.
- `benchbox/core/tpcdi/__init__.py` exports `TPCDIBenchmark`, `TPCDIDataGenerator`, `TPCDIQueryManager`, schema constants, and schema helpers; it does not export the specification validator classes or convenience function.
- Whole-tree reference check before editing:
  `rg -n "benchbox\\.core\\.tpcdi\\.specification_validator|from benchbox.core.tpcdi.specification_validator|import benchbox.core.tpcdi.specification_validator|TPCDISpecificationValidator|SpecificationComplianceReport|ComplianceCheckResult|validate_tpcdi_benchmark_compliance" benchbox tests docs README.md pyproject.toml`
  found references only in the target module and its two dedicated test files.

## Verification

- `make shrink-rollup`: 11 merged fragments; cumulative merged credited reduction 3,258; remaining to 12,000 floor 8,742; raw cloc delta sanity 2,110.
- `cloc --include-lang=Python benchbox/`: 928 files, 202,885 Python code lines after edits.
- `cloc --by-file --include-lang=Python benchbox/core/tpcdi/specification_validator.py tests/unit/tpcdi/test_specification_validator.py tests/integration/test_phase4_validation_integration.py`: target runtime module measured 864 code lines before deletion; deleted tests measured 356 and 299 uncredited test code lines.
- Removed-symbol reference check:
  `rg -n "benchbox\\.core\\.tpcdi\\.specification_validator|from benchbox.core.tpcdi.specification_validator|import benchbox.core.tpcdi.specification_validator|TPCDISpecificationValidator|SpecificationComplianceReport|ComplianceCheckResult|validate_tpcdi_benchmark_compliance" benchbox tests docs README.md pyproject.toml`: no matches.
- `uv run -- ruff check benchbox/core/tpcdi tests/unit/tpcdi tests/integration`: pass.
- `uv run -- python -m compileall -q benchbox/core/tpcdi`: pass.
- `uv run -- python -m pytest tests/unit/tpcdi -q -n 0`: 152 passed.
- `uv run -- python -m pytest tests/test_tpcdi.py tests/integration/test_tpcdi_full_benchmark.py -q -n 0`: 19 passed, 19 deselected.
- `make pr-preflight`: pass; `ci-lint` passed and fast tests reported 22,943 passed, 5 skipped, 47 warnings, and 4 subtests passed.

## Residual Risk

External users could import `benchbox.core.tpcdi.specification_validator` directly despite the module not being in the
public contract map or package `__all__`. Preserving it would keep a large, uncalled validation subsystem in maintained
runtime code with only self-tests as consumers.

## Next Target

After this slice lands, re-run `make shrink-rollup` from the merged `develop` baseline before choosing the next
non-overlapping surface.
