"""Protocol-level coverage for localhost stateless Streamable HTTP."""

from __future__ import annotations

from pathlib import Path

import anyio
import pytest
from mcp.types import TextContent

from tests.integration.mcp._transport import http_client

pytestmark = [pytest.mark.integration, pytest.mark.fast]


def test_modern_discovery_and_tool_call_are_sessionless(tmp_path: Path) -> None:
    request_headers: list[dict[str, str]] = []
    response_headers: list[dict[str, str]] = []

    async def exercise() -> None:
        async with http_client(
            tmp_path,
            mode="auto",
            request_headers=request_headers,
            response_headers=response_headers,
        ) as client:
            assert client.session.discover_result is not None
            tools = await client.list_tools()
            assert {tool.name for tool in tools.tools} >= {"list_available", "run_benchmark", "get_results"}

            result = await client.call_tool("list_available", {"category": "charts"})
            assert not result.is_error
            assert isinstance(result.content[0], TextContent)
            assert "charts" in result.content[0].text

    anyio.run(exercise)

    assert len(request_headers) >= 3  # discover, tools/list, and tools/call
    assert all("mcp-session-id" not in headers for headers in request_headers)
    assert all("mcp-session-id" not in headers for headers in response_headers)


def test_supported_legacy_http_client_does_not_require_sticky_session(tmp_path: Path) -> None:
    request_headers: list[dict[str, str]] = []
    response_headers: list[dict[str, str]] = []

    async def exercise() -> None:
        async with http_client(
            tmp_path,
            mode="legacy",
            request_headers=request_headers,
            response_headers=response_headers,
        ) as client:
            tools = await client.list_tools()
            assert len(tools.tools) == 12

    anyio.run(exercise)

    assert request_headers
    assert all("mcp-session-id" not in headers for headers in request_headers)
    assert all("mcp-session-id" not in headers for headers in response_headers)
