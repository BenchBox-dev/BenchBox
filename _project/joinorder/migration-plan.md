# JoinOrder Bundle Migration Plan

## Licensing ADR

- Canonical data redistribution decision:
  `_project/decisions/joinorder-canonical-data-licensing-2026-05-12.md`
- Status: not clearly permitted for BenchBox-hosted redistribution; follow-up
  remediation is tracked in
  `_project/TODO/main/planning/joinorder-data-fetch-from-dataverse-remediation.yaml`.

Pairs: 5
Files: 10

## Scale Factor Migration Decision

Canonical `joinorder` accepts only `scale_factor=1.0`. Calls such as
`JoinOrder(scale_factor=0.1)` and CLI runs such as `--benchmark joinorder
--scale 0.1` intentionally hard-raise instead of warning and silently running
at 1.0.

Decision: no one-release warn-and-ignore shim.

Rationale:

- BenchBox 0.2.x is still beta, so preserving a misleading sub-scale contract is
  less valuable than making the canonical data cutover explicit.
- The old scalable synthetic generator remains available as
  `joinorder_synthetic` for smoke-test data.
- Silently coercing sub-scale values to 1.0 would hide a materially different
  run: a full ~1.2 GB canonical archive download and 74M-row workload.
- The public docs and error message point users at `joinorder_synthetic` when
  they need synthetic scaled smoke data.

## Provenance And Rebuild Attestation

- Canonical data attestation:
  `_project/joinorder/provenance-attestation.md`
- Status: Dataverse source checksum and conversion fidelity are verified.
  Byte-identical rebuild is not established; the determinism decision is tracked
  in
  `_project/TODO/main/planning/joinorder-parquet-rebuild-determinism-decision.yaml`.

## joinorder_sf1_clickhouse_local_sql_20260505_203919_70acdc69.json

- Result: `results-data/bundles/joinorder_sf1_clickhouse_local_sql_20260505_203919_70acdc69.json` -> `results-data/bundles/joinorder_synthetic_sf1_clickhouse_local_sql_20260505_203919_70acdc69.json`
- Manifest: `results-data/bundles/joinorder_sf1_clickhouse_local_sql_20260505_203919_70acdc69.manifest.json` -> `results-data/bundles/joinorder_synthetic_sf1_clickhouse_local_sql_20260505_203919_70acdc69.manifest.json`
- Result JSON: benchmark.id `joinorder` -> `joinorder_synthetic`; benchmark.name -> `JoinOrderSyntheticBenchmark`
- Manifest JSON: bundle_file updated; benchmark -> `JoinOrderSyntheticBenchmark`; bundle_hash recomputed after result JSON update

## joinorder_sf1_duckdb_sql_20260505_195300_be289a53.json

- Result: `results-data/bundles/joinorder_sf1_duckdb_sql_20260505_195300_be289a53.json` -> `results-data/bundles/joinorder_synthetic_sf1_duckdb_sql_20260505_195300_be289a53.json`
- Manifest: `results-data/bundles/joinorder_sf1_duckdb_sql_20260505_195300_be289a53.manifest.json` -> `results-data/bundles/joinorder_synthetic_sf1_duckdb_sql_20260505_195300_be289a53.manifest.json`
- Result JSON: benchmark.id `joinorder` -> `joinorder_synthetic`; benchmark.name -> `JoinOrderSyntheticBenchmark`
- Manifest JSON: bundle_file updated; benchmark -> `JoinOrderSyntheticBenchmark`; bundle_hash recomputed after result JSON update

## joinorder_sf1_spark_sql_20260506_092910_4f603854.json

- Result: `results-data/bundles/joinorder_sf1_spark_sql_20260506_092910_4f603854.json` -> `results-data/bundles/joinorder_synthetic_sf1_spark_sql_20260506_092910_4f603854.json`
- Manifest: `results-data/bundles/joinorder_sf1_spark_sql_20260506_092910_4f603854.manifest.json` -> `results-data/bundles/joinorder_synthetic_sf1_spark_sql_20260506_092910_4f603854.manifest.json`
- Result JSON: benchmark.id `joinorder` -> `joinorder_synthetic`; benchmark.name -> `JoinOrderSyntheticBenchmark`
- Manifest JSON: bundle_file updated; benchmark -> `JoinOrderSyntheticBenchmark`; bundle_hash recomputed after result JSON update

## joinorder_sf1_sqlite_sql_20260506_085050_4e521870.json

- Result: `results-data/bundles/joinorder_sf1_sqlite_sql_20260506_085050_4e521870.json` -> `results-data/bundles/joinorder_synthetic_sf1_sqlite_sql_20260506_085050_4e521870.json`
- Manifest: `results-data/bundles/joinorder_sf1_sqlite_sql_20260506_085050_4e521870.manifest.json` -> `results-data/bundles/joinorder_synthetic_sf1_sqlite_sql_20260506_085050_4e521870.manifest.json`
- Result JSON: benchmark.id `joinorder` -> `joinorder_synthetic`; benchmark.name -> `JoinOrderSyntheticBenchmark`
- Manifest JSON: bundle_file updated; benchmark -> `JoinOrderSyntheticBenchmark`; bundle_hash recomputed after result JSON update

## joinorder_sf1_starrocks_sql_20260506_112717_d3968adb.json

- Result: `results-data/bundles/joinorder_sf1_starrocks_sql_20260506_112717_d3968adb.json` -> `results-data/bundles/joinorder_synthetic_sf1_starrocks_sql_20260506_112717_d3968adb.json`
- Manifest: `results-data/bundles/joinorder_sf1_starrocks_sql_20260506_112717_d3968adb.manifest.json` -> `results-data/bundles/joinorder_synthetic_sf1_starrocks_sql_20260506_112717_d3968adb.manifest.json`
- Result JSON: benchmark.id `joinorder` -> `joinorder_synthetic`; benchmark.name -> `JoinOrderSyntheticBenchmark`
- Manifest JSON: bundle_file updated; benchmark -> `JoinOrderSyntheticBenchmark`; bundle_hash recomputed after result JSON update
