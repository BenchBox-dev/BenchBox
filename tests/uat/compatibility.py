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


def compatibility_rule_for(platform: str, benchmark: str, info: BenchmarkInfo) -> CompatibilityRule | None:
    """Return the rule that blocks a platform/benchmark pair, if any."""
    if platform in DATAFRAME_PLATFORMS and _is_sql_only_benchmark(benchmark, info):
        return DATAFRAME_SQL_ONLY_RULE
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
