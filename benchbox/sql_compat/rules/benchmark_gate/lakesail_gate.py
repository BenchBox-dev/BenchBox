"""Benchmark-gate rules for LakeSail/Sail."""

from __future__ import annotations

from benchbox.sql_compat.actions import CompatAction
from benchbox.sql_compat.context import Phase
from benchbox.sql_compat.decision import BlockBenchmarkPayload, CompatibilityDecision, FailureMode, SupportLevel
from benchbox.sql_compat.registry import REGISTRY

REGISTRY.register(
    CompatibilityDecision(
        rule_id="benchmark_gate.lakesail.ai_primitives.unsupported",
        action=CompatAction.BLOCK_BENCHMARK,
        support_level=SupportLevel.BLOCKED,
        failure_mode=FailureMode.UNSUPPORTED_FEATURE,
        payload=BlockBenchmarkPayload(
            reason=(
                "AI primitives is an LLM/tooling benchmark, not a SQL engine workload. "
                "LakeSail/Sail schema creation fails before load because AIPrimitivesBenchmark "
                "does not provide get_create_tables_sql; targeted UAT on 2026-05-12 failed with "
                "AttributeError before any query execution."
            )
        ),
        reason=("AI primitives requires LLM/tool execution APIs and has no SQL schema contract for LakeSail/Sail."),
    ),
    Phase.BENCHMARK_GATE,
    "lakesail",
    benchmark="ai_primitives",
)

REGISTRY.register(
    CompatibilityDecision(
        rule_id="benchmark_gate.lakesail.transaction_primitives.unsupported",
        action=CompatAction.BLOCK_BENCHMARK,
        support_level=SupportLevel.BLOCKED,
        failure_mode=FailureMode.UNSUPPORTED_FEATURE,
        payload=BlockBenchmarkPayload(
            reason=(
                "Transaction primitives requires DBAPI-style transactional execution with BEGIN, COMMIT, ROLLBACK, "
                "SAVEPOINT, and isolation-level statements. LakeSail/Sail SQL mode exposes a Spark Connect "
                "SparkSession, and the 2026-05-13 focused UAT run failed every operation at the operation-executor "
                "boundary with `Invalid connection type: SparkSession` before any transaction semantics could run."
            )
        ),
        reason=(
            "LakeSail/Sail SQL mode does not expose the DBAPI transactional contract required by "
            "transaction_primitives."
        ),
    ),
    Phase.BENCHMARK_GATE,
    "lakesail",
    benchmark="transaction_primitives",
)

REGISTRY.register(
    CompatibilityDecision(
        rule_id="benchmark_gate.lakesail.metadata_primitives.unsupported",
        action=CompatAction.BLOCK_BENCHMARK,
        support_level=SupportLevel.BLOCKED,
        failure_mode=FailureMode.UNSUPPORTED_FEATURE,
        payload=BlockBenchmarkPayload(
            reason=(
                "Metadata primitives relies on INFORMATION_SCHEMA-style catalog tables such as schemata, tables, "
                "columns, views, and table_constraints. The 2026-05-13 focused LakeSail UAT run created the test "
                "schema but every metadata query failed with `Table not found` for those catalog relations, proving "
                "current Sail does not expose the metadata contract this benchmark measures."
            )
        ),
        reason="LakeSail/Sail does not expose the INFORMATION_SCHEMA catalog contract required by metadata_primitives.",
    ),
    Phase.BENCHMARK_GATE,
    "lakesail",
    benchmark="metadata_primitives",
)

REGISTRY.register(
    CompatibilityDecision(
        rule_id="benchmark_gate.lakesail.write_primitives.unsupported",
        action=CompatAction.BLOCK_BENCHMARK,
        support_level=SupportLevel.BLOCKED,
        failure_mode=FailureMode.UNSUPPORTED_FEATURE,
        payload=BlockBenchmarkPayload(
            reason=(
                "Write primitives currently executes through the SQL operation executor, which requires an "
                "`execute()`/`fetchall()` connection contract and row-level DML/DDL operation semantics. "
                "LakeSail/Sail SQL mode supplies a Spark Connect SparkSession; the 2026-05-13 focused UAT run "
                "loaded the schema but failed all operations with `Invalid connection type: SparkSession`."
            )
        ),
        reason=(
            "LakeSail/Sail SQL mode does not expose the SQL operation-executor contract required by write_primitives."
        ),
    ),
    Phase.BENCHMARK_GATE,
    "lakesail",
    benchmark="write_primitives",
)
