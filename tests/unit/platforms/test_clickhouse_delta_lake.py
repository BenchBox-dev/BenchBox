"""Unit tests for native ClickHouse Delta Lake SQL builders.

Server-free: these tests pin the exact SQL BenchBox generates for native
Delta reads (``deltaLake`` table function, ``deltaLakeLocal``, and the
``DeltaLake`` engine), including quoting and validation. Live execution
against a real server is covered by the Docker-gated native suite.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import pytest

from benchbox.platforms.clickhouse.delta_lake import (
    delta_lake_count_sql,
    delta_lake_engine_ddl,
    delta_lake_local_table_function,
    delta_lake_select_sql,
    delta_lake_table_function,
    quote_identifier,
    quote_literal,
)

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


class TestQuoteLiteral:
    def test_wraps_simple_value(self) -> None:
        assert quote_literal("s3://bucket/table") == "'s3://bucket/table'"

    def test_escapes_single_quote_and_backslash(self) -> None:
        assert quote_literal("o'clock\\path") == "'o\\'clock\\\\path'"

    def test_rejects_empty_value(self) -> None:
        with pytest.raises(ValueError, match="empty"):
            quote_literal("   ")


class TestQuoteIdentifier:
    def test_wraps_table_name(self) -> None:
        assert quote_identifier("orders") == "`orders`"

    def test_escapes_backtick(self) -> None:
        assert quote_identifier("odd`name") == "`odd\\`name`"

    def test_rejects_empty_name(self) -> None:
        with pytest.raises(ValueError, match="empty"):
            quote_identifier("")


class TestTableFunction:
    def test_bare_url(self) -> None:
        assert delta_lake_table_function("s3://bucket/orders") == "deltaLake('s3://bucket/orders')"

    def test_s3_alias(self) -> None:
        assert (
            delta_lake_table_function("s3://bucket/orders", function="deltaLakeS3")
            == "deltaLakeS3('s3://bucket/orders')"
        )

    def test_with_credentials(self) -> None:
        assert (
            delta_lake_table_function("s3://bucket/orders", access_key_id="AK", secret_access_key="SK")
            == "deltaLake('s3://bucket/orders', 'AK', 'SK')"
        )

    def test_credential_values_are_quoted(self) -> None:
        expression = delta_lake_table_function("s3://bucket/orders", access_key_id="a'k", secret_access_key="s\\k")
        assert expression == "deltaLake('s3://bucket/orders', 'a\\'k', 's\\\\k')"

    def test_rejects_empty_url(self) -> None:
        with pytest.raises(ValueError, match="non-empty URL"):
            delta_lake_table_function("")

    def test_rejects_unknown_function(self) -> None:
        with pytest.raises(ValueError, match="Unknown Delta Lake table function"):
            delta_lake_table_function("s3://bucket/orders", function="deltaLakeLocal")

    def test_rejects_lone_credential(self) -> None:
        with pytest.raises(ValueError, match="together or not at all"):
            delta_lake_table_function("s3://bucket/orders", access_key_id="AK")


class TestLocalTableFunction:
    def test_builds_expression(self) -> None:
        assert delta_lake_local_table_function("/data/orders") == "deltaLakeLocal('/data/orders')"

    def test_rejects_empty_path(self) -> None:
        with pytest.raises(ValueError, match="non-empty path"):
            delta_lake_local_table_function("  ")


class TestEngineDdl:
    def test_bare_attach(self) -> None:
        assert delta_lake_engine_ddl("orders", "s3://bucket/orders") == (
            "CREATE TABLE `orders` ENGINE = DeltaLake('s3://bucket/orders')"
        )

    def test_database_qualified_with_credentials(self) -> None:
        assert delta_lake_engine_ddl(
            "orders",
            "s3://bucket/orders",
            database="lake",
            access_key_id="AK",
            secret_access_key="SK",
        ) == ("CREATE TABLE `lake`.`orders` ENGINE = DeltaLake('s3://bucket/orders', 'AK', 'SK')")

    def test_rejects_empty_table(self) -> None:
        with pytest.raises(ValueError, match="empty"):
            delta_lake_engine_ddl("", "s3://bucket/orders")

    def test_rejects_lone_credential(self) -> None:
        with pytest.raises(ValueError, match="together or not at all"):
            delta_lake_engine_ddl("orders", "s3://bucket/orders", secret_access_key="SK")


class TestSelectAndCount:
    def test_select_star_with_limit(self) -> None:
        source = delta_lake_table_function("s3://bucket/orders")
        assert delta_lake_select_sql(source, limit=10) == ("SELECT * FROM deltaLake('s3://bucket/orders') LIMIT 10")

    def test_select_column_list_is_quoted(self) -> None:
        source = delta_lake_local_table_function("/data/orders")
        assert delta_lake_select_sql(source, columns=["id", "v"]) == (
            "SELECT `id`, `v` FROM deltaLakeLocal('/data/orders')"
        )

    def test_select_rejects_empty_columns(self) -> None:
        with pytest.raises(ValueError, match="at least one column"):
            delta_lake_select_sql("deltaLake('s3://b/t')", columns=[])

    def test_select_rejects_negative_limit(self) -> None:
        with pytest.raises(ValueError, match="non-negative"):
            delta_lake_select_sql("deltaLake('s3://b/t')", limit=-1)

    def test_count(self) -> None:
        assert delta_lake_count_sql("deltaLake('s3://bucket/orders')") == (
            "SELECT count() FROM deltaLake('s3://bucket/orders')"
        )

    def test_count_rejects_empty_source(self) -> None:
        with pytest.raises(ValueError, match="non-empty source"):
            delta_lake_count_sql("  ")
