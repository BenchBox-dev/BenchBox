# Copyright 2026 Joe Harris / BenchBox Project

# Licensed under the MIT License. See LICENSE file in the project root for details.

from __future__ import annotations

from typing import Any


class PsycopgConnectionMixin:
    _max_identifier_length: int = 63

    def execute_query(
        self,
        connection: Any,
        query: str,
        query_id: str,
        benchmark_type: str | None = None,
        scale_factor: float | None = None,
        validate_row_count: bool = True,
        stream_id: int | None = None,
    ) -> dict[str, Any]:
        from benchbox.platforms.base.sql_execution import execute_sql_query

        return execute_sql_query(
            connection,
            query,
            query_id,
            log_verbose=self.log_verbose,
            build_query_result_with_validation=self._build_query_result_with_validation,
            benchmark_type=benchmark_type,
            scale_factor=scale_factor,
            validate_row_count=validate_row_count,
            stream_id=stream_id,
        )

    def _validate_identifier(self, identifier: str) -> bool:
        from benchbox.utils.sql_identifier import is_valid_sql_identifier

        return is_valid_sql_identifier(identifier, max_length=self._max_identifier_length)

    def close_connection(self, connection: Any) -> None:
        if connection:
            try:
                connection.close()
            except Exception as e:
                self.logger.debug(f"Error closing connection: {e}")

    def _get_existing_tables(self, connection: Any) -> list[str]:
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
