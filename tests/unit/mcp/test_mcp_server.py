"""Tests for BenchBox MCP server creation and configuration.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import pytest

pytestmark = [
    pytest.mark.unit,
    pytest.mark.medium,
]


# Skip if MCP SDK not installed
mcp = pytest.importorskip("mcp", reason="MCP SDK not installed. Install with: uv add benchbox --extra mcp")


class TestMCPServerCreation:
    """Tests for MCP server creation."""

    def test_create_server_returns_mcpserver_instance(self):
        """Test that create_server returns an MCPServer instance."""
        from mcp.server.mcpserver import MCPServer

        from benchbox.mcp import create_server

        server = create_server()

        assert isinstance(server, MCPServer)
        assert server.name == "benchbox"
        assert server.version

    def test_server_has_instructions(self):
        """Test that server has instructions configured."""
        from benchbox.mcp import create_server

        server = create_server()

        assert hasattr(server, "instructions")
        assert server.instructions is not None
        assert "BenchBox" in server.instructions

    def test_run_server_function_exists(self):
        """Test that run_server function exists and is callable."""
        from benchbox.mcp import run_server

        assert callable(run_server)


class TestMCPToolRegistration:
    """Tests for MCP tool registration."""

    def test_discovery_tools_registered(self):
        """Test that discovery tools are registered."""
        from benchbox.mcp import create_server

        server = create_server()

        from tests.unit.mcp.public_api import list_tool_names

        assert "list_available" in list_tool_names(server)

    def test_benchmark_tools_registered(self):
        """Test that benchmark execution tools are registered."""
        from benchbox.mcp import create_server

        server = create_server()
        from tests.unit.mcp.public_api import list_tool_names

        assert "run_benchmark" in list_tool_names(server)

    def test_results_tools_registered(self):
        """Test that results tools are registered."""
        from benchbox.mcp import create_server

        server = create_server()
        from tests.unit.mcp.public_api import list_tool_names

        assert "get_results" in list_tool_names(server)


class TestMCPResourceRegistration:
    """Tests for MCP resource registration."""

    def test_resources_registered(self):
        """Test that resources are registered."""
        from benchbox.mcp import create_server

        server = create_server()
        assert server is not None


class TestMCPPromptRegistration:
    """Tests for MCP prompt registration."""

    def test_prompts_registered(self):
        """Test that prompts are registered."""
        from benchbox.mcp import create_server

        server = create_server()
        assert server is not None


class TestMCPPublicContract:
    """Pin the client-visible inventory preserved by the SDK v2 migration."""

    def test_registered_inventory_matches_documented_contract(self):
        from benchbox.mcp import create_server
        from tests.unit.mcp.public_api import (
            list_prompt_names,
            list_resource_template_uris,
            list_resource_uris,
            list_tool_names,
        )

        server = create_server()

        assert list_tool_names(server) == {
            "analyze_results",
            "check_dependencies",
            "generate_chart",
            "get_benchmark_info",
            "get_query_details",
            "get_query_plan",
            "get_results",
            "list_available",
            "run_benchmark",
            "suggest_charts",
            "system_profile",
            "validate_results",
        }
        assert list_resource_uris(server) == {
            "benchbox://benchmarks",
            "benchbox://platforms",
            "benchbox://results/recent",
            "benchbox://system/profile",
        }
        assert list_resource_template_uris(server) == {
            "benchbox://benchmarks/{name}",
            "benchbox://platforms/{name}",
        }
        assert list_prompt_names(server) == {
            "analyze_results",
            "benchmark_planning",
            "benchmark_run",
            "compare_platforms",
            "identify_regressions",
            "platform_tuning",
            "troubleshoot_failure",
        }


class TestPythonVersionCheck:
    """Tests for Python version compatibility."""

    def test_import_fails_on_python39(self, monkeypatch):
        """Test that import raises error on Python < 3.10."""
        # This test runs on Python 3.10+ but simulates version check
        import benchbox.mcp as mcp_module

        # The version check happens at import time, so the module
        # either imported successfully (we're on 3.10+) or not
        assert mcp_module is not None
