---
iteration: shrink-campaign-scaffolding
date: 2026-05-24
surface: shrink campaign tooling
branch: chore/shrink-campaign-scaffolding
pr: 615
raw_cloc_delta: 0
credited_reduction: 0
uncredited_relocation: 0
repair_only_delta: 0
generated_python_delta: 0
moved_content: none
decision_gate: conservative default
verification:
  - make shrink-rollup
  - cloc --include-lang=Python benchbox/
  - uv run -- ruff check _project/scripts/shrink_rollup.py tests/unit/scripts/test_shrink_rollup.py
  - uv run -- python -m pytest tests/unit/scripts/test_shrink_rollup.py -q -n 0
  - make pr-preflight
---

## Thesis

Guardrail repair iteration. The retargeted shrink goal requires one
`_project/shrink-ledger/<branch-slug>.md` fragment per PR, `make shrink-rollup`
at iteration start, and `make pr-open PR_BODY_FILE=<fragment>` at publication.
`origin/develop` has the goal, ADR, and feasibility analysis, but not the
tracked fragment directory/template, rollup script, or PR-body plumbing needed
to run the workflow from a fresh worktree.

This slice adds only campaign scaffolding:

- `_project/scripts/shrink_rollup.py` sums merged ledger fragments from a Git ref.
- `_project/shrink-ledger/TEMPLATE.md` gives future slices the required
  frontmatter and body shape.
- `_project/shrink-ledger.md` becomes a legacy pointer so the retired 66%
  target no longer competes with the active per-PR fragment ledger.
- `make shrink-rollup` fetches `origin/develop` and reports the active
  12,000-19,000 credited-reduction band.
- `make pr-open PR_BODY_FILE=...` creates or updates the PR body from the
  fragment file.
- focused unit tests cover fragment parsing, empty missing-ledger state, target
  band reporting, and invalid target-band rejection.

Expected credited reduction is 0. The repair unlocks future credited shrink
iterations by making the accounting source of truth and PR-body ritual
available from the repo instead of from local untracked state.

## Guardrail evidence

- Iteration type: guardrail repair.
- Subsystem: shrink campaign project tooling; no `benchbox/**/*.py` files
  touched.
- Moved-content classification: none; no Python-to-data relocation, generated
  Python, SQL migration, or benchmark/query surface movement.
- Decision-gate status: conservative default. The slice does not approve any
  open objective-function, import-loading, generated-implementation,
  codegen/runtime-source, or catalog/YAML migration gate.
- Open PR overlap: `gh pr list --base develop --state open` showed PR #614 on
  `fix/pr-review-followups-review-retry`; it does not touch this campaign
  scaffolding surface.
- Behavior preservation: no runtime package, benchmark registry, query
  registry, platform adapter, CLI command, or public API behavior changes.

## Verification

- `make shrink-rollup`: PASS before this fragment landed locally; reported 0
  merged fragments, 0 credited reduction, target band 12000-19000, 12000
  remaining to committed floor, 19000 remaining to stretch target.
- `cloc --include-lang=Python benchbox/`: PASS before this fragment landed
  locally; 929 Python files, 206854 code lines.
- `uv run -- ruff check _project/scripts/shrink_rollup.py
  tests/unit/scripts/test_shrink_rollup.py`: PASS.
- `uv run -- python -m pytest tests/unit/scripts/test_shrink_rollup.py -q -n
  0`: PASS, 4 passed.
- `_project/shrink-ledger.md` review: PASS; the legacy single-file ledger now
  points to fragment-based accounting instead of carrying operative retired
  target math.
- `make pr-preflight`: PASS; 22767 passed, 5 skipped, 47 warnings, 4 subtests
  passed.

## Residual risk

This PR is intentionally a repair-only slice. It does not reduce maintained
Python lines, so campaign credit remains at 0 until a later shrink PR merges.
Future fragments are counted only after they are present on `origin/develop`,
which means a branch's own pending fragment is not credited by `make
shrink-rollup` before merge.

## Next target

After this repair merges, resume credited shrink selection from the high-value
runtime surfaces named in `_project/goal-shrink-core-code.md`: CLI wiring,
benchmark lifecycle, platform adapters, SQL compatibility, DataFrame platforms,
validation/result integrity, publishing/reporting, and utilities.
