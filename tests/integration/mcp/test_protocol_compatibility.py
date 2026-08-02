"""Production protocol-version compatibility policy."""

from __future__ import annotations

from pathlib import Path

import anyio
import pytest

from benchbox.mcp.readiness import CURRENT_PROTOCOL_VERSION, SUPPORTED_LEGACY_VERSION
from tests.integration.mcp._transport import http_client

pytestmark = [pytest.mark.integration, pytest.mark.fast]


@pytest.mark.parametrize(
    ("mode", "expected_version"),
    [("auto", CURRENT_PROTOCOL_VERSION), ("legacy", SUPPORTED_LEGACY_VERSION)],
)
def test_supported_protocol_is_sessionless(tmp_path: Path, mode: str, expected_version: str) -> None:
    request_headers: list[dict[str, str]] = []
    response_headers: list[dict[str, str]] = []

    async def exercise() -> None:
        async with http_client(
            tmp_path,
            mode=mode,
            request_headers=request_headers,
            response_headers=response_headers,
        ) as client:
            assert client.protocol_version == expected_version
            assert (await client.list_tools()).tools

    anyio.run(exercise)
    assert request_headers
    assert all("mcp-session-id" not in headers for headers in request_headers)
    assert all("mcp-session-id" not in headers for headers in response_headers)


@pytest.mark.parametrize("mode", ["auto", "legacy"])
def test_conformance_baseline_assumptions_are_guarded(tmp_path: Path, mode: str) -> None:
    """Keep the pinned fixture gaps separate from BenchBox's supported surface."""

    async def exercise() -> None:
        async with http_client(tmp_path, mode=mode, request_headers=[], response_headers=[]) as client:
            tool_names = {tool.name for tool in (await client.list_tools()).tools}
            first_tools = [tool.model_dump(mode="json") for tool in (await client.list_tools()).tools]
            second_tools = [tool.model_dump(mode="json") for tool in (await client.list_tools()).tools]
            first_prompts = [prompt.model_dump(mode="json") for prompt in (await client.list_prompts()).prompts]
            second_prompts = [prompt.model_dump(mode="json") for prompt in (await client.list_prompts()).prompts]

            assert "test_missing_capability" not in tool_names
            assert first_tools == second_tools
            assert first_prompts == second_prompts

    anyio.run(exercise)
