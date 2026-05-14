---
branch: fix/uat-release-gate-remediation
run_date: 2026-05-14
# audit_sha_backfill parent fallback from d14cdde6df0a576534b72265f5fa9dc011e61fac
develop_sha: 1a37ae6f1d90594471cbb0a1f49871c3c3cd760d
---

# UAT Enabled Platforms Full Release Gate - 2026-05-14

## Command

```bash
BENCHBOX_OUTPUT_DIR=/Users/joe/Developer/benchmark_runs \
  make uat-sweep CONFIG=tests/uat/configs/uat-enabled-platforms-full.yaml
```

Run root: `/Users/joe/Developer/benchmark_runs/logs/uat_enabled_platforms_full_20260514`

## Outcome

The enabled-platform release gate is green for the supported local matrix:

```json
{
  "preflight": 0,
  "enumerate": 0,
  "execute": 0,
  "validate": 0,
  "package": 0,
  "explorer_smoke": 0,
  "report": 0
}
```

Matrix accounting:

| Candidates | Executed | Compatibility-pruned | Passed | Failed | Timed out |
|---:|---:|---:|---:|---:|---:|
| 88 | 64 | 24 | 64 | 0 | 0 |

Per-platform executed rows:

| Platform | Passed | Failed | Timed out |
|---|---:|---:|---:|
| lakesail | 17 | 0 | 0 |
| pg-duckdb | 16 | 0 | 0 |
| pg-mooncake | 14 | 0 | 0 |
| timescaledb | 17 | 0 | 0 |

## Validation And Explorer

`validator_rollup.tsv` was emitted and the validate phase returned zero.
Submittable bundles were clean. The three TPC-DS subscale bundles were
reported as `refused-by-cli` with `compliance_class=unofficial_subscale`, as
expected for local subscale UAT outputs.

Explorer external-corpus smoke passed against the packaged run corpus:

- `explorer_corpus_contract.json`: 152 bundles, 20 benchmarks, 4 platforms, 24,644 queries.
- `playwright_smoke.log`: `@uat-external-corpus` Chromium smoke, 1 passed.

## Compatibility Pruning

The 24 pruned cells all came from registry-backed compatibility rules, not
ad hoc skips:

- LakeSail: `ai_primitives`, `metadata_primitives`, `transaction_primitives`,
  `vector_search`, `write_primitives`.
- PostgreSQL-family: `ai_primitives`, `joinorder`, `read_primitives`,
  `tpcds_obt`, `vector_search`.
- pg_mooncake only: `tpcds`, `transaction_primitives`, `write_primitives`.
- TimescaleDB only: `datavault`.

The LakeSail `vector_search` rule is intentionally benchmark-level: the prior
run loaded 10,100 rows but executed zero queries because every LakeSail vector
query source was compatibility-skipped.

## Docker Cleanup

UAT ran one Docker stack at a time. The lifecycle log shows clean `up` and
`down -v --remove-orphans` for LakeSail, pg-duckdb, pg-mooncake, and
TimescaleDB. After the run:

```bash
make uat-docker-cleanup APPLY=1
```

removed the UAT-owned `benchbox-lakesail:dev` image. No UAT-owned containers
remained; non-UAT base images were reported and intentionally left alone.

No raw UAT logs, result bundles, screenshots, browser reports, or generated
binary evidence are committed.
