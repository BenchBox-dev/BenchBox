---
iteration: shrink-dead-cloud-error-context
date: 2026-05-25
surface: unused cloud platform error-context helper
branch: chore/shrink-dead-cloud-error-context
pr:
raw_cloc_delta: -317
credited_reduction: 317
uncredited_relocation: 0
repair_only_delta: 0
generated_python_delta: 0
moved_content: none
decision_gate: conservative default; unused internal helper deletion, no registered platform or public adapter contract removed
verification: cloc, reference sweep, ruff, compileall, representative platform tests, pr-preflight
---

## Thesis

Shrink iteration using the smaller-subsystem exception. The named subsystem is
the standalone internal helper module
`benchbox/platforms/cloud_error_context.py`, measured at 317 maintained-Python
code lines before editing. Exact references are limited to the module itself,
its dedicated unit test, and the ABC-conformance skip list. No production
adapter imports the module, and the platform public contract covers adapter
subclassing hooks and base mixins rather than this unused helper.

Measured reduction is 317 credited maintained-Python lines by deleting the
unused helper. The dedicated unit test is deleted as uncredited test cleanup,
and the stale ABC-conformance skip entry is removed.

## Guardrail evidence

- Open develop PR overlap checked: PR #635 touches TPC-DI cleaner files only;
  PR #626 touches JoinOrder DataFrame plan-shape files only.
- `cloc --include-lang=Python benchbox/platforms/cloud_error_context.py`:
  317 code lines.
- Exact reference check before editing:
  `rg -n "cloud_error_context|CloudErrorContext|detect_error_type|enhance_cloud_error|wrap_cloud_operation|BIGQUERY_ERROR_PATTERNS|REDSHIFT_ERROR_PATTERNS|SNOWFLAKE_ERROR_PATTERNS|DATABRICKS_ERROR_PATTERNS|PLATFORM_ERROR_PATTERNS" benchbox tests docs README.md pyproject.toml --glob '!docs/_build/**'`.
  Production hits were limited to the module itself; no adapter, registry, CLI,
  MCP, docs, or public-contract consumer imports it.
- No moved content; this deletes unused maintained-Python helper logic rather
  than relocating it.

## Verification

Completed post-edit measurement and tests:

- `cloc --include-lang=Python benchbox/`: 926 files, 202,225 code lines
  after editing, down from 202,542 at slice start.
- Exact post-edit reference check for deleted module/symbols: no matches.
- `uv run -- ruff check tests/unit/platforms/test_abc_conformance.py`:
  passed.
- `uv run -- ruff format --check tests/unit/platforms/test_abc_conformance.py`:
  passed.
- `uv run -- python -m compileall -q benchbox/platforms tests/unit/platforms/test_abc_conformance.py`:
  passed.
- `uv run -- python -m pytest tests/unit/platforms/test_abc_conformance.py tests/unit/platforms/test_bigquery_adapter.py tests/unit/platforms/test_redshift_adapter.py tests/unit/platforms/test_snowflake_adapter.py -q -n 0`:
  545 passed.

- `make pr-preflight > /tmp/shrink-dead-cloud-error-context-preflight.log 2>&1`:
  passed; artifact hygiene passed; CI lint passed; fast tests reported
  22,876 passed, 5 skipped, 47 warnings, 4 subtests passed in 234.92s.

## Residual risk

Low but nonzero import-compatibility risk for external callers importing an
undocumented internal helper. The helper was not wired into adapters or docs,
so preserving it would maintain code that never affects runtime cloud-platform
error handling.

## Next target

Continue exact-reference screening for internal helper modules and true
cross-platform dedup opportunities after this slice lands.
