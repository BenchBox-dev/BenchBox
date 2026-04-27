# CI Validation Workflow — End-to-End Evidence

**Date**: 2026-04-27
**Workflow**: `.github/workflows/validate-submission.yml`
**Result**: workflow trigger + PR comment rendering proven; **a real bug
in the hash-validation algorithm was surfaced and filed for follow-up**
(`fix-submission-hash-mismatch-vs-validator-directory-scope`).

This file is the verification artifact for the
[`verify-ci-validation-workflow-end-to-end`][todo] TODO.

[todo]: ../DONE/main/planning/verify-ci-validation-workflow-end-to-end.yaml

## Setup

1. Created `published-results` branch on origin from `main` (the
   workflow's required base branch did not previously exist on the
   remote). Created via:
   `git push origin origin/main:refs/heads/published-results`.
2. Generated a small bundle locally:
   `benchbox run --platform duckdb --benchmark tpch --scale 0.01
   --queries 1,6` (note: the TODO's example used `Q1,Q6` which the
   current CLI rejects; numeric IDs are required).
3. Packaged via `benchbox submit --last --output /tmp/submission-test`.
   Manifest bundle_hash:
   `e5821554c491fd52e48474ba5dd1cd64d7482d02f400329455edffb47cecbd10`.

## Test cases

Three test PRs were opened against `published-results`. All were
**closed without merging** after evidence capture.

### Test 1 — Happy path (PR #27)

- **Branch**: `test/ci-validation-happy-path`
- **Bundle**: unmodified, copied directly from the `benchbox submit`
  output directory.
- **Expected**: workflow accepts; corpus inventory check passes.
- **Actual**: workflow **fails** with a hash mismatch (manifest says
  `e5821554c491fd52...`, computed `b3ab95bc332e1fcc...`).

This was unexpected — the bundle was untouched. The mismatch is the
**major bug** (see "Defects observed" below).

### Test 2 — Tampered bundle (PR #28)

- **Branch**: `test/ci-validation-hash-mismatch`
- **Bundle**: `queries[0].ms` changed from `22` → `22.001` after the
  manifest hash was computed.
- **Expected**: workflow rejects with a hash mismatch error citing the
  offending file path.
- **Actual**: workflow fails as expected. Comment:

  > `tpch_sf001_duckdb_sql_20260427_192436_a64d36db.json`
  > ERROR: Bundle hash mismatch: manifest says
  > `e5821554c491fd52...`, computed `a893c408f46cc17b...`

  The error is clear, names the file, and gives 16-char prefixes for
  both hashes.

### Test 3 — Schema-invalid bundle (PR #29)

- **Branch**: `test/ci-validation-schema-fail`
- **Bundle**: `summary` (a required schema-v2 top-level key) deleted.
- **Expected**: workflow rejects with a schema validation error.
- **Actual**: workflow fails as expected. Comment:

  > `tpch_sf001_duckdb_sql_20260427_192436_a64d36db.json`
  > ERROR: Missing required top-level keys: ['summary']
  > ERROR: Bundle hash mismatch: manifest says
  > `e5821554c491fd52...`, computed `fc9d9ea6a710925b...`

  Both errors render. The schema error names the missing key. The hash
  mismatch is the same bug as Test 1 + Test 2's tampering combined.

## Workflow capabilities verified

| Capability                                     | Status | Evidence                                    |
|------------------------------------------------|--------|---------------------------------------------|
| Trigger filter (`paths: results-data/bundles/**` on PRs to `published-results`) | OK | All 3 PRs auto-triggered the workflow without manual dispatch. |
| PR-comment creation                            | OK     | All 3 comments rendered with the same markdown structure. |
| PR-comment update (idempotent)                 | not exercised | Did not push a second commit per PR. Filing as a follow-up gap; cheap to test. |
| Hash mismatch error rendering                  | OK     | All 3 PRs cite manifest vs computed hash with file path. |
| Schema validation error rendering              | OK     | PR #29 lists the missing key explicitly. |
| Corpus inventory check                         | not reached | Workflow fails at the validate step before the inventory check runs. |
| Fork PR permissions                            | not exercised | Maintainer-only PRs in this round; filing as a follow-up. |

## Defects observed

### D1 — Submission hash algorithm mismatch (high severity)

**Symptom**: Even an untouched bundle produced by `benchbox submit
--last` fails the validator with a hash mismatch.

**Root cause**: The two implementations of the hash-over-bundle
algorithm disagree on what "bundle" means:

- `benchbox/cli/commands/submit.py:_compute_bundle_hash` runs over
  `output_path/bundle/`, which contains only the new submission's
  files. Manifest written with this hash.
- `scripts/validate_submission.py:_validate_manifest_hash` runs over
  `bundle_path.parent`, where `bundle_path` is the changed file under
  `results-data/bundles/`. That parent already contains every other
  bundle in the corpus.

So the submitter hashes one file, the validator hashes ~13. They can
never match.

**Filed as**:
`_project/TODO/main/planning/fix-submission-hash-mismatch-vs-validator-directory-scope.yaml`.

**Impact**: every Phase 2 PR submission fails CI today regardless of
content. Phase 2 is not actually shippable until this is fixed.

### D2 — Documented `--queries Q1,Q6` syntax does not work

The TODO's w1 notes used `--queries Q1,Q6`. The current CLI requires
numeric IDs (`--queries 1,6`); the `Q`-prefixed form fails with an
`int()` parse error. Minor doc bug.

**Filed as**: not filing a separate TODO; trivial fix when someone
updates the CLI help text. Logged here as a finding.

### D3 — Workflow's `actions/setup-python@v5` step appears unused

The workflow installs Python 3.11 explicitly, but `astral-sh/setup-uv`
above it already provides Python via `uv`. Looking at the validate
step output, `uv run` resolves to the uv-managed interpreter, not the
setup-python one. Harmless but adds ~5s to the run.

**Filed as**: not filing a separate TODO; cleanup candidate when
anyone touches the workflow.

## Closure

PRs #27, #28, #29 closed without merging. The `test/*` branches on
origin can be deleted at maintainer discretion; they're useful as
historical evidence until the validator bug (D1) is fixed.

The `published-results` branch on origin is now established and
ready for legitimate community submissions once D1 lands.

## What this TODO is NOT closing

- **Fork-PR permissions test (w4)**: requires a fork or throwaway
  account and was not exercised. Logged as a coverage gap.
- **PR-comment update idempotency (w2 step 5)**: not exercised.
- **Validator hash bug (D1)**: filed for follow-up; not fixed in this
  task (per the TODO's own anti_pattern: "DO NOT modify the validation
  workflow or validator script during this task — file follow-up
  TODOs for any fixes needed").
