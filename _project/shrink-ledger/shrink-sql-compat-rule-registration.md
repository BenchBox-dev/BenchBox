---
iteration: shrink-sql-compat-rule-registration
date: 2026-05-25
surface: SQL compatibility rule registration boilerplate
branch: chore/shrink-sql-compat-rule-registration
pr:
raw_cloc_delta: -568
credited_reduction: 568
uncredited_relocation: 0
repair_only_delta: 0
generated_python_delta: 0
moved_content: logic
decision_gate: conservative default; explicit static helper functions preserve import-time registration and rule identity
verification: focused sql-compat tests, exact registry fingerprint parity, compat-docs-check, DDL drift, ruff
---

## Thesis

Shrink iteration. The slice consolidates duplicated SQL compatibility rule-registration mechanics in
`benchbox/sql_compat/rules/ddl_optimize/` and the write/transaction PRIMARY KEY capability rule modules.
The target surface is 1,055 Python code lines. The expected reduction path is true boilerplate dedup:
replace repeated `CompatibilityDecision` / payload construction with explicit shared helpers while keeping
each rule module importable and each registered decision byte-for-byte equivalent in rule id, phase,
platform, benchmark, payload, reason, support level, and failure mode.

No benchmarks, platforms, deprecated public surfaces, generated Python, or Python-to-data relocation are
removed. The rule files remain explicit grep-findable modules, and registration still happens at module import.
Credited reduction: 568 maintained-Python lines.

## Guardrail evidence

- Baseline campaign rollup: 756 merged credited lines; 11,244 remaining to floor; 18,244 remaining to stretch.
- Baseline raw maintained Python: `cloc --include-lang=Python benchbox/` = 206,098 code lines.
- Target surface baseline: 1,055 Python code lines across DDL optimize and PK capability rule files.
- No open `develop` PR file overlap: `gh pr list --state open --base develop --json ...` returned `[]`.
- Baseline registry fingerprint: `/tmp/shrink-sql-compat-baseline-fingerprint.json` (986 lines,
  SHA256 `aa969c140419db3706d33fb7814f6b9cb2f3e266127ff7b2dfb84064cad78e46`).
- Baseline focused tests: `uv run -- python -m pytest tests/unit/sql_compat/test_singlestore_rules.py tests/unit/sql_compat/test_pk_coverage_parity.py -q -n 0`
  passed, 59 tests.
- Baseline DDL drift: `uv run -- python -m benchbox.sql_compat.inventory --check-ddl-drift` reported clean
  DDL governance status with 0 unregistered or uninspectable transforms.
- Post-edit raw maintained Python: `cloc --include-lang=Python benchbox/` = 205,530 code lines.
- Post-edit target surface: 487 Python code lines including the new shared helper.
- Post-edit registry fingerprint: `/tmp/shrink-sql-compat-post-fingerprint.json` matched baseline exactly,
  SHA256 `aa969c140419db3706d33fb7814f6b9cb2f3e266127ff7b2dfb84064cad78e46`.

## Verification

- `uv run -- ruff check benchbox/sql_compat/rules/_registration.py benchbox/sql_compat/rules/ddl_optimize benchbox/sql_compat/rules/schema_emit/pk_capability.py benchbox/sql_compat/rules/schema_emit/pk_capability_txn.py` passed.
- `uv run -- python -m pytest tests/unit/sql_compat/test_singlestore_rules.py tests/unit/sql_compat/test_pk_coverage_parity.py -q -n 0` passed, 59 tests.
- `uv run -- python -m pytest tests/unit/sql_compat -q -n 0` passed, 134 tests.
- `make compat-docs-check` passed; compat docs matched registry and DDL drift was clean.
- `make duplicate-check-json` passed.
- `make pr-preflight` pending before PR open.

## Residual risk

The main risk is import-time registration drift: a helper could accidentally change a rule key, payload type,
or registration order. The exact JSON fingerprint and SingleStore order tests are the gating controls.

## Next target

After this PR merges, re-run `make shrink-rollup` and choose the next highest-confidence mechanical dedup
surface from platform adapter configuration builders or SQL/query-plan parser boilerplate.
