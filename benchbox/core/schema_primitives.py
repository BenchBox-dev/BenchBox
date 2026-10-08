from __future__ import annotations

from typing import Any


class BaseSchemaTable:
    def __init__(self, name: str, columns: list[Any]) -> None:
        self.name = name
        self.columns = columns

    def get_primary_key(self) -> list[str]:
        return [col.name for col in self.columns if col.primary_key]

    def get_foreign_keys(self) -> dict[str, tuple[str, str]]:
        return {col.name: col.foreign_key for col in self.columns if col.foreign_key is not None}

    def get_create_table_sql(
        self,
        enable_primary_keys: bool = True,
        enable_foreign_keys: bool = True,
    ) -> str:
        column_defs: list[str] = []
        pk_columns: list[str] = []
        fk_defs: list[str] = []

        for col in self.columns:
            col_def = f"{col.name} {col.get_sql_type()}"

            if not col.nullable:
                col_def += " NOT NULL"

            if col.primary_key and enable_primary_keys:
                pk_columns.append(col.name)

            if col.foreign_key and enable_foreign_keys:
                ref_table, ref_col = col.foreign_key
                fk_defs.append(f"FOREIGN KEY ({col.name}) REFERENCES {ref_table}({ref_col})")

            column_defs.append(col_def)

        if pk_columns and enable_primary_keys:
            column_defs.append(f"PRIMARY KEY ({', '.join(pk_columns)})")

        if enable_foreign_keys:
            column_defs.extend(fk_defs)

        sql = f"CREATE TABLE {self.name} (\n    "
        sql += ",\n    ".join(column_defs)
        sql += "\n);"

        return sql


def get_fk_ordered_table_names(tables: list[Any]) -> list[str]:
    names = [table.name for table in tables]
    name_set = set(names)
    deps: dict[str, set[str]] = {
        table.name: {
            ref_table
            for ref_table, _ref_col in table.get_foreign_keys().values()
            if ref_table in name_set and ref_table != table.name
        }
        for table in tables
    }
    return _stable_topological_order(names, deps)


def _stable_topological_order(names: list[str], deps: dict[str, set[str]]) -> list[str]:
    ordered: list[str] = []
    placed: set[str] = set()
    remaining = list(names)

    while remaining:
        progressed = False
        for name in list(remaining):
            if deps.get(name, set()) <= placed:
                ordered.append(name)
                placed.add(name)
                remaining.remove(name)
                progressed = True
        if not progressed:
            ordered.extend(remaining)
            break

    return ordered


class _DottedForeignKeyTable:
    def __init__(self, name: str, table_spec: dict[str, Any]) -> None:
        self.name = name
        self._columns = table_spec.get("columns", [])

    def get_foreign_keys(self) -> dict[str, tuple[str, str]]:
        result: dict[str, tuple[str, str]] = {}
        for column in self._columns:
            foreign_key = column.get("foreign_key")
            if foreign_key:
                ref_table, ref_column = foreign_key.split(".", 1)
                result[column["name"]] = (ref_table, ref_column)
        return result


def get_fk_ordered_table_names_from_column_specs(tables: dict[str, dict[str, Any]]) -> list[str]:
    adapters = [_DottedForeignKeyTable(name, spec) for name, spec in tables.items()]
    return get_fk_ordered_table_names(adapters)
