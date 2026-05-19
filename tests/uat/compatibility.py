"""UAT platform/benchmark compatibility policy.

This is intentionally UAT-local policy, not runtime SQL compatibility. Runtime
`benchbox.sql_compat` rules describe SQL translation/execution behavior, while
these rules explain why a UAT matrix cell is not attempted at all.
"""

from __future__ import annotations

from dataclasses import dataclass

from benchbox.core.platform_registry import PlatformRegistry
from tests.uat.matrix import DATAFRAME_PLATFORMS, KNOWN_SQL_ONLY_BENCHMARKS, BenchmarkInfo


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
    evidence=("tests/uat/matrix.py:KNOWN_SQL_ONLY_BENCHMARKS and benchmark registry `supports_dataframe` metadata"),
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


def compatibility_rule_for(
    platform: str,
    benchmark: str,
    info: BenchmarkInfo,
    *,
    include_release_gate_runtime_envelopes: bool = False,
) -> CompatibilityRule | None:
    """Return the rule that blocks a platform/benchmark pair, if any."""
    if platform in DATAFRAME_PLATFORMS and _is_sql_only_benchmark(benchmark, info):
        return DATAFRAME_SQL_ONLY_RULE
    if include_release_gate_runtime_envelopes:
        runtime_envelope_reason = _PG_FAMILY_RELEASE_GATE_RUNTIME_ENVELOPES.get((platform, benchmark))
        if runtime_envelope_reason:
            return CompatibilityRule(
                rule_id=f"uat.compat.{platform}.{benchmark}.release_gate_runtime_envelope",
                status="blocked",
                reason=runtime_envelope_reason,
                evidence="2026-05-14 enabled-platform UAT release-gate audit; not a runtime compatibility gate",
            )
    caps = PlatformRegistry.get_platform_capabilities(platform)
    unsupported_benchmarks = getattr(caps, "unsupported_benchmarks", {}) if caps else {}
    reason = unsupported_benchmarks.get(benchmark)
    if reason:
        return CompatibilityRule(
            rule_id=f"uat.compat.{platform}.{benchmark}.benchmark_gate",
            status="blocked",
            reason=reason,
            evidence="benchbox.sql_compat benchmark_gate registry via PlatformRegistry.unsupported_benchmarks",
        )
    return None


def _is_sql_only_benchmark(benchmark: str, info: BenchmarkInfo) -> bool:
    if benchmark in KNOWN_SQL_ONLY_BENCHMARKS:
        return True
    return not info.supports_dataframe
