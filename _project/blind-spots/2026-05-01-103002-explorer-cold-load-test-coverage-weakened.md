---
id: 2026-05-01-103002-explorer-cold-load-test-coverage-weakened
date: 2026-05-01
status: open
finding_kind: bug-class
review_context: "/code review of PR #86 (Results Explorer QA pass 2)"
related_paths:
  - results-explorer/e2e/failures/platform-index-cold-load.spec.ts
  - results-explorer/src/pages/Home.tsx
suggested_sweep: "Restore strict row-count assertions for the cold-load regression, or document why polling-based assertions are sufficient."
todo_id: null
---

# Cold-load regression test was loosened from strict row counts to "any rows"

## Finding

The pass-1 cold-load regression test
(`platform-index-cold-load.spec.ts`) used to:

1. Mock the production `results.duckdb` byte-for-byte via Playwright
   route interception.
2. Assert exact row counts: `await expect(page.locator("table tbody
   tr")).toHaveCount(4)` for DuckDB and `2` for Polars.

After PR #86 the test:

1. Drops the route mocking entirely (now polls fixtures DB).
2. Asserts only `count > 0`, no upper bound.
3. Adds a guard against the empty-state copy.

The pass-1 finding (`results-explorer-qa-pass1-fixes`) was specifically
that *partial-row* loads occurred (some platforms had fewer rows than
expected on cold-load). Asserting "any rows present" cannot detect a
regression where, e.g., DuckDB renders 1 row instead of 4 — exactly the
class of bug the original test was guarding.

The pass-2 fix in `Home.tsx` (the inconsistent-empty-snapshot retry)
addresses Home-level empty flashes, not PlatformIndex-level partial
loads. So the loosened assertion is not justified by the fix landing
elsewhere.

## Why the five-axis review missed it

The "what's done well" + "missing tests" frames don't have a slot for
*regression-coverage downgrade*. The diff goes from 100 lines of strict
test to 30 lines of permissive test, which reads as simplification.
Without comparing the failure mode this test was originally written
to catch, the reviewer accepts the diff as cleanup.

## Why this matters

A future cold-load partial-row regression — which is the one we
actually had — would now slip past CI silently.

## Suggested next steps

Either:
1. Restore the route-interception harness and exact row counts (treat
   the simplification as a regression in coverage); or
2. Update `_project/audits/results-explorer-qa-pass1-fixes.md` to
   record the *test simplification rationale* — why the team decided
   the fixture-DB assertion is sufficient — so the next reviewer can
   tell loose-on-purpose from loose-by-accident.
