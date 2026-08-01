"""Synchronous test helpers built on MCPServer's public API."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import anyio
from mcp.server.mcpserver import MCPServer
from mcp.types import TextContent, Tool as MCPTool


def list_tool_names(server: MCPServer) -> set[str]:
    """Return registered tool names through the public listing API."""

    async def collect() -> set[str]:
        return {tool.name for tool in await server.list_tools()}

    return anyio.run(collect)


def list_tools_by_name(server: MCPServer) -> dict[str, MCPTool]:
    """Return public tool definitions keyed by name."""

    async def collect() -> dict[str, MCPTool]:
        return {tool.name: tool for tool in await server.list_tools()}

    return anyio.run(collect)


def call_tool(server: MCPServer, name: str, **arguments: Any) -> Any:
    """Call a registered tool and unwrap its structured protocol result."""

    async def invoke() -> Any:
        result = await server.call_tool(name, arguments)
        if result.structured_content is not None:
            return result.structured_content
        if result.content and isinstance(result.content[0], TextContent):
            return json.loads(result.content[0].text)
        return result.content

    return anyio.run(invoke)


@dataclass(frozen=True)
class PublicTool:
    """Small compatibility object for tests that call a tool's ``fn`` method."""

    server: MCPServer
    name: str
    definition: MCPTool

    def fn(self, **arguments: Any) -> Any:
        return call_tool(self.server, self.name, **arguments)

    @property
    def description(self) -> str | None:
        return self.definition.description


def get_tool(server: MCPServer, name: str) -> PublicTool:
    """Resolve a tool by its public list API and return an invocation adapter."""
    tools = list_tools_by_name(server)
    if name not in tools:
        raise KeyError(name)
    return PublicTool(server, name, tools[name])


def get_tool_functions(server: MCPServer) -> dict[str, Any]:
    """Return public tool invokers keyed by registered name."""
    return {
        name: (lambda _name=name, **arguments: call_tool(server, _name, **arguments))
        for name in list_tool_names(server)
    }


def read_resource_text(server: MCPServer, uri: str) -> str:
    """Read one resource through the public API and return its text payload."""

    async def read() -> str:
        contents = await server.read_resource(uri)
        values = list(contents)
        if len(values) != 1 or not isinstance(values[0].content, str):
            raise AssertionError(f"Expected one text resource for {uri!r}")
        return values[0].content

    return anyio.run(read)


def list_resource_uris(server: MCPServer) -> set[str]:
    """Return static resource URIs through the public listing API."""

    async def collect() -> set[str]:
        return {str(resource.uri) for resource in await server.list_resources()}

    return anyio.run(collect)


def list_resource_template_uris(server: MCPServer) -> set[str]:
    """Return resource-template URIs through the public listing API."""

    async def collect() -> set[str]:
        return {template.uri_template for template in await server.list_resource_templates()}

    return anyio.run(collect)


def list_prompt_names(server: MCPServer) -> set[str]:
    """Return prompt names through the public listing API."""

    async def collect() -> set[str]:
        return {prompt.name for prompt in await server.list_prompts()}

    return anyio.run(collect)


def get_prompt_contents(server: MCPServer, name: str, **arguments: Any) -> list[TextContent]:
    """Get a prompt through the public API and normalize its text content."""

    async def get() -> list[TextContent]:
        result = await server.get_prompt(name, arguments)
        contents: list[TextContent] = []
        for message in result.messages:
            content = message.content
            if not isinstance(content, TextContent):
                raise AssertionError(f"Expected text prompt content for {name!r}")
            decoded = json.loads(content.text)
            contents.append(TextContent.model_validate(decoded))
        return contents

    return anyio.run(get)
