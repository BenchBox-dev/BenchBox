"""Unit tests for PgMooncakeDDLGenerator.

Tests the PgMooncakeDDLGenerator class for:
- USING columnstore appended to CREATE TABLE statements
- Empty tuning clauses (columnstore manages its own layout)
- No partition children generated

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import pytest

from benchbox.core.tuning import TuningColumn
from benchbox.core.tuning.ddl_generator import ColumnDefinition, ColumnNullability, TuningClauses
from benchbox.core.tuning.generators.pg_mooncake import PgMooncakeDDLGenerator
from benchbox.core.tuning.interface import TableTuning

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


@pytest.fixture
def generator() -> PgMooncakeDDLGenerator:
    return PgMooncakeDDLGenerator()


@pytest.fixture
def simple_columns() -> list[ColumnDefinition]:
    return [
        ColumnDefinition(name="id", data_type="INTEGER", nullable=ColumnNullability.NOT_NULL),
        ColumnDefinition(name="name", data_type="TEXT", nullable=ColumnNullability.NULLABLE),
    ]


class TestPgMooncakePlatformName:
    """Tests for platform name property."""

    def test_platform_name(self, generator: PgMooncakeDDLGenerator) -> None:
        assert generator.platform_name == "pg_mooncake"

    def test_platform_name_not_postgresql(self, generator: PgMooncakeDDLGenerator) -> None:
        assert generator.platform_name != "postgresql"


class TestPgMooncakeTuningClauses:
    """Tests for generate_tuning_clauses."""

    def test_returns_empty_clauses_with_no_tuning(self, generator: PgMooncakeDDLGenerator) -> None:
        """Columnstore tables need no PostgreSQL tuning."""
        clauses = generator.generate_tuning_clauses(None)
        assert isinstance(clauses, TuningClauses)
        # All fields should be empty/None — columnstore manages its own layout
        assert not clauses.partition_by
        assert not clauses.cluster_by

    def test_returns_empty_clauses_even_with_partitioning_config(self, generator: PgMooncakeDDLGenerator) -> None:
        """Even if TableTuning specifies partitioning, pg_mooncake ignores it."""
        table_tuning = TableTuning(
            table_name="orders",
            partitioning=[TuningColumn(name="order_date", type="DATE", order=1)],
        )
        clauses = generator.generate_tuning_clauses(table_tuning)
        assert isinstance(clauses, TuningClauses)
        assert not clauses.partition_by

    def test_returns_empty_clauses_with_platform_opts(self, generator: PgMooncakeDDLGenerator) -> None:
        """Platform options are also ignored for columnstore."""
        clauses = generator.generate_tuning_clauses(None, platform_opts=None)
        assert isinstance(clauses, TuningClauses)


class TestPgMooncakeCreateTableDDL:
    """Tests for generate_create_table_ddl."""

    def test_appends_using_columnstore(
        self, generator: PgMooncakeDDLGenerator, simple_columns: list[ColumnDefinition]
    ) -> None:
        """CREATE TABLE should end with USING columnstore."""
        clauses = TuningClauses()
        ddl = generator.generate_create_table_ddl("my_table", simple_columns, clauses)
        assert "USING columnstore" in ddl

    def test_ddl_contains_table_name(
        self, generator: PgMooncakeDDLGenerator, simple_columns: list[ColumnDefinition]
    ) -> None:
        clauses = TuningClauses()
        ddl = generator.generate_create_table_ddl("lineitem", simple_columns, clauses)
        assert "lineitem" in ddl

    def test_ddl_contains_columns(
        self, generator: PgMooncakeDDLGenerator, simple_columns: list[ColumnDefinition]
    ) -> None:
        clauses = TuningClauses()
        ddl = generator.generate_create_table_ddl("my_table", simple_columns, clauses)
        assert "id" in ddl
        assert "name" in ddl

    def test_using_columnstore_not_duplicated_if_already_present(
        self, generator: PgMooncakeDDLGenerator, simple_columns: list[ColumnDefinition]
    ) -> None:
        """Should not double-append USING columnstore."""
        clauses = TuningClauses()
        ddl = generator.generate_create_table_ddl("t", simple_columns, clauses)
        assert ddl.count("USING columnstore") == 1

    def test_ddl_with_schema(self, generator: PgMooncakeDDLGenerator, simple_columns: list[ColumnDefinition]) -> None:
        """Should include schema prefix when provided."""
        clauses = TuningClauses()
        ddl = generator.generate_create_table_ddl("orders", simple_columns, clauses, schema="public")
        assert "orders" in ddl
        assert "USING columnstore" in ddl

    def test_ddl_ends_with_semicolon(
        self, generator: PgMooncakeDDLGenerator, simple_columns: list[ColumnDefinition]
    ) -> None:
        """DDL should terminate with a semicolon."""
        clauses = TuningClauses()
        ddl = generator.generate_create_table_ddl("t", simple_columns, clauses)
        assert ddl.rstrip().endswith(";")


class TestPgMooncakePartitionChildren:
    """Tests for generate_partition_children."""

    def test_returns_empty_list(
        self, generator: PgMooncakeDDLGenerator, simple_columns: list[ColumnDefinition]
    ) -> None:
        """Columnstore tables manage partitioning via Iceberg; no children needed."""
        clauses = TuningClauses()
        children = generator.generate_partition_children("orders", simple_columns, clauses)
        assert children == []

    def test_returns_empty_list_with_table_tuning(
        self, generator: PgMooncakeDDLGenerator, simple_columns: list[ColumnDefinition]
    ) -> None:
        table_tuning = TableTuning(
            table_name="orders",
            partitioning=[TuningColumn(name="order_date", type="DATE", order=1)],
        )
        clauses = TuningClauses()
        children = generator.generate_partition_children("orders", simple_columns, clauses, table_tuning=table_tuning)
        assert children == []
