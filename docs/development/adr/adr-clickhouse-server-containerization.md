# ADR: `clickhouse-server` runs in a container, and SF1 certification runs on Linux

## Status

Accepted. This decision records why the `clickhouse-server` UAT stack is
containerized and where its certification sweeps run. It does not authorize
changes to `benchbox/platforms/clickhouse/setup.py`, and it does not change
the rung ladder or the admission arithmetic in
`docs/operations/uat-framework.md`.

## Date

2026-08-19. Amended 2026-08-20 to correct the tracking claim in
"Follow-up ownership", record that this decision is documented but not
enforced, and mark the superseded remediation text in the w2 evidence artifact.

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
- **This decision is documented, not enforced.** No preflight check refuses SF1
  certification on darwin. `check_memory_headroom` blocks the current host on
  available memory alone, which is a coincidence of this machine's size: a macOS
  host with enough RAM would clear admission and emit an SF1 certification
  result that this ADR considers invalid, because the VM layer and the absent
  cgroup contract do not appear in the admission arithmetic. Treat a darwin SF1
  result as unqualified until a gate exists.

## Evidence and superseded records

`~/Developer/benchmark_runs/clickhouse-certification-20260818/sf1-admission-8g-blocked-20260818.json`
is the admission-denial evidence for work unit w2 and remains valid as a
measurement. Its `operator_remediation_required` narrative predates this ADR
and is superseded: it offers "reboot this host and run the SF1 sweep with no
interactive agent session competing" as a first remedy, which this decision
rejects. Freeing memory on the macOS host does not make it a certification
host, because the objection is the virtualization layer and the missing cgroup
contract, not the byte count on any given day. Read that field as history.

## Follow-up ownership

Two follow-ups remain. Findings are captured locally first and discovered with
`_project/scripts/todo finding candidates`; hosted synchronization is a
separately authorized tracker action.

**Per-query `max_memory_usage` exceeds the decimal container request.** The
query default `"8GB"` is parsed as 8 × 1024³ bytes, while the compose request
`"8g"` is parsed as 8 × 1000³ bytes. The query cap is therefore about 7.4%
larger than the cgroup request, so the cgroup can kill the process before
ClickHouse reaches its configured query ceiling. The values are also configured
independently. Whether to lower the query cap is undecided; it is a candidate
lever only after a qualified Linux trace, not a way to certify SF1 on macOS.

Capture the finding as
`~/.benchbox/finding-drafts/YYYY-MM-DD-HHMMSS-clickhouse-per-query-memory-exceeds-container-limit.md`.
`_project/scripts/todo finding candidates` discovers local drafts. A separately
authorized `_project/scripts/todo finding sync` owns hosted disposition and
lifecycle; do not rename the immutable timestamp-first finding id.

**No gate enforces the Linux requirement.** Making it real means a platform
check in the UAT admission path that fails SF1 certification on darwin
regardless of available memory, rather than relying on this document being read.
That is platform-code work, unscoped and unauthorized here.
