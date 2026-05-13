# UAT Enabled Platforms Full Release Gate - 2026-05-13

## Command

```bash
BENCHBOX_OUTPUT_DIR=/Users/joe/Developer/benchmark_runs \
  make uat-sweep CONFIG=tests/uat/configs/uat-enabled-platforms-full.yaml
```

Run root: `/Users/joe/Developer/benchmark_runs/logs/uat_enabled_platforms_full_20260513`

Checked commit: `0fc3d78b1` plus the release-gate config added in this branch.

## Outcome

The release gate is not green. The sweep completed without phase aborts and Docker
lifecycle was clean, but execution and validation returned nonzero:

```json
{
  "preflight": 0,
  "enumerate": 0,
  "execute": 1,
  "validate": 1,
  "package": 0,
  "explorer_smoke": 0,
  "report": 0
}
```

Matrix summary:

| Platform | Passed | Failed | Timed out |
|---|---:|---:|---:|
| lakesail | 18 | 0 | 0 |
| pg-duckdb | 7 | 15 | 0 |
| pg-mooncake | 1 | 21 | 0 |
| timescaledb | 7 | 14 | 1 |

Overall accounting: 88 candidates, 84 executed, 4 compatibility-pruned,
33 passed, 50 failed, 1 timed out.

## Compatibility Pruning

The four pruned cells were all LakeSail benchmark gates backed by SQL
compatibility registry rules:

- `lakesail/write_primitives`
- `lakesail/metadata_primitives`
- `lakesail/transaction_primitives`
- `lakesail/ai_primitives`

## Validation And Explorer

`validator_rollup.tsv` was emitted. LakeSail validation was clean for all
submittable bundles except:

- `tpcds`: `refused-by-cli` because `compliance_class=unofficial_subscale`.
- `vector_search`: `warning_only` with two warnings.

Explorer external-corpus smoke passed against the packaged run corpus:

- `explorer_corpus_contract.json`: 32 bundles, 17 benchmarks, 4 platforms,
  4100 queries.
- `playwright_smoke.log`: `@uat-external-corpus` Chromium smoke, 1 passed.

## Remaining Red Cells

The gate still needs a follow-up remediation pass for the PG extension and
TimescaleDB cells. The most visible signatures from this run:

- `timescaledb/tpchavoc`: timed out at 600s after repeated 15s Q20 variants;
  earlier in the cell, `17_v4` also failed with missing `dual`.
- `timescaledb/datavault`: partial result, 3 failed query executions; query 1
  fails on `DATE '1998-12-01' - 90` syntax.
- PG extension failures mostly produced no result bundle and show
  `missing_manifest` in matrix accounting. The failing cells need per-log
  clustering before they can be fixed or converted to evidence-backed
  compatibility rules.

No raw UAT logs, result bundles, screenshots, or browser reports are committed.
