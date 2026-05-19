"""pg_mooncake DDL compatibility rule for Phase.DDL_OPTIMIZE.

pg_mooncake 0.2.0 cannot load data with PostgreSQL COPY directly into
``USING mooncake`` access-method tables. BenchBox therefore keeps CREATE TABLE
DDL as PostgreSQL heap DDL for the load phase, then promotes loaded tables into
mooncake mirrors via ``mooncake.create_table``.

This governance-only rule records that the pg_mooncake DDL optimization is
implemented outside ``BaseDdlOptimizer`` by the adapter load/promotion path.
"""

from __future__ import annotations

from benchbox.sql_compat.actions import CompatAction
from benchbox.sql_compat.context import Phase
from benchbox.sql_compat.decision import (
    CompatibilityDecision,
    FailureMode,
    RewriteDDLPayload,
    SupportLevel,
)
from benchbox.sql_compat.registry import REGISTRY

REGISTRY.register(
    CompatibilityDecision(
        rule_id="ddl_optimize.pg_mooncake.all.heap_load_then_mooncake_mirror",
        action=CompatAction.REWRITE_DDL,
        support_level=SupportLevel.REWRITTEN,
        failure_mode=FailureMode.PERFORMANCE_REGRESSION,
        payload=RewriteDDLPayload(
            transformer_id="pg_mooncake_heap_load_then_mirror",
            description=(
                "Keep CREATE TABLE loadable as heap DDL, then promote loaded tables "
                "into mooncake mirrors with the original benchmark table names."
            ),
            governance_only=True,
        ),
        reason=(
            "Direct COPY into mooncake access-method tables fails on pg_mooncake 0.2.0; "
            "heap-load plus mirror promotion preserves both load compatibility and "
            "DuckDB-backed columnar query execution."
        ),
    ),
    Phase.DDL_OPTIMIZE,
    "pg_mooncake",
)
