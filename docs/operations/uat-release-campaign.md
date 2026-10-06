# UAT release campaign

Maintainer procedure for the three-stage UAT campaign and its report. The UAT
framework itself is described in `docs/operations/uat-framework.md`.

## Three-stage UAT campaign

A UAT campaign produces a report (a COMPLETED report per config with a commit
SHA). It runs in three stages, in this order, so that all
native and dataframe platforms finish before any Docker stack starts — the
ordering the 2026-05-28/29 evidence violated. First time on a machine: work
through `docs/operations/uat-local-provisioning.md` "First-run checklist"
before starting stage 1.

Stages (run each to completion before starting the next):

1. **Native SQL + dataframe** — `tests/uat/configs/release-gate-01-native-dataframe.yaml` (scales 0.01/0.1/1)
2. **Docker non-OLTP** — `tests/uat/configs/release-gate-02-docker-nonoltp.yaml` (scales 0.01/0.1/1)
3. **Docker OLTP** — `tests/uat/configs/release-gate-03-docker-oltp.yaml` (scale 0.01)

(Stage 1 covers release-gate stages 1–2 of the contract — native SQL then
dataframe — in a single Docker-free sweep; stages 2 and 3 are the Docker tiers.)

Run rules:

- Use a **fresh run root** under `BENCHBOX_OUTPUT_DIR=~/Developer/benchmark_runs`
  (the three configs leave their output templates unset, so the env var sets
  the base — see "Output artefacts"); never resume into the failed 2026-05-28/29
  dirs (they are non-evidentiary).
- One platform / one Docker stack at a time (`execute.parallel_platforms` is
  hard-rejected). A single Docker stack's compose-up failure records FAIL and
  the sweep advances; it does not truncate the run.
- For slow Docker stacks (e.g. LakeSail), set `cleanup.docker_start_timeout_s`
  from a measured healthy startup (see "Managed Docker startup failures are
  non-fatal") before the stage-2 run.

Every sweep writes a machine-readable `uat_gate_summary.json` beside
`cells.jsonl` (versioned schema; verdict `green|red`, or `dry_run` for
dry-run sweeps): config name, source provenance, container engine,
completion timestamp, per-phase exit codes, accounting counts, validator
clean rate vs floor, cross-scale pairs vs floor, and explorer-smoke status.

Ordering + aggregation check: after the three runs,

```bash
make uat-gate-check STAGE1=<stage1-run-dir> STAGE2=<stage2-run-dir> STAGE3=<stage3-run-dir>
```

reads the three stage summaries, verifies from their machine-recorded
`completed_at` timestamps that no Docker `action=up` in stages 2/3 preceded
stage-1 completion (nor stage 3 before stage-2 completion), enforces the
mechanized campaign-report items below, and writes the combined evidence file
to `_project/release-evidence/uat-gate-summary.json`. Exit 0 means the
campaign report is complete. The report may be reviewed or committed as
historical evidence; `scripts/release_readiness_check.py` does not require it
for `validate-base` (see `docs/operations/release-guide.md`).

`cross_scale_coverage_min_pairs` in each config is the report-phase teeth: a
breach forces a non-zero report exit, so a partial or regressed sweep cannot
be reported as complete. The values are derived, not hand-picked: floor =
max(stage minimum, floor(0.8 × cross-scale-eligible pairs from
`enumerate_cells_with_pruning`)) — each config carries its derivation comment,
and `tests/uat/test_config.py` pins the sound band.

### Campaign report: COMPLETE / HOLD

`make uat-gate-check` classifies this report: all stages verdict-green
(every phase exit 0, incl. validator and cross-scale floors), accounting
sidecar present (`unreachable_is_estimated=false`), explorer smoke actually
ran for stages that configure it, one clean `source_commit_sha` across
stages (`source_dirty=false`), and no ordering violations. Exit 0 = COMPLETE;
any HOLD reason is printed and lands in the evidence file's `reasons`. It is a
campaign report, not a release-cut precondition.

Still useful before recording the report: DuckDB (the reference) is green or
its cells are explicitly pruned, and no `NO_JSON` cell lacks captured error
text.
