"""Shared psycopg connection mechanics for PostgreSQL wire-protocol adapters.

Provides a mixin with connection management and identifier validation logic
shared across PostgreSQL-compatible platforms (PostgreSQL, QuestDB, etc.).

Usage:
    class MyAdapter(PsycopgConnectionMixin, PlatformAdapter):
        _max_identifier_length = 63  # override per platform

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

from typing import Any


class PsycopgConnectionMixin:
    """Mixin for adapters that use psycopg (PostgreSQL wire protocol).

    Provides shared connection mechanics that differ only in
    platform-specific constants or catalog queries.  Subclasses should
    inherit this mixin *before* PlatformAdapter so that MRO resolution
    picks up these overrides correctly::

        class PostgreSQLAdapter(PsycopgConnectionMixin, PlatformAdapter): ...

    Class attributes to override per platform:

    ``_max_identifier_length`` (int, default 63):
        Maximum byte-length of a SQL identifier accepted by the database.
        PostgreSQL caps at 63; QuestDB caps at 127.
    """

    _max_identifier_length: int = 63

    def _validate_identifier(self, identifier: str) -> bool:
        """Validate a SQL identifier to prevent injection.

        Delegates to ``benchbox.utils.sql_identifier.is_valid_sql_identifier``,
        passing the engine-specific ``_max_identifier_length`` (PostgreSQL
        family caps at 63; QuestDB at 127).
        """
        from benchbox.utils.sql_identifier import is_valid_sql_identifier

        return is_valid_sql_identifier(identifier, max_length=self._max_identifier_length)

    def close_connection(self, connection: Any) -> None:
        """Close a psycopg connection, ignoring errors on close."""
        if connection:
            try:
                connection.close()
            except Exception as e:
                self.logger.debug(f"Error closing connection: {e}")

    def _get_existing_tables(self, connection: Any) -> list[str]:
        """Return existing table names via ``information_schema.tables``.

        Platforms whose catalog uses a different API (e.g. QuestDB's
        ``tables()`` function) should override this method.

        Returns:
            Lowercase table names, or an empty list on error.
        """
        try:
            cursor = connection.cursor()
        except Exception as e:
            self.logger.warning(f"Failed to get existing tables: {e}")
            return []
        try:
            cursor.execute(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = %s AND table_type = 'BASE TABLE'
                """,
                (self.schema,),
            )
            result = cursor.fetchall()
            return [row[0].lower() for row in result]
        except Exception as e:
            self.logger.warning(f"Failed to get existing tables: {e}")
            return []
        finally:
            cursor.close()
