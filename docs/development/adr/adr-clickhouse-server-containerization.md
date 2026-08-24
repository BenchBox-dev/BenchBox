# ADR: `clickhouse-server` containerization and SF1 certification on Linux or Apple Container

## Status

Accepted. Amended 2026-08-23 to select the experimentally passing
`candidate-5.25g` envelope and accept Apple Container's Linux guest cgroup
contract as certification evidence when the evidence requirements below are
present.

This decision does not authorize changes to the ClickHouse platform adapter or
the native streaming loader contract.

## Context

`clickhouse-server` is exercised through
`docker/clickhouse/docker-compose.yml`. The container boundary is load-bearing:
the memory calibration and compose admission test an externally enforced
memory ceiling, not an incidental development setup.

The former 8 GiB request plus 2 GiB host reserve was a conservative candidate,
not a measured ClickHouse requirement. The 4 GiB TPC-H SF1 trace failed near
its cgroup ceiling, but the engine's measured peak was substantially lower.
Exploratory Apple Container runs then measured the following complete TPC-H SF1
load-plus-power outcomes:

| nominal cgroup request | outcome | evidence |
|---:|---|---|
| 5 GiB | failed three power queries; no cgroup/OOM event | `tpch_sf1_clickhouse_server_sql_20260823_085737_dafb9272.json` |
| 5.25 GiB | 66/66 queries passed; exact eight-table rows | `tpch_sf1_clickhouse_server_sql_20260823_090633_3e841a03.json` |
| 5.5 GiB | 66/66 queries passed | `tpch_sf1_clickhouse_server_sql_20260823_090340_dec290a6.json` |
| 6 GiB | 66/66 queries passed | `tpch_sf1_clickhouse_server_sql_20260823_090049_c8fcd4aa.json` |
| 8 GiB | 66/66 queries passed | `tpch_sf1_clickhouse_server_sql_20260823_085324_045ac0bf.json` |

The 5.25 GiB TPC-H run had zero cgroup/OOM events and passed the result
validator, including exact SF1 row counts. TPC-DS SF1 at the same 5.25 GiB
request loaded 19,557,376 rows without a cgroup/OOM event and reached a
measured engine peak of about 3.11 GB (`tpcds_sf1_clickhouse_server_sql_20260823_093153_449b1f7e.json`). Its power phase completed but contained query failures; those are separate TPC-DS compatibility/correctness evidence, not a memory-limit failure. The TPC-DS result must not be represented as a clean benchmark pass until those query failures are resolved.

No default host reserve is assumed. The calibration established the
5.25 GiB runtime request, but did not validate an additional host margin; the
former 2 GiB reserve was an unvalidated policy assumption. Operators may set a
nonzero reserve only when a separate host-headroom measurement justifies it,
and that policy must remain distinct from ClickHouse working-set demand.

## Decision

`clickhouse-server` remains containerized. The selected SF1 memory envelope is
`candidate-5.25g`, the lowest exploratory envelope that passed the complete
TPC-H SF1 load-plus-power path in the current calibration sequence. The formal
calibration ladder includes 1 GiB, 4 GiB, 5.25 GiB, 8 GiB, and 12 GiB; a rung
must still be selected from a valid trace before changing a release default.

SF1 certification is valid on either:

1. Linux with Docker and native Linux cgroup enforcement; or
2. macOS with Apple Container/Mocker, when the Linux guest cgroup evidence is
   captured and bound to the run.

Apple Container's lightweight Linux VM is not treated as a missing-cgroup
runtime. Its guest `/sys/fs/cgroup/memory.max` and the runtime-reported limit
are acceptable external memory-bound evidence when they agree exactly with
the selected rung.

A qualifying SF1 memory/certification package must include:

- the selected named rung and requested memory spelling;
- runtime memory limit equal to that rung, accepting only its exact decimal or
  binary unit equivalent;
- for Apple Container, guest cgroup `memory.max` evidence bound to the same
  project/container and runtime capture;
- host available/free memory and swap telemetry throughout the run;
- no cgroup OOM, container OOM, or unexplained memory-limit failure;
- `native_streaming=true`, `application_batch_rows=null`, and the fixed driver
  timeout recorded by the trace;
- exact per-table SF1 row counts from the generated manifest; and
- a clean result validator outcome with all required power queries passing.

Native macOS `clickhouse-server` remains excluded. It has no external cgroup
boundary and is not equivalent to Apple Container's guest Linux boundary.
`clickhouse-local` remains a separate embedded platform and is not a substitute
for server-mode certification.

## Consequences

- The default managed ClickHouse request is `5.25g`; the default additional
  host reserve is `0.0`. A nonzero reserve remains separately configurable,
  but requires separate host-headroom evidence and must not be reported as
  measured engine demand.
- Linux Docker and macOS Apple Container evidence are comparable only at the
  cgroup-contract boundary. Host VM overhead and swap pressure remain required
  telemetry, especially on macOS.
- The TPC-H SF1 result at 5.25 GiB is empirical macOS certification evidence
  under this decision. The TPC-DS 5.25 GiB run establishes memory behavior for
  the load path but is not a clean TPC-DS correctness result because its power
  queries still need triage.
- Calibration traces ignore only startup samples taken before cumulative
  ClickHouse insert counters exist. Once the first complete sample is present,
  any later required-telemetry gap invalidates the trace.

## Evidence and follow-up

The Apple Container cgroup probe and full-run console captures are retained in
`/tmp/clickhouse-host-overhead-rungs-20260822.log`,
`/tmp/clickhouse-host-overhead-8g-repeats-20260822.log`, and the corresponding
`/tmp/clickhouse-candidate8-*` logs from the calibration session. The durable
result JSON files are under `~/Developer/benchmark_runs/results/` as named
above.

The trace collector must remain fail-closed for missing telemetry after the
startup warm-up boundary. TPC-DS power-query failures require a separate
compatibility investigation; they must not be converted into a memory-rung
failure or silently treated as a clean TPC-DS certification.
