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
