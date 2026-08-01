"""Shared supported-API transport fixtures for MCP integration tests."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import httpx2
from mcp.client import Client
from mcp.client.streamable_http import streamable_http_client

from benchbox.mcp import create_server


@asynccontextmanager
async def http_client(
    tmp_path: Path,
    *,
    mode: str,
    request_headers: list[dict[str, str]],
    response_headers: list[dict[str, str]],
) -> AsyncIterator[Client]:
    """Yield an SDK client connected to the in-process HTTP transport."""
    server = create_server(results_dir=tmp_path / "results", charts_dir=tmp_path / "charts")
    app = server.streamable_http_app(
        host="127.0.0.1",
        streamable_http_path="/mcp",
        stateless_http=True,
        json_response=False,
    )

    async def record_request(request: httpx2.Request) -> None:
        request_headers.append(dict(request.headers))

    async def record_response(response: httpx2.Response) -> None:
        response_headers.append(dict(response.headers))

    transport = httpx2.ASGITransport(app=app)
    async with app.router.lifespan_context(app):
        async with httpx2.AsyncClient(
            transport=transport,
            base_url="http://127.0.0.1:8000",
            event_hooks={"request": [record_request], "response": [record_response]},
        ) as sdk_http_client:
            mcp_transport = streamable_http_client(
                "http://127.0.0.1:8000/mcp",
                http_client=sdk_http_client,
            )
            async with Client(mcp_transport, mode=mode) as client:
                yield client
