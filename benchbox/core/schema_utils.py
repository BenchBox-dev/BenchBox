from __future__ import annotations

from collections.abc import Callable


def collect_create_table_sql(
    table_order: list[str],
    get_single_table_fn: Callable[..., str],
    dialect: str = "standard",
    *,
    enable_primary_keys: bool = True,
    enable_foreign_keys: bool = True,
) -> str:
    sql_statements = []
    for table_name in table_order:
        sql_statements.append(
            get_single_table_fn(
                table_name,
                dialect,
                enable_primary_keys=enable_primary_keys,
                enable_foreign_keys=enable_foreign_keys,
            )
        )
    return "\n\n".join(sql_statements)
