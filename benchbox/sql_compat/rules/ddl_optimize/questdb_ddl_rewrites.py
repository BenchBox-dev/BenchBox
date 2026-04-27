"""QuestDB DDL rewrite rules for Phase.DDL_OPTIMIZE.

QuestDB 9.3.4 rejects both FOREIGN KEY and PRIMARY KEY constraint syntax in
CREATE TABLE statements. The shared strip_foreign_keys() helper handles FK
and inline REFERENCES stripping; QuestDBAdapter._strip_pk_constraints() handles
PRIMARY KEY stripping.

This rule registers the REWRITE_DDL intent for governance - compat_lint enforcement
only; transformer_id is not resolved at runtime.
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
        rule_id="ddl_optimize.questdb.all.strip_fk_and_pk_constraints",
        action=CompatAction.REWRITE_DDL,
        support_level=SupportLevel.REWRITTEN,
        failure_mode=FailureMode.SYNTAX_ERROR,
        payload=RewriteDDLPayload(
            transformer_id="questdb_strip_fk_and_pk_constraints",
            description=(
                "Remove FOREIGN KEY and PRIMARY KEY constraint clauses from CREATE TABLE; "
                "QuestDB 9.3.4 rejects both with 'unsupported column type: KEY'. "
                "Also strips inline column-level REFERENCES clauses (QuestDB-specific)."
            ),
            governance_only=True,
        ),
        reason=(
            "QuestDB does not support FOREIGN KEY or PRIMARY KEY constraint syntax. "
            "QuestDB 9.3.4 raises 'Schema statement failed: unsupported column type: KEY' "
            "when either is present in a CREATE TABLE statement."
        ),
    ),
    Phase.DDL_OPTIMIZE,
    "questdb",
)
