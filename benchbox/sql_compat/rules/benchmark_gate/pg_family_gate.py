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


def _register_pg_mooncake_gate(
    *,
    benchmark: str,
    rule_suffix: str,
    reason: str,
    payload_reason: str | None = None,
    failure_mode: FailureMode = FailureMode.UNSUPPORTED_FEATURE,
) -> None:
    REGISTRY.register(
        CompatibilityDecision(
            rule_id=f"benchmark_gate.pg-mooncake.{benchmark}.{rule_suffix}",
            action=CompatAction.BLOCK_BENCHMARK,
            support_level=SupportLevel.BLOCKED,
            failure_mode=failure_mode,
            payload=BlockBenchmarkPayload(reason=payload_reason or reason),
            reason=reason,
        ),
        Phase.BENCHMARK_GATE,
        "pg-mooncake",
        benchmark=benchmark,
    )


def _register_timescaledb_gate(
    *,
    benchmark: str,
    rule_suffix: str,
    reason: str,
    payload_reason: str | None = None,
    failure_mode: FailureMode = FailureMode.UNSUPPORTED_FEATURE,
) -> None:
    REGISTRY.register(
        CompatibilityDecision(
            rule_id=f"benchmark_gate.timescaledb.{benchmark}.{rule_suffix}",
            action=CompatAction.BLOCK_BENCHMARK,
            support_level=SupportLevel.BLOCKED,
            failure_mode=failure_mode,
            payload=BlockBenchmarkPayload(reason=payload_reason or reason),
            reason=reason,
        ),
        Phase.BENCHMARK_GATE,
        "timescaledb",
        benchmark=benchmark,
    )


_register_pg_family_gate(
    benchmark="ai_primitives",
    rule_suffix="unsupported",
    reason=(
        "AI primitives is an LLM/tooling benchmark, not a PostgreSQL-family SQL engine workload. "
        "Runs fail before schema creation with "
        "`argument should be a str or an os.PathLike object` on pg-duckdb, pg-mooncake, and TimescaleDB."
    ),
)

_register_pg_family_gate(
    benchmark="vector_search",
    rule_suffix="no_vector_type",
    reason=(
        "Vector search requires a VECTOR column type and vector-distance operators. "
        "Schema creation fails with "
        '`type "vector" does not exist` on pg-duckdb, pg-mooncake, and TimescaleDB.'
    ),
)

_register_pg_family_gate(
    benchmark="read_primitives",
    rule_suffix="duckdb_intrinsics",
    reason=(
        "Read primitives currently includes a DuckDB-heavy SQL primitive catalog without PostgreSQL-family "
        "variants for approximate aggregates, arg_min/arg_max, GROUP BY ALL, ORDER BY ALL, ASOF JOIN, "
        "UNPIVOT, struct/map/list intrinsics, and related functions, so runs hit repeated "
        "unsupported-function and syntax failures across pg-duckdb, pg-mooncake, and TimescaleDB."
    ),
)

_register_pg_mooncake_gate(
    benchmark="tpcds",
    rule_suffix="moonlink_scan_plan_gaps",
    reason=(
        "pg_mooncake loads TPC-DS data, but several queries cannot be planned. Queries "
        "4, 11, 23a, 23b, 74, and 95 fail during PGDuckDB plan creation because "
        "`mooncake_scan` is not registered, and query 90 fails in the same plan path on "
        "PostgreSQL-style numeric casts. pg-duckdb and TimescaleDB run the same benchmark, so "
        "this is a Mooncake query-planning gap rather than a benchmark loader issue."
    ),
)

_register_pg_mooncake_gate(
    benchmark="write_primitives",
    rule_suffix="moonlink_read_only_mirrors",
    reason=(
        "pg_mooncake benchmark tables are promoted to mooncake mirrors for analytical execution, and those "
        "mirrors do not support the write_primitives setup/write contract. Even with raised replication "
        "sender limits, setup fails with `DuckDB does not support modifying Postgres tables`."
    ),
)

_register_pg_mooncake_gate(
    benchmark="transaction_primitives",
    rule_suffix="moonlink_read_only_mirrors",
    reason=(
        "pg_mooncake benchmark tables are promoted to mooncake mirrors for analytical execution, but "
        "transaction_primitives requires repeated transactional writes against the TPC-H corpus. Runs "
        "fail in the same promotion/write path, including Moonlink duplicate replication registration."
    ),
)
