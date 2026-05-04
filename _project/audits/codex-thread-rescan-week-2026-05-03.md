# Codex Thread Rescan - Week Ending 2026-05-03

Rescan date: 2026-05-04

Scope:

- PR range: #95 through #170 merged to `develop` between 2026-04-26 and
  2026-05-03 (the second weekly Codex sweep).
- API source: `gh api repos/joeharris76/BenchBox/pulls/<pr>/comments`.
- Author filter: `chatgpt-codex-connector[bot]`.
- Original TODO inventory: 36 inline Codex findings across 29 PRs filed in
  `_project/TODO/main/active/codex-pr-review-followups-week-2026-05-03.yaml`.

The original TODO grouped the work into 24 numbered work units (w1-w24)
plus four explicitly-deferred items. Implementation landed in three
batched waves rather than one PR per finding (operator-directed deviation
from the TODO's `anti_patterns:` guidance):

- Wave 1 (PR #175, merge SHA `837963342`) - security batch (w3, w10, w11, w17).
- Wave 2 (PR #179, merge SHA `d3a458776`) - P1 correctness batch
  (w1, w2, w4, w5, w6, w7, w8, w9, w12, w22, w23).
- Wave 3 (PR #183, head `ad52f249e`) - P2 polish batch
  (w13, w14, w15, w16, w18, w19, w20, w21, w24). Open with auto-merge
  enabled at audit time; merge SHA will be pinned by the
  develop-post-merge workflow.

This audit confirms every actionable Codex thread in the window is either
fixed in one of those three merges, addressed by an earlier follow-up, or
listed under `deferred:` in the TODO with reason.

## Resolved By w1-w24

| PR | Thread | Current disposition | Fix |
| --- | --- | --- | --- |
| #102 | [Preserve multi-select semantics for benchmark/scale cohort filters](https://github.com/joeharris76/BenchBox/pull/102#discussion_r3174367121) | Fixed by exporting `toggleFacetValue` and routing benchmark/scale dropdowns through it (w13). | PR #183 |
| #103 | [Stop linking unpublished `.plans.json` sidecars from the run receipt](https://github.com/joeharris76/BenchBox/pull/103#discussion_r3174480692) | Fixed by gating `planDownloadUrl` on a new optional `plans_published` field on `DetailResult` (w1). The pipeline emitter side was wired up in the follow-up below. | PR #179 (consumer side); follow-up PR for the producer side. |
| #105 | [Extract cloud/region metadata for non-DB cloud adapters (Athena, Synapse, ...)](https://github.com/joeharris76/BenchBox/pull/105#discussion_r3174793237) | Fixed by adding a generic `else:` fallback after the per-platform branches in `_extract_platform_config_from_results` (w2). | PR #179 |
| #105 | [Add datafusion-df, pyspark-df (and any peer DataFrame engines) to the local-platform allowlist](https://github.com/joeharris76/BenchBox/pull/105#discussion_r3174793239) | Fixed by adding `datafusion-df`, `pyspark-df`, `lakesail`, `lakesail-df` to the local set in `CostCalculator` (w14). | PR #183 |
| #107 | [Include log-scale endpoint ticks in the latency axis](https://github.com/joeharris76/BenchBox/pull/107#discussion_r3176628095) | Fixed by always including `domainMin`/`domainMax` then deduping against canonical powers (w15). | PR #183 |
| #111 | [Preserve both legacy shape aliases when canonicalizing the URL facet model](https://github.com/joeharris76/BenchBox/pull/111#discussion_r3176716507) | Fixed by merging values across legacy aliases (concat + dedupe) when the canonical URL key is absent (w16). | PR #183 |
| #113 | [Normalize secret key names before redaction so camelCase keys are caught](https://github.com/joeharris76/BenchBox/pull/113#discussion_r3176769303) | Fixed by stripping non-alphanumerics from both the secret-parts list and the input key before substring match (w3). | PR #175 |
| #113 | [Preserve `saved_config` provenance when the saved value happens to equal the registered default](https://github.com/joeharris76/BenchBox/pull/113#discussion_r3176769305) | Fixed by leaving the source as `saved_config` and `continue`-ing when the key was already populated from `database_options` (w17). | PR #175 |
| #114 | [Validate every row, not just `[0][0]`, when checking `expected_value_min/max`](https://github.com/joeharris76/BenchBox/pull/114#discussion_r3176765596) | Fixed by iterating every row and failing on the first out-of-range scalar; empty result now also fails (w4). | PR #179 |
| #115 | [Propagate winner-claim suppression into the chart-level summary on the Compare page](https://github.com/joeharris76/BenchBox/pull/115#discussion_r3176818720) | Fixed by threading `suppressWinnerClaims`/`suppressionReason` through `ChartPanelProps` -> `renderChart` -> `SummaryBoxPanel` (w18). | PR #183 |
| #119 | [Propagate the configured MotherDuck database into runtime config](https://github.com/joeharris76/BenchBox/pull/119#discussion_r3176973035) | Fixed by adding `_build_motherduck_config` and registering it via the lazy registry (w19). Live cloud verification deferred (account required). | PR #183 |
| #127 | [Relax snapshot readiness so optional empty tables don't block the explorer](https://github.com/joeharris76/BenchBox/pull/127#discussion_r3177095782) | Fixed by tagging each scan with `required: bool` and only failing readiness on empty required scans (w5). | PR #179 |
| #129 | [Exclude in-flight claims from `worktree-pool-check` aborted-marker false positives](https://github.com/joeharris76/BenchBox/pull/129#discussion_r3177117127) | Fixed by introducing `POOL_CLAIM_MARKER_STALE_SECONDS` (default 600s); only stale markers count as aborted (w20). | PR #183 |
| #131 | [Make hosted-vs-PR submit manifest parity test exercise the actual call sites](https://github.com/joeharris76/BenchBox/pull/131#discussion_r3177127856) | Fixed by driving each manifest through its CLI dispatch (PR-package via `--output`, hosted via `--service` with stubbed network) (w21). | PR #183 |
| #132 | [Use end-of-day inclusive bound for the Axis 3 git log scan in the weekly sweep template](https://github.com/joeharris76/BenchBox/pull/132#discussion_r3177129340) | Fixed by aligning Axis 3 with Axis 1's inclusive end-of-day bound (`--until="$END_DATE 23:59:59 -0400"`) (w6). | PR #179 |
| #132 | [Replace the Axis 2 "precise" blind-spot listing guidance in the weekly sweep template](https://github.com/joeharris76/BenchBox/pull/132#discussion_r3177129342) | Fixed by replacing `make blind-spots-list` with a date-bounded `awk` filter and an explicit note that `sweep_blind_spots.py list` lacks `--since`/`--until` (w22). | PR #179 |
| #141 | [Round-trip cost.total_usd for legacy bundles that have no normalized_cost block](https://github.com/joeharris76/BenchBox/pull/141#discussion_r3177580644) | Fixed by preserving the `normalized_cost` block in `_extract_cost_summary` and treating a missing block as "allow direct total" in `_normalized_cost_allows_direct_total` (w7). | PR #179 |
| #144 | [Restrict Q10 skip guard in dask-df to local-envelope runs](https://github.com/joeharris76/BenchBox/pull/144#discussion_r3177676880) | Fixed by gating the skip on `_is_local_envelope()` (no `scheduler_address`, not `use_distributed`) (w8). | PR #179 |
| #145 | [Guard empty common prefix in DataFusion CSV multi-file glob](https://github.com/joeharris76/BenchBox/pull/145#discussion_r3177722807) | Fixed by detecting empty common prefix and registering each shard by exact path then UNION ALL into a view named after the table (w9). | PR #179 |
| #147 | [Keep `benchbox submit --dry-run` usable when validate_submission.py is absent](https://github.com/joeharris76/BenchBox/pull/147#discussion_r3177754515) | Fixed by catching FileNotFoundError, printing a soft warning, and continuing dry-run preview output (w10). | PR #175 |
| #147 | [Reject cwd-relative `validate_submission.py` to prevent code execution from arbitrary directories](https://github.com/joeharris76/BenchBox/pull/147#discussion_r3177754516) | Fixed by dropping the `Path.cwd()` candidate from `_load_submission_validator_module` (w11). The original Wave 1 regression test was strengthened in the follow-up below to actually exercise the real loader. | PR #175 |
| #151 | [Stop failing `benchbox platforms check` when an available-but-disabled platform's readiness probe fails](https://github.com/joeharris76/BenchBox/pull/151#discussion_r3177842037) | Fixed by reordering the branches so available-but-disabled platforms are reported informationally before the readiness-failed check (w12). | PR #179 |
| #151 | [Mark LakeSail readiness as ready when local auto-start is feasible (`pysail` importable)](https://github.com/joeharris76/BenchBox/pull/151#discussion_r3177842040) | Fixed by returning `ready` with auto-start detail when `platform == "lakesail"` and pysail is importable; `lakesail-df` continues to require an already-running endpoint (w23). | PR #179 |
| #167 | [Pin the sync-results-data-to-published workflow checkout to the triggering SHA](https://github.com/joeharris76/BenchBox/pull/167#discussion_r3178675036) | Fixed by pinning checkout to `${{ github.sha }}` (w24). Workflow-only change; runtime confirmation depends on the next sync-to-published run after merge. | PR #183 |

## Already-Fixed By Earlier Merges (Filtered Out At Scan Time)

These threads were dispositioned in the TODO's `description:` block and
intentionally not assigned a work unit because the underlying defect was
already addressed by a prior fix-PR.

| PR | Thread | Current disposition |
| --- | --- | --- |
| #99 | Makefile `test-unlock` `uv run` resolution | Already fixed: the current target uses pure shell `$HOME` expansion with no `uv run`. |
| #112 | `expected_value_min/max` enforcement in `_check_validation_query` | Already fixed in PR #114 (the branch loaders the validator now uses); w4 hardens it further to multi-row results. |
| #154 | `benchbox results --paths` reparses files | Already fixed in PR #156, which restructured `results()` so `--paths` no longer also calls `show_results_summary()`. |

## Blocked / Tracked Elsewhere

| PR | Thread | Disposition |
| --- | --- | --- |
| #134 | Redshift theta-merge validation queries | Tracked in blind-spot `2026-05-02-155448-validation-query-no-per-platform-override` -> `merged-to-todo` -> `write-primitives-architecture-fixes`. The Redshift override is unsafe to ship until that architectural fix lands; not duplicated in this sweep. |

## Deferred (Documented In TODO)

The TODO's `deferred:` block lists four items that were intentionally not
addressed in this sweep. They remain open as future-looking process or
dependency-blocked work; this audit confirms they are not silent gaps.

1. The four DONE-state TODO comments (PRs #110, #117, #121, #122) flagged
   verification-command bugs in already-closed TODO YAMLs. The TODOs are
   in DONE and the verification commands are no longer executed; recorded
   as a forward-looking control to fold into the weekly-sweep template
   (e.g. teach `validate_todo.py` to reject wildcard `--queries`,
   `find -newer` arity, and `$(date)` recomputation).
2. The convention question from PR #163 (whether
   `actioned`-state blind-spots satisfy the
   "merged-to-todo or dismissed" acceptance criterion). Convention work,
   not a runtime defect.
3. PR #161 multi-line shell `command:` parsing - DONE item; suggested as
   a future schema-validator extension.
4. Live MotherDuck cloud verification of w19 - needs an account; w19's
   local config-builder behavior is covered by unit tests.

## Still Actionable

No current Codex inline review thread from the #95-#170 rescan remains
actionable after w1-w24 and the items above. The follow-up PR carrying
this audit also lands the post-review action items surfaced by
`/code review` against the three merged waves:

- Loader-level w11 regression test that exercises the real
  `_load_submission_validator_module` (the original test monkeypatched
  the loader and short-circuited the regression coverage).
- Pipeline-side wire-up of `plans_published` (Wave 2 added the field on
  the consumer side; without the producer side, the gate disabled the
  feature entirely).
- Routing-decision test for w9 (the original test calls the helper
  directly; this adds a test that drives `_load_table_csv` with
  empty-common-prefix shards).

## Blind-Spot Cross-Check

Open / actioned blind-spot files filed in the 2026-04-26 -> 2026-05-03
window (filtered via `awk`-bounded prefix listing per the updated Axis 2
template guidance from w22):

| Finding | Status | Audit disposition |
| --- | --- | --- |
| `2026-05-02-155448-validation-query-no-per-platform-override` | merged-to-todo | Folded into `write-primitives-architecture-fixes`. Out of scope for this Codex-thread sweep. |
| `2026-05-03-081920-uat-cross-scale-deliverable-not-guarded` | actioned | Convention question raised by PR #163; tracked in the TODO `deferred:` list. |
| `2026-05-04-120000-w11-cwd-validator-test-monkeypatches-loader` | open | Filed by the post-Wave-3 review; addressed in the follow-up PR alongside this audit. |
| `2026-05-04-120100-w1-pipeline-emitter-not-updated` | open | Filed by the post-Wave-3 review; addressed in the follow-up PR alongside this audit. |
| `2026-05-04-120200-w9-test-bypasses-routing-decision` | open | Filed by the post-Wave-3 review; addressed in the follow-up PR alongside this audit. |
| `2026-05-04-120300-rescan-audit-missing` | open | This file closes the finding. |
| `2026-05-04-120400-todo-not-moved-to-done` | open | Closed by the same follow-up PR (TODO moved to `_project/DONE/main/` with `status: Completed`). |

Notes:

- The conflict warnings logged at PR-open time (#179 vs #173, #183 vs
  #181) were verified to be heuristic false positives via `git
  merge-tree` - both produce clean trees with zero conflict markers.
- PR #173 (chore/codex-pr-review-fixes-todo) still references the
  pre-Wave-1 path `_project/TODO/main/planning/...` and needs a rebase
  before it can land; that is a separate operator action.
- No new TODO is created from this audit. The action items it records
  are bundled into the same follow-up PR.
