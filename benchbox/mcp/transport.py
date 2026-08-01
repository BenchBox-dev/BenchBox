"""Transport configuration for the BenchBox MCP server."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings

from benchbox.mcp.security import RemoteSecurityRuntime

MCPTransport = Literal["stdio", "streamable-http"]


def is_supported_loopback_host(host: str) -> bool:
    """Return whether *host* is a loopback spelling protected by the SDK policy."""
    return host.strip().lower() in {"127.0.0.1", "localhost", "::1"}


@dataclass(frozen=True, slots=True)
class MCPTransportSettings:
    """Validated startup settings for stdio or localhost Streamable HTTP."""

    transport: MCPTransport = "stdio"
    host: str = "127.0.0.1"
    port: int = 8000
    streamable_http_path: str = "/mcp"
    remote_security: RemoteSecurityRuntime | None = None

    def __post_init__(self) -> None:
        if self.transport not in ("stdio", "streamable-http"):
            raise ValueError(f"Unsupported MCP transport: {self.transport}")
        if not 1 <= self.port <= 65535:
            raise ValueError("MCP HTTP port must be between 1 and 65535")
        if not self.streamable_http_path.startswith("/"):
            raise ValueError("MCP Streamable HTTP path must start with '/'")
        if self.transport == "stdio" and self.remote_security is not None:
            raise ValueError("Remote security configuration is only valid with Streamable HTTP")
        if (
            self.transport == "streamable-http"
            and not is_supported_loopback_host(self.host)
            and self.remote_security is None
        ):
            raise ValueError(
                "MCP Streamable HTTP currently supports loopback hosts only; "
                "remote binding requires the authentication and tenancy controls"
            )
        if self.transport == "streamable-http":
            object.__setattr__(self, "host", self.host.strip().lower())
        if self.transport == "streamable-http" and not is_supported_loopback_host(self.host):
            assert self.remote_security is not None
            self.remote_security.config.require_remote_tls()


def run_transport(server: MCPServer, settings: MCPTransportSettings) -> None:
    """Run *server* through the SDK-owned transport implementation."""
    if settings.transport == "stdio":
        server.run(transport="stdio")
        return

    if settings.remote_security is None:
        allowed_hosts = ["127.0.0.1", "127.0.0.1:*", "localhost", "localhost:*", "[::1]", "[::1]:*"]
        allowed_origins = [
            "http://127.0.0.1",
            "http://127.0.0.1:*",
            "http://localhost",
            "http://localhost:*",
            "http://[::1]",
            "http://[::1]:*",
        ]
    else:
        allowed_hosts = list(settings.remote_security.config.allowed_hosts)
        allowed_origins = list(settings.remote_security.config.allowed_origins)

    server.run(
        transport="streamable-http",
        host=settings.host,
        port=settings.port,
        streamable_http_path=settings.streamable_http_path,
        # Modern MCP is sessionless by construction. This flag also keeps the
        # supported handshake-era HTTP leg stateless between requests.
        stateless_http=True,
        # Keep the SDK's streaming-capable response mode for progress and
        # future request-scoped notifications.
        json_response=False,
        # Pass this explicitly for every accepted loopback address. The SDK's
        # automatic policy covers only its three canonical host spellings.
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=allowed_hosts,
            allowed_origins=allowed_origins,
        ),
    )
