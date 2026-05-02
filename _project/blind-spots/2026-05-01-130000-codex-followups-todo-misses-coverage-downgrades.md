---
id: 2026-05-01-130000-codex-followups-todo-misses-coverage-downgrades
date: 2026-05-01
status: actioned
finding_kind: framework-gap
review_context: "/todo review of codex-pr-review-followups-week-2026-05-01"
related_paths:
  - _project/TODO/main/planning/codex-pr-review-followups-week-2026-05-01.yaml
  - _project/blind-spots/2026-05-01-103002-explorer-cold-load-test-coverage-weakened.md
  - _project/blind-spots/2026-05-01-103000-hosted-submit-no-local-validate-preflight.md
  - _project/blind-spots/2026-05-01-103001-published-results-validator-no-per-bundle-test.md
  - results-explorer/e2e/failures/platform-index-cold-load.spec.ts
suggested_sweep: "Before sweeping codex-followups w12, diff blind-spots filed in the same window and either fold them in, link them, or explicitly mark them out-of-scope. Add a 'review-window cross-check' step to the next weekly Codex sweep template."
todo_id: codex-pr-review-followups-week-2026-05-01
---

# "Codex thread sweep" framework misses coverage downgrades and locally-filed blind-spots from the same window

## Finding

`codex-pr-review-followups-week-2026-05-01.yaml` frames itself as
"unresolved Codex review threads from PRs #19-#94 → fix list". That
frame is good at catching what Codex flagged-and-was-never-resolved,
but blind to two adjacent failure modes:

1. **Coverage downgrades from later PRs in the same window.** The
   per-PR Codex thread scan reads each thread in isolation. If PR #N
   adds a strict assertion and PR #N+M weakens it, no Codex thread
   exists to follow because Codex didn't flag it. The local
   blind-spot `2026-05-01-103002-explorer-cold-load-test-coverage-weakened.md`
   captures exactly this case for PR #86: row-count assertions in
   `platform-index-cold-load.spec.ts` were loosened from
   `toHaveCount(4)` / `toHaveCount(2)` to `count > 0`. The Codex
   followups TODO has w8 for the Home.tsx empty-state issue from the
   same PR, but does not surface that the regression test for the
   *original* cold-load symptom got weaker.

2. **Locally-filed blind-spots from the same review window are not
   cross-linked.** Three blind-spots filed today
   (`2026-05-01-103000`, `103001`, `103002`) cover hosted-submit
   pre-flight, published-results validator, and the explorer
   coverage downgrade — all from `/code review` on the same merge
   window. The Codex sweep TODO is silent about them. A reader
   working w8 won't discover the related cold-load coverage finding
   unless they grep `_project/blind-spots/` independently.

## Why the framework missed it

The "Codex thread per PR" sweep template only iterates one source
(GitHub inline review threads) and one author
(`chatgpt-codex-connector`). It has no slot for:

- Local human/agent review findings filed as blind-spots in the
  same window.
- Tests whose assertions weakened across the window.
- "Reviewer was right, fix landed, but the fix subtly regressed an
  adjacent test" — the kind of N+M chain that no single PR thread
  can express.

Because the rubric never asks "what else was filed about these PRs
this week?", co-located but separately-tracked findings stay
invisible.

## Why this matters

The cold-load partial-row regression is the exact failure mode the
original e2e test was written to catch (per the pass-1 audit). If
the Home.tsx fix in w8 lands without restoring the strict
assertions, the next regression of that class slips past CI silently
— and the Codex followups TODO will report "done" because Codex
never flagged the test downgrade in the first place.

## Suggested next steps

1. Add a step to the next weekly Codex sweep that diffs
   `_project/blind-spots/` for findings filed in the review window
   and either folds them into the TODO or explicitly marks them
   out-of-scope with a one-line rationale.
2. For *this* TODO specifically, cross-link
   `2026-05-01-103002-explorer-cold-load-test-coverage-weakened.md`
   from w8's notes so whoever picks up w8 knows the partial-row
   regression test still needs restoration (separate fix from the
   Home.tsx empty-state).
3. Consider a longer-term rubric change: weekly review sweeps
   should include "tests weakened in this window" as an explicit
   axis, sourced from `git log -p -- '*.spec.ts' '*test*.py'` and
   filtered for assertion-loosening patterns.

## Triage log

- 2026-05-02: partially actioned; rubric/template change still owed.
  Step 2 landed inside
  `_project/DONE/main/active/codex-pr-review-followups-week-2026-05-01.yaml`
  — the TODO is `Completed`, w9 covers the Home.tsx persistent-mismatch
  fix, and the file's `must_not_do` list explicitly forbids landing the
  Home.tsx fix without restoring `toHaveCount` in
  `platform-index-cold-load.spec.ts` (the row counts were restored;
  see `2026-05-01-103002-...-coverage-weakened.md → actioned`). Step 1
  (process change to next weekly sweep) and Step 3 (rubric axis "tests
  weakened in this window") have NOT been encoded as a reusable
  template — there is no `_project/templates/` directory and no
  weekly-sweep template to amend. Verified actionable for the
  framework-gap dimension only.
- 2026-05-02: actioned — Sweep 2026-05-02: created _project/audits/codex-weekly-sweep-template.md with all five required scope axes. Axis 2 (in-window blind-spot cross-check) and Axis 3 (tests weakened in the window — with concrete grep patterns for assertion-loosening like toHaveCount->count>0, fixture-DB polling replacing strict mocks, etc.) were the gaps the original frame missed. Future weekly Codex sweeps copy from this template and skip an axis only with an explicit out-of-scope citation. The 2026-05-01 sweep already executed Axis 2 manually (cold-load coverage cross-link in must_not_do); template now codifies the practice. (Note: `_project/prompts/` is gitignored, so the template lives in `_project/audits/` alongside the per-week rescan files.)
