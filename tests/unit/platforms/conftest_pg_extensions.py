# Copyright 2026 Joe Harris / BenchBox Project

# Licensed under the MIT License. See LICENSE file in the project root for details.

from __future__ import annotations

from unittest.mock import Mock


def create_psycopg_mock(version: str = "3.1.0") -> Mock:
    mock_psycopg = Mock()
    mock_psycopg.__version__ = version
    return mock_psycopg


def patch_psycopg_for_extension(monkeypatch, extension_module, postgresql_module, version: str = "3.1.0") -> Mock:
    mock_psycopg = create_psycopg_mock(version)
    monkeypatch.setattr(extension_module, "psycopg", mock_psycopg)
    monkeypatch.setattr(postgresql_module, "psycopg", mock_psycopg)
    return mock_psycopg


def make_extension_check_responses(
    extension_version: str | None = "1.0.0",
    extension_name: str = "pg_duckdb",
) -> list:
    if extension_version is not None:
        return [
            None,
            None,
            (extension_version,),
            (1,),
        ]
    else:
        return [
            None,
            None,
            None,
            None,
            (1,),
        ]


def create_mock_connection() -> tuple[Mock, Mock]:
    mock_conn = Mock()
    mock_cursor = Mock()
    mock_conn.cursor.return_value = mock_cursor
    return mock_conn, mock_cursor


class GUCCapture:
    def __init__(self, mock_cursor: Mock):
        self._calls = [str(call) for call in mock_cursor.execute.call_args_list]

    def was_set(self, parameter: str) -> bool:
        return any(parameter in call for call in self._calls if "SET" in call.upper() or "set" in call)

    def was_executed(self, sql_fragment: str) -> bool:
        return any(sql_fragment.lower() in call.lower() for call in self._calls)

    def get_set_calls(self) -> list[str]:
        return [call for call in self._calls if "SET" in call.upper() or "set" in call]

    def get_all_calls(self) -> list[str]:
        return self._calls
