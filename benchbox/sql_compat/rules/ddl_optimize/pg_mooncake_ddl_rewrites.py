"""pg_mooncake DDL rewrite rules for Phase.DDL_OPTIMIZE.

pg_mooncake (a PostgreSQL columnstore extension) appends ``USING columnstore``
to every CREATE TABLE statement so tables land in the columnstore access method
instead of the default heap. The transformation happens inside
``PgMooncakeAdapter._transform_create_statement`` (an override of the
PostgreSQLAdapter hook); the parent ``create_schema`` flow calls that hook
directly rather than going through ``BaseDdlOptimizer``.

This rule registers the REWRITE_DDL intent for governance / compat_lint
enforcement only; ``transformer_id`` is documentary and not resolved at
runtime.
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
        rule_id="ddl_optimize.pg_mooncake.all.add_columnstore_access_method",
        action=CompatAction.REWRITE_DDL,
        support_level=SupportLevel.REWRITTEN,
        failure_mode=FailureMode.PERFORMANCE_REGRESSION,
        payload=RewriteDDLPayload(
            transformer_id="pg_mooncake_add_columnstore_access_method",
            description=(
                "Append ``USING columnstore`` to CREATE TABLE so pg_mooncake places the "
                "table in the columnstore access method instead of the default heap."
            ),
            governance_only=True,
        ),
        reason=(
            "Without ``USING columnstore``, pg_mooncake tables fall back to the row-store "
            "heap and lose the analytical scan performance the extension exists to provide."
        ),
    ),
    Phase.DDL_OPTIMIZE,
    "pg_mooncake",
)
