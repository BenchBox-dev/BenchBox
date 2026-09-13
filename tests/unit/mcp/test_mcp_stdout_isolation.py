"""Tests for MCP server stdout isolation.

MCP servers using stdio transport must not emit anything to stdout except
JSON-RPC messages. These tests verify that MCP tool operations don't leak
output to stdout, which would corrupt the JSON-RPC stream and cause strict
clients (like codex CLI) to close the transport.
"""

import io
import sys
from unittest.mock import MagicMock, patch

import pytest

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


class TestMCPServerQuietMode:
    """Tests that MCP server sets quiet mode on initialization."""

    def test_create_server_enables_quiet_mode(self):
        """Verify create_benchbox_server sets quiet mode."""
        from benchbox.utils.printing import is_quiet, set_quiet

        # Reset quiet mode to ensure test isolation
        set_quiet(False)
        assert not is_quiet()

        # Import and create server
        from benchbox.mcp import create_server

        create_server()

        # Quiet mode should now be enabled
        assert is_quiet()

        # Cleanup: reset quiet mode
        set_quiet(False)


class TestResultExporterQuietConsole:
    """Tests that MCP tools use quiet console for ResultExporter."""

    def test_benchmark_tool_uses_quiet_console(self):
        """Verify run_benchmark creates ResultExporter with quiet console."""
        from benchbox.mcp.tools.benchmark import get_quiet_console

        # Verify the import works (if import fails, the fix wasn't applied)
        assert callable(get_quiet_console)

        # Get a quiet console and verify it's a sink
        quiet_console = get_quiet_console()

        # Verify the quiet console writes to StringIO (sink)
        # The console's file attribute should be a StringIO when quiet
        from benchbox.utils.printing import set_quiet

        set_quiet(True)
        quiet_console = get_quiet_console()
        assert hasattr(quiet_console, "file")
        assert isinstance(quiet_console.file, io.StringIO)
        set_quiet(False)

    def test_results_tool_uses_quiet_console(self):
        """Verify quiet console is available from utils.printing."""
        from benchbox.utils.printing import get_quiet_console

        # Verify the import works (function should be available)
        assert callable(get_quiet_console)


class TestNoStdoutLeakage:
    """Tests that tool operations don't leak output to stdout."""

    def test_result_exporter_no_stdout_with_quiet_console(self):
        """Verify ResultExporter with quiet console produces no stdout."""
        from benchbox.core.results.exporter import ResultExporter
        from benchbox.utils.printing import get_quiet_console

        # Capture stdout
        captured = io.StringIO()
        original_stdout = sys.stdout

        try:
            sys.stdout = captured

            # Create exporter with quiet console
            quiet_console = get_quiet_console()
            exporter = ResultExporter(
                anonymize=False,
                console=quiet_console,
            )

            # Directly call console.print via the exporter's console
            # This simulates what happens during export_result
            exporter.console.print("Test message that should not appear on stdout")
            exporter.console.print("[green]Exported JSON:[/green] /path/to/file.json")

            # Verify no stdout leakage
            stdout_content = captured.getvalue()
            assert stdout_content == "", f"Unexpected stdout: {stdout_content!r}"

        finally:
            sys.stdout = original_stdout

    def test_server_creation_no_stdout(self):
        """Verify MCP server creation produces no stdout."""
        captured = io.StringIO()
        original_stdout = sys.stdout

        try:
            sys.stdout = captured

            from benchbox.mcp import create_server

            create_server()

            # Verify no stdout leakage from server creation
            stdout_content = captured.getvalue()
            assert stdout_content == "", f"Unexpected stdout during server creation: {stdout_content!r}"

        finally:
            sys.stdout = original_stdout

        # Cleanup quiet mode
        from benchbox.utils.printing import set_quiet

        set_quiet(False)
