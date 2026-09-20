# Decision: run the heavy CI tier only in the merge queue (proposal)

Date: 2026-09-16
Status: Accepted. Maintainer decision recorded 2026-09-19. No further workflow,
ruleset, or queue change lands under this
record. The maintainer decision in section 9 is the only authorization, and
an agent must not record it.

Related:

- `_project/analysis/replay_heavy_tier_queue_only_baseline.py`
- `_project/analysis/heavy-tier-queue-only-2026-09-16-manifest.json`
- `_project/decisions/native-merge-queue-activation-20260822.md`
- `docs/operations/merge-queue-governance.md`
- `docs/operations/repo-admin-settings.md`
- `.github/workflows/pr.yml`
- `.github/workflows/develop-refresh-shadow.yml`
- `_project/scripts/auto_merge_soundness_paths.py`

---

## 1. Context and evidence

`pr.yml` runs the full test tier twice for most code changes: once as
`pull_request` CI and again as `merge_group` CI on the exact tree the queue
lands. The merge-queue run already covers the tree that reaches `develop`,
so the question is whether the expensive jobs need their pre-merge run too.

Pinned baseline, `pr.yml` runs created 2026-08-23 through 2026-09-16
(manifest above; replay with
`uv run -- python _project/analysis/replay_heavy_tier_queue_only_baseline.py`):

| Event | Runs | Runner-minutes | Heavy-tier share |
|---|---:|---:|---:|
| `pull_request` | 795 | 45,547 | 29,272 (64%) |
| `merge_group` | 344 | 21,585 | — |

Heavy-tier pull_request minutes by job:

| Job | Runner-minutes | Ran | Failed | Cancelled mid-flight |
|---|---:|---:|---:|---:|
| medium-test | 13,058 | 750 | 10 | 217 |
| correctness-gate | 10,344 | 750 | 2 | 179 |
| tpch-binary-framing | 2,060 | 1,498 | 0 | 19 |
| postgres-integration | 1,359 | 750 | 0 | 24 |
| datafusion-integration | 894 | 750 | 0 | 16 |
| clickhouse-integration | 876 | 750 | 0 | 16 |
| plan-capture-gate | 682 | 750 | 0 | 18 |

Failure attribution in the window:

- The heavy tier failed in 11 `pull_request` runs on 8 branches
  (medium-test 10, correctness-gate 2, everything else 0). For each one the
  manifest pins the earliest later `pull_request` run on the same branch
  whose previously-failed jobs are all green on a different SHA, and the
  replay validates every pin. Two were dependency upgrades (pandas 3,
  sqlglot). Merge ordering is not a replayed fact — run payloads carry no
  merge timestamps — so recovery before merge is branch-history inference,
  stated as such.
- No `merge_group` run has a gating heavy-tier failure (medium-test,
  correctness-gate, plan-capture-gate, tpch-binary-framing: 0 failures in
  318 code-routed runs). The single postgres-integration failure in the
  window (run 34135929941) is a 13-second `continue-on-error` sample
  failure on a run whose conclusion and `ci-required-result` were success;
  it is recorded in the manifest, not hidden, and it does not count as a
  gating failure.
- Job p50: medium-test 21.2 min, correctness-gate 15.8 min, code-test
  13.5 min (p90 22.5 min).

Two measurement notes, both pinned in the manifest rather than smoothed
over: one `pull_request` run created after the window end was still in
flight at collection, so the pinned PR total sits 14.6 minutes below the
unbounded collection total; and thirteen startup-cancelled jobs on run
32797475819 carry one second of negative clock skew and count with their
negative durations, matching the baseline collectors.

Expected effect: about 29,000 fewer `pull_request` runner-minutes per
25 days, with typical code-PR feedback moving from medium-test's p50
(~21 min) toward code-test's p50 (~14 min). That 29,000 is an upper
bound, not the expected saving: it sums the whole historical heavy tier,
including soundness-path and packaging runs that keep the full tier under
section 3's carve-outs. The pinned cohort carries no per-run classifier
or changed-path data with which to subtract those runs, so no tighter
figure is claimed. The planning figure for the worst case, if every
historical pre-merge catch instead reached the queue, is about 3,900
additional queue minutes per 25 days.

## 2. Proposal

On `pull_request` runs of `pr.yml`, skip the heavy tier unless a carve-out
(section 3) applies. `merge_group` runs keep the full tier on every
code-routed tree.

Moved job set (exact `pr.yml` job ids):

- `medium-test`
- `correctness-gate`
- `plan-capture-gate`
- `tpch-binary-framing`
- `postgres-integration`
- `datafusion-integration`
- `clickhouse-integration`

Stays on `pull_request` runs, unchanged:

- `code-test`, including every promoted slow-marked reproducer wired into
  it today (the TPC-H power/throughput boundary-query reproducers and the
  other slow-marked steps in the `code-test` job). Post-merge has no
  slow-signature lane, so this is their only required execution path.
- `code-lint`, `ci-paths`, `certification-identity`, content and
  skill-integrity lanes, packaging jobs, explorer jobs, and every other
  current `pull_request` job.

The moved set must not be widened by the implementation. Moving anything
else (a `code-test` split, the browser suite) needs a new decision.

## 3. Carve-outs

A `pull_request` run keeps the full heavy tier when either holds:

1. The PR touches soundness paths: the union of the base-ref copy and the
   PR copy of `_project/scripts/auto_merge_soundness_paths.py`
   (`SOUNDNESS_PREFIXES`, `SOUNDNESS_FILES`, `_VALIDATION_RE`), evaluated
   the way `auto-merge-on-open.yml` evaluates it. Any evaluation error
   fails closed to running the heavy tier.
2. The `ci-paths` classifier reports `packaging-needed` as true.

The event name comes only from `github.event_name`. No PR label, body text,
or workflow input may select the light path.

## 4. Umbrella rule

`ci-required-result` keeps `if: always()` (a skipped required check counts
as passing, so the umbrella itself must never skip) and checks both
directions:

- When the heavy tier is needed (carve-out applies, or the event is
  `merge_group` on a code-routed tree): `medium-test`,
  `correctness-gate`, `plan-capture-gate`, and `tpch-binary-framing` must
  be `success`. Anything else fails the umbrella.
- When the heavy tier is not needed: those jobs must be `skipped`.
  Anything else (including an unexpected `success`) fails the umbrella, so
  a misconfigured skip can never read as coverage.
- `merge_group` never skips the heavy tier for a code-routed tree.
- Integration samples keep `continue-on-error`: their red does not fail
  the umbrella, as today.

Required check names (`ci-required-result`, `Results Explorer browser
gate`, `ruleset-drift`), ruleset `15611785`, and the merge-queue parameters
do not change. The implementation verifies this with
`scripts/ruleset_drift_check.py --queue-policy` against live state.

## 5. Local preflight addition

`make pr-preflight` gains the medium tier as its own receipt-bound stage
when the existing classifier decision (`scripts/path_filter_decision.py`,
consumed through `scripts/local_validation.py`) says the diff needs code
CI. Content-only and skill-integrity-only diffs skip the stage. The stage
uses the same marker expression as CI `make test-medium`, fails
pre-flight on failure with no skip flag, and reuses its receipt on
unchanged trees. Medium-test caught 10 of the 11 historical pre-merge
heavy-tier failures, which is the coverage this replaces. Local results
stay a pre-filter; they never satisfy a hosted required check. The
implementation reports wall time on at least one Apple silicon developer
machine against the CI p50 of 21.2 minutes on a 4-vCPU runner.

## 6. Rollback trigger

Attribution, not rates: 3 or more `merge_group` failures of a moved job in
any rolling 7-day window restores `pull_request` execution of the moved set
the same day, using the rollback plan the implementation pre-authors in its
PR body. Failures in jobs that were not moved (`code-test`, publication
reconciliation, `audit-sha`, and the rest) do not count toward the
trigger. Revert first; do not tune thresholds or add exceptions to keep the
change. The 14-day watch after landing tracks PR minutes, PR p50 feedback
time, queue rebuilds caused by moved-job failures, and local medium
escapes, each against the section 1 baseline, with run IDs.

## 7. Records reconciled

On approval, the implementation updates each of these in the same change;
this record alone changes none of them:

- `docs/operations/merge-queue-governance.md`, section 2 table: the
  `ci-required-result` contract row must state the light-PR versus full
  queue coverage, and the slow-reproducer note below the table stays true
  because the reproducers stay in `code-test` on PR runs.
- `.github/workflows/pr.yml`, `tpch-binary-framing` comment (the
  "pre-merge foreign-platform smoke coverage" promise that every code PR
  gets macOS and Windows execution before merge): reworded to the queue
  execution with the soundness carve-out, or the promise is kept by
  carving that job out. One of the two; the comment must not promise what
  the workflow no longer does.
- `certification_kind` semantics: `.github/workflows/pr.yml`
  `certification-identity` (a PR run without the heavy tier must not claim
  `full`) and its consumer `.github/workflows/develop-refresh-shadow.yml`
  `parse_identity` (which only honors `full`), lines around 107-128.
- `docs/operations/repo-admin-settings.md`: the required-check and lane
  description for the PR path.

## 8. What this record does not do

- Changes no workflow file, required check, ruleset setting, or queue
  parameter.
- Narrows no path filter and changes no job content (docs-lane failure
  causes are a separate investigation).
- Makes docs a required check.

## 9. Maintainer decision (maintainer only)

Exactly one outcome, recorded here by the maintainer with a date. An agent
must not complete this section.

- [ ] APPROVE (date: ____)
- [ ] APPROVE_WITH_CHANGES (date: ____; changes listed below)
- [ ] REJECT (date: ____; reason below; the dependent local-preflight,
      queue-only, and watch items are then dropped with that reason —
      dropping is the maintainer's call)

Changes / reason:
