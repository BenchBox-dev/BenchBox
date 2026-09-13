---
develop_sha: 2eb03f3e67ec8f7f1347738f29696fa39ed5f526
measured_at_sha: 820130af9eb8afea998f8776bac1249a3a2be9d2
checked_sha: 820130af9eb8afea998f8776bac1249a3a2be9d2
---

# Remediation contract evidence

This record re-derives the accepted remediation claims from their source
instances. The exact test nodes and control outcomes below are the evidence;
the counts are only a replay summary.

## SCD2 validation

The source of truth is the SCD2 operation set in
`benchbox/core/write_primitives/catalog/operations.yaml`. Every operation has
an intended case and a rejected case in
`tests/integration/test_write_primitives_duckdb.py::TestWritePrimitivesSCD2DuckDB`:

- `merge_scd_type2_basic`: `test_scd2_basic_executes_validates_and_cleans_up`
  succeeds; `test_basic_wrong_insert_count_fails_cardinality_bound` rejects an
  under-inserted write.
- `merge_scd_type2_no_change`: `test_scd2_no_change_is_idempotent` succeeds;
  `test_no_change_noop_against_missing_keys_fails_validation` rejects a no-op
  with deleted unchanged keys. `test_no_change_companion_check_is_load_bearing`
  is the vacuity control.
- `merge_scd_type2_new_keys_only`:
  `test_scd2_new_keys_only_inserts_without_closing` succeeds;
  `test_failing_validation_reports_validation_failed_not_success` rejects a
  duplicate current version. `test_new_keys_only_no_rows_closed_scoped_to_new_keys`
  is the cross-operation scope control.

The isolated N2 control deletes unchanged keys 21-40 and applies the real
`merge_scd_type2_no_change` write SQL. The three old offending queries return
zero rows, while `every_unchanged_key_has_current_version_matching_hash`
returns 20 rows. The old query set therefore passes vacuously; the positive
companion rejects the missing persistence state. The SCD2 selection replay
passed 13 tests.

Producer-to-persistence-to-consumer trace: the staging tables and operation
write SQL produce the dimension rows; `scd2_ops_dim_customer` is the
persistence; validation queries and `OperationResult` consume the rows. The
successful, rejected, repeatability, and companion-control nodes exercise that
write-to-validation seam for all three operations.

## Cohort ranking and read-model persistence

The source of truth is `_build_benchmark_summaries` in
`_project/scripts/explorer_pipeline/pipeline.py`, with persisted consumers in
`results`, `benchmark_rankings`, `cohort_metadata`, and
`result_detail_metrics`:

- `test_mismatched_query_sets_are_not_ranked` rejects a cohort whose three
  members have query sets of 197, 206, and 220 IDs; the exclusion is persisted
  as `mismatched_query_set` and every member is ineligible.
- `test_non_rankable_query_gap_does_not_exclude_rankable_peers` rejects the
  incomplete member with `missing_primary_metric` while two complete peers
  remain eligible.
- `test_partial_query_set_does_not_poison_complete_majority` rejects the
  partial member with `mismatched_query_set` while the complete majority stays
  eligible.
- `test_partial_query_set_exclusion_reaches_every_read_model_consumer` runs
  the producer through the real pipeline and verifies the partial member's
  exclusion and ineligibility in all four persisted consumers; the two
  complete peers remain eligible in `benchmark_rankings`.

Producer-to-persistence-to-consumer trace: result bundles produce
`ManifestEntry` and `DetailResult`; `DuckDBSnapshotBuilder` persists the
cohort and result rows; the explorer's result, ranking, cohort-metadata, and
detail views consume those rows. The end-to-end partial fixture is the seam
control for the prior failure mode where a partial input could leave the
downstream read model incomplete or poison peer rankings.

## Publication receipt and journal reconciliation

The authorized receipt producers are the legacy publication workflow and the
publication-transaction workflow. Their durable attestation is stored in the
publication journal; the deploy-time reconciliation consumer compares the
signed receipt identity with the candidate's recorded parent before a Pages
write. The cross-writer contract is exercised by
`tests/unit/workflows/test_publication_rollback.py::test_deploy_revalidates_signed_receipt_identity_across_both_live_receipt_writers`.

The allowed publication seam replay covers both successful and rejected
paths:

- `test_recovery_required_reconciles_forward_to_durable` accepts a successful
  provider observation and commits the durable transaction.
- `test_recovery_reconciliation_requires_succeed_status`,
  `test_recovery_reconciliation_rejects_mismatched_deployment_id`,
  `test_recovery_reconciliation_rejects_missing_deployment_id`,
  `test_recovery_reconciliation_requires_controller_workflow_sha`, and
  `test_recovery_reconciliation_rejects_pre_send_failure` reject mismatched,
  incomplete, stale, or pre-send evidence.
- `test_cas_conflict_detection` rejects a writer using an old journal parent;
  `test_ambiguous_push_failure_reconciles_remote_success` and
  `test_timeout_resolution` distinguish an unknown push outcome from a
  confirmed remote journal head; `test_corrupt_journal_fails_closed` rejects
  missing or invalid persistence state.

The prescribed pipeline and publication seam replay passed 109 tests
the end-to-end cohort consumer control was added. Re-run the cited nodes after
any source or consumer change; a passing aggregate count is not acceptance of
the collective claim.
