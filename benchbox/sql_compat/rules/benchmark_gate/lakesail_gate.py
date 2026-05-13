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
