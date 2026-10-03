# Development Loop Safety Property Ledger

Safety properties keep their guards until a replacement guard proves
coverage. No workflow, script, test, or hook listed here may be deleted by
a modernization change unless its row shows the property still covered or
classifies the file pure-process.

Classification values:

- `product-safety` — guards a user-facing correctness, data integrity,
  privacy, or release guarantee. Keep or port to the replacement loop.
- `pure-process` — guards internal branch, queue, or workflow mechanics
  with no product-safety content. May retire once its replacement is green.
- `tooling` — agent, tracker, or hygiene support. Keep.

## Safety properties

| Property | Current guard | Replacement guard | Proof | Status |
| --- | --- | --- | --- | --- |
| Correctness oracle: digest arming | `TestCorrectnessGateOracle` in `tests/unit/test_standardized_test_commands.py`, `correctness-gate` job in `.github/workflows/pr.yml` |ci.yml `core` | pending | open |
| Correctness oracle: query discrimination | `TestCorrectnessGateOracle` in `tests/unit/test_standardized_test_commands.py` | ci.yml `core` | pending | open |
| Correctness oracle: no-skip | `TestCorrectnessGateOracle` in `tests/unit/test_standardized_test_commands.py` | ci.yml `core` | pending | open |
| SQL self-binding lint | `_project/scripts/detect_self_binding.py` | ci.yml `tooling` | pending | open |
| Monotonic-clock policy (wall-clock part) | `_project/scripts/timing_policy_check.py`, `_project/scripts/timing_audit.py` | ci.yml `tooling` | pending | open |
| Submission validation | `scripts/validate_submission.py`, `.github/workflows/validate-submission.yml`, `.github/workflows/validate-submission-comment.yml`, `tests/unit/workflows/test_validate_submission_changed_bundles.py`, `tests/unit/workflows/test_validate_submission_comment_security.py`, `tests/unit/scripts/test_validate_submission*.py` | ci.yml `results-data` | pending | open |
| Corpus trust boundary | `tests/unit/workflows/test_corpus_trust_boundary.py`, `.github/workflows/sync-results-data-to-published.yml` | ci.yml `results-data` | pending | open |
| Artifact privacy (no private paths in published site) | `assemble_public_site.py` privacy scan step in `.github/workflows/docs.yml` build job, `tests/unit/scripts/test_corpus_privacy_invariant.py` | site-deploy pre-deploy gates | pending | open |
| Publication rollback and transactions | `.github/workflows/publication-transaction.yml`, `.github/workflows/publication-recover.yml`, `.github/workflows/publication-soak-monitor.yml`, `tests/unit/workflows/test_publication_transaction.py`, `tests/unit/workflows/test_publication_recover.py`, `tests/unit/workflows/test_publication_rollback.py` | site-deploy rollback with last-known-good validation | pending | open |
| Explorer snapshot and UI compatibility | `results-explorer/src/db.ts` read-model version gate, `tests/unit/scripts/test_results_explorer_snapshot_invariants.py` | ci.yml `explorer` | pending | open |
| Public-site visual acceptance | `Public-site visual acceptance` required check from `.github/workflows/docs.yml` | site-deploy route and digest probes | pending | open |
| Binary integrity (vendored engine hashes, dbgen framing) | `_binaries/` hashes, TPC-H binary framing tests | ci.yml `core` hash checks and required macOS/Windows dbgen framing; nightly-v2.yml matrix dbgen framing on all three OS at Python 3.12 | pending | open |
| Wheel installability | `package-smoke` job, release workflow build | release workflow artifact verification | pending | open |
| Shipped bundled generator integrity | `benchbox/_binaries/SHA256MANIFEST.json`, `tests/unit/utils/test_binary_manifest.py` | ci.yml `dist-artifact` verifies source, wheel, and sdist membership and hashes; installed-package verifier for release checks | pending | open |
| Dependency bounds | `scripts/check_dependency_bounds.py`, `tests/unit/scripts/test_check_dependency_bounds.py` | ci.yml `tooling` | pending | open |
| Release curation and readiness | `scripts/check_release_curation.py`, `tests/unit/scripts/test_check_release_curation.py`, `.github/workflows/validate-release-pr.yml`, `.github/workflows/release-canary.yml`, `scripts/release_flow.py`, `tests/unit/scripts/test_release_flow.py` | ci.yml always-required `ci-paths` selects release identity changes and checks them against the immutable event base; release workflow | pending | open |
| Ruleset and settings drift | `scripts/ruleset_drift_check.py`, `.github/workflows/develop-ruleset-drift.yml`, `tests/unit/workflows/test_develop_ruleset_drift.py`, `tests/unit/release/test_ruleset_drift_review_coverage.py`, `tests/unit/release/test_ruleset_review_enforcement.py` | ci.yml `tooling` | pending | open |
| Soundness-path owner hold | `_project/scripts/auto_merge_soundness_paths.py`, `tests/unit/test_auto_merge_soundness_paths.py`, `tests/unit/test_auto_merge_hold_is_durable.py` | ci.yml `tooling` soundness flag plus external adversarial review | pending | open |
| Workflow context validity | `tests/unit/workflows/test_workflow_expression_contexts.py` | ci.yml `tooling` | pending | open |
| merge_group triggers on required gates | `tests/unit/workflows/test_merge_group_triggers.py` | ci.yml (all six units report on merge_group) | pending | open |
| read_primitives cross-surface check | `_project/scripts/rp_scoped_check.py` | nightly T3 per-domain suites | pending | open |

## Known KEEP traps

These were misclassified as process in earlier plan revisions and must stay.
Each is `product-safety` or `tooling`, never `pure-process`:

- `_project/scripts/detect_self_binding.py`
- `_project/scripts/rp_scoped_check.py`
- `_project/scripts/timing_audit.py` and the wall-clock policy in
  `_project/scripts/timing_policy_check.py`
- `tests/unit/workflows/test_workflow_expression_contexts.py`
- `scripts/ruleset_drift_check.py`
- `scripts/validate_submission.py`

## File classification

### `.github/workflows/`

| File | Classification | Property or reason |
| --- | --- | --- |
| `auto-merge-on-open.yml` | pure-process | Auto-merge mechanics; replaced by merge queue |
| `corpus-drift-check.yml` | product-safety | Corpus drift detection |
| `corpus-event-bridge.yml` | product-safety | Corpus event integrity |
| `corpus-reconciler.yml` | product-safety | Corpus reconciliation |
| `cross-platform-validation.yml` | product-safety | Cross-platform correctness |
| `cross-surface-baseline-autodetect.yml` | tooling | Baseline maintenance support |
| `docker-integration.yml` | product-safety | Container integration coverage |
| `docs.yml` | product-safety | Public-site build, privacy scan, visual acceptance |
| `extension-smoke.yml` | product-safety | Extension smoke coverage |
| `gitignore-lint.yml` | tooling | Hygiene; standalone, not part of the ci.yml units |
| `lint.yml` | tooling | Lint gate |
| `nightly.yml` | product-safety | Scheduled validation; replaced by nightly T3; Windows legs, scheduled-workflow liveness and the Postgres throughput cell are non-blocking; ruleset drift runs as advisory |
| `nightly-v2.yml` | product-safety | Nightly T3: platform matrix, docker engines, cross-browser, extension, install, drift, external documentation links |
| `oracle-review.yml` | product-safety | Result-affecting changes need the Codex connector's review, whose identity is the only unforgeable review signal |
| `perf-smoke.yml` | product-safety | Performance smoke |
| `pricing-data-drift-check.yml` | product-safety | Pricing data integrity |
| `publication-canaries.yml` | product-safety | Publication canary protection |
| `publication-corpus-cutover.yml` | product-safety | Corpus cutover protection |
| `publication-deploy.yml` | product-safety | Publication deployment; replaced by site-deploy |
| `publication-preview-deploy.yml` | product-safety | Preview deployment; replaced by site-deploy |
| `publication-preview-soak.yml` | product-safety | Preview soak; replaced by site-deploy shadow |
| `publication-recover.yml` | product-safety | Publication recovery and rollback |
| `publication-soak-monitor.yml` | product-safety | Publication availability monitoring |
| `publication-transaction.yml` | product-safety | Publication transaction integrity |
| `rehearse-release-isolation.yml` | product-safety | Release isolation rehearsal |
| `release.yml` | product-safety | Release publishing |
| `release-canary.yml` | product-safety | Release canary protection |
| `seed-corpus.yml` | product-safety | Corpus seeding |
| `submission-validator-drift-check.yml` | product-safety | Submission validator sync |
| `sync-results-data-to-published.yml` | product-safety | Corpus trust boundary sync |
| `test.yml` | product-safety | Test tiers; replaced by ci.yml units |
| `todo-state-validate.yml` | tooling | Tracker state validation |
| `tpcds-staged-maturation.yml` | tooling | Weekly TPC-DS cross-surface maturation report |
| `trunk.yml` | product-safety | Post-merge fast lane, medium tier and correctness gate on develop |
| `upload-answers.yml` | product-safety | Answer file publication |
| `validate-release-pr.yml` | product-safety | Release PR base validation |
| `validate-submission.yml` | product-safety | Submission validation |
| `validate-submission-comment.yml` | product-safety | Submission validation comment |
| `tpcds-platform-identity.yml` | product-safety | Bundled TPC-DS generators agree across platforms (data checksums and dsqgen parameters) |

### `tests/unit/workflows/`

| File | Classification | Property or reason |
| --- | --- | --- |
| `test_binary_manifest_workflow.py` | product-safety | Queue artifact verifies source-bound bundled generator hashes before upload |
| `test_corpus_cutover.py` | product-safety | Corpus cutover |
| `test_corpus_event_bridge.py` | product-safety | Corpus event integrity |
| `test_corpus_trust_boundary.py` | product-safety | Corpus trust boundary |
| `test_docker_integration_workflow.py` | product-safety | Container integration |
| `test_docs_skip_marker.py` | pure-process | Docs skip mechanics |
| `test_nightly_t3_workflow.py` | product-safety | Nightly T3 domain coverage |
| `test_oracle_review_workflow.py` | product-safety | The required check name, triggers, read-only token and script invocation of the connector-review check |
| `test_t2_partition_workflow.py` | product-safety | Complete medium selection, correctness gate conservation, and binary framing placement |
| `test_public_site_visual_workflow.py` | product-safety | Visual acceptance |
| `test_trunk_workflow.py` | product-safety | Post-merge workflow triggers, per-ref queueing and read-only permissions |
| `test_publication_canaries.py` | product-safety | Publication canaries |
| `test_publication_preview.py` | product-safety | Preview deployment |
| `test_publication_recover.py` | product-safety | Publication recovery |
| `test_publication_rollback.py` | product-safety | Publication rollback |
| `test_publication_soak_monitor.py` | product-safety | Availability monitoring |
| `test_publication_transaction.py` | product-safety | Transaction integrity |
| `test_published_results_base_ci.py` | product-safety | Published corpus CI |
| `test_release_canary_shard_evidence.py` | product-safety | Release canary evidence |
| `test_release_isolation.py` | product-safety | Release isolation |
| `test_release_uat_charter_guard.py` | product-safety | Release charter guard |
| `test_results_explorer_dependency_audit.py` | product-safety | Explorer dependency audit |
| `test_results_explorer_publication.py` | product-safety | Explorer publication |
| `test_seed_corpus_pr_base.py` | product-safety | Corpus seeding |
| `test_stacked_pr_base_guard.py` | pure-process | Stacked-PR base mechanics |
| `test_validate_submission_changed_bundles.py` | product-safety | Submission validation |
| `test_validate_submission_comment_security.py` | product-safety | Submission comment security |
| `test_validate_submission_corpus_allowlist.py` | product-safety | Submission corpus allowlist |
| `test_validate_submission_fail_open.py` | product-safety | Submission fail-open behavior |
| `test_validate_submission_override_approval.py` | product-safety | Submission override approval |
| `test_validate_submission_trusted_checkout.py` | product-safety | Submission trusted checkout |
| `test_validate_submission_vendor_gate.py` | product-safety | Submission vendor gate |
| `test_validate_submission_workflow_guard_mirror.py` | product-safety | Submission workflow guard mirror |
| `test_workflow_context_availability.py` | product-safety | Workflow context availability (KEEP trap) |
| `test_workflow_expression_contexts.py` | product-safety | Workflow context validity (KEEP trap) |

### `tests/unit/scripts/` (complete)

| File | Classification |
| --- | --- |
| `test_agent_instruction_audit.py` | tooling |
| `test_assemble_public_site.py` | product-safety |
| `test_audit_sha_check.py` | product-safety |
| `test_batch_integration.py` | product-safety |
| `test_blind_spot_tools.py` | product-safety |
| `test_blog_content_validation.py` | product-safety |
| `test_branch_prune_merged.py` | pure-process |
| `test_browser_gate_aggregate.py` | product-safety |
| `test_build_joinorder_data.py` | product-safety |
| `test_check_complexity.py` | tooling |
| `test_check_dependency_bounds.py` | product-safety |
| `test_check_doc_relative_links.py` | tooling |
| `test_check_duplicate_code.py` | tooling |
| `test_check_makefile_inventory.py` | tooling |
| `test_check_project_references.py` | product-safety |
| `test_check_release_curation.py` | product-safety |
| `test_check_rerun_shard_retention.py` | tooling |
| `test_check_sqlglot_repro_retirement.py` | tooling |
| `test_check_submission_validator_sync.py` | product-safety |
| `test_check_uv_lock_revision.py` | tooling |
| `test_check_windows_antipatterns.py` | tooling |
| `test_comment_policy.py` | tooling |
| `test_comment_syntax_js.cjs` | tooling |
| `test_ci_lint_environment_boundary.py` | tooling |
| `test_comment_cleanup_scope.py` | tooling |
| `test_comment_parity.py` | tooling |
| `test_compile_all_platforms.py` | product-safety |
| `test_compose_joinorder_hero.py` | product-safety |
| `test_corpus_cohort_depth.py` | product-safety |
| `test_corpus_drift_canary.py` | product-safety |
| `test_corpus_privacy_invariant.py` | product-safety |
| `test_corpus_pseudonym_recovery.py` | product-safety |
| `test_dev_loop_pr_metrics.py` | pure-process |
| `test_ci_unit_result.py` | tooling |
| `test_ci_units.py` | tooling |
| `test_duckdb_datasketches_smoke.py` | product-safety |
| `test_duckdb_version_matrix.py` | product-safety |
| `test_e2e_specs_have_no_hardcoded_ids.py` | tooling |
| `test_explorer_build_contract.py` | product-safety |
| `test_explorer_receipt_ui_contract.py` | product-safety |
| `test_fast_lane_ceiling_check.py` | pure-process |
| `test_generate_changelog_entry.py` | product-safety |
| `test_heavy_tier_needed.py` | product-safety |
| `test_generate_corpus_inventory.py` | product-safety |
| `test_guard_messages.py` | tooling |
| `test_inline_applied_ledger_bounds.py` | product-safety |
| `test_local_validation.py` | pure-process |
| `test_migrate_clickhouse_labels.py` | product-safety |
| `test_mirror_partial_validation_policy.py` | pure-process |
| `test_oracle_review_check.py` | product-safety | Connector review decision for soundness-path changes |
| `test_path_filter_decision.py` | tooling |
| `test_phase2_metrics.py` | pure-process |
| `test_post_merge_signature.py` | pure-process |
| `test_pr_arm.py` | pure-process |
| `test_pr_ready_make.py` | pure-process |
| `test_pr_landing.py` | pure-process |
| `test_pytest_shard_evidence.py` | product-safety | Real serial and distributed test selection and execution conservation |
| `test_required_case_evidence.py` | product-safety | A required local-engine case that skips, is deselected, fails or is expected to fail fails the required-case check |
| `test_pr_refresh_certification.py` | pure-process |
| `test_pr_refresh_replay.py` | pure-process |
| `test_pr_review_followups.py` | pure-process |
| `test_reference_usage_audit.py` | tooling |
| `test_release_admitted_dist.py` | product-safety | Admitted directory matches its admission receipt, the tag and the commit before publication; only the verified wheel and sdist are staged |
| `test_release_artifact_consumer.py` | product-safety | Producer receipt, provenance selection and archive admission fail closed |
| `test_release_artifact_execution.py` | product-safety | Real tag objects, isolated verifier boundary, credential and Git configuration isolation, bounded download and no-replace publication |
| `test_release_cut_start.py` | product-safety |
| `test_release_finalize.py` | product-safety |
| `test_release_flow.py` | product-safety |
| `test_results_explorer_corpus_migrate.py` | product-safety |
| `test_results_explorer_cpu_attestation_backfill.py` | product-safety |
| `test_results_explorer_snapshot_invariants.py` | product-safety |
| `test_scan_explorer_stale_theme.py` | product-safety |
| `test_scan_explorer_tokens.py` | product-safety |
| `test_shrink_rollup.py` | pure-process |
| `test_skill_sync_ci_policy.py` | tooling |
| `test_sqlglot_generator.py` | product-safety |
| `test_sqlglot_generator_known_failures.py` | product-safety |
| `test_sqlite_extract_repro.py` | product-safety |
| `test_submission_workflow_waiver.py` | product-safety |
| `test_timing_policy_check.py` | product-safety |
| `test_todo_review_own_edit_freshness.py` | tooling |
| `test_todo_state_contract_check.py` | tooling |
| `test_todo_state_workflow.py` | tooling |
| `test_update_version.py` | product-safety |
| `test_validate_submission.py` | product-safety |
| `test_validate_submission_corpus_allowlist.py` | product-safety |
| `test_validate_submission_corpus_paths.py` | product-safety |
| `test_validate_submission_resource_heavy.py` | product-safety |
| `test_validate_submission_slim_fallback.py` | product-safety |
| `test_verify_mcp_conformance.py` | tooling |
| `test_worktree_audit.py` | tooling |
| `explorer_pipeline/test_cpu_hardware_identity.py` | product-safety |
| `explorer_pipeline/test_duckdb_browser_contract.py` | product-safety |
| `explorer_pipeline/test_duckdb_builder.py` | product-safety |
| `explorer_pipeline/test_duckdb_readonly_fuzz.py` | product-safety |
| `explorer_pipeline/test_duplicate_result_id.py` | product-safety |
| `explorer_pipeline/test_legacy_artifact_guard.py` | pure-process |
| `explorer_pipeline/test_measurement_basis.py` | product-safety |
| `explorer_pipeline/test_meta_leaderboard.py` | product-safety |
| `explorer_pipeline/test_normalized_cost_contract.py` | product-safety |
| `explorer_pipeline/test_override_display.py` | product-safety |
| `explorer_pipeline/test_pipeline.py` | pure-process |
| `explorer_pipeline/test_privacy_rejection.py` | product-safety |
| `explorer_pipeline/test_ranking.py` | product-safety |
| `explorer_pipeline/test_read_model_contract.py` | product-safety |
| `explorer_pipeline/test_result_id_contract.py` | product-safety |
| `explorer_pipeline/test_transformer.py` | pure-process |
| `explorer_pipeline/test_visible_metrics_registry.py` | product-safety |
| `publication/test_acquire_canary_evidence.py` | product-safety |
| `publication/test_artifacts.py` | product-safety |
| `publication/test_assembler.py` | product-safety |
| `publication/test_audit_mirror_prs.py` | product-safety |
| `publication/test_baseline.py` | product-safety |
| `publication/test_candidate.py` | product-safety |
| `publication/test_check_control_plane.py` | tooling |
| `publication/test_check_corpus_bijection.py` | product-safety |
| `publication/test_check_explorer_compat.py` | product-safety |
| `publication/test_check_pages_artifact_wiring.py` | product-safety |
| `publication/test_check_workflow_permissions.py` | tooling |
| `publication/test_db_digest.py` | product-safety |
| `publication/test_journal.py` | product-safety |
| `publication/test_ledger_seed.py` | product-safety |
| `publication/test_manifest.py` | product-safety |
| `publication/test_override_companion_exclusion.py` | product-safety |
| `publication/test_pages.py` | product-safety |
| `publication/test_plan_reconciliation.py` | product-safety |
| `publication/test_reconciler.py` | product-safety |
| `publication/test_reconciliation.py` | product-safety |
| `publication/test_transaction.py` | product-safety |
| `publication/test_transaction_executor.py` | product-safety |
| `publication/test_verify_corpus_promotion.py` | product-safety |
| `publication/test_verify_live.py` | product-safety |
| `test_tpcds_divergence_report.py` | tooling |
| `test_tpcds_platform_identity.py` | product-safety |

### `tests/unit/release/`

| File | Classification | Property or reason |
| --- | --- | --- |
| `test_changelog_tag_guard.py` | product-safety | Release tag integrity |
| `test_ruleset_drift_review_coverage.py` | product-safety | Ruleset drift |
| `test_ruleset_review_enforcement.py` | product-safety | Ruleset review enforcement |

### `tests/unit/test_auto_merge_*`

| File | Classification | Property or reason |
| --- | --- | --- |
| `test_auto_merge_soundness_paths.py` | product-safety | Soundness path manifest lockstep |

### `tests/unit/test_release_*`

| File | Classification | Property or reason |
| --- | --- | --- |
| `test_release_canary_incident.py` | product-safety | Release canary |
| `test_release_canary_sharding.py` | product-safety | Release canary sharding |
| `test_release_infrastructure.py` | product-safety | Release infrastructure |
| `test_release_readiness.py` | product-safety | Release readiness |

### `scripts/`

| File | Classification | Property or reason |
| --- | --- | --- |
| `validate_submission.py` | product-safety | Submission validation (KEEP trap) |
| `ruleset_drift_check.py` | product-safety | Ruleset drift (KEEP trap) |
| `check_dependency_bounds.py` | product-safety | Dependency bounds |
| `check_release_curation.py` | product-safety | Release curation |
| `assemble_public_site.py` | product-safety | Public-site assembly and privacy scan |
| `generate_landing_quickstarts.py` | product-safety | Landing quickstart generation |
| `check_doc_relative_links.py` | tooling | Docs hygiene |
| `check_duplicate_code.py` | tooling | Hygiene |
| `check_windows_antipatterns.py` | tooling | Hygiene |
| `path_filter_decision.py` | tooling | Path classifier shared with ci.yml units |
| `pytest_shard_evidence.py` | product-safety | Exact assigned, collected, and executed medium test evidence |
| `pr_landing.py` | pure-process | PR-loop mechanics |
| `pr_refresh_certification.py` | pure-process | Refresh mechanics |
| `pr_refresh_replay.py` | pure-process | Refresh mechanics |
| `post_merge_signature.py` | pure-process | Post-merge mechanics |
| `local_validation.py` | pure-process | PR-loop mechanics |
| `phase2_metrics.py` | pure-process | Legacy metrics mechanics |
| `bundled_binary_manifest.py` | product-safety | Deterministic hashes of the shipped generator tree |
| `verify_distribution_binaries.py` | product-safety | Distribution membership, archive safety, and source-bound generator hashes |
| Remaining scripts (ledger-catch-all: scripts/) | product-safety | Benchmark, corpus, and validation product code; reclassify individually before any deletion |
| `tpcds_divergence_report.py` | product-safety | Cause labels for DataFrame-versus-SQL divergences (report only, no verdict) |
| `tpcds_platform_identity.py` | product-safety | Cross-platform agreement of the bundled TPC-DS generators |

### `_project/scripts/`

| File | Classification | Property or reason |
| --- | --- | --- |
| `detect_self_binding.py` | product-safety | SQL self-binding lint (KEEP trap) |
| `rp_scoped_check.py` | product-safety | read_primitives cross-surface check (KEEP trap) |
| `timing_audit.py` | product-safety | Timing audit (KEEP trap) |
| `timing_policy_check.py` | product-safety | Monotonic-clock policy (KEEP trap) |
| `fast_lane_ceiling_check.py` | pure-process | Fast-lane marker and path guards; retires with the fast lane |
| `auto_merge_soundness_paths.py` | product-safety | Soundness path manifest |
| `oracle_review_check.py` | product-safety | Connector review check for soundness-path changes |
| `ruleset_review_enforcement.py` | product-safety | Ruleset review enforcement |
| `soundness_drain_report.py` | pure-process | Drain digest mechanics |
| `reference_usage_audit.py` | tooling | Reference hygiene |
| `agent_instruction_audit.py` | tooling | Agent instruction lockstep |
| `worktree_audit.py` | tooling | Worktree hygiene |
| `todo_state_contract_check.py` | tooling | Tracker state contract |
| `check_uv_lock_revision.py` | tooling | Lockfile hygiene |
| `pr_review_followups.py` | pure-process | PR-loop mechanics |
| `dev_loop_pr_metrics.py` | pure-process | Program baseline metrics mechanics |
| Remaining project scripts (ledger-catch-all: _project/scripts/) | product-safety | Sweep, corpus, and validation product code; reclassify individually before any deletion |

### `.pre-commit-config.yaml` hooks

| Hook | Classification | Property or reason |
| --- | --- | --- |
| `corpus-inventory` | product-safety | Corpus inventory integrity |
| `uv-lock-revision-guard` | tooling | Lockfile hygiene |
| `uat-loc-table` | tooling | UAT table hygiene |
| `timing-policy-check` | product-safety | Monotonic-clock policy |
| `comment-policy` | tooling | Comments, docstrings, parser coverage and completed-scope enforcement |
| `timing-policy-fast-lane` | pure-process | Fast-lane mechanics |
| `pr-preflight-fast-tests` | pure-process | PR-loop mechanics |
| `blind-spot-validate` | product-safety | Blind-spot coverage |
| `explorer-tokens` | product-safety | Explorer token integrity |
| `duplicate-code-warn` | tooling | Hygiene |
| `agent-instructions-check` | tooling | Agent instruction lockstep |
| `agent-write-preflight` | tooling | Worktree safety |
| `agent-git-identity` | tooling | Identity pinning |
| `agent-attribution-trailers` | tooling | Attribution hygiene |
| `ruff-check`, `ruff-format` | tooling | Lint and format |
| `codespell` | tooling | Spelling |
| Standard hooks (`check-yaml`, `end-of-file-fixer`, `trailing-whitespace`, `check-added-large-files`, `check-merge-conflict`, `detect-private-key`, `markdownlint`) | tooling | Standard hygiene |
