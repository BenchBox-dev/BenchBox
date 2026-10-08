from pathlib import Path
from typing import Any, cast

import yaml

from benchbox.core.schema_primitives import get_fk_ordered_table_names_from_column_specs
from benchbox.core.tuning import BenchmarkTunings, TableTuning, TuningColumn


def _load_schema_specs() -> dict[str, Any]:
    with (Path(__file__).with_name("schema_specs.yaml")).open(encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


_SCHEMA_SPECS = _load_schema_specs()
_TABLE_DEFS = {entry["id"]: entry for entry in _SCHEMA_SPECS["tables"]}
globals().update({symbol: entry["schema"] for symbol, entry in _TABLE_DEFS.items()})

TABLES: dict[str, dict] = {entry["key"]: globals()[symbol] for symbol, entry in _TABLE_DEFS.items()}
_TABLE_ORDER = list(_SCHEMA_SPECS["table_order"])


def get_table_loading_order() -> list[str]:

    return get_fk_ordered_table_names_from_column_specs(TABLES)


def get_create_table_sql(
    table_name: str,
    dialect: str = "standard",
    enable_primary_keys: bool = True,
    enable_foreign_keys: bool = True,
) -> str:

    if table_name not in TABLES:
        raise ValueError(f"Unknown table: {table_name}")

    table = TABLES[table_name]
    columns = []

    for col in cast(list, table["columns"]):
        col_def = f"{cast(str, col['name'])} {cast(str, col['type'])}"
        if col.get("primary_key") and enable_primary_keys:
            col_def += " PRIMARY KEY"
        columns.append(col_def)

    if "primary_key" in table and isinstance(table["primary_key"], list) and enable_primary_keys:
        pk_cols = ", ".join(cast(list[str], table["primary_key"]))
        columns.append(f"PRIMARY KEY ({pk_cols})")

    table_name_lower = cast(str, table["name"]).lower()
    sql = f"CREATE TABLE {table_name_lower} (\n"
    sql += ",\n".join(f"  {col}" for col in columns)
    sql += "\n);"

    return sql


def get_all_create_table_sql(
    dialect: str = "standard",
    enable_primary_keys: bool = True,
    enable_foreign_keys: bool = True,
) -> str:

    from benchbox.core.schema_utils import collect_create_table_sql

    return collect_create_table_sql(
        _TABLE_ORDER,
        get_create_table_sql,
        dialect,
        enable_primary_keys=enable_primary_keys,
        enable_foreign_keys=enable_foreign_keys,
    )


def get_tunings() -> BenchmarkTunings:

    tunings = BenchmarkTunings("ssb")

    lineorder_tuning = TableTuning(
        table_name="lineorder",
        partitioning=[TuningColumn("lo_orderdate", "INTEGER", 1)],
        clustering=[
            TuningColumn("lo_custkey", "INTEGER", 1),
            TuningColumn("lo_suppkey", "INTEGER", 2),
        ],
        sorting=[
            TuningColumn("lo_orderkey", "INTEGER", 1),
            TuningColumn("lo_linenumber", "INTEGER", 2),
        ],
    )
    tunings.add_table_tuning(lineorder_tuning)

    date_tuning = TableTuning(table_name="date", sorting=[TuningColumn("d_datekey", "INTEGER", 1)])
    tunings.add_table_tuning(date_tuning)

    customer_tuning = TableTuning(
        table_name="customer",
        distribution=[TuningColumn("c_custkey", "INTEGER", 1)],
        sorting=[
            TuningColumn("c_region", "VARCHAR(12)", 1),
            TuningColumn("c_nation", "VARCHAR(15)", 2),
        ],
    )
    tunings.add_table_tuning(customer_tuning)

    supplier_tuning = TableTuning(
        table_name="supplier",
        distribution=[TuningColumn("s_suppkey", "INTEGER", 1)],
        sorting=[
            TuningColumn("s_region", "VARCHAR(12)", 1),
            TuningColumn("s_nation", "VARCHAR(15)", 2),
        ],
    )
    tunings.add_table_tuning(supplier_tuning)

    part_tuning = TableTuning(
        table_name="part",
        distribution=[TuningColumn("p_partkey", "INTEGER", 1)],
        sorting=[
            TuningColumn("p_category", "VARCHAR(7)", 1),
            TuningColumn("p_brand1", "VARCHAR(9)", 2),
        ],
    )
    tunings.add_table_tuning(part_tuning)

    return tunings
