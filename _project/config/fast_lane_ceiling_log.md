# Fast-lane ceiling bump log

Append-only history of every `max_fast_tests` change in
`_project/config/fast_test_lane_policy.json`. This file replaced that
JSON's `_ceiling_note` field (a single-line prose string that had grown to
~9.8KB and made every bump a diff on the same value) -- see
`fast-lane-decouple-ceiling-contention-2` and
`docs/operations/fast-lane-budget.md` for why.

**File semantics**: append-only, `merge=union` in `.gitattributes` (see
that file) -- two branches that each add a dated entry compose cleanly on
merge instead of conflicting on adjacent lines the way the old single JSON
string field did. Never edit or delete a historical entry; if a bump turns
out to have been wrong, add a new dated entry correcting it (a ratchet-down
entry, a superseded-by note, etc.) rather than rewriting history.

**Bump convention (in effect starting with the 2026-07-24 entry below;
entries above it are the pre-convention history, reflowed verbatim from the
old `_ceiling_note` field into one dated bullet per bump -- mechanical
reflow, not a rewrite)**:

- Quantum: bump `max_fast_tests` by **+500** at a time (round up to the next
  quantum if a single +500 step would not clear the headroom floor below).
- Resulting headroom (`max_fast_tests` minus the collected count that
  triggered the bump) must be **>= 250** after the bump. Never bump with
  minimal headroom again -- see the 2026-07-24 entry and
  `fast-lane-decouple-ceiling-contention-2` for the incident history (~30
  minimal-headroom bumps since April, two multi-PR hand-composed episodes,
  and a develop-red incident, #1281, from three PRs composing over the cap
  in one merge queue) that this convention exists to end.
- One dated entry per bump, appended below the last entry -- never edited
  in place.
- `_project/scripts/timing_policy_check.py`'s fast-lane check prints a
  `FAST_LANE_WARNING` when headroom drops below 100, referencing this file
  and the +500 quantum. That warning does not fail the build by itself; the
  absolute `max_fast_tests` ceiling remains the actual backstop everywhere
  it's enforced (`--strict`, `make ci-lint`, `develop-post-merge.yml`).
- The nightly `fast_lane_ratchet_check.py` signal (see
  `docs/operations/fast-lane-budget.md`) auto-files/updates a tracking
  issue when headroom drops below the same 100 threshold, so a bump becomes
  visible before the next test-adding PR collides with the ceiling -- it
  never opens or pushes a PR itself; a ceiling bump is still always a
  deliberate human/agent-authored PR.

## History

- 2026-04-13: Bumped 13200 -> 22000 on 2026-04-13 to reflect grown fast-lane (20,184 collected).
- 2026-05-10: Bumped 22000 -> 22100 on 2026-05-10 for joinorder-canonical-foundation Phase-1 (data_fetch + scale-factor + surface-field tests; 22038 collected).
- 2026-05-11: Bumped 22100 -> 22400 on 2026-05-11 for joinorder-canonical-cutover canonical SQL/DataFrame, MCP, publishing, and corpus-inventory guards; 22317 collected.
- 2026-05-13: Bumped 22400 -> 22500 on 2026-05-13 for UAT enabled-platform remediation coverage; pr-preflight collected 22419.
- 2026-05-15: Bumped 22500 -> 22510 on 2026-05-15 after rebasing onto develop at 36ab01058; pr-preflight collected 22501 before this branch's new public theme contract tests, which are medium-marked to avoid fast-lane growth.
- 2026-05-14: Bumped 22510 -> 22530 on 2026-05-14 for pr-review-followup batch coverage (joinorder dataframe family, pg_mooncake adapter, landing quickstart validation, explorer read-model retry); pr-preflight collected 22520.
- 2026-05-15: Bumped 22530 -> 22540 on 2026-05-15 for results-explorer-post-theme-reconcile count-aware Home/script coverage; CI collected 22537.
- 2026-05-16: Bumped 22540 -> 22543 on 2026-05-16 for pr-review-followups coverage on UAT CLI dispatch, UAT release-gate envelope scoping, and develop-post-merge orphan ordering; ci-lint collected 22543.
- 2026-05-16: Bumped 22543 -> 22550 on 2026-05-16 for prompts landing Phase 1 CLI hygiene validator/prompt-shape coverage; pr-preflight collected 22550.
- 2026-05-16: Bumped 22550 -> 22553 on 2026-05-16 for prompts landing Phase 2 cost-class and registry prompt-safety coverage; timing policy collected 22553.
- 2026-05-16: Bumped 22553 -> 22558 on 2026-05-16 for prompts landing Phase 3 platform-option and TPC-DS dsdgen validator coverage; timing_policy_check collected 22558.
- 2026-05-16: Bumped 22558 -> 22561 on 2026-05-16 for prompts landing Phase 4 provenance template and capture-plan footer coverage; timing_policy_check collected 22561.
- 2026-05-16: Bumped 22561 -> 22563 on 2026-05-16 for prompts landing review fixes covering MCP cost-gating parity and compare summary discipline; targeted lane count increased by two fast tests.
- 2026-05-16: Bumped 22563 -> 22568 on 2026-05-16 for prompts landing Phase 5 MCP parity prompt-surface coverage; timing_policy_check collected 22568.
- 2026-05-16: Bumped 22568 -> 22570 on 2026-05-16 for prompts landing MCP real-tool parity and platform-option gap follow-up coverage; timing_policy_check collected 22570.
- 2026-05-19: Bumped 22570 -> 22572 on 2026-05-19 for pr-review-followups prompt regressions covering credential-before-smoke ordering and smoke-scale dsdgen warning behavior; timing_policy_check collected 22572.
- 2026-05-19: Set 22572 -> 25000 on 2026-05-19 by maintainer direction during pr-review-followups cleanup. Ratchet down if the lane contracts; never raise without justification.
- 2026-07-16: Bumped 25000 -> 25050 on 2026-07-16 for tuning-mode-vocabulary-and-facet-implementation-20260712 (ADR-2 canonical_mode/tuned-fallback/official-refusal coverage, the PACKAGED_RESOURCE composition pin added when merging develop's #1188 packaged-template tier, and the physical_mechanisms unknown-vs-empty ingest-pipeline regression tests); develop alone collected 24995, this branch's merge collected 25022.
- 2026-07-17: Bumped 25050 -> 25060 on 2026-07-17 for tuning-capability-registry-coverage-20260716 (alias-resolution invariant tests and derived generator-coverage drift guards for the 9 newly-registered platforms); CI collected 25052 on the merge ref.
- 2026-07-17: Bumped 25060 -> 25080 on 2026-07-17 composing #1198's registry-coverage guards with #1176's provenance/hash export coverage (test_tuning_provenance_export.py + test_requested_config_hash.py); both branches independently bumped from 25050 (#1198: 25052 collected; #1176 pre-compose: 25062 collected); composed merge tree collects 25077.
- 2026-07-17: Bumped 25080 -> 25140 on 2026-07-17 for tuning-from-config-forwarding-sweep-20260716 (test_tuning_config_forwarding.py's registry-driven parametrized test, one case per registered platform adapter, verifying from_config forwards tuning_enabled/tuning_config/unified_tuning_configuration/tuning_source/tuning_source_file); timing_policy_check collected 25128.
- 2026-07-18: Bumped 25140 -> 25180 on 2026-07-18 for the todo-db-tracker local-SQLite spike (tests/unit/scripts/test_todo_db.py: 49 fast unit tests covering the enforced lifecycle invariants, archive import, and concurrency guards); develop collected 25128, this branch collects 25177.
- 2026-07-18: Bumped 25180 -> 25190 on 2026-07-18 composing the todo-db spike branch with develop's post-25128 growth: the branch alone collects 25177 (49 fast tracker tests; the 11 wrapper tests are medium-marked and collect 0 under -m fast), but the PR merge ref collects 25187.
- 2026-07-18: Bumped 25190 -> 25220 on 2026-07-18 for the post-CODEOWNERS-retirement merge queue, composed once so the queued branches carry byte-identical policy content instead of five conflicting bumps (#1142 seed-validation exclusion coverage +10; #1116 bot-finding sweep regressions +4; #1202 capability-registry/report regressions ~+8; #1206 object-schema loader regressions ~+5; #1114 branch-rename test moves +0): develop alone collects 25187; the queue's final merge ref is expected to collect ~25214.
- 2026-07-19: Bumped 25220 -> 25245 on 2026-07-19 for the UAT-hardening batch tail, composed once so #1228 (uat-throughput-result-resolution-hardening: multi-token benchmark-prefix matching + pg_duckdb/duckdb collision + scale-factor filter + equal-mtime determinism + runner scale-threading regression tests) and #1229 (uat-operator-provisioning: release-gate driver import-probe + BENCHBOX_OUTPUT_DIR output-root precedence + provenance-based default-detection tests) carry byte-identical policy content instead of two conflicting bumps: #1228 merge ref collects 25225, #1229 merge ref collects 25227, and the composed develop tree (both landed) collects <=25238 (develop alone ~25214-25220 plus the two branches' ~5 and ~7 disjoint fast tests).
- 2026-07-19: Bumped 25245 -> 25250 on 2026-07-19 for nightly-throughput-gate-restoration (T8): 10 strict per-stream-success unit tests brought the lane to exactly the 25245 ceiling; +5 restores minimal working headroom for the active merge queue (branch collects 25245).
- 2026-07-19: Bumped 25250 -> 25350 on 2026-07-19 for uat-config-schema-spec-realignment (T11): w1 load-time enforcement tests (phases order/duplicate rejection, scales rungs/override mutual-exclusivity + bool rejection, phases_arg/output-template type checks, package terminal-state vocab/service-required checks gated on phase membership), w2 missing_platforms_from_include unit tests + enumerate registry-accounting coverage, w3's 32-config corpus-runnability guard (parametrized, incl. generated-rerun-shards/), and w4's 15-config lifecycle-header guard together brought the fast lane to 25317 collected; +33 restores minimal working headroom for the active merge queue.
- 2026-07-22: Bumped 25350 -> 25410 on 2026-07-22 for tuning-applied-ledger-and-validation-status-20260712 (w5 applied-ledger coverage: test_applied_ledger.py status-derivation/hash-determinism/dropped-intent/recording-connection-harness incl. readback-not-recorded filter, test_applied_ledger_export.py factory->result->loader companion round-trip incl. anonymized `.applied.json` statement/error redaction, test_builder.py ledger-field survival, plus the rewritten vocabulary/requested-vs-applied/provenance-export tests); this branch collects 25380, +30 restores minimal working headroom.
- 2026-07-22: Bumped 25410 -> 25430 on 2026-07-22 for tuning-starrocks-ddl-generator-20260716 (StarRocksDDLGenerator unit tests test_starrocks_ddl_generator.py + snapshot/parity + applied-ledger-instrumentation tests test_renderer_snapshot_starrocks.py; net-zero registry/drift edits) composed on #1-merged develop (which carries the 25410 ceiling); this branch collects 25411, +19 restores minimal working headroom.
- 2026-07-22: Bumped 25430 -> 25480 on 2026-07-22 for tuning-introspection-receipts-20260716 (post-load introspection receipt coverage: test_introspection.py corroborate/classification/trust-rule, test_duckdb_introspection.py incl. adapter-upgrades-to-verified-only-via-corroboration + mismatch/absent/introspection-failure, test_clickhouse_introspection.py, test_applied_receipt_export.py companion round-trip) composed on develop-with-#1/#2/#3 (cap 25430); this branch collects 25461, +19 restores minimal working headroom.
- 2026-07-22: Bumped 25480 -> 25500 on 2026-07-22 for tuning-df-ledger-parity-20260716 (DataFrame applied-ledger parity: test_tuning_ledger_parity.py polars/pandas runtime-setting + write-layout recording + noop/status, test_dataframe_applied_ledger_export.py companion export, test_data_loader.py applied_write_layout, +1 DF-bundle explorer ingest) composed on develop-with-#4 (cap 25480 after #1268 merged); this branch collects 25436, merge ref ~25484, +16 headroom.
- 2026-07-22: Bumped 25500 -> 25520 on 2026-07-22 for tuning-policy-generation-seam-20260716 (#1270, policy-generation marker export/ingest + cross-generation-warning tests) composed on develop-with-#5 (cap 25500 after #1269 merged); merge ref collects ~25506, +14 headroom. findings-domain-phase1-capture-redirect (#1271) added 10 fast unit tests in test_blind_spot_tools.py (optional capture-field validation + --drafts-dir mode + inverted-line-range rejection) but needed NO cap bump after merging develop-with-#1269/#1270: the merged tree collects 25505, within the existing 25520 ceiling (+15 headroom). The branch's earlier standalone 25480->25500 bump is superseded by develop's higher cap.
- 2026-07-23: Bumped 25520 -> 25545 on 2026-07-23 for tuning-drift-validation-bundle-routing (#1277): CI's fast-lane collect reached 25523 (the branch's drift-routing tests; the author's local run undercounted at 25515, so the PR shipped without a bump and lint failed FAST_LANE_VIOLATION), and this review follow-up adds one more fast regression test (reused-DB drift-reset survival in test_adapter_lifecycle.py) -> ~25524; +21 restores working headroom.
- 2026-07-24: Bumped 25545 -> 26050 on 2026-07-24 (+505) for fast-lane-decouple-ceiling-contention-2. This is the FIRST bump under the new quantum convention (see the header above), replacing the minimal-headroom pattern every entry above this one followed: develop currently collects ~25543 against the old 25545 ceiling (<5 headroom, the same contention pattern that produced the develop-red incident #1281 and forced this very batch to medium-mark two tests to dodge the cap). The new ceiling restores ~507 headroom (26050 - 25543) -- comfortably above the new 250 floor -- and this bump carries no test-count change of its own (structural-only PR: log split, quantum warning, develop-count persistence, PR-lane delta guard, nightly ratchet signal). Future bumps should look like this one: +500 quantum, headroom >= 250, one entry, no hand-composed multi-PR bumps.
- 2026-07-29: NO bump needed for explorer-applied-receipt-drilldown (#1343). The branch adds 10 fast tests (8 transformer tests for the `{stem}.applied.json` receipt ingest -- verbatim/canonical-serialization/absent/malformed/no-receipt-key/null-receipt/non-object/unreadable -- plus 2 pipeline discovery-filter regressions) and originally carried its own 26050 -> 26550 bump. #1342 landed the same 26550 ceiling on develop first, so that bump is superseded: the merged tree collects 26012 against the 26550 ceiling (+538 headroom, above the 250 floor). Recorded rather than dropped because the duplicate-bump pattern is the thing the quantum convention exists to prevent.
- 2026-07-29: Bumped 26050 -> 26550 on 2026-07-29 (+500) for the recurring FAST_LANE_WARNING on develop: at develop tip fe2c1b83d `timing_policy_check.py --strict` collects 26015 against the 26050 ceiling -- headroom 35, i.e. the next test-adding PR of any size trips FAST_LANE_VIOLATION in CI's lint job. (An older develop checkout at efcf8544f collected 25972/headroom 78, so the lane grew ~43 tests across the intervening merge queue; the tip figure is the one that governs.) This is the second bump under the quantum convention and, like the 2026-07-24 entry, carries no test-count change of its own -- it is a standalone ceiling PR, deliberately not folded into any test-adding branch (the 2026-07-29 nightly-Windows batch, #1330/#1332, shipped without bumping precisely so the ceiling stayed a separate, reviewable decision). New headroom 535 (26550 - 26015), above the 250 floor.
