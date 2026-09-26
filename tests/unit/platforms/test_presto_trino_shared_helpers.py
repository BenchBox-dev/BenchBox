"""Unit tests for the untested presto_trino_utils shared helpers.

Pins the contract for validate_catalog_exists (auto-select, explicit match,
both ConfigurationError branches) and execute_schema_statements (normal
execution, normalize/optimize delegation, already-exists drop-and-recreate
recovery, non-recoverable error propagation, cursor cleanup).

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import logging
from unittest.mock import MagicMock

import pytest

from benchbox.core.exceptions import ConfigurationError
from benchbox.platforms.presto_trino_utils import (
    execute_schema_statements,
    validate_catalog_exists,
)

pytestmark = [pytest.mark.unit, pytest.mark.fast]


def _logger() -> logging.Logger:
    return logging.getLogger("test.presto-trino-utils")


class TestValidateCatalogExists:
    def test_explicit_catalog_matching_server_returns_not_auto_selected(self) -> None:
        catalog, auto = validate_catalog_exists(
            "hive",
            platform_name="Trino",
            auto_select_catalog=lambda: "memory",
            get_available_catalogs=lambda: ["hive", "memory"],
            logger=_logger(),
        )
        assert catalog == "hive"
        assert auto is False

    def test_none_catalog_auto_selects_first_usable(self) -> None:
        catalog, auto = validate_catalog_exists(
            None,
            platform_name="Trino",
            auto_select_catalog=lambda: "iceberg",
            get_available_catalogs=lambda: ["iceberg"],
            logger=_logger(),
        )
        assert catalog == "iceberg"
        assert auto is True

    def test_empty_string_catalog_triggers_auto_select(self) -> None:
        catalog, auto = validate_catalog_exists(
            "",
            platform_name="Presto",
            auto_select_catalog=lambda: "hive",
            get_available_catalogs=lambda: ["hive"],
            logger=_logger(),
        )
        assert catalog == "hive"
        assert auto is True

    def test_no_auto_select_with_system_only_catalogs_raises(self) -> None:
        with pytest.raises(ConfigurationError, match="system-only"):
            validate_catalog_exists(
                None,
                platform_name="Trino",
                auto_select_catalog=lambda: None,
                get_available_catalogs=lambda: ["system", "information_schema"],
                logger=_logger(),
            )

    def test_no_auto_select_unreachable_server_raises(self) -> None:
        with pytest.raises(ConfigurationError, match="server is unreachable"):
            validate_catalog_exists(
                None,
                platform_name="Trino",
                auto_select_catalog=lambda: None,
                get_available_catalogs=list,
                logger=_logger(),
            )

    def test_unlistable_catalogs_proceeds_with_specified(self) -> None:
        catalog, auto = validate_catalog_exists(
            "hive",
            platform_name="Trino",
            auto_select_catalog=lambda: None,
            get_available_catalogs=list,
            logger=_logger(),
        )
        assert catalog == "hive"
        assert auto is False

    def test_unknown_catalog_raises_with_available_list(self) -> None:
        with pytest.raises(ConfigurationError, match="does not exist"):
            validate_catalog_exists(
                "nosuch",
                platform_name="Trino",
                auto_select_catalog=lambda: None,
                get_available_catalogs=lambda: ["hive", "memory"],
                logger=_logger(),
            )

    def test_unknown_catalog_message_lists_available(self) -> None:
        try:
            validate_catalog_exists(
                "nosuch",
                platform_name="Trino",
                auto_select_catalog=lambda: None,
                get_available_catalogs=lambda: ["hive", "memory"],
                logger=_logger(),
            )
            raise AssertionError("expected ConfigurationError")
        except ConfigurationError as exc:
            assert "Available catalogs: hive, memory" in str(exc)


class TestExecuteSchemaStatements:
    def _run(
        self,
        schema_sql: str,
        cursor: MagicMock,
        *,
        normalize=lambda s: s,
        optimize=lambda s: s,
        extract=lambda s: None,
    ) -> MagicMock:
        connection = MagicMock()
        connection.cursor.return_value = cursor
        notices = MagicMock()
        execute_schema_statements(
            schema_sql,
            connection,
            _logger(),
            normalize_table_name_in_sql=normalize,
            optimize_table_definition=optimize,
            extract_table_name=extract,
            log_notice=notices,
        )
        return notices

    def test_executes_each_statement_and_closes_cursor(self) -> None:
        cursor = MagicMock()
        self._run("CREATE TABLE a (x INT); CREATE TABLE b (y INT)", cursor)
        executed = [c[0][0] for c in cursor.execute.call_args_list]
        assert executed == ["CREATE TABLE a (x INT)", "CREATE TABLE b (y INT)"]
        cursor.close.assert_called_once_with()

    def test_applies_normalize_and_optimize_in_order(self) -> None:
        cursor = MagicMock()
        order: list[str] = []
        self._run(
            "create table A (x int)",
            cursor,
            normalize=lambda s: order.append("normalize") or s.upper(),
            optimize=lambda s: order.append("optimize") or s + " WITH (format='PARQUET')",
        )
        assert order == ["normalize", "optimize"]
        assert cursor.execute.call_args[0][0] == "CREATE TABLE A (X INT) WITH (format='PARQUET')"

    def test_already_exists_drops_and_recreates(self) -> None:
        cursor = MagicMock()
        cursor.execute.side_effect = [RuntimeError("Table 't' already exists"), None, None]
        notices = self._run(
            "CREATE TABLE t (x INT)",
            cursor,
            extract=lambda s: "t",
        )
        executed = [c[0][0] for c in cursor.execute.call_args_list]
        assert executed == ["CREATE TABLE t (x INT)", "DROP TABLE IF EXISTS t", "CREATE TABLE t (x INT)"]
        notices.assert_called_once()
        assert "t" in notices.call_args[0][0]

    def test_already_exists_without_table_name_reraises(self) -> None:
        cursor = MagicMock()
        cursor.execute.side_effect = RuntimeError("relation already exists")
        with pytest.raises(RuntimeError, match="already exists"):
            self._run("CREATE TABLE t (x INT)", cursor, extract=lambda s: None)
        cursor.execute.assert_called_once_with("CREATE TABLE t (x INT)")
        cursor.close.assert_called_once_with()

    def test_non_recoverable_error_reraises(self) -> None:
        cursor = MagicMock()
        cursor.execute.side_effect = RuntimeError("syntax error at or near FOO")
        with pytest.raises(RuntimeError, match="syntax error"):
            self._run("CREATE TABLE t (x INT)", cursor)
        cursor.close.assert_called_once_with()

    def test_empty_statements_execute_nothing(self) -> None:
        cursor = MagicMock()
        self._run("  ;  ", cursor)
        cursor.execute.assert_not_called()
        cursor.close.assert_called_once_with()

    def test_match_is_case_insensitive_for_already_exists(self) -> None:
        cursor = MagicMock()
        cursor.execute.side_effect = [RuntimeError("Already Exists"), None, None]
        self._run("CREATE TABLE t (x INT)", cursor, extract=lambda s: "t")
        assert cursor.execute.call_count == 3
