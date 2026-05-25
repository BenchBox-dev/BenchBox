"""Redshift DDL rewrite rules for Phase.DDL_OPTIMIZE.

Redshift benefits from explicit distribution and sort key declarations for
analytical workloads. DuckDB DDL output does not include these clauses.

RedshiftAdapter._optimize_table_definition() is the runtime implementation for
these transformations. This rule registers the REWRITE_DDL intent for governance -
compat_lint enforcement only; transformer_id is not resolved at runtime.
"""

from __future__ import annotations

from benchbox.sql_compat.rules._registration import register_ddl_rewrite

register_ddl_rewrite(
    platform="redshift",
    rule_name="optimize_table_definition",
    transformer_id="redshift_ddl_optimizer",
    description="Append Redshift distribution and sort key clauses to CREATE TABLE: DISTSTYLE AUTO and SORTKEY AUTO",
    reason="Redshift requires explicit DISTSTYLE and SORTKEY declarations for optimal "
    "analytical performance; DuckDB DDL output omits these Redshift-specific clauses.",
)
