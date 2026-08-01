"""Contract parity between the stdio and Streamable HTTP MCP transports."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

import anyio
import pytest
from mcp.client import Client
from mcp.client.stdio import StdioServerParameters, stdio_client

from tests.integration.mcp._transport import http_client

pytestmark = [pytest.mark.integration, pytest.mark.fast]


async def _inventory(client: Client) -> dict[str, list[dict[str, Any]]]:
    """Return the public discovery contract in a transport-neutral shape."""

    def normalize(items: list[Any]) -> list[dict[str, Any]]:
        return sorted(
            (item.model_dump(mode="json", by_alias=True, exclude_none=True) for item in items),
            key=lambda item: str(item.get("name", item.get("uri", item.get("uriTemplate", "")))),
        )

    tools = await client.list_tools()
    resources = await client.list_resources()
    templates = await client.list_resource_templates()
    prompts = await client.list_prompts()
    return {
        "tools": normalize(tools.tools),
        "resources": normalize(resources.resources),
        "resource_templates": normalize(templates.resource_templates),
        "prompts": normalize(prompts.prompts),
    }


def test_stdio_and_streamable_http_publish_identical_contracts(tmp_path: Path) -> None:
    async def exercise() -> tuple[dict[str, list[dict[str, Any]]], dict[str, list[dict[str, Any]]]]:
        results_dir = tmp_path / "results"
        charts_dir = tmp_path / "charts"
        params = StdioServerParameters(
            command=sys.executable,
            args=[
                "-m",
                "benchbox.mcp",
                "--results-dir",
                str(results_dir),
                "--charts-dir",
                str(charts_dir),
            ],
            env=dict(os.environ),
        )
        with open(os.devnull, "w", encoding="utf-8") as errlog:
            async with Client(stdio_client(params, errlog=errlog), mode="legacy") as stdio:
                stdio_inventory = await _inventory(stdio)

        async with http_client(
            tmp_path,
            mode="auto",
            request_headers=[],
            response_headers=[],
        ) as http:
            http_inventory = await _inventory(http)

        return stdio_inventory, http_inventory

    stdio_inventory, http_inventory = anyio.run(exercise)

    assert stdio_inventory == http_inventory
    assert len(http_inventory["tools"]) == 12
    assert len(http_inventory["resources"]) == 4
    assert len(http_inventory["resource_templates"]) == 2
    assert len(http_inventory["prompts"]) == 7
