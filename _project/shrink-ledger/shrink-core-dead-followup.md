---
iteration: shrink-core-dead-followup
date: 2026-05-25
surface: result integrity validator check-result boilerplate
branch: chore/shrink-core-dead-followup
pr:
raw_cloc_delta: 252
credited_reduction: 252
uncredited_relocation: 0
repair_only_delta: 0
generated_python_delta: 0
moved_content: logic consolidation; no Python-to-data relocation
decision_gate: conservative default; public validator API and emitted check contracts preserved
verification: targeted pytest, ruff, ty, old-vs-new emitted-check comparison, whole-tree reference check, pr-preflight passed
---

## Thesis

Shrink iteration, smaller-subsystem exception. The named subsystem is
`benchbox/core/results/integrity_validator.py`, measured at 831 Python code
lines before edits, below the 1,000-line smaller-subsystem ceiling. The file is
mostly private check methods with repeated `CheckResult(...)` construction.
Consolidating that construction into private helpers should remove at least 250
credited maintained-Python lines while preserving the public validator types,
module-level convenience functions, check names, statuses, messages, and
details payloads.

## Guardrail evidence

- Current rollup from `origin/develop`: 10,704 credited lines merged; 1,296
  remaining to the committed floor; raw `benchbox/` cloc 196,394.
- Open develop PR overlap scan returned no open develop PR file list.
- Public references are limited to `ResultIntegrityValidator`,
  `IntegrityReport`, `CheckResult`, `CheckStatus`, `CheckCategory`,
  `validate_file`, and `validate_directory`; the targeted consolidation keeps
  those names and private check method names intact.
- Baseline targeted test:
  `uv run -- python -m pytest tests/unit/core/results/test_integrity_validator.py -q -n 0`
  passed with 27 passed, 3 skipped before edits.
- No benchmark/query registry or generated callable surface changes are planned;
  no fingerprint is required.

## Verification

- `cloc --include-lang=Python --csv --quiet benchbox/core/results/integrity_validator.py`
  reports 579 Python code lines, down from 831.
- `uv run -- python -m pytest tests/unit/core/results/test_integrity_validator.py -q -n 0`
  passed with 27 passed, 3 skipped.
- `uv run -- ruff check benchbox/core/results/integrity_validator.py tests/unit/core/results/test_integrity_validator.py`
  passed.
- `uv run -- ty check benchbox/core/results/integrity_validator.py` passed.
- Old-vs-new emitted-check comparison matched 7 integrity-validator scenarios.
- `_project/scripts/validate_results.py --help` import/CLI smoke passed.
- `git diff --check` passed.
- Whole-tree reference check for integrity-validator public names completed:
  public callers remain `_project/scripts/validate_results.py` and
  `tests/unit/core/results/test_integrity_validator.py`.
- Whole-tree cloc sanity check: `cloc --include-lang=Python benchbox/ --csv --quiet`
  reports 196,142 Python code lines after the edit.
- `make pr-preflight` passed after rebasing onto `origin/develop` at PR #653:
  22,638 passed, 5 skipped, 47 warnings, 4 subtests passed in 44.14s.

## Residual risk

Low. The main risk is accidental drift in check status, message, or details
payloads while replacing repeated construction with helpers. The targeted unit
tests exercise all named failure modes, and the implementation will keep private
method names stable for grep and debugging.

## Next target

If this slice lands, continue with duplicate-heavy primitive benchmark helper
consolidation only if it can clear the campaign floor without increasing
abstraction risk.
