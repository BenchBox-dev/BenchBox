"""QuestDB DDL rewrite rules for Phase.DDL_OPTIMIZE.

QuestDB 9.3.4 rejects both FOREIGN KEY and PRIMARY KEY constraint syntax in
CREATE TABLE statements. The shared strip_foreign_keys() helper handles FK
and inline REFERENCES stripping; QuestDBAdapter._strip_pk_constraints() handles
PRIMARY KEY stripping.

This rule registers the REWRITE_DDL intent for governance - compat_lint enforcement
only; transformer_id is not resolved at runtime.
"""

from __future__ import annotations

from benchbox.sql_compat.rules._registration import register_ddl_rewrite

register_ddl_rewrite(
    platform="questdb",
    rule_name="strip_fk_and_pk_constraints",
    transformer_id="questdb_strip_fk_and_pk_constraints",
    description="Remove FOREIGN KEY and PRIMARY KEY constraint clauses from CREATE TABLE; "
    "QuestDB 9.3.4 rejects both with 'unsupported column type: KEY'. "
    "Also strips inline column-level REFERENCES clauses (QuestDB-specific).",
    reason="QuestDB does not support FOREIGN KEY or PRIMARY KEY constraint syntax. "
    "QuestDB 9.3.4 raises 'Schema statement failed: unsupported column type: KEY' "
    "when either is present in a CREATE TABLE statement.",
)
