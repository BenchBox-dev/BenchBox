"""Benchmark gates for capabilities absent from embedded ClickHouse Local."""

from __future__ import annotations

from benchbox.sql_compat.actions import CompatAction
from benchbox.sql_compat.context import Phase
from benchbox.sql_compat.decision import BlockBenchmarkPayload, CompatibilityDecision, FailureMode, SupportLevel
from benchbox.sql_compat.registry import REGISTRY

_REASON = (
    "clickhouse-local runs embedded chDB as its built-in default user. The local connection cannot grant the "
    "SHOW USERS/SHOW ROLES privileges required by metadata_primitives ACL introspection (system.users, "
    "system.roles, and system.grants). Use clickhouse-server or ClickHouse Cloud with an appropriately privileged "
    "user for this benchmark."
)

REGISTRY.register(
    CompatibilityDecision(
        rule_id="benchmark_gate.clickhouse-local.metadata_primitives.unsupported",
        action=CompatAction.BLOCK_BENCHMARK,
        support_level=SupportLevel.BLOCKED,
        failure_mode=FailureMode.UNSUPPORTED_FEATURE,
        payload=BlockBenchmarkPayload(reason=_REASON),
        reason="Embedded ClickHouse Local has no privileged ACL introspection contract.",
    ),
    Phase.BENCHMARK_GATE,
    "clickhouse-local",
    benchmark="metadata_primitives",
)
