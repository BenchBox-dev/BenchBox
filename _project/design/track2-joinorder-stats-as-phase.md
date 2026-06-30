# Track-2 Phase-Model Survey: Statistics-as-a-Phase

Status: Design survey (Track-2 groundwork). Surveys the current phase model,
identifies the statistics-as-a-phase gap, sketches the change, and seeds the
Track-2 implementation TODO (`track2-joinorder-stats-phase`). No code changes.

Track 2 evaluates "the interplay of statistics maintenance and predicate
selectivity." That measurement is only valid if statistics-build time is
attributed to its own phase. This doc establishes that BenchBox has no such
phase today and specifies the change at principal-engineer depth so the Track-2
implementer starts from a concrete plan.

## Current phase model

BenchBox expresses benchmark execution as a small set of lifecycle phases plus
nested setup/execution sub-phases.

- **Lifecycle phases** — `LifecyclePhases` dataclass with three booleans:
  `generate`, `load`, `execute` (`benchbox/core/runner/runner.py:600`).
- **CLI phase vocabulary** — `_parse_phases_list()` accepts
  `{generate, load, warmup, power, throughput, maintenance}`
  (`benchbox/cli/commands/run.py:689`) and the orchestrator maps them back onto
  `LifecyclePhases` (`benchbox/cli/orchestrator.py:279`), where any of
  `warmup/power/throughput/maintenance` collapses into `execute`.
- **Setup sub-phases** — `DataGenerationPhase`, `SchemaCreationPhase`,
  `DataLoadingPhase`, `ValidationPhase`, grouped by the `SetupPhase` aggregator
  (`benchbox/core/results/models.py:131`).
- **Execution sub-phases** — `PowerTestPhase`, `ThroughputTestPhase`,
  `MaintenanceTestPhase` (and platform-specific `MigrationPhase`), grouped by the
  `ExecutionPhases` aggregator (`benchbox/core/results/models.py:245`).

Each phase dataclass carries an aggregate `duration_ms` field, and query-level
timing is captured by `QueryTiming` (execution/parse/optimization/fetch splits,
`benchbox/core/results/timing.py:24`) collected via `TimingCollector.time_phase()`
(`benchbox/core/results/timing.py:159`). So per-phase timing infrastructure
already exists — there is simply no statistics phase plugged into it.

Where statistics land today, per engine:

| Engine | Explicit ANALYZE method | Called during lifecycle? | Where stats actually accrue |
| --- | --- | --- | --- |
| PostgreSQL | `analyze_table()` (`benchbox/platforms/postgresql.py:799`) | No — `load_data()` (`postgresql.py:559`) never calls it | First-query planning, or a manual ANALYZE outside the run |
| DuckDB | `analyze_tables()` (`benchbox/platforms/duckdb.py:1109`) | No | Background/auto-stats after load |
| Spark | `analyze_table()` (`benchbox/platforms/spark.py:818`) | No | Not gathered unless invoked manually |
| Redshift | `auto_analyze` config gating ANALYZE | Only in isolated vacuum/analyze maintenance, not load | Maintenance path or first-query |
| ClickHouse | none found | n/a | Auto-statistics on insert |
| StarRocks | none found | n/a | Relies on auto/manual ANALYZE TABLE |

The pattern is consistent: `analyze_table()` exists in 26+ adapters but has **no
centralized call site** in the runner. Statistics gathering is therefore
scattered, optional, and unattributed.

## Why this matters

Track 2's research question is the interplay of statistics maintenance and
predicate selectivity. If stats-build time is silently folded into load (engines
that auto-analyze after COPY/INSERT) or into query (engines that build stats at
first-query planning), the measurement is invalid before it starts.

Concrete failure mode: an engine with sophisticated auto-statistics that takes
30s to build looks **30s slower at load** (auto-on-load engines) **or 30s slower
at first-query** (lazy-stats engines) — and neither attribution is correct. Two
engines with identical raw load and query performance but different stats
strategies would be ranked differently purely by where their stats time happens
to land. Because BenchBox has the per-phase `duration_ms` machinery but no
statistics phase, this misattribution is the current default, not an edge case.

## Proposed change

Introduce an explicit statistics phase between load and query: ordering becomes
`load → statistics → query`.

- **New phase dataclass** — add a `StatisticsGatheringPhase` (sibling of
  `DataLoadingPhase` / `ValidationPhase` in `benchbox/core/results/models.py`)
  carrying `duration_ms`, plus a `stats_mode` field.
- **Centralized call site** — the runner invokes the platform `analyze_table()` /
  `analyze_tables()` in this phase after load completes, instead of leaving each
  adapter's method unreferenced.
- **Per-engine knob** — engines with explicit ANALYZE run it and time it.
  Engines that auto-analyze during load are **documented, not double-built**:
  they report zero stats-phase wall-clock with `stats_mode: auto-on-load` so the
  attribution is unambiguous (the lean here is *document, not disable* —
  auto-analyze is what production engines do, so measuring it is realistic).
- **CLI vocabulary** — add `statistics` to the `_parse_phases_list()` valid set
  (`benchbox/cli/commands/run.py:689`) and the orchestrator mapping
  (`benchbox/cli/orchestrator.py:279`); default runs keep it off.
- **Result-bundle manifest** — carry the statistics-phase `duration_ms` and
  `stats_mode` separately from load and query timing, alongside the existing
  `dataset_version` identity fields (`benchbox/core/results/models.py:383`).

## Migration strategy

The change must not invalidate historical result bundles or in-flight
comparisons.

- **Backwards compatibility** — existing benchmarks default to *no explicit
  statistics phase* (legacy load-includes-stats behavior). The new phase is
  off unless requested, so old runs and new runs of legacy benchmarks remain
  comparable.
- **Opt-in** — `joinorder`, `tpch`, `tpcds` enable the statistics phase once
  Track 2 lands; other benchmarks are untouched.
- **Bundle interpretability** — `dataset_version` plus the benchmark schema
  version distinguish pre- vs post-phase-model bundles
  (`benchbox/core/results/models.py:383`, `benchbox/core/data_fetch/manifest.py:106`),
  so a consumer can tell whether a bundle's load timing includes or excludes
  stats. No historical bundle is rewritten.

## Open design questions

- **Detect-and-disable vs document auto-analyze** — lean: *document, not
  disable*. Auto-analyze is what production engines do, so measuring it (and
  attributing zero explicit stats wall-clock via `stats_mode: auto-on-load`) is
  more realistic than forcing engines into an artificial no-auto-stats mode.
- **Per-table vs whole-database ANALYZE** — JOB has 21 tables. Decide whether to
  measure each table's stats build separately (richer attribution, more
  telemetry) or aggregate to one phase number. Lean: aggregate phase total with
  optional per-table breakdown in `timing_breakdown`.
- **Cold-stats vs warm-stats across runs** — when stats persist between runs,
  does the subsequent query phase see them or not? Track 2 needs both modes
  (fresh-stats and stale-stats-after-additional-load) to study maintenance, so
  the phase must support an explicit reset/persist control.
- **Idempotence** — re-running ANALYZE on already-analyzed data should produce
  the same plan; this is the sanity check that the phase is measuring stats build
  rather than incidental cache warmth.
