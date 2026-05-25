# BenchBox Core Python Shrink Goal

Reduce maintained Python under `benchbox/` by a safe autonomous ~5-9% (12,000-19,000 credited code lines) without losing functionality, safety, public behavior, platform compatibility, benchmark correctness, or result integrity. The former 66% target was retired as infeasible without metric-gaming or product-surface deletion; see `_project/analysis/shrink-feasibility.md` and `_project/decisions/shrink-objective.md`.

## Target and Scope

- Credit applies only to maintained Python in `benchbox/**/*.py`.
- Do not shrink tests, fixtures, benchmark data, SQL, CSV, YAML, Markdown, TOML, docs, TODOs, scripts, outputs, vendored code, lockfiles, or mirrors for credit.
- A shrink PR may also touch its ledger fragment, focused characterization tests, verification helpers, PR-body plumbing, and narrow project config needed for this goal; those changes are uncredited.
- Tests may change only to prove preserved behavior, characterization coverage, guardrail repair, or benchmark semantics.
- Baseline: `cloc --include-lang=Python benchbox/` = 234,211 code lines (reference denominator). Current raw `cloc` must be measured on the checked branch and reported as a sanity check only; raw movement before ledger adoption is not credited unless a merged ledger fragment records credited reduction. On this branch, the 2026-05-24 measurement is 206,854 Python code lines.
- Campaign target: cumulative merged credited reduction of 12,000-19,000 maintained-Python code lines (~5-9% of baseline), the safe autonomous ceiling from feasibility analysis, cross-validated by two independent reviews. 12,000 is the committed floor; 19,000 the stretch. Reductions beyond this band require a separate human-approved product-deletion plan and are out of scope for the autonomous loop (see Out of Scope below).
- Raw `cloc` is a sanity check, not the distance metric. Raw `cloc` drops without matching credit do not reduce distance; line-adding guardrail repairs do not increase distance.
- Cold start: prior shrink PRs without ledger fragments are not backfilled unless the user explicitly authorizes it.

## Out of Scope (requires separate human/product approval)

The large line masses are not autonomous-shrinkable. These are out of scope for the autonomous loop and may not be undertaken without an explicit human/product decision recorded in `_project/decisions/`:

- Deleting whole benchmark families or platforms; drive any such decision from `benchmark_registry.yaml` / `platform_registry.py` `support_status`, not from the loop.
- Deleting the `benchbox.experimental` package (shipped-but-unsupported per `pyproject.toml`).
- Removing deprecated/back-compat surfaces or beta-public contracts (`docs/reference/public-contracts.md`, `backward-compatibility.md`).
- Codegen rewrites, god-class decompositions, or dual-impl collapses that trade correctness risk for lines.

These are the honest levers for a larger reduction, but they are product/architecture calls: file them as a deletion-plan decision, not campaign iterations.

## Non-Negotiables

- Preserve public APIs, CLI behavior, config formats, benchmark semantics, validation behavior, safety boundaries, and documented workflows.
- Do not weaken filesystem, subprocess, credential/env, live/cloud, timing, publishing, manifest, or user-data safety.
- Hard failures: behavior regression, unexplained failure, import-time regression, or benchmark-semantic drift.
- Use `uv run -- ...`; never bare `python`, `pytest`, `ruff`, or `pip`.
- Do not use `git add -A`; stage explicit paths only.
- Follow AGENTS.md and valid repo patterns. Existing guardrail violations are repair surface, not templates; do not extend or rely on them in a touched surface.
- Edit inside the claimed worktree only, never the main checkout.
- `GPT-5.3-Codex-Spark` is executor-only: measurement, command execution, approved mechanical edits, and PR/status summaries. Spark must not approve credited reduction, benchmark semantics, Python-to-data relocation, generator replacement, canonical-source decisions, or PR readiness.

## Open Decision Gates

Unresolved TODOs, ADRs, and user decisions default to the conservative path. Autonomous agents may repair blockers but must not choose the permissive arm of an open policy gate. Approved exceptions must cite the TODO, ADR, PR, or user instruction that resolved the gate.

- Objective-function TODO ratified (2026-05-24; see `_project/analysis/shrink-objective-backfill.md`): the logic-vs-data discriminator in "Ledger and Credit" plus the Guardrails *are* the objective function, validated against #587-604 (credits genuine logic reductions, refuses gamed relocations). The provisional credit formula and the conservative default below stand — `approved_credit_for_valid_data_extraction` remains 0 until a human approves that credit class; executor agents may not (see the executor-only boundary above).
- JoinOrder/benchmark-semantics TODO unresolved: prove benchmark-shape preservation or stop; agents may not reclassify benchmark intent.
- Import-loading TODO resolved (2026-05-24; see `_project/DONE/main/shrink-followup-registry-lazy-cached-load.yaml`): default to lazy/memoized loading. Eager import-time loading needs linked approval, import-delta measurement, and budget.
- Generated-implementation findability TODO resolved (2026-05-24; see `_project/DONE/main/shrink-followup-generated-impl-findability.yaml`): default to explicit registries or typed mappings. Dynamic symbol injection needs linked approval and grep/type-check evidence.
- Codegen/runtime-source ADR resolved (2026-05-25; see `_project/decisions/catalog-runtime-parse-vs-codegen.md`): the canonical catalog pattern is human-authored structured source loaded through lazy runtime accessors, cached when the surface is hot or preserves compatibility exports. Build-time generated Python is not the default and earns no maintained-code shrink credit unless a future explicit ADR supersedes that decision.
- New catalog/YAML migrations must name the canonical source, preserve reviewability, use lazy loading, include schema or typed validation, and fingerprint public symbols/queries when relevant. Extending an existing catalog with newly relocated Python counts as a new migration.

## Ledger and Credit

Use one tracked ledger fragment per PR: `_project/shrink-ledger/<branch-slug>.md`; start from `_project/shrink-ledger/TEMPLATE.md`. `_project/*` is ignored by default, so stage new fragments explicitly by path with `git add -f`.

Each fragment uses YAML frontmatter plus markdown body and doubles as the PR body:

```markdown
---
iteration:
date:
surface:
branch:
pr:
raw_cloc_delta:
credited_reduction:
uncredited_relocation:
repair_only_delta:
generated_python_delta:
moved_content:
decision_gate:
verification:
---
## Thesis
## Guardrail evidence
## Verification
## Residual risk
## Next target
```

Campaign progress is the sum of `credited_reduction` from fragments merged to `develop`. Pending branch-only fragments do not count. Reverting a shrink PR must revert or negate its fragment. At iteration start, run `make shrink-rollup`; report cumulative merged credited reduction, distance to the 12,000-19,000 target band, and raw `cloc`.

Credit unit is Python `cloc` code lines. Provisional formula:

`credited = net_deleted_or_consolidated_maintained_python_logic - added_maintained_python - uncredited_relocation`

The objective-function TODO resolved without approving data-extraction credit: `approved_credit_for_valid_data_extraction = 0`. When in doubt, classify Python-to-data movement as uncredited relocation. Consolidation credit is net maintained-Python reduction after additions.

Do not count Python logic moved into data/string blobs; SQL/query semantics moved into escaped scalars or opaque blobs; control flow, lookup rules, or execution rules relocated without simplification; generated Python unless the codegen ADR defines accounting; or whitespace/comment/formatting/cosmetic edits.

Python-to-data relocation earns credit only after a separate human-approved decision approves that class and only when content is pure data, metadata, or declared query surface; the target is more readable/searchable/maintainable; validation is exercised; loading is lazy or import-neutral by approved budget; and maintenance burden falls.

SQL is benchmark/query surface. Moving SQL out of Python counts only when reviewability, searchability, and tooling are preserved. Prefer existing `.sql` assets or structured catalogs. YAML SQL requires block scalars and round-trip equality; escaped newline scalars are forbidden.

Generated `.py` must live in a marked generated path. The official raw measurement command remains `cloc --include-lang=Python benchbox/` until the codegen ADR changes it. Generated lines are ledgered separately and do not reduce official distance.

## Iteration Types

Classify every iteration before editing.

`Shrink iteration`: coherent module-family or subsystem slice; at least 500 credited Python lines removed; smaller-subsystem exception requires the whole named subsystem to be under 1,000 Python code lines and the change to remove at least 250 credited lines and 10% of that subsystem; removes real logic/maintenance surface; passes guardrails before PR open.

`Guardrail repair iteration`: may remove fewer than 500 lines, remove zero lines, or temporarily add lines; directly removes a blocker to future credited shrink; names the future surface and expected payoff; counts toward the target only if it also removes credited Python surface. Valid repairs include import-time I/O removal, dynamic-registration replacement, schema validation, SQL readability repair, benchmark-semantic checks, characterization tests for under-tested legacy behavior, and canonical-source decisions.

If high-line shrink candidates are blocked by existing violations, do not stop. Pick the smallest coherent repair that unlocks the largest future credited reduction. After one repair PR for a surface, the next iteration must attempt the unlocked shrink or re-justify another repair; after two repair PRs without credited shrink landing, escalate or mark the surface irreducible-for-now.

## Planning Gate

Before editing, write a thesis with: iteration type, subsystem and total line count, expected files, reduction path or blocker removed, expected credited reduction or future shrink unlocked, moved-content classification (`logic`, `data`, `metadata`, `query surface`, `generated`), decision-gate status (`resolved`, `conservative default`, or `approved exception`), behavior/benchmark preservation plan, and reproducible guardrail evidence.

Before selecting a slice, inspect open develop PR changed files and avoid source overlap. Treat shared campaign tooling, PR templates, rollup scripts, and metadata paths as overlap surfaces. Per-PR fragments avoid ledger conflicts; `pr-conflict-scan` is only a late backstop.

Reject arbitrary slices, duplicate PR titles or thesis statements, overlapping PRs without dependency rationale, and below-threshold shrink PRs that do not unlock larger same-surface work.

## Guardrails

Each PR must satisfy relevant gates before `make pr-open`; evidence must be command output or named CI result, not assertion.

1. No new import-time I/O by default; approved eager loading requires linked decision, measured import delta, and stated budget.
2. No new dynamic symbol injection by default; approved exceptions require linked findability decision plus grep/type-check evidence.
3. Preserve benchmark semantics, not just row-value equivalence. Generator or hand-translation replacement must prove intended shape using logical-plan operator set, join graph, aggregation grouping, or equivalent domain-specific structure.
4. No unreadable migrated SQL. Prefer `.sql` or structured catalogs; YAML SQL requires block scalars and round-trip equality.
5. Catalog/data migrations need schema or typed validation and a named command or CI gate.
6. PR boundaries must be coherent by ownership, risk, or dependency.
7. No quality regression: a reduction must not worsen per-unit cyclomatic complexity, module coupling, fast-suite time, or the cost to add a platform/benchmark. Baseline cyclomatic complexity is already low (radon avg ~A/3.8), so the codebase is broad, not complex, and a "shrink" that increases per-unit complexity is not credited.

Closure/factory builders are allowed within the conservative default when every exported callable is bound to an explicit grep-findable name, registry keys and identities are static, type checking resolves exports, and `__name__`/`__qualname__` plus category metadata are preserved. Builders that synthesize names, mutate module globals, or dynamically key registries remain banned.

For query, registry, or generated-callable consolidation, capture pre/post fingerprints covering registry IDs, callable names, categories, family mappings, and deterministic outputs where relevant. Use `uv run -- python _project/scripts/shrink_fingerprint.py ...` if available; otherwise include the manual command/output in the ledger fragment.

## Workflow and PR Cadence

Work one coherent slice at a time across high-value surfaces: CLI wiring, benchmark lifecycle, platform adapters, SQL compatibility, DataFrame platforms, validation/result integrity, publishing/reporting, and utilities.

1. Claim worktree: `make worktree-claim BRANCH=chore/shrink-<surface-or-module-slug>`.
2. Rebase: `git fetch origin develop && git rebase origin/develop`.
3. Run `make shrink-rollup`, then measure raw `cloc`.
4. Read implementation, callers, contracts, docs, and tests for the slice.
5. Record the thesis and ledger fragment.
6. Execute the smallest coherent shrink or repair.
7. Preserve platform-specific behavior and documented extension points.
8. Update the ledger fragment.
9. Run slice-scoped narrow checks and fingerprints before commit.
10. Run `make pr-preflight`, then `make pr-open PR_BODY_FILE=<fragment>`.

- Do not run the full `-m fast` suite separately when `make pr-preflight` will run immediately; preflight owns the broad fast gate.
- When removing or relocating behavior, symbols, commands, docs, or orientation text, search the whole tree for surviving references; diff-only evidence is insufficient.
- Do not spend preflight/push/PR time on below-threshold shrink slices unless they are valid guardrail repairs.
- Delegate boilerplate waits (full suites, preflight, push, PR open) to a low-thinking-effort subagent when available. Require command status, PR URL, PR body status, `pr-conflict-scan` warnings verbatim, and concise failure tail. Do not delegate slice selection, credit classification, or guardrail sign-off.
- Use the ledger fragment as the PR body.
- Do not accumulate unrelated surfaces or stack on unmerged shrink PRs unless unavoidable and documented.
- Do not poll CI after opening a PR; pending is terminal for the iteration, but campaign accounting updates only after merge.
- Release the worktree when the project workflow allows.

## Stop Conditions

Stop before editing, committing, or opening a PR when no coherent shrink or repair thesis exists; savings are mainly relocation, syntax churn, single-file trim, or non-Python; code purpose lacks behavior evidence and characterization-test repair is not in scope; import-time behavior, safety, public behavior, or benchmark semantics would weaken; a new Python-to-YAML/catalog migration lacks a canonical-source decision; or the PR boundary is arbitrary or duplicative.

When the safe autonomous reservoir is exhausted, several consecutive iterations find no qualifying safe slice, or cumulative credited reduction plateaus inside the 12,000-19,000 band, declare maximum-safe-reduction reached and convene human review. Do not reach for out-of-scope product/architecture levers to keep the number moving. If the band itself proves unreachable, report evidence, irreducible surfaces, and the maximum safe credited reduction.

Self-review each milestone, fix findings, then report raw `cloc`, cumulative merged credited reduction, guardrail repairs completed, changed files, checks run, and next high-value targets.
