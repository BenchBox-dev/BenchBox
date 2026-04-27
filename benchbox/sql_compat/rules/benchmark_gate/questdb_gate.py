"""Benchmark-gate rules for QuestDB.

Registers BLOCK_BENCHMARK decisions for (platform, benchmark) pairs that
cannot run on QuestDB due to structural incompatibilities.
"""

from benchbox.sql_compat.actions import CompatAction
from benchbox.sql_compat.context import Phase
from benchbox.sql_compat.decision import BlockBenchmarkPayload, CompatibilityDecision, FailureMode, SupportLevel
from benchbox.sql_compat.registry import REGISTRY

REGISTRY.register(
    CompatibilityDecision(
        rule_id="benchmark_gate.questdb.vector_search.unsupported",
        action=CompatAction.BLOCK_BENCHMARK,
        support_level=SupportLevel.BLOCKED,
        failure_mode=FailureMode.UNSUPPORTED_FEATURE,
        payload=BlockBenchmarkPayload(
            reason=(
                "QuestDB 9.3.4 has no VECTOR column type. "
                "Schema creation fails immediately. "
                "No fix planned: requires QuestDB to add native vector support."
            )
        ),
        reason=(
            "QuestDB 9.3.4 has no VECTOR column type. "
            "Schema creation fails immediately. "
            "No fix planned: requires QuestDB to add native vector support."
        ),
    ),
    Phase.BENCHMARK_GATE,
    "questdb",
    benchmark="vector_search",
)
