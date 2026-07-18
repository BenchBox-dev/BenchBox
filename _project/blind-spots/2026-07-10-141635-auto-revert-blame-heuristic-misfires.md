---
id: 2026-07-10-141635-auto-revert-blame-heuristic-misfires
date: 2026-07-10
status: actionable
finding_kind: framework-gap
review_context: "ducklake deep review / PR #1104 auto-revert triage (origin/develop 7b6d1eef4)"
related_paths:
  - .github/workflows/develop-post-merge.yml
  - tests/unit/test_query_generation_preflight.py
  - benchbox/core/tpcds/throughput_test.py
suggested_sweep: "grep .github/workflows for the auto-revert bot's blame logic; confirm it can distinguish 'PR introduced the failure' from 'PR is first red run after a latent break'"
todo_id: null
---

# Auto-revert bot blames the first red post-merge SHA, not the PR that caused the break

## Finding
PR #1104 (github-actions[bot]) proposed reverting #1096 because "develop went red
post-merge" on run 29094411121. The failing test
`test_tpcds_throughput_preflight_detects_generation_failures` contains zero
DuckLake code. It fails deterministically in isolation at origin/develop HEAD
(after #1096) — not flaky, not order-dependent. The real cause is #1093
(2f9439b13, merged 17 min BEFORE #1096), which rerouted the TPC-DS throughput
preflight from `benchmark.get_query()` to a batch `dsqgen -STREAMS` pass
(`generate_dsqgen_streams`). The test still injected failure via
`benchmark.get_query`, which the new path never calls — so preflight no longer
raised. #1093's own post-merge run went green because that path raises
`DSQGenStreamsError` (→ RuntimeError) when the dsqgen binary is ABSENT, making
the stale test pass for the wrong reason; on a runner WITH the binary, generation
succeeds and the test fails "DID NOT RAISE". The bot reverted the innocent head
SHA of the first run that happened to execute on a binary-present runner.

The correct remediation was fix-forward (PR #1113 aligns the test with the
dsqgen path); #1104 was correctly closed. Repo also carries many other
`auto-revert/*` branches (incl. `auto-revert/2f9439b13cc9` for #1093 itself),
showing the bot fires broadly.

## Why this matters
"Revert the head SHA of the first red post-merge run" cannot distinguish a PR
that *introduced* a failure from a PR that is merely the *first to run CI after a
latent break was already merged*. Environment-dependent spurious passes (here:
dsqgen-binary presence) let a breaking PR merge green, so the blast lands on an
unrelated later PR. Auto-reverting the wrong commit both fails to fix develop and
risks reverting good work. A blame heuristic that reads the failing test's
identity/history (git-bisect or "which PR last touched the code under test")
would have pointed at #1093, not #1096.

## Suggested next steps
- [ ] Locate the auto-revert bot's workflow/action and document its blame rule.
- [ ] Make the bot bisect or map the failing test to the PR that last modified
      the code-under-test before blaming; failing that, require human confirm
      before opening a revert PR that touches a different subsystem than the
      failing test.
- [ ] Add a guard: if the failing test file is untouched by the blamed PR's
      diff, downgrade the revert PR to an advisory comment.

## Triage log

- 2026-07-18: actionable — Re-verified at origin/develop 542590b66 on 2026-07-18: signature-aware comparison suppresses persistent-red duplicates, but a latent environment-dependent first failure can still open a revert for the current SHA; retain as a residual attribution gap.
