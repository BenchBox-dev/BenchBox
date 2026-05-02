# Results Explorer UAT Retrospective - 2026-05-02

## W1 Pre-Flight

Status: passed after the free-space cutoff was revised from ~50 GiB to ~40 GiB.

- Output root: `~/Developer/benchmark_runs` (`BENCHBOX_OUTPUT_DIR` unset, so default applies).
- Free space: `46 GiB` available on `/System/Volumes/Data`, above the revised ~40 GiB cutoff.
- Docker: reachable; `docker ps` showed no running containers.
- Docker Desktop: `MemTotal=12,528,578,560`, `NCPU=10`.
- Host CPUs: `sysctl -n hw.ncpu hw.logicalcpu hw.physicalcpu` reported `10 / 10 / 10`.
- Host noise: current load is acceptable for a sequential UAT sweep on 10 cores; no process was killed.

## W2 Run Matrix

Sources:

- `scripts/local_stress_test.sh`, read only for platform groupings, TCP probes, uv extras, platform options, and CLI flags.
- `benchbox.core.benchmark_registry`, queried live with `uv run --no-sync -- python`.

### Platform Groups

| Group | Platforms |
| --- | --- |
| Fast native SQL | `duckdb`, `datafusion`, `lakesail`, `clickhouse-local` |
| Fast Docker SQL | `clickhouse-server`, `cedardb`, `starrocks` |
| Slow native SQL | `sqlite`, `spark` |
| Slow Docker SQL | `postgresql`, `presto`, `trino`, `databend`, `doris`, `influxdb`, `pg-duckdb`, `pg-mooncake`, `timescaledb`, `questdb`, `singlestore`, `velox` |
| DataFrame | `polars-df`, `pandas-df`, `modin-df`, `pyspark-df`, `dask-df`, `datafusion-df` |

SQL platforms: 21. DataFrame platforms: 6. Cloud platforms remain deferred by the TODO.

### Platform Modifiers

| Platform | TCP probe | uv mode | Extra benchbox args |
| --- | --- | --- | --- |
| `clickhouse-local` | none | `uv run --extra clickhouse-local --` | none |
| `clickhouse-server` | `localhost:9000` | `uv run --no-sync --` | none |
| `cedardb` | `localhost:5435` | `uv run --no-sync --` | none |
| `starrocks` | `localhost:19030` | `uv run --no-sync --` | `--platform-option port=19030 --platform-option http_port=18040` |
| `postgresql` | `localhost:5432` | `uv run --no-sync --` | none |
| `presto` | `localhost:18081` | `uv run --no-sync --` | none |
| `trino` | `localhost:18080` | `uv run --no-sync --` | none |
| `databend` | `localhost:8000` | `uv run --no-sync --` | none |
| `doris` | `localhost:19031` | `uv run --no-sync --` | `--platform-option port=19031 --platform-option http_port=18030 --platform-option be_http_port=18040` |
| `influxdb` | `localhost:8181` | `uv run --extra influxdb --` | none |
| `pg-duckdb` | `localhost:5432` | `uv run --no-sync --` | none |
| `pg-mooncake` | `localhost:5432` | `uv run --no-sync --` | none |
| `timescaledb` | `localhost:5432` | `uv run --no-sync --` | none |
| `questdb` | `localhost:8812` | `uv run --no-sync --` | `--platform-option http_port=19000` |
| `singlestore` | `localhost:13306` | `uv run --extra singlestore --` | `--platform-option port=13306 --platform-option password=benchbox` |
| `velox` | `localhost:50051` | `uv run --no-sync --` | `--platform-option deployment=remote --platform-option endpoint=sc://localhost:50051 --iterations 1` |

All other native SQL and DataFrame platforms use `uv run --no-sync --` with no TCP probe and no extra platform options.

### Benchmark Scale Ladder

Target scales: `0.01`, `0.1`, `1.0`; filter by registry `min_scale` / `max_scale`.

| Category | Benchmark | DataFrame? | Registry min | Registry max | UAT scales |
| --- | --- | --- | --- | --- | --- |
| TPC | `tpch` | yes | `0.01` | none | `0.01`, `0.1`, `1.0` |
| TPC | `tpcds` | yes | none | none | `0.01`, `0.1`, `1.0` |
| TPC | `tpcdi` | yes | `0.01` | none | `0.01`, `0.1`, `1.0` |
| Primitives | `read_primitives` | yes | `0.01` | none | `0.01`, `0.1`, `1.0` |
| Primitives | `write_primitives` | yes | `0.01` | none | `0.01`, `0.1`, `1.0` |
| Primitives | `metadata_primitives` | yes | `1.0` | none | `1.0` |
| Primitives | `transaction_primitives` | yes | `0.01` | none | `0.01`, `0.1`, `1.0` |
| Primitives | `ai_primitives` | no | `0.01` | none | `0.01`, `0.1`, `1.0` |
| Industry | `clickbench` | yes | `1.0` | none | `1.0` |
| Industry | `h2odb` | yes | `0.01` | none | `0.01`, `0.1`, `1.0` |
| Industry | `coffeeshop` | yes | `0.001` | none | `0.01`, `0.1`, `1.0` |
| Academic | `ssb` | yes | `0.01` | none | `0.01`, `0.1`, `1.0` |
| Academic | `amplab` | yes | `0.01` | none | `0.01`, `0.1`, `1.0` |
| Academic | `joinorder` | yes | `1.0` | none | `1.0` |
| Time Series | `tsbs_devops` | yes | `0.01` | none | `0.01`, `0.1`, `1.0` |
| Real World | `nyctaxi` | yes | `0.01` | none | `0.01`, `0.1`, `1.0` |
| Real World | `flightdata` | yes | `0.01` | none | `0.01`, `0.1`, `1.0` |
| AI/ML | `vector_search` | no | `0.01` | none | `0.01`, `0.1`, `1.0` |
| Experimental | `tpcds_obt` | yes | `1.0` | none | `1.0` |
| Experimental | `tpchavoc` | yes | `0.01` | none | `0.01`, `0.1`, `1.0` |
| Experimental | `tpch_skew` | yes | `0.01` | none | `0.01`, `0.1`, `1.0` |
| Experimental | `datavault` | yes | `0.01` | none | `0.01`, `0.1`, `1.0` |

SQL-only benchmarks: `ai_primitives`, `vector_search`.

Candidate cells before reachability checks and scale-ladder early stops:

- SQL: 58 cells per SQL platform x 21 platforms = 1,218 cells.
- DataFrame: 52 cells per DataFrame platform x 6 platforms = 312 cells.
- Total: 1,530 candidate cells.

### W3 Execution Template

Per cell, adapt platform modifiers above:

```bash
[timeout-backend] 600 uv run [--no-sync | --extra <extra>] -- \
  benchbox run \
  --platform <platform> \
  --benchmark <benchmark> \
  --scale <scale> \
  --phases load,power \
  --non-interactive \
  [platform options] \
  [platform CLI flags]
```

Timeout backend check: this host currently has neither `timeout` nor `gtimeout`; `/usr/bin/perl` is available. W3 must use
the same real-timeout Perl fallback pattern from `scripts/local_stress_test.sh` or install/use `gtimeout` before executing
cells. Do not run cells without a hard 600-second wall-clock cap.

Run order should stay sequential by platform, with scale ladder order `0.01 -> 0.1 -> 1.0` per platform/benchmark pair.
