"""Shared authenticated HTTP fixtures for MCP security integration tests."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import httpx2
from mcp.client import Client
from mcp.client.streamable_http import streamable_http_client
from mcp.server.transport_security import TransportSecuritySettings

from benchbox.mcp import create_server
from benchbox.mcp.security import RemoteSecurityRuntime, token_sha256


def write_security_config(
    tmp_path: Path,
    *,
    tokens: dict[str, tuple[str, tuple[str, ...]]],
    admission: dict[str, object] | None = None,
) -> Path:
    """Write a digest-only test policy and return its path."""
    policy = {
        "issuer_url": "https://auth.example.test",
        "resource_server_url": "https://mcp.example.test/mcp",
        "allowed_hosts": ["127.0.0.1", "127.0.0.1:*"],
        "allowed_origins": ["https://client.example.test"],
        "workspace_root": str(tmp_path / "workspaces"),
        "state_db": str(tmp_path / "security.sqlite3"),
        "tokens": [
            {
                "token_sha256": token_sha256(token),
                "client_id": f"client-{subject}",
                "subject": subject,
                "scopes": list(scopes),
            }
            for token, (subject, scopes) in tokens.items()
        ],
        "allowed_platforms": ["duckdb"],
        "allowed_benchmarks": ["tpch"],
        "max_scale_factor": 1.0,
    }
    if admission is not None:
        policy["admission"] = admission
    path = tmp_path / "security.json"
    path.write_text(json.dumps(policy), encoding="utf-8")
    return path


@asynccontextmanager
async def authenticated_http_client(
    config_path: Path, token: str
) -> AsyncIterator[tuple[Client, RemoteSecurityRuntime]]:
    """Yield an SDK client authenticated to an in-process server."""
    runtime = RemoteSecurityRuntime.from_file(config_path)
    server = create_server(remote_security=runtime)
    app = server.streamable_http_app(
        host="127.0.0.1",
        streamable_http_path="/mcp",
        stateless_http=True,
        json_response=False,
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=list(runtime.config.allowed_hosts),
            allowed_origins=list(runtime.config.allowed_origins),
        ),
    )
    transport = httpx2.ASGITransport(app=app)
    async with app.router.lifespan_context(app):
        async with httpx2.AsyncClient(
            transport=transport,
            base_url="http://127.0.0.1:8000",
            headers={"Authorization": f"Bearer {token}"},
        ) as sdk_http_client:
            mcp_transport = streamable_http_client(
                "http://127.0.0.1:8000/mcp",
                http_client=sdk_http_client,
            )
            async with Client(mcp_transport, mode="auto") as client:
                yield client, runtime
