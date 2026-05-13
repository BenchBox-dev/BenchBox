from __future__ import annotations

import pytest

from benchbox.core.tuning import TuningColumn
from benchbox.core.tuning.ddl_generator import ColumnDefinition, ColumnNullability
from benchbox.core.tuning.generators.pg_mooncake import PgMooncakeDDLGenerator
from benchbox.core.tuning.interface import PlatformOptimizationConfiguration, TableTuning

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


def _make_columns() -> list[ColumnDefinition]:
    return [
        ColumnDefinition("id", "BIGINT", ColumnNullability.NOT_NULL),
        ColumnDefinition("order_date", "DATE"),
    ]


def test_platform_name_and_tuning_clauses_ignore_postgresql_options() -> None:
    generator = PgMooncakeDDLGenerator()
    table_tuning = TableTuning(
        table_name="orders",
        partitioning=[TuningColumn(name="order_date", type="DATE", order=1)],
        clustering=[TuningColumn(name="id", type="BIGINT", order=1)],
        sorting=[TuningColumn(name="id", type="BIGINT", order=1)],
        distribution=[TuningColumn(name="id", type="BIGINT", order=1)],
    )

    clauses = generator.generate_tuning_clauses(table_tuning, PlatformOptimizationConfiguration())

    assert generator.platform_name == "pg_mooncake"
    assert clauses.is_empty()


def test_generate_create_table_ddl_preserves_heap_load_ddl_and_skips_partition_fragments() -> None:
    generator = PgMooncakeDDLGenerator()
    tuning = generator.generate_tuning_clauses(
        TableTuning(
            table_name="orders",
            partitioning=[TuningColumn(name="order_date", type="DATE", order=1)],
        )
    )

    ddl = generator.generate_create_table_ddl("orders", _make_columns(), tuning)

    assert "CREATE TABLE orders" in ddl
    assert "id BIGINT NOT NULL" in ddl
    assert "order_date DATE" in ddl
    assert "PARTITION BY" not in ddl
    assert "USING mooncake" not in ddl
    assert ddl.endswith(";")


def test_generate_create_table_ddl_preserves_postgresql_base_shape_without_mooncake_access_method() -> None:
    generator = PgMooncakeDDLGenerator()

    ddl = generator.generate_create_table_ddl(
        "orders", _make_columns(), tuning=generator.generate_tuning_clauses(None), schema="public"
    )

    assert "CREATE TABLE IF NOT EXISTS orders" in ddl
    assert "id BIGINT NOT NULL" in ddl
    assert "USING mooncake" not in ddl


@pytest.mark.parametrize(
    "table_tuning",
    [
        None,
        TableTuning(
            table_name="orders",
            partitioning=[TuningColumn(name="order_date", type="DATE", order=1)],
        ),
    ],
)
def test_generate_partition_children_always_returns_empty_list(table_tuning: TableTuning | None) -> None:
    generator = PgMooncakeDDLGenerator()

    children = generator.generate_partition_children(
        "orders",
        _make_columns(),
        tuning=generator.generate_tuning_clauses(table_tuning),
        table_tuning=table_tuning,
    )

    assert children == []
