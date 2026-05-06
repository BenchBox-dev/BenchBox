---
id: 2026-05-03-130000-stress-script-uat-driver-drift
date: 2026-05-03
status: actioned
finding_kind: framework-gap
review_context: "code review of scripts/local_stress_test.sh against the 2026-05-02 UAT retrospective"
related_paths:
  - scripts/local_stress_test.sh
  - _project/handoffs/results-explorer-uat-retrospective-20260502.md
  - _project/specs/uat-methodology-blind-spot-remediation.md
suggested_sweep: "fold the matrix-execution machinery (timeout wrapper, scale-ladder, reuse-aware cleanup, sentinel TSV, validation, packaging, explorer smoke) into a single tracked Python framework so future sweeps configure rather than reinvent"
todo_id: null
---

# Stress script and bespoke UAT drivers reinvent the same machinery in parallel

## Finding

`scripts/local_stress_test.sh` and the 2026-05-02 UAT driver are two
parallel surfaces for matrix-shape execution that drift. The bash script
already ships timeout/gtimeout/perl fallback, registry enumeration,
per-platform port maps, per-platform `--platform-option` tables,
per-platform CLI flags, per-platform uv-extra mapping, TCP probing with
sentinel cache, and result-JSON path extraction. The 2026-05-02 UAT W3
hand-rolled a Perl-based timeout wrapper (the script already has this),
plus scale-ladder pruning, reuse-aware database cleanup, a
matrix-summary TSV, validator subset filtering, submission packaging
exit-code interpretation, explorer build orchestration, and Playwright
smoke — none of which the bash script has, none of which is reusable
because they live only as ad-hoc artifacts under
`~/Developer/benchmark_runs/logs/uat_20260502/` and the retrospective.

The methodology-remediation spec at
`_project/specs/uat-methodology-blind-spot-remediation.md` deliberately
scoped this question out. It addresses *how UAT TODOs are authored* —
cross-scale convention, validator-clean-rate metric, terminal-state
vocab. It does not address *how UAT machinery is built*. The drift
between `scripts/local_stress_test.sh` and the next bespoke UAT driver
is a separate gap.

## Why this matters

Each future UAT pays the re-invention tax. The 2026-05-02 sweep author
documented building a Perl timeout wrapper, scale-ladder logic, and
reuse-aware cleanup from scratch — work that either could have been
contributed back to the bash script (drift-reducing but inadequate for
the broader phase set) or could have lived in a tracked Python
framework (drift-preventing). Neither happened, so the next sweep
inherits the same starting point and pays the tax again.

A second-order effect: the spec's recommended `scripts/uat_validator_rollup.py`
helper (Finding 2 deliverable) becomes an orphan if no framework
consumes it as a phase. Filing helpers without a runner that composes
them encourages each sweep to invent its own composition.

## Suggested next steps

- [ ] Build a tracked Python UAT framework under `tests/uat/` that hosts the matrix-execution machinery as composable phases (preflight, enumerate, execute with scale-ladder + cleanup, validate via the rollup helper, package with explicit terminal state, explorer smoke, report).
- [ ] Expose the framework via `make uat-*` targets — keep the user CLI surface (`benchbox`) unchanged.
- [ ] Encode the 2026-05-02 sweep parameters as a frozen replay config (`tests/uat/configs/uat-2026-05-02.yaml`) and assert structural parity with the historical retrospective.
- [ ] Document the migration path for `scripts/local_stress_test.sh` (leave alone, thin-delegate, or retire) without forcing a deprecation cycle in the framework's first delivery.

## Triage log

- 2026-05-05: actioned — UAT Python framework shipped under tests/uat/ (orchestrator/runner/matrix/ladder/cleanup/configs/phases) via PR #205; recommended migration delivered
