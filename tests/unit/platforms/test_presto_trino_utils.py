"""Unit tests for presto_trino_utils helpers.

Pins the contract for the five helpers extracted by the dedup consolidation:
  * escape_insert_value: NULL handling, date literals, numeric passthrough, string quoting
  * is_date_value: date pattern detection
  * normalize_existing_files: path list normalization and empty-file exclusion
  * load_file_batches: batched INSERT VALUES cursor delegation
  * resolve_data_files: DataSourceResolver delegation and ValueError on empty result
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from benchbox.platforms.presto_trino_utils import (
    escape_insert_value,
    is_date_value,
    load_file_batches,
    normalize_existing_files,
    resolve_data_files,
    show_tables_lower,
)

pytestmark = [pytest.mark.unit, pytest.mark.fast]


class TestIsDateValue:
    def test_valid_date(self) -> None:
        assert is_date_value("2023-01-15") is True

    def test_valid_date_start_of_year(self) -> None:
        assert is_date_value("1992-01-01") is True

    def test_valid_date_end_of_year(self) -> None:
        assert is_date_value("1998-12-31") is True

    def test_empty_string(self) -> None:
        assert is_date_value("") is False

    def test_numeric_string(self) -> None:
        assert is_date_value("12345") is False

    def test_date_with_time(self) -> None:
        assert is_date_value("2023-01-15 10:00:00") is False

    def test_partial_date(self) -> None:
        assert is_date_value("2023-01") is False

    def test_slashes_not_valid(self) -> None:
        assert is_date_value("2023/01/15") is False

    def test_alpha_not_valid(self) -> None:
        assert is_date_value("Jan-01-2023") is False


class TestEscapeInsertValue:
    def test_empty_string_returns_null(self) -> None:
        assert escape_insert_value("") == "NULL"

    def test_null_literal_returns_null(self) -> None:
        assert escape_insert_value("null") == "NULL"

    def test_null_uppercase_returns_null(self) -> None:
        assert escape_insert_value("NULL") == "NULL"

    def test_date_value_wrapped_in_date_literal(self) -> None:
        assert escape_insert_value("1995-03-14") == "DATE '1995-03-14'"

    def test_integer_string_passthrough(self) -> None:
        assert escape_insert_value("42") == "42"

    def test_float_string_passthrough(self) -> None:
        assert escape_insert_value("3.14") == "3.14"

    def test_negative_number_passthrough(self) -> None:
        assert escape_insert_value("-100") == "-100"

    def test_plain_string_quoted(self) -> None:
        assert escape_insert_value("hello") == "'hello'"

    def test_string_with_single_quote_escaped(self) -> None:
        assert escape_insert_value("O'Brien") == "'O''Brien'"

    def test_string_with_multiple_quotes_escaped(self) -> None:
        assert escape_insert_value("it's a dog's life") == "'it''s a dog''s life'"

    def test_string_that_looks_like_date_but_is_not_quoted(self) -> None:
        # "not-a-date" has letters, so is_date_value returns False → quoted as string
        assert escape_insert_value("not-a-date") == "'not-a-date'"


class TestNormalizeExistingFiles:
    def test_empty_list_returns_empty(self) -> None:
        assert normalize_existing_files([]) == []

    def test_nonexistent_path_excluded(self) -> None:
        result = normalize_existing_files(["/tmp/does-not-exist-xyz.csv"])
        assert result == []

    def test_existing_file_included(self, tmp_path: Path) -> None:
        f = tmp_path / "data.csv"
        f.write_text("a,b\n1,2\n")
        result = normalize_existing_files([str(f)])
        assert result == [f]

    def test_empty_file_excluded(self, tmp_path: Path) -> None:
        f = tmp_path / "empty.csv"
        f.write_text("")
        result = normalize_existing_files([str(f)])
        assert result == []

    def test_single_path_not_in_list_still_works(self, tmp_path: Path) -> None:
        f = tmp_path / "data.csv"
        f.write_text("row\n")
        result = normalize_existing_files(str(f))
        assert result == [f]

    def test_mixed_existing_and_missing(self, tmp_path: Path) -> None:
        good = tmp_path / "good.csv"
        good.write_text("data\n")
        result = normalize_existing_files([str(good), "/tmp/missing-xyz.csv"])
        assert result == [good]

    def test_returns_path_objects(self, tmp_path: Path) -> None:
        f = tmp_path / "data.csv"
        f.write_text("x\n")
        result = normalize_existing_files([str(f)])
        assert all(isinstance(p, Path) for p in result)


class TestShowTablesLower:
    def test_returns_lowercase_table_names_and_closes_cursor(self) -> None:
        cursor = MagicMock()
        cursor.fetchall.return_value = [("ORDERS",), ("LineItem",)]
        connection = MagicMock()
        connection.cursor.return_value = cursor

        assert show_tables_lower(connection) == ["orders", "lineitem"]
        cursor.execute.assert_called_once_with("SHOW TABLES")
        cursor.close.assert_called_once_with()

    def test_returns_empty_list_and_closes_cursor_on_error(self) -> None:
        cursor = MagicMock()
        cursor.execute.side_effect = RuntimeError("boom")
        connection = MagicMock()
        connection.cursor.return_value = cursor

        assert show_tables_lower(connection) == []
        cursor.close.assert_called_once_with()


class TestLoadFileBatches:
    def _make_file(self, tmp_path: Path, content: str) -> Path:
        f = tmp_path / "data.tbl"
        f.write_text(content)
        return f

    def test_single_row_inserted(self, tmp_path: Path) -> None:
        f = self._make_file(tmp_path, "1|Alice|1992-01-01\n")
        cursor = MagicMock()
        with (
            patch("benchbox.utils.file_format.get_delimiter_for_file", return_value="|"),
            patch("benchbox.platforms.base.data_loading.FileFormatRegistry") as mock_reg,
        ):
            ctx = MagicMock()
            ctx.__enter__ = lambda s: open(f, encoding="utf-8")
            ctx.__exit__ = MagicMock(return_value=False)
            mock_reg.get_compression_handler.return_value.open.return_value = ctx
            rows = load_file_batches(cursor, f, "schema.table")
        assert rows == 1
        cursor.execute.assert_called_once()
        sql = cursor.execute.call_args[0][0]
        assert sql.startswith("INSERT INTO schema.table VALUES")

    def test_rows_counted_correctly(self, tmp_path: Path) -> None:
        lines = "\n".join(f"{i}|name{i}" for i in range(5))
        f = self._make_file(tmp_path, lines + "\n")
        cursor = MagicMock()
        with (
            patch("benchbox.utils.file_format.get_delimiter_for_file", return_value="|"),
            patch("benchbox.platforms.base.data_loading.FileFormatRegistry") as mock_reg,
        ):
            ctx = MagicMock()
            ctx.__enter__ = lambda s: open(f, encoding="utf-8")
            ctx.__exit__ = MagicMock(return_value=False)
            mock_reg.get_compression_handler.return_value.open.return_value = ctx
            rows = load_file_batches(cursor, f, "s.t")
        assert rows == 5


class TestResolveDataFiles:
    def test_raises_value_error_when_no_files(self) -> None:
        empty_source = MagicMock()
        empty_source.tables = {}
        with patch("benchbox.platforms.base.data_loading.DataSourceResolver") as mock_cls:
            mock_cls.return_value.resolve.return_value = empty_source
            with pytest.raises(ValueError, match="No data files found"):
                resolve_data_files(
                    MagicMock(),
                    Path("/data"),
                    platform_name="presto",
                    table_mode="native",
                    platform_config=MagicMock(),
                    requested_format=None,
                )

    def test_raises_value_error_when_resolver_returns_none(self) -> None:
        with patch("benchbox.platforms.base.data_loading.DataSourceResolver") as mock_cls:
            mock_cls.return_value.resolve.return_value = None
            with pytest.raises(ValueError, match="No data files found"):
                resolve_data_files(
                    MagicMock(),
                    Path("/data"),
                    platform_name="presto",
                    table_mode="native",
                    platform_config=MagicMock(),
                    requested_format=None,
                )

    def test_returns_tables_dict_on_success(self) -> None:
        tables = {"lineitem": [Path("/data/lineitem.tbl")]}
        source = MagicMock()
        source.tables = tables
        with patch("benchbox.platforms.base.data_loading.DataSourceResolver") as mock_cls:
            mock_cls.return_value.resolve.return_value = source
            result = resolve_data_files(
                MagicMock(),
                Path("/data"),
                platform_name="trino",
                table_mode="native",
                platform_config=MagicMock(),
                requested_format=None,
            )
        assert result is tables
