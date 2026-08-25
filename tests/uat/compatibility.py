"""UAT platform/benchmark compatibility policy.

This is intentionally UAT-local policy, not runtime SQL compatibility. Runtime
`benchbox.sql_compat` rules describe SQL translation/execution behavior, while
these rules explain why a UAT matrix cell is not attempted at all.
"""

from __future__ import annotations

from dataclasses import dataclass

from benchbox.core.platform_registry import PlatformRegistry
from tests.uat.matrix import DATAFRAME_PLATFORMS, BenchmarkInfo


@dataclass(frozen=True)
class CompatibilityRule:
    rule_id: str
    status: str
    reason: str
    evidence: str


DATAFRAME_SQL_ONLY_RULE = CompatibilityRule(
    rule_id="uat.compat.dataframe.sql_only_benchmark",
    status="blocked",
    reason="DataFrame platforms cannot execute SQL-only benchmark implementations.",
    evidence="benchmark registry `supports_dataframe` metadata",
)

_NATIVE_MODEL_BENCHMARK_GATES = {
    ("datafusion", "write_primitives"): (
        "DataFusion UAT runs through the in-memory SessionContext adapter; the adapter only rewrites "
        "write_primitives bulk-load operations and does not expose the durable row-level DML contract "
        "needed by the full write-primitives workload."
    ),
    ("datafusion", "transaction_primitives"): (
        "Transaction primitives requires ACID transaction semantics. The DataFusion UAT adapter is an "
        "in-memory analytical query path with no DBAPI transaction contract."
    ),
    ("datafusion", "ai_primitives"): (
        "AI primitives requires platform AI/ML SQL functions; DataFusion is listed in the AI primitives "
        "unsupported platform set."
    ),
    ("datafusion", "vector_search"): (
        "Vector search requires vector/array similarity functions and ANN-index semantics. The DataFusion "
        "UAT adapter has no vector-search dialect implementation."
    ),
    ("clickhouse-local", "write_primitives"): (
        "clickhouse-local uses embedded chDB in-process mode; the UAT local path has no durable server-side "
        "write contract for the full write-primitives staging workload."
    ),
    ("clickhouse-local", "transaction_primitives"): (
        "Transaction primitives requires BEGIN/COMMIT/ROLLBACK-style ACID semantics; clickhouse-local "
        "uses embedded chDB analytical execution, not a transactional DBAPI contract."
    ),
    ("clickhouse-local", "ai_primitives"): (
        "AI primitives requires platform AI/ML SQL functions; ClickHouse is listed in the AI primitives "
        "unsupported platform set."
    ),
}

_NATIVE_MODEL_BENCHMARK_EVIDENCE = (
    "benchbox/core/ai_primitives/specs.yaml unsupported_platforms; "
    "benchbox/platforms/datafusion.py DataFusionConnectionCompat; "
    "benchbox/platforms/clickhouse_local.py embedded chDB local adapter"
)

_DATAFRAME_TRANSACTIONAL_BENCHMARK_GATES = {
    "transaction_primitives": (
        "Transaction primitives requires ACID transaction semantics. The UAT DataFrame selector set does "
        "not include a Delta Lake or Iceberg transactional table-format platform."
    ),
    "tpcdi": (
        "TPC-DI DataFrame ETL requires transactional maintenance capabilities for incremental/SCD2 writes; "
        "the UAT DataFrame selector set does not provide a transactional table-format backend."
    ),
}

_DATAFRAME_TRANSACTIONAL_EVIDENCE = (
    "benchbox/core/transaction_primitives/dataframe_operations.py "
    "validate_transaction_primitives_platform; "
    "benchbox/core/tpcdi/benchmark.py execute_dataframe_workload transactional capability gate; "
    "benchbox/platforms/dataframe/pyspark_maintenance.py PySpark Parquet capability profile"
)

_DATAFRAME_WRITE_MANAGER_UNSUPPORTED = frozenset({"dask-df", "datafusion-df", "modin-df"})
_DATAFRAME_WRITE_MANAGER_REASON = (
    "Write primitives DataFrame mode is currently implemented only for Polars, Pandas, and PySpark managers; "
    "this UAT platform has no write manager for the benchmark."
)
_DATAFRAME_WRITE_MANAGER_EVIDENCE = (
    "benchbox/core/write_primitives/dataframe_operations.py get_dataframe_write_manager supported_platforms"
)

_JOINORDER_RUNTIME_ENVELOPE_REASON = (
    "Canonical JoinOrder uses the full IMDb 2013 dataset at scale 1.0 only. A targeted 2026-05-14 "
    "pg-duckdb UAT rerun loaded and validated the dataset, then timed out at the 1200s release-gate "
    "budget on warm-up query 7a after the first 23 queries completed. The benchmark has no smaller "
    "public scale; use joinorder_synthetic for PostgreSQL-family smoke coverage."
)

_TPCDS_OBT_RUNTIME_ENVELOPE_REASON = (
    "TPC-DS OBT is currently scale-1.0-only and materializes a very wide sales/returns table. A targeted "
    "2026-05-14 pg-duckdb UAT rerun with delimited output loaded and validated the table, but query 1 "
    "took 5:14, query 2 failed on PostgreSQL round(double precision, integer), and query 4 timed out at "
    "the 2400s diagnostic budget. The parquet path also requires PostgreSQL-family loader fallbacks. "
    "Until the benchmark has a subscale or PostgreSQL-family OBT query rewrites, it is outside the local "
    "enabled-platform release-gate envelope."
)

_TIMESCALEDB_DATAVAULT_RUNTIME_ENVELOPE_REASON = (
    "TimescaleDB loaded and row-count validated DataVault SF 0.01 in the 2026-05-14 full UAT gate, "
    "but timed out at the 1200s release-gate budget during warm-up query 17 after query 5 alone took "
    "2:26.8. LakeSail, pg-duckdb, and pg-mooncake cleared the same DataVault cell, so this is a "
    "TimescaleDB-specific runtime envelope failure for the current release gate."
)

_SQLITE_TPCDS_OBT_RUNTIME_ENVELOPE_REASON = (
    "SQLite TPC-DS OBT SF1 cannot meet the 1200s release-gate cell contract on the native UAT host. "
    "The 2026-08-25 bounded probe used the canonical ParquetFileHandler against the 5,041,336-row, "
    "518-column OBT artifact: it inserted 1,325,000 rows in 304.9s without committing, with 4,345 "
    "rows/s overall and 2,350 rows/s in the final 25,000-row interval. The last 625,000-row linear "
    "projection is 1,391s for loading alone, before validation and power queries. The source table has "
    "no indexes, primary keys, or foreign keys, and the second SQLite connection saw zero rows until "
    "commit; this is the SQLite bind/WAL growth path, not schema/indexing or SQL compatibility. Keep "
    "the cell pruned until a bounded atomic SQLite bulk-loader change has measured evidence within the "
    "declared budget."
)
_SQLITE_TPCDS_OBT_RUNTIME_ENVELOPE_EVIDENCE = (
    "PR #1904 2026-08-25 bounded native probe; original killed-run evidence under "
    "BENCHBOX_OUTPUT_DIR=~/Developer/benchmark_runs; docs/operations/uat-framework.md"
)

_PG_FAMILY_RELEASE_GATE_RUNTIME_ENVELOPES = (
    {
        (platform, "joinorder"): _JOINORDER_RUNTIME_ENVELOPE_REASON
        for platform in ("pg-duckdb", "pg-mooncake", "timescaledb")
    }
    | {
        (platform, "tpcds_obt"): _TPCDS_OBT_RUNTIME_ENVELOPE_REASON
        for platform in ("pg-duckdb", "pg-mooncake", "timescaledb")
    }
    | {("timescaledb", "datavault"): _TIMESCALEDB_DATAVAULT_RUNTIME_ENVELOPE_REASON}
)

_RELEASE_GATE_RUNTIME_ENVELOPES = _PG_FAMILY_RELEASE_GATE_RUNTIME_ENVELOPES | {
    ("sqlite", "tpcds_obt"): _SQLITE_TPCDS_OBT_RUNTIME_ENVELOPE_REASON,
}


def compatibility_rule_for(
    platform: str,
    benchmark: str,
    info: BenchmarkInfo,
    *,
    include_release_gate_runtime_envelopes: bool = False,
) -> CompatibilityRule | None:
    """Return the rule that blocks a platform/benchmark pair, if any."""
    native_reason = _NATIVE_MODEL_BENCHMARK_GATES.get((platform, benchmark))
    if native_reason:
        return _benchmark_gate_rule(
            platform,
            benchmark,
            reason=native_reason,
            evidence=_NATIVE_MODEL_BENCHMARK_EVIDENCE,
        )
    if platform in DATAFRAME_PLATFORMS and _is_sql_only_benchmark(info):
        return DATAFRAME_SQL_ONLY_RULE
    if platform in DATAFRAME_PLATFORMS:
        transactional_reason = _DATAFRAME_TRANSACTIONAL_BENCHMARK_GATES.get(benchmark)
        if transactional_reason:
            return _benchmark_gate_rule(
                platform,
                benchmark,
                reason=transactional_reason,
                evidence=_DATAFRAME_TRANSACTIONAL_EVIDENCE,
            )
        if platform in _DATAFRAME_WRITE_MANAGER_UNSUPPORTED and benchmark == "write_primitives":
            return _benchmark_gate_rule(
                platform,
                benchmark,
                reason=_DATAFRAME_WRITE_MANAGER_REASON,
                evidence=_DATAFRAME_WRITE_MANAGER_EVIDENCE,
            )
    if include_release_gate_runtime_envelopes:
        runtime_envelope_reason = _RELEASE_GATE_RUNTIME_ENVELOPES.get((platform, benchmark))
        if runtime_envelope_reason:
            runtime_envelope_evidence = (
                _SQLITE_TPCDS_OBT_RUNTIME_ENVELOPE_EVIDENCE
                if (platform, benchmark) == ("sqlite", "tpcds_obt")
                else "2026-05-14 enabled-platform UAT release-gate audit; not a runtime compatibility gate"
            )
            return CompatibilityRule(
                rule_id=f"uat.compat.{platform}.{benchmark}.release_gate_runtime_envelope",
                status="blocked",
                reason=runtime_envelope_reason,
                evidence=runtime_envelope_evidence,
            )
    caps = PlatformRegistry.get_platform_capabilities(platform)
    unsupported_benchmarks = getattr(caps, "unsupported_benchmarks", {}) if caps else {}
    reason = unsupported_benchmarks.get(benchmark)
    if reason:
        return _benchmark_gate_rule(
            platform,
            benchmark,
            reason=reason,
            evidence="benchbox.sql_compat benchmark_gate registry via PlatformRegistry.unsupported_benchmarks",
        )
    return None


def _benchmark_gate_rule(platform: str, benchmark: str, *, reason: str, evidence: str) -> CompatibilityRule:
    return CompatibilityRule(
        rule_id=f"uat.compat.{platform}.{benchmark}.benchmark_gate",
        status="blocked",
        reason=reason,
        evidence=evidence,
    )


def _is_sql_only_benchmark(info: BenchmarkInfo) -> bool:
    return not info.supports_dataframe
