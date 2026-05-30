"""SingleStore DDL rewrite rules for Phase.DDL_OPTIMIZE.

SingleStore requires several DDL transformations on CREATE TABLE statements generated
by DuckDB, each registered here for governance / compat_lint audit. The runtime
implementations live in ``benchbox/platforms/singlestore.py`` as methods named by
``transformer_id``; ``BaseDdlOptimizer`` dispatches them in registration order.

Four transforms (applied in this order — order is load-bearing):
  1. strip_foreign_keys         – SingleStore raises error 2752 on FK clauses.
  2. reference_table_for_dims   – small dimension tables use REFERENCE TABLE replication.
                                  Must run before inject_shard_key so REFERENCE TABLE
                                  is visible in the stmt when the shard/sort guards fire.
  3. inject_shard_key           – columnstore tables need SHARD KEY for distribution.
  4. inject_sort_key            – SORT KEY drives analytical ordering.

IMPORTANT — multi-rule conflict:
  All four rules are registered at the same (Phase.DDL_OPTIMIZE, "singlestore") key.
  REGISTRY.resolve() will raise CompatibilityRegistryConflict for this platform+phase
  because multiple candidates match. Use REGISTRY.resolve_all() for governance/audit
  queries (see tests/unit/sql_compat/test_singlestore_rules.py).
  Do NOT pass SingleStore through CompatibilityResolver.build_plan() — build_plan()
  calls resolve() for every Phase.
"""

from __future__ import annotations

from benchbox.sql_compat.decision import FailureMode
from benchbox.sql_compat.rules._registration import register_ddl_rewrite

register_ddl_rewrite(
    platform="singlestore",
    rule_name="strip_foreign_keys",
    transformer_id="singlestore_strip_foreign_keys",
    description="Remove FOREIGN KEY clauses from CREATE TABLE (SingleStore error 2752).",
    reason="SingleStore raises error 2752 when a CREATE TABLE statement contains FOREIGN KEY "
    "clauses with referential actions. FK constraints are stripped so tables can be created "
    "without enforcement (acceptable for benchmarking workloads).",
    governance_only=False,
)

register_ddl_rewrite(
    platform="singlestore",
    rule_name="reference_table_for_dimensions",
    transformer_id="singlestore_reference_table",
    description="Rewrite small dimension tables (nation, region) to CREATE REFERENCE TABLE.",
    reason="Small TPC-H dimension tables (nation, region) benefit from REFERENCE TABLE replication "
    "in SingleStore, which eliminates broadcast joins at query time. "
    "Tables in _REFERENCE_TABLES are converted from CREATE TABLE to CREATE REFERENCE TABLE.",
    failure_mode=FailureMode.PERFORMANCE_REGRESSION,
    governance_only=False,
)

register_ddl_rewrite(
    platform="singlestore",
    rule_name="inject_shard_key",
    transformer_id="singlestore_inject_shard_key",
    description="Inject SHARD KEY clause for columnstore tables (per-table or random distribution).",
    reason="SingleStore columnstore tables require an explicit SHARD KEY for data distribution. "
    "Without it, tables default to random sharding which degrades co-located join performance. "
    "Shard columns are mapped from _TPCH_SHARD_KEYS; tables without a known shard column "
    "receive SHARD KEY () (random distribution).",
    failure_mode=FailureMode.PERFORMANCE_REGRESSION,
    governance_only=False,
)

register_ddl_rewrite(
    platform="singlestore",
    rule_name="inject_sort_key",
    transformer_id="singlestore_inject_sort_key",
    description="Inject SORT KEY clause for columnstore tables from _TPCH_SORT_KEYS mapping.",
    reason="SingleStore columnstore SORT KEY controls the on-disk ordering used by analytical scans. "
    "Without an appropriate sort key, range-scan and aggregation queries suffer. "
    "Sort columns are mapped from _TPCH_SORT_KEYS per table.",
    failure_mode=FailureMode.PERFORMANCE_REGRESSION,
    governance_only=False,
)
