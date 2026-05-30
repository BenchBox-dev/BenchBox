"""pg_mooncake DDL compatibility rule for Phase.DDL_OPTIMIZE.

pg_mooncake 0.2.0 cannot load data with PostgreSQL COPY directly into
``USING mooncake`` access-method tables. BenchBox therefore keeps CREATE TABLE
DDL as PostgreSQL heap DDL for the load phase, then promotes loaded tables into
mooncake mirrors via ``mooncake.create_table``.

This governance-only rule records that the pg_mooncake DDL optimization is
implemented outside ``BaseDdlOptimizer`` by the adapter load/promotion path.
"""

from __future__ import annotations

from benchbox.sql_compat.decision import FailureMode
from benchbox.sql_compat.rules._registration import register_ddl_rewrite

register_ddl_rewrite(
    platform="pg_mooncake",
    rule_name="heap_load_then_mooncake_mirror",
    transformer_id="pg_mooncake_heap_load_then_mirror",
    description="Keep CREATE TABLE loadable as heap DDL, then promote loaded tables "
    "into mooncake mirrors with the original benchmark table names.",
    reason="Direct COPY into mooncake access-method tables fails on pg_mooncake 0.2.0; "
    "heap-load plus mirror promotion preserves both load compatibility and "
    "DuckDB-backed columnar query execution.",
    failure_mode=FailureMode.PERFORMANCE_REGRESSION,
)
