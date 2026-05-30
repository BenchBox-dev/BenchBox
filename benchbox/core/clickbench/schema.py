"""ClickBench schema definitions.

The ClickBench ``hits`` table is a single flat web analytics table. The column
specification lives in ``schema_specs.yaml``; the generator intentionally keeps
most unsigned ClickHouse source columns within signed SMALLINT ranges. Columns
that can exceed SMALLINT_MAX in BenchBox data remain widened to INTEGER/BIGINT.
"""

from pathlib import Path
from typing import cast

import yaml

from benchbox.core.tuning import BenchmarkTunings, TableTuning, TuningColumn


def _load_schema_specs() -> dict:
    with (Path(__file__).with_name("schema_specs.yaml")).open(encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


HITS_TABLE = _load_schema_specs()["hits_table"]


def get_create_table_sql(
    dialect: str = "standard",
    enable_primary_keys: bool = True,
    enable_foreign_keys: bool = True,
) -> str:
    """Generate CREATE TABLE SQL for the ClickBench hits table."""
    table = HITS_TABLE
    target = dialect.lower()
    enforce_not_null = target not in {"spark", "lakesail", "pyspark"}
    columns = []

    for col in table["columns"]:
        col_def = f"{cast(str, col['name'])} {cast(str, col['type'])}"
        if enforce_not_null and not col.get("nullable", True):
            col_def += " NOT NULL"
        columns.append(f"  {col_def}")

    if table.get("primary_key") and enable_primary_keys:
        pk_cols = ", ".join(cast(list[str], table["primary_key"]))
        columns.append(f"  PRIMARY KEY ({pk_cols})")

    columns_sql = ",\n".join(columns)
    return f"""CREATE TABLE {table["name"]} (
{columns_sql}
);"""


TABLES = {"hits": HITS_TABLE}


def get_tunings() -> BenchmarkTunings:
    """Get the default tuning configurations for ClickBench tables."""
    tunings = BenchmarkTunings("clickbench")
    tunings.add_table_tuning(
        TableTuning(
            table_name="hits",
            partitioning=[TuningColumn("EventDate", "DATE", 1)],
            clustering=[
                TuningColumn("CounterID", "BIGINT", 1),
                TuningColumn("UserID", "BIGINT", 2),
            ],
            sorting=[
                TuningColumn("EventTime", "TIMESTAMP", 1),
                TuningColumn("RegionID", "BIGINT", 2),
            ],
        )
    )
    return tunings
