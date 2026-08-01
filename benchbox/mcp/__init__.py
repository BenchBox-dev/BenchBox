"""BenchBox MCP Server - Model Context Protocol integration.

This module provides an MCP server that enables AI agents (Claude Code, etc.)
to interact with BenchBox programmatically through the Model Context Protocol.

The MCP server exposes BenchBox functionality through:
- **Tools**: Executable actions (run benchmarks, export results)
- **Resources**: Read-only data (benchmark metadata, historical results)
- **Prompts**: Reusable templates for common analysis patterns

## Available Modules

- **server**: Main server creation and configuration
- **errors**: Structured error handling with error codes and categories
- **schemas**: Pydantic input validation models
- **observability**: Structured logging and metrics collection
- **execution**: Async execution tracking for long-running benchmarks

## Example Usage

With Claude Code:

    # In claude_desktop_config.json:
    {
        "mcpServers": {
            "benchbox": {
                "command": "benchbox-mcp"
            }
        }
    }

Or run directly:

    $ python -m benchbox.mcp

## Tool Annotations

All tools include MCP protocol annotations for trust/safety:
- readOnlyHint: Whether tool modifies state
- destructiveHint: Whether tool can delete data
- idempotentHint: Whether repeated calls are safe
- openWorldHint: Whether tool interacts with external systems

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

try:
    from mcp.server.mcpserver import MCPServer
except ImportError as e:
    raise ImportError(
        "MCP SDK not installed. Install with:\n"
        "  pip install 'benchbox[mcp]'  # pip/venv\n"
        "  uv add benchbox --extra mcp  # uv project"
    ) from e

# Lazy imports to avoid circular dependencies
__all__ = [
    "create_server",
    "run_server",
    # Error handling
    "ErrorCode",
    "ErrorCategory",
    "MCPError",
    "make_error",
    # Observability
    "ToolCallContext",
    "get_metrics_collector",
    # Execution
    "ExecutionStatus",
    "ExecutionState",
    "get_execution_tracker",
]


def create_server(
    *,
    results_dir: str | Path | None = None,
    charts_dir: str | Path | None = None,
    log_level: str | int | None = None,
    env: Mapping[str, str] | None = None,
) -> MCPServer:
    """Create and configure the BenchBox MCP server.

    Returns:
        Configured MCPServer instance with all tools, resources, and prompts registered.
    """
    from benchbox.mcp.server import create_benchbox_server

    return create_benchbox_server(
        results_dir=results_dir,
        charts_dir=charts_dir,
        log_level=log_level,
        env=env,
    )


def run_server(
    *,
    results_dir: str | Path | None = None,
    charts_dir: str | Path | None = None,
    log_level: str | int | None = None,
    env: Mapping[str, str] | None = None,
) -> None:
    """Run the BenchBox MCP server.

    This is the main entry point for the MCP server, typically invoked via:
    - `benchbox-mcp` CLI command
    - `python -m benchbox.mcp`
    """
    server = create_server(
        results_dir=results_dir,
        charts_dir=charts_dir,
        log_level=log_level,
        env=env,
    )
    server.run()


# Lazy-loaded exports for error handling
def __getattr__(name: str):
    """Lazy load exports to avoid import issues."""
    if name in ("ErrorCode", "ErrorCategory", "MCPError", "make_error"):
        from benchbox.mcp.errors import ErrorCategory, ErrorCode, MCPError, make_error

        return {"ErrorCode": ErrorCode, "ErrorCategory": ErrorCategory, "MCPError": MCPError, "make_error": make_error}[
            name
        ]
    elif name in ("ToolCallContext", "get_metrics_collector"):
        from benchbox.mcp.observability import ToolCallContext, get_metrics_collector

        return {"ToolCallContext": ToolCallContext, "get_metrics_collector": get_metrics_collector}[name]
    elif name in ("ExecutionStatus", "ExecutionState", "get_execution_tracker"):
        from benchbox.mcp.execution import ExecutionState, ExecutionStatus, get_execution_tracker

        return {
            "ExecutionStatus": ExecutionStatus,
            "ExecutionState": ExecutionState,
            "get_execution_tracker": get_execution_tracker,
        }[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
