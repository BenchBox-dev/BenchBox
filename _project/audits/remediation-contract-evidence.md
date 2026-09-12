---
develop_sha: b221e852dba0ec2aa4bce79f15100fb909ff5599
measured_at_sha: c0b4ce94de3514939338c3e05457816e42356b7e
checked_sha: c0b4ce94de3514939338c3e05457816e42356b7e
---

# Remediation contract evidence

Per-instance record for the SCD2 N2 remediation class
(`docs/agent/pr-review-evidence.md` contract). All outcomes observed on the
`feat/pr-batch-process-improvements` tree; rerun the cited nodes to re-verify.

## Enumerated instances

SCD2 operations in `benchbox/core/write_primitives/catalog/operations.yaml`,
each with success, idempotency, and rejected-case coverage in
`tests/integration/test_write_primitives_duckdb.py::TestWritePrimitivesSCD2DuckDB`:

- `merge_scd_type2_basic`: `test_scd2_basic_executes_validates_and_cleans_up`,
  `test_basic_wrong_insert_count_fails_cardinality_bound` (rejected).
- `merge_scd_type2_no_change`: `test_scd2_no_change_is_idempotent`,
  `test_no_change_noop_against_missing_keys_fails_validation` (rejected),
  `test_no_change_companion_check_is_load_bearing` (control, below).
- `merge_scd_type2_new_keys_only`: `test_scd2_new_keys_only_inserts_without_closing`,
  `test_new_keys_only_no_rows_closed_scoped_to_new_keys`,
  `test_failing_validation_reports_validation_failed_not_success` (rejected).

SCD2 selection: 12 passed, 34 deselected
(`-k 'scd2 or no_change_noop_against_missing_keys or no_change_prior_behavior'`).

## Load-bearing control (N2)

Isolated fixture (in-memory DuckDB, real catalog SQL, no repo edits):
deleted dimension keys 21-40, applied the real `no_change` write SQL.

- `at_most_one_current_per_business_key`: 0 rows (passes vacuously).
- `no_rows_closed_by_batch`: 0 rows (passes vacuously).
- `no_new_versions_inserted`: 0 rows (passes vacuously).
- `every_unchanged_key_has_current_version_matching_hash`: 20 rows (fires).

Repo regression: `test_no_change_companion_check_is_load_bearing` asserts
exactly this split, so dropping the companion fails the suite. The prior
three-query set alone would report success on deleted input.

## Seam trace (producer to persistence to consumer)

- Producer/persistence: explorer pipeline
  (`tests/unit/scripts/explorer_pipeline/test_pipeline.py`), publication
  transaction and journal
  (`tests/unit/scripts/publication/test_transaction.py`,
  `tests/unit/scripts/publication/test_journal.py`): 97 passed.
- The SCD2 dimension is the persistence; validation queries are the
  contract; the checks above exercise the write-to-validation seam per op.

## Publication live-head receipt identity

The publication deployer accepts signed live receipts from both authorized
writers and compares their common receipt identity before a Pages write.

### Enumerated instances

- `Publication Control Plane Deployment`: the legacy writer's signed
  `receipt_id` is accepted when it matches the candidate's recorded parent.
- `Publication Transactions`: the transaction writer's signed `receipt_id` is
  accepted when it matches the candidate's recorded parent.

The contract is exercised by
`tests/unit/workflows/test_publication_rollback.py::test_deploy_revalidates_signed_receipt_identity_across_both_live_receipt_writers`.
The same test rejects the previous artifact-ID comparison and requires the
candidate-derived parent receipt output, so an empty dispatch input cannot
bypass the identity check.

### Seam trace (producer to persistence to consumer)

- Producers: the legacy deploy workflow and the publication transaction
  workflow create signed live receipts.
- Persistence: the publication journal stores the durable transaction's
  signed attestation, while candidate receipts retain its `receipt_id` as the
  parent identity.
- Consumer: the deploy-time `Revalidate authoritative live head` step selects
  a valid receipt from either producer and refuses the Pages write unless its
  signed `receipt_id` matches the candidate's recorded parent.
