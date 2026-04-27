"""Shared pytest fixtures for PostgreSQL extension adapter testing.

Provides reusable mocks for psycopg connections, extension checks,
and GUC parameter capture. These fixtures can be used across all
PostgreSQL extension adapter test files (TimescaleDB, pg_duckdb,
pg_mooncake, and future extensions).

Usage:
    Import the fixture functions directly in your test file's conftest
    or use them as helper factories:

        from tests.unit.platforms.conftest_pg_extensions import (
            create_psycopg_mock,
            make_extension_check_responses,
            create_guc_capture_cursor,
        )

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

from unittest.mock import Mock


def create_psycopg_mock(version: str = "3.1.0") -> Mock:
    """Create a mock psycopg module suitable for PostgreSQL extension adapters.

    Returns a mock with the correct attributes that PostgreSQLAdapter checks
    during initialization (__version__, connect).

    Args:
        version: psycopg version string to report.

    Returns:
        Mock configured as a psycopg module replacement.

    Example:
        >>> mock_psycopg = create_psycopg_mock()
        >>> monkeypatch.setattr(pg_duckdb_module, "psycopg", mock_psycopg)
        >>> monkeypatch.setattr(postgresql_module, "psycopg", mock_psycopg)
    """
    mock_psycopg = Mock()
    mock_psycopg.__version__ = version
    return mock_psycopg


def patch_psycopg_for_extension(monkeypatch, extension_module, postgresql_module, version: str = "3.1.0") -> Mock:
    """Patch psycopg in both the extension and parent PostgreSQL modules.

    PostgreSQLAdapter checks for psycopg in its own module during __init__,
    so both the extension module AND the parent module must be patched.

    Args:
        monkeypatch: pytest monkeypatch fixture.
        extension_module: The extension's Python module (e.g., pg_duckdb_module).
        postgresql_module: The benchbox.platforms.postgresql module.
        version: psycopg version string to report.

    Returns:
        The mock psycopg object (for configuring connect() etc.).

    Example:
        >>> import benchbox.platforms.pg_duckdb as pg_duckdb_module
        >>> import benchbox.platforms.postgresql as postgresql_module
        >>> mock_psycopg = patch_psycopg_for_extension(
        ...     monkeypatch, pg_duckdb_module, postgresql_module
        ... )
    """
    mock_psycopg = create_psycopg_mock(version)
    monkeypatch.setattr(extension_module, "psycopg", mock_psycopg)
    monkeypatch.setattr(postgresql_module, "psycopg", mock_psycopg)
    return mock_psycopg


def make_extension_check_responses(
    extension_version: str | None = "1.0.0",
    extension_name: str = "pg_duckdb",
) -> list:
    """Create mock cursor.fetchone() responses for extension verification.

    Simulates the sequence of fetchone() calls during create_connection():
    1. check_server_database_exists (None = no pre-check result)
    2. _create_database check (None)
    3. Extension version check (tuple or None if not installed)
    4. Verify connection (tuple)

    Args:
        extension_version: Version string if extension is installed,
            None to simulate missing extension.
        extension_name: Name of the extension (for documentation only).

    Returns:
        List of fetchone() return values to use as side_effect.

    Example:
        >>> # Extension installed
        >>> responses = make_extension_check_responses("1.1.0", "pg_duckdb")
        >>> mock_cursor.fetchone.side_effect = responses
        >>>
        >>> # Extension missing (will trigger CREATE EXTENSION fallback)
        >>> responses = make_extension_check_responses(None, "pg_mooncake")
        >>> mock_cursor.fetchone.side_effect = responses
    """
    if extension_version is not None:
        # Extension is installed
        return [
            None,  # check_server_database_exists
            None,  # _create_database check
            (extension_version,),  # extension version found
            (1,),  # verify connection
        ]
    else:
        # Extension not installed, CREATE EXTENSION also fails
        return [
            None,  # check_server_database_exists
            None,  # _create_database check
            None,  # extension not found
            None,  # still not found after CREATE EXTENSION
            (1,),  # verify connection
        ]


def create_mock_connection() -> tuple[Mock, Mock]:
    """Create a mock psycopg connection with cursor.

    Returns a (connection, cursor) tuple where the connection's
    cursor() method returns the cursor mock.

    Returns:
        Tuple of (mock_connection, mock_cursor).

    Example:
        >>> mock_conn, mock_cursor = create_mock_connection()
        >>> mock_psycopg.connect.return_value = mock_conn
        >>> mock_cursor.fetchone.side_effect = make_extension_check_responses()
    """
    mock_conn = Mock()
    mock_cursor = Mock()
    mock_conn.cursor.return_value = mock_cursor
    return mock_conn, mock_cursor


class GUCCapture:
    """Captures SET parameter calls from a mock cursor for verification.

    Inspects cursor.execute() call history and extracts SET statements,
    making it easy to verify that specific GUC parameters were configured.

    Example:
        >>> adapter.create_connection()
        >>> capture = GUCCapture(mock_cursor)
        >>> assert capture.was_set("duckdb.force_execution")
        >>> assert capture.get_value("duckdb.force_execution") == "true"
    """

    def __init__(self, mock_cursor: Mock):
        """Initialize with a mock cursor that has been used for queries.

        Args:
            mock_cursor: Mock cursor with execute() call history.
        """
        self._calls = [str(call) for call in mock_cursor.execute.call_args_list]

    def was_set(self, parameter: str) -> bool:
        """Check if a SET statement was executed for the given parameter.

        Args:
            parameter: GUC parameter name (e.g., "duckdb.force_execution").

        Returns:
            True if a SET statement containing the parameter was found.
        """
        return any(parameter in call for call in self._calls if "SET" in call.upper() or "set" in call)

    def was_executed(self, sql_fragment: str) -> bool:
        """Check if any execute() call contained the given SQL fragment.

        Args:
            sql_fragment: Substring to search for in execute() calls.

        Returns:
            True if any call contained the fragment.
        """
        return any(sql_fragment.lower() in call.lower() for call in self._calls)

    def get_set_calls(self) -> list[str]:
        """Get all SET statements that were executed.

        Returns:
            List of execute() call strings that contain SET.
        """
        return [call for call in self._calls if "SET" in call.upper() or "set" in call]

    def get_all_calls(self) -> list[str]:
        """Get all execute() calls.

        Returns:
            List of all execute() call strings.
        """
        return self._calls
