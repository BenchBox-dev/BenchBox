"""Shared Livy statement execution for Azure Spark adapters."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

import requests

from benchbox.core.exceptions import ConfigurationError
from benchbox.utils.clock import elapsed_seconds, mono_time


class LivyStatementState:
    """Livy statement state constants (shared across Fabric and Synapse)."""

    WAITING = "waiting"
    RUNNING = "running"
    AVAILABLE = "available"
    ERROR = "error"
    CANCELLING = "cancelling"
    CANCELLED = "cancelled"


def wait_for_livy_statement(
    livy_endpoint: str,
    session_id: int,
    statement_id: int,
    get_headers: Callable[[], dict[str, str]],
    timeout_minutes: float,
) -> dict[str, Any]:
    """Wait for a Livy statement to complete and return its output.

    Args:
        livy_endpoint: Base Livy REST endpoint URL.
        session_id: Livy session ID.
        statement_id: Livy statement ID.
        get_headers: Callable returning auth headers.
        timeout_minutes: Maximum wait time in minutes.

    Returns:
        The statement output dict.
    """
    timeout_seconds = timeout_minutes * 60
    start_time = mono_time()
    statement_url = f"{livy_endpoint}/{session_id}/statements/{statement_id}"

    while elapsed_seconds(start_time) < timeout_seconds:
        response = requests.get(
            statement_url,
            headers=get_headers(),
            timeout=30,
        )

        if response.status_code != 200:
            raise ConfigurationError(f"Failed to get statement status: {response.status_code}")

        statement = response.json()
        state = statement["state"]

        if state == LivyStatementState.AVAILABLE:
            output = statement.get("output", {})
            if output.get("status") == "error":
                error_value = output.get("evalue", "Unknown error")
                raise ConfigurationError(f"Statement failed: {error_value}")
            return output
        if state in [LivyStatementState.ERROR, LivyStatementState.CANCELLED]:
            raise ConfigurationError(f"Statement is in {state} state")

        time.sleep(2)

    raise ConfigurationError(f"Timeout waiting for statement {statement_id} after {timeout_seconds}s")


def execute_livy_statement(
    livy_endpoint: str,
    session_id: int,
    code: str,
    kind: str,
    get_headers: Callable[[], dict[str, str]],
    timeout_minutes: float,
) -> tuple[dict[str, Any], float]:
    """Submit and wait for a Livy statement, returning result and elapsed time.

    Args:
        livy_endpoint: Base Livy REST endpoint URL.
        session_id: Livy session ID.
        code: Code to execute.
        kind: Statement kind ('sql', 'spark', 'pyspark').
        get_headers: Callable returning auth headers.
        timeout_minutes: Maximum wait time in minutes.

    Returns:
        Tuple of (statement output dict, execution time in seconds).
    """
    statements_url = f"{livy_endpoint}/{session_id}/statements"

    statement_data = {
        "code": code,
        "kind": kind,
    }

    start_time = mono_time()

    response = requests.post(
        statements_url,
        headers=get_headers(),
        json=statement_data,
        timeout=60,
    )

    if response.status_code not in (200, 201):
        raise ConfigurationError(f"Failed to submit statement: {response.status_code} - {response.text}")

    statement = response.json()
    statement_id = statement["id"]

    result = wait_for_livy_statement(livy_endpoint, session_id, statement_id, get_headers, timeout_minutes)

    execution_time = elapsed_seconds(start_time)
    return result, execution_time
