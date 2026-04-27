"""Shared Livy statement-execution wrappers for Azure Spark adapters.

Both Fabric and Synapse Spark adapters wrap the same
``spark_execution_utils.execute_livy_statement`` /
``wait_for_livy_statement`` helpers with identical accounting (update
``_total_statement_time_seconds`` and ``_query_count``). Consolidating the
wrappers here keeps the per-adapter ``_ensure_session`` lifecycle local
(it differs between Fabric and Synapse) while removing the 37-line
duplicate pair pylint R0801 flagged.

Subclasses must provide:
  * ``livy_endpoint: str``
  * ``timeout_minutes: int``
  * ``_get_headers() -> dict[str, str]``
  * ``_ensure_session() -> int``
  * ``_total_statement_time_seconds: float``
  * ``_query_count: int``
"""

from __future__ import annotations

from typing import Any


class LivyStatementMixin:
    """Provides ``_execute_statement`` and ``_wait_for_statement`` wrappers."""

    livy_endpoint: str
    timeout_minutes: int
    _total_statement_time_seconds: float
    _query_count: int

    def _get_headers(self) -> dict[str, str]:  # pragma: no cover - interface hook
        raise NotImplementedError

    def _ensure_session(self) -> int:  # pragma: no cover - interface hook
        raise NotImplementedError

    def _execute_statement(self, code: str, kind: str = "sql") -> dict[str, Any]:
        """Execute a statement in the Livy session."""
        from benchbox.platforms.azure.spark_execution_utils import execute_livy_statement

        session_id = self._ensure_session()
        result, execution_time = execute_livy_statement(
            livy_endpoint=self.livy_endpoint,
            session_id=session_id,
            code=code,
            kind=kind,
            get_headers=self._get_headers,
            timeout_minutes=self.timeout_minutes,
        )
        self._total_statement_time_seconds += execution_time
        self._query_count += 1
        return result

    def _wait_for_statement(self, session_id: int, statement_id: int) -> dict[str, Any]:
        """Wait for statement to complete and return result."""
        from benchbox.platforms.azure.spark_execution_utils import wait_for_livy_statement

        return wait_for_livy_statement(
            livy_endpoint=self.livy_endpoint,
            session_id=session_id,
            statement_id=statement_id,
            get_headers=self._get_headers,
            timeout_minutes=self.timeout_minutes,
        )
