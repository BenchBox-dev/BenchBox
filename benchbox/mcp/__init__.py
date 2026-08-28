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
- **schemas**: Platform-option admission and input validation
- **jobs**: Durable job queue for authenticated remote execution
- **telemetry**: Server-side telemetry for remote deployments

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
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from benchbox.mcp.security import RemoteSecurityRuntime

try:
    from mcp.server.mcpserver import MCPServer
except ImportError as e:
    raise ImportError(
        "MCP SDK not installed. Install with:\n"
        "  pip install 'benchbox[mcp]'  # pip/venv\n"
        "  uv add benchbox --extra mcp  # uv project"
    ) from e

from benchbox.mcp.transport import MCPTransport

# Lazy imports to avoid circular dependencies
__all__ = [
    "create_server",
    "run_server",
    # Error handling
    "ErrorCode",
    "ErrorCategory",
    "MCPError",
    "make_error",
]


def create_server(
    *,
    results_dir: str | Path | None = None,
    charts_dir: str | Path | None = None,
    log_level: str | int | None = None,
    env: Mapping[str, str] | None = None,
    remote_security: RemoteSecurityRuntime | None = None,
) -> MCPServer:
    """Create and configure the BenchBox MCP server.

    Returns:
        Configured MCPServer instance with all tools, resources, and prompts registered.
    """
    from benchbox.mcp.server import create_benchbox_server

    kwargs: dict[str, Any] = {
        "results_dir": results_dir,
        "charts_dir": charts_dir,
        "log_level": log_level,
        "env": env,
    }
    if remote_security is not None:
        kwargs["remote_security"] = remote_security
    return create_benchbox_server(**kwargs)


def run_server(
    *,
    results_dir: str | Path | None = None,
    charts_dir: str | Path | None = None,
    log_level: str | int | None = None,
    env: Mapping[str, str] | None = None,
    transport: MCPTransport = "stdio",
    host: str = "127.0.0.1",
    port: int = 8000,
    streamable_http_path: str = "/mcp",
    security_config: str | Path | None = None,
    readiness_evidence: str | Path | None = None,
) -> None:
    """Run the BenchBox MCP server.

    This is the main entry point for the MCP server, typically invoked via:
    - `benchbox-mcp` CLI command
    - `python -m benchbox.mcp`
    """
    from benchbox.mcp.security import RemoteSecurityRuntime
    from benchbox.mcp.transport import MCPTransportSettings, run_transport

    remote_security = RemoteSecurityRuntime.from_file(security_config) if security_config is not None else None

    transport_settings = MCPTransportSettings(
        transport=transport,
        host=host,
        port=port,
        streamable_http_path=streamable_http_path,
        remote_security=remote_security,
        readiness_evidence=Path(readiness_evidence) if readiness_evidence is not None else None,
        env=env,
    )
    server_kwargs: dict[str, Any] = {
        "results_dir": results_dir,
        "charts_dir": charts_dir,
        "log_level": log_level,
        "env": env,
    }
    if remote_security is not None:
        server_kwargs["remote_security"] = remote_security
    server = create_server(**server_kwargs)
    run_transport(server, transport_settings)


# Lazy-loaded exports for error handling
def __getattr__(name: str):
    """Lazy load exports to avoid import issues."""
    if name in ("ErrorCode", "ErrorCategory", "MCPError", "make_error"):
        from benchbox.mcp.errors import ErrorCategory, ErrorCode, MCPError, make_error

        return {"ErrorCode": ErrorCode, "ErrorCategory": ErrorCategory, "MCPError": MCPError, "make_error": make_error}[
            name
        ]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
