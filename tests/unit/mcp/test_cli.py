"""Transport configuration tests for the BenchBox MCP CLI."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from mcp.server.transport_security import TransportSecuritySettings

from benchbox.mcp.cli import parse_args
from benchbox.mcp.transport import MCPTransportSettings, is_supported_loopback_host, run_transport

pytestmark = [pytest.mark.unit, pytest.mark.fast]


def test_transport_defaults_preserve_stdio() -> None:
    args = parse_args([])

    assert args.transport == "stdio"
    assert args.host == "127.0.0.1"
    assert args.port == 8000
    assert args.streamable_http_path == "/mcp"


def test_streamable_http_cli_options_are_forwarded(monkeypatch: pytest.MonkeyPatch) -> None:
    from benchbox.mcp import cli

    captured: dict[str, object] = {}
    monkeypatch.setattr(cli, "run_server", lambda **kwargs: captured.update(kwargs))

    cli.main(
        [
            "--transport",
            "streamable-http",
            "--host",
            "::1",
            "--port",
            "8765",
            "--streamable-http-path",
            "/benchbox-mcp",
        ]
    )

    assert captured["transport"] == "streamable-http"
    assert captured["host"] == "::1"
    assert captured["port"] == 8765
    assert captured["streamable_http_path"] == "/benchbox-mcp"


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "::1"])
def test_loopback_hosts_are_accepted(host: str) -> None:
    assert is_supported_loopback_host(host)
    MCPTransportSettings(transport="streamable-http", host=host)


@pytest.mark.parametrize("host", ["0.0.0.0", "::", "192.0.2.1", "mcp.example.com"])
def test_non_loopback_http_host_is_rejected(host: str) -> None:
    with pytest.raises(ValueError, match="loopback hosts only"):
        MCPTransportSettings(transport="streamable-http", host=host)


def test_stdio_uses_explicit_sdk_transport() -> None:
    server = MagicMock()

    run_transport(server, MCPTransportSettings())

    server.run.assert_called_once_with(transport="stdio")


def test_streamable_http_uses_streaming_capable_stateless_sdk_route() -> None:
    server = MagicMock()

    run_transport(
        server,
        MCPTransportSettings(
            transport="streamable-http",
            host="localhost",
            port=8765,
            streamable_http_path="/benchbox-mcp",
        ),
    )

    server.run.assert_called_once_with(
        transport="streamable-http",
        host="localhost",
        port=8765,
        streamable_http_path="/benchbox-mcp",
        stateless_http=True,
        json_response=False,
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=["127.0.0.1", "127.0.0.1:*", "localhost", "localhost:*", "[::1]", "[::1]:*"],
            allowed_origins=[
                "http://127.0.0.1",
                "http://127.0.0.1:*",
                "http://localhost",
                "http://localhost:*",
                "http://[::1]",
                "http://[::1]:*",
            ],
        ),
    )


def test_run_server_rejects_public_http_host_before_creating_server() -> None:
    with patch("benchbox.mcp.create_server") as create_server:
        from benchbox.mcp import run_server

        with pytest.raises(ValueError, match="loopback hosts only"):
            run_server(transport="streamable-http", host="0.0.0.0")

    create_server.assert_not_called()


@pytest.mark.parametrize("port", ["0", "65536"])
def test_cli_rejects_invalid_http_port(port: str) -> None:
    with pytest.raises(SystemExit):
        parse_args(["--port", port])
