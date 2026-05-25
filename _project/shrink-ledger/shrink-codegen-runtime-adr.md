---
iteration: guardrail-repair
date: 2026-05-25
surface: catalog-source-pattern-decision
branch: chore/shrink-codegen-runtime-adr
pr: 638
raw_cloc_delta: 0
credited_reduction: 0
uncredited_relocation: 0
repair_only_delta: 0
generated_python_delta: 0
moved_content: none
decision_gate: conservative-default
verification:
  - grep -rniE 'codegen|runtime.parse|canonical catalog' docs/ _project/ 2>/dev/null | grep -i adr
  - uv run --project _project/scripts -- python _project/scripts/todo_cli.py validate
  - git diff --check
  - make pr-preflight
---

## Thesis

Guardrail repair iteration for the open codegen/runtime-source decision gate.
Current `origin/develop` has 5,111 merged credited shrink lines, 6,889 lines
remaining to the 12,000 floor, and 201,896 raw maintained-Python `cloc` lines
under `benchbox/`. The next large non-overlapping reservoir is catalog/query
surface, especially generated TPC-DS DataFrame query implementation structure.
At slice start, the control document blocked new catalog/YAML migrations while
the canonical runtime-parse-vs-codegen pattern was unresolved.

This slice records the decision without changing runtime code. The expected
credited reduction is zero; the expected future payoff is that subsequent
catalog/query shrink can use one conservative pattern instead of re-litigating
whether YAML/data catalogs should be parsed lazily at runtime or converted into
generated Python.

## Guardrail evidence

- Iteration type: guardrail repair, because it directly removes an open
  decision blocker to future credited catalog/query shrink.
- Moved-content classification: none. This PR does not move Python logic,
  metadata, data, query surface, or generated code.
- Decision gate status: conservative default. The prior lazy registry/spec
  repair measured eager YAML import overhead and converted it to lazy cached
  runtime loading; this ADR ratifies that pattern unless future explicit
  evidence and approval supersede it.
- Goal gate alignment: the control document now cites the already-completed
  import-loading and generated-findability repairs, plus this ADR, without
  loosening the ledger credit formula.
- Behavior preservation: documentation/TODO-only change; no runtime imports,
  registry entries, query callables, platform adapters, benchmark semantics,
  or public APIs are touched.

## Verification

Passed:

- `grep -rniE 'codegen|runtime.parse|canonical catalog' docs/ _project/ 2>/dev/null | grep -i adr`
  found the ADR and completed TODO references.
- `uv run --project _project/scripts -- python _project/scripts/todo_cli.py validate`
  reported 1,052 valid files and 0 invalid files.
- `uv run --project _project/scripts -- python _project/scripts/todo_cli.py check-graph`
  reported no inter-item dependency cycles, no work-unit cycles, and no
  dangling references across 49 active items.
- `git diff --check` passed.
- `make pr-preflight` passed: 22,828 passed, 5 skipped, 47 warnings, and
  4 subtests passed in 154.49s.

## Residual risk

The repair does not by itself reduce maintained Python. The next iteration
must either attempt the unlocked catalog/query shrink or re-justify why another
guardrail repair is still required for the same surface.

## Next target

After this decision lands, reassess the TPC-DS generated DataFrame query
surface and the smaller TPC-DI helper-export surface once PR #637 is merged or
its overlap is gone.
