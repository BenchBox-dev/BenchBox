# Independent publication A0 and A1 tracker completion evidence and immutability decision

**Status:** Accepted
**Date:** 2026-09-01
**Tracker:** `independent-publication-a0-a1-tracker-record-correction`
**Incident / Review Context:** Adversarial review of CI-efficiency batch & independent publication milestones

---

## 1. Context and Problem Statement

During adversarial review of the independent publication milestone records in the project TODO database, discrepancies were noted in the completion metadata of two foundational items:

1. `independent-publication-a0-baseline-and-freeze`: Recorded in `todo-db` as `state: done` with `completed_at: 2026-08-31T21:02:53Z` and `completed_pr: null`.
2. `independent-publication-a1-authority-and-threat-contract`: Recorded in `todo-db` as `state: done` with `completed_at: 2026-08-31T22:35:40Z` and `completed_pr: 1987`. At the time of initial review, PR #1987 was in open status.

This decision record investigates the root causes, evaluates repository and tracker invariants, and ratifies the authoritative reconciliation.

---

## 2. Factual Evidence and PR Provenance

### A0: Baseline and Migration Freeze (`independent-publication-a0-baseline-and-freeze`)

* **Live Tracker Record:**
  * `state`: `done`
  * `completed_at`: `2026-08-31T21:02:53Z`
  * `completed_pr`: `null`
* **Shipping Pull Request:** [PR #1984](https://github.com/benchbox-dev/BenchBox/pull/1984) (`feat/publication a0 baseline`)
  * Head branch: `feat/publication-a0-baseline`
  * Merge commit: `171a665fb40539aa827b5f93ea9866d929426f43`
  * Merged at: `2026-08-31T22:04:03Z`
  * Merged into: `develop`
* **Shipped Deliverables:**
  * `_project/decisions/independent-publication-a0-freeze-2026-08-31.md`
  * `docs/operations/publication-baseline-2026-08-31.json`
  * `docs/operations/independent-publication-baseline.md`
  * `scripts/publication/capture_baseline.py`
  * `tests/unit/scripts/publication/test_baseline.py`
* **Root Cause Analysis:**
  The item was marked `done` during final verification (~1 hour before PR squash-merge) without `--pr 1984` passed to the CLI.

---

### A1: Ratify Publication Authorities (`independent-publication-a1-authority-and-threat-contract`)

* **Live Tracker Record:**
  * `state`: `done`
  * `completed_at`: `2026-08-31T22:35:40Z`
  * `completed_pr`: `1987`
* **Shipping Pull Request:** [PR #1987](https://github.com/benchbox-dev/BenchBox/pull/1987) (`docs/publication a1 authority contract`)
  * Head branch: `docs/publication-a1-authority-contract`
  * Merge commit: `7f26fc181efcb8dcbccf74577823f6c5e20eb47d`
  * Merged at: `2026-09-01T03:03:40Z`
  * Merged into: `develop`
* **Shipped Deliverables:**
  * `docs/development/adr/adr-independent-publication-authorities.md`
  * `docs/development/independent-publication-threat-model.md`
  * `docs/operations/independent-publication-contract.md`
  * `docs/reference/hosted-results-contract.md`
  * `scripts/check_decision_records.py`
  * `tests/unit/docs/test_publication_architecture.py`
* **Status Resolution:**
  PR #1987 merged cleanly into `develop`. The tracker pointer `completed_pr: 1987` is factually correct and refers to the true shipping PR.

---

## 3. Tracker State Machine and Invariants

1. **Terminal State Immutability:**
   In `todo_db.tracker.TRANSITIONS`, allowed lifecycle transitions are strictly:
   * `planning -> active`
   * `active -> done`
   * `planning -> dropped`
   * `active -> dropped`
   There is no legal transition out of `done`. `done` is an immutable terminal state.

2. **Audit Event Integrity:**
   The tracker maintains a cryptographic `sha256-chain-v2` append-only audit event log in the database. Out-of-band SQL modifications directly against the `items` table break the invariant that the CLI is the sole write path.

3. **CLI Mutation Surface:**
   The `todo update` command intentionally restricts edits on `done` items to descriptive fields (with explicit `--reason`), and does not provide an interface for rewriting historical completion pointers.

---

## 4. Decision and Policy

1. **Preserve Historical Immutability (No Database Hacks):**
   No raw SQL queries or retroactive synthetic audit events shall be executed against the hosted database. The live database state for A0 (`completed_pr: null`) and A1 (`completed_pr: 1987`) remains untouched.

2. **Authoritative Citation Binding:**
   This decision document serves as the authoritative, permanent cross-reference reconciling tracker records to GitHub pull requests:
   * `independent-publication-a0-baseline-and-freeze` is permanently bound to **PR #1984** (`171a665fb`).
   * `independent-publication-a1-authority-and-threat-contract` is ratified as shipped in **PR #1987** (`7f26fc181`).

3. **Post-Merge Completion Operational Invariant:**
   For all remaining publication tasks (`A3` through `A11`), agents and maintainers must strictly sequence tracker completion **after** PR merge:
   * `todo complete <id> --pr <PR_NUMBER>` must only be executed once the PR is merged into `develop`.
   * Pre-merge execution of `todo complete` without `--pr` is prohibited.
