"""Tests for benchbox.mcp.__init__ lazy exports and public API.

All tests are guarded with pytest.importorskip("mcp") because the module
raises ImportError if the MCP SDK is not installed.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from unittest.mock import MagicMock, patch

import pytest

mcp = pytest.importorskip("mcp", reason="requires benchbox[mcp] extra")

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


class TestMcpCreateServer:
    def test_create_server_forwards_all_kwargs(self, tmp_path):
        with patch("benchbox.mcp.server.create_benchbox_server") as mock_create:
            mock_create.return_value = MagicMock()
            import benchbox.mcp as mcp_mod

            mcp_mod.create_server(
                results_dir=tmp_path,
                charts_dir=tmp_path / "charts",
                log_level="DEBUG",
                env={"FOO": "bar"},
            )
            mock_create.assert_called_once_with(
                results_dir=tmp_path,
                charts_dir=tmp_path / "charts",
                log_level="DEBUG",
                env={"FOO": "bar"},
            )


class TestMcpRunServer:
    def test_run_server_calls_server_run(self):
        with patch("benchbox.mcp.server.create_benchbox_server") as mock_create:
            mock_server = MagicMock()
            mock_create.return_value = mock_server

            import benchbox.mcp as mcp_mod

            mcp_mod.run_server()
            mock_server.run.assert_called_once()


class TestMcpLazyExports:
    def test_getattr_error_code(self):
        import benchbox.mcp as mcp_mod

        ErrorCode = mcp_mod.ErrorCode
        assert ErrorCode is not None

    def test_getattr_mcp_error(self):
        import benchbox.mcp as mcp_mod

        MCPError = mcp_mod.MCPError
        assert MCPError is not None

    def test_getattr_tool_call_context(self):
        import benchbox.mcp as mcp_mod

        ToolCallContext = mcp_mod.ToolCallContext
        assert ToolCallContext is not None

    def test_getattr_execution_status(self):
        import benchbox.mcp as mcp_mod

        ExecutionStatus = mcp_mod.ExecutionStatus
        assert ExecutionStatus is not None

    def test_getattr_unknown_raises_attribute_error(self):
        import benchbox.mcp as mcp_mod

        with pytest.raises(AttributeError, match="benchbox.mcp"):
            _ = mcp_mod.totally_unknown_name_xyz
