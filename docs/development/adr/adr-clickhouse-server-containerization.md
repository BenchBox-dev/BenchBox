# ADR: `clickhouse-server` runs in a container, and SF1 certification runs on Linux

## Status

Accepted. This decision records why the `clickhouse-server` UAT stack is
containerized and where its certification sweeps run. It does not authorize
changes to `benchbox/platforms/clickhouse/setup.py`, and it does not change
the rung ladder or the admission arithmetic in
`docs/operations/uat-framework.md`.

## Date

2026-08-19

## Context

`clickhouse-server` has always been exercised through
`docker/clickhouse/docker-compose.yml`, whose header still describes it as
"Single-node ClickHouse for integration testing (server mode)". No ADR and no
commit message recorded a container-versus-native evaluation. The container
was inherited from ordinary integration-test scaffolding and only later became
load-bearing, when the streaming memory calibration (PR #1706) and compose
memory admission (PR #1713) made an externally enforced memory ceiling the
object under test rather than incidental setup.

The premise surfaced because
`uat-clickhouse-server-sf1-streaming-certification` is blocked. Admission
requires the selected 8 GiB request plus a 2 GiB host reserve, so at least
10 GiB available, on a 16 GiB macOS development host that measured 2.79 GiB
available at 86.4% swap.

Three measurements matter for the choice.

**The engine's actual demand is far below the envelope.** The failed SF1 4g
trace (`clickhouse-memory-sf1-4g.json`, 2026-08-13) recorded
`peak_engine_usage_bytes = 3.4 GB` and a peak `metric.MemoryTracking` of
3.21 GB at t=127s of a 142-second load, falling back to 589 MB by the final
sample. The peak is a transient driven by background MergeTree merges running
against accumulated `lineitem` parts while inserts are still streaming; it
scales with concurrent merges, part size, and `max_threads`, not with dataset
size. SF1 TPC-H is roughly 1.26 GB of compressed input
(`event.InsertedBytes`). The 8 GiB rung is a ceiling chosen with headroom
above the failing 4 GiB rung, not a measured requirement.

**The container limit partly manufactures the ceiling it enforces.**
ClickHouse derives its server-wide cap from the RAM it detects
(`max_server_memory_usage_to_ram_ratio`, default 0.9). The 4g run tripped at
"(total) memory limit exceeded: would use 3.51 GiB" against a 3.73 GiB cgroup,
about 94% of the cap. A larger container raises the internal ceiling while the
~3.4 GB working peak stays put.

**On macOS the container costs roughly double.** `mocker` executes the stack
inside a Linux virtual machine, so an 8 GiB container consumes 8 GiB of host
RAM plus VM overhead. On a 16 GiB laptop that is most of the machine, to host
a process whose measured peak is ~3.4 GB. A material share of the 10 GiB
admission bar is therefore a property of the macOS harness, not of ClickHouse.

## Options Considered

**Option A — keep the container, certify SF1 on Linux.** cgroups are native,
there is no VM tax, and the enforced ceiling means what it claims.

**Option B — run `clickhouse-server` natively on macOS.** The adapter already
permits this: `benchbox/platforms/clickhouse_server.py` documents "Docker-backed
or dedicated self-hosted" access and takes `host`/`port` platform options, so
no platform code requires a container. The blocking problems are elsewhere.
macOS has no cgroups, so no external agent can cap the process; ClickHouse's own
`max_server_memory_usage` is self-enforced, and using it as the bound would make
the certification circular. The trace's `oom_killed` field also requires an
external supervisor to observe at all. Independently, the Homebrew cask is
unusable and expiring: the shipped binary is ad-hoc/linker-signed and
unnotarized (`Identifier=decompressor`, `flags=0x20002(adhoc,linker-signed)`),
`spctl` rejects it, and Homebrew disables the deprecated cask on 2026-09-01.

**Option C — run a native ClickHouse process on Linux.** Removes the VM tax but
still forfeits the externally enforced limit unless the harness adds its own
cgroup management, which duplicates what compose already provides.

**Option D — drop the enforced ceiling and certify against ClickHouse's own
accounting.** Rejected outright: the enforced envelope is the object of
certification, so this deletes the test rather than relocating it.

## Decision

Choose **Option A**. `clickhouse-server` stays containerized, and SF1
certification runs on Linux, where the cgroup contract is real and no VM sits
between the limit and the host. macOS keeps the SF0.01 smoke, which passes at
the `baseline-1g` rung and does not approach the admission bar.

Certifying a cgroup envelope through a macOS virtualization layer on a
swap-saturated host measures the harness as much as the engine. Relocating the
sweep unblocks the work without weakening any gate, changing the selected rung,
or touching the no-fallback loader contract.

`clickhouse-local` (chDB, in-process) remains the supported native path. It is a
different platform target — embedded execution rather than the native TCP
client/server protocol — and is not a substitute for what `clickhouse-server`
certifies.

## Consequences

- SF1 load, power, and evidence work units require a Linux host or CI runner
  that can admit 8 GiB plus the 2 GiB reserve. The macOS development host is
  not a certification host for SF1 and should not be treated as one.
- The 8 GiB rung remains the selected SF1 envelope. Nothing here authorizes a
  downgrade to 4 GiB, a rung drop, or any return to `RowBatchProcessor` or a
  1,000-row batch.
- Native macOS `clickhouse-server` is closed as an option while the binary is
  unnotarized. Revisit only if ClickHouse ships a notarized macOS build, and
  note that removing the Gatekeeper quarantine to force the current binary is a
  security decision that also disables tamper detection on the download.
- The container remains the only place the memory envelope is externally
  enforced, so compose stays authoritative for `CLICKHOUSE_MEMORY_LIMIT` and the
  no-default contract documented in `docs/operations/uat-framework.md` stands.

## Follow-up ownership

Per-query `max_memory_usage` defaults to `"8GB"` in
`benchbox/platforms/clickhouse/setup.py:33`, equal to the container limit, which
permits a single query to claim the entire cgroup with nothing left for merges,
caches, or page cache. That is a tuning question in platform code, out of scope
for the certification item, and is tracked separately. It is a candidate lever if
the goal ever becomes lowering the admission bar rather than satisfying it.
