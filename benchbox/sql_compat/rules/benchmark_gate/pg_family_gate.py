"""Benchmark-gate rules for PostgreSQL-family local platforms.

These rules cover current pg_duckdb, pg_mooncake, and TimescaleDB UAT
incompatibilities where the benchmark contract requires a feature outside the
platform's exposed SQL surface.
"""

from __future__ import annotations

from benchbox.sql_compat.actions import CompatAction
from benchbox.sql_compat.context import Phase
from benchbox.sql_compat.decision import BlockBenchmarkPayload, CompatibilityDecision, FailureMode, SupportLevel
from benchbox.sql_compat.registry import REGISTRY

_PG_FAMILY_PLATFORMS = ("pg-duckdb", "pg-mooncake", "timescaledb")


def _register_pg_family_gate(
    *,
    benchmark: str,
    rule_suffix: str,
    reason: str,
    payload_reason: str | None = None,
    failure_mode: FailureMode = FailureMode.UNSUPPORTED_FEATURE,
) -> None:
    for platform in _PG_FAMILY_PLATFORMS:
        REGISTRY.register(
            CompatibilityDecision(
                rule_id=f"benchmark_gate.{platform}.{benchmark}.{rule_suffix}",
                action=CompatAction.BLOCK_BENCHMARK,
                support_level=SupportLevel.BLOCKED,
                failure_mode=failure_mode,
                payload=BlockBenchmarkPayload(reason=payload_reason or reason),
                reason=reason,
            ),
            Phase.BENCHMARK_GATE,
            platform,
            benchmark=benchmark,
        )


_register_pg_family_gate(
    benchmark="ai_primitives",
    rule_suffix="unsupported",
    reason=(
        "AI primitives is an LLM/tooling benchmark, not a PostgreSQL-family SQL engine workload. "
        "The 2026-05-13 enabled-platform UAT run failed before schema creation with "
        "`argument should be a str or an os.PathLike object` on pg-duckdb, pg-mooncake, and TimescaleDB."
    ),
)

_register_pg_family_gate(
    benchmark="vector_search",
    rule_suffix="no_vector_type",
    reason=(
        "Vector search requires a VECTOR column type and vector-distance operators. "
        "The 2026-05-13 enabled-platform UAT run failed during schema creation with "
        '`type "vector" does not exist` on pg-duckdb, pg-mooncake, and TimescaleDB.'
    ),
)

_register_pg_family_gate(
    benchmark="read_primitives",
    rule_suffix="duckdb_intrinsics",
    reason=(
        "Read primitives currently includes a DuckDB-heavy SQL primitive catalog without PostgreSQL-family "
        "variants for approximate aggregates, arg_min/arg_max, GROUP BY ALL, ORDER BY ALL, ASOF JOIN, "
        "UNPIVOT, struct/map/list intrinsics, and related functions. The 2026-05-13 enabled-platform "
        "UAT run showed repeated unsupported-function and syntax failures across pg-duckdb, "
        "pg-mooncake, and TimescaleDB."
    ),
)
