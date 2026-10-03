import io
import sys
from unittest.mock import MagicMock, patch

import pytest

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


class TestMCPServerQuietMode:
    def test_create_server_enables_quiet_mode(self):
        from benchbox.utils.printing import is_quiet, set_quiet

        set_quiet(False)
        assert not is_quiet()

        from benchbox.mcp import create_server

        create_server()

        assert is_quiet()

        set_quiet(False)


class TestResultExporterQuietConsole:
    def test_benchmark_tool_uses_quiet_console(self):
        from benchbox.mcp.tools.benchmark import get_quiet_console

        assert callable(get_quiet_console)

        quiet_console = get_quiet_console()

        from benchbox.utils.printing import set_quiet

        set_quiet(True)
        quiet_console = get_quiet_console()
        assert hasattr(quiet_console, "file")
        assert isinstance(quiet_console.file, io.StringIO)
        set_quiet(False)

    def test_results_tool_uses_quiet_console(self):
        from benchbox.utils.printing import get_quiet_console

        assert callable(get_quiet_console)


class TestNoStdoutLeakage:
    def test_result_exporter_no_stdout_with_quiet_console(self):
        from benchbox.core.results.exporter import ResultExporter
        from benchbox.utils.printing import get_quiet_console

        captured = io.StringIO()
        original_stdout = sys.stdout

        try:
            sys.stdout = captured

            quiet_console = get_quiet_console()
            exporter = ResultExporter(
                anonymize=False,
                console=quiet_console,
            )

            exporter.console.print("Test message that should not appear on stdout")
            exporter.console.print("[green]Exported JSON:[/green] /path/to/file.json")

            stdout_content = captured.getvalue()
            assert stdout_content == "", f"Unexpected stdout: {stdout_content!r}"

        finally:
            sys.stdout = original_stdout

    def test_server_creation_no_stdout(self):
        captured = io.StringIO()
        original_stdout = sys.stdout

        try:
            sys.stdout = captured

            from benchbox.mcp import create_server

            create_server()

            stdout_content = captured.getvalue()
            assert stdout_content == "", f"Unexpected stdout during server creation: {stdout_content!r}"

        finally:
            sys.stdout = original_stdout

        from benchbox.utils.printing import set_quiet

        set_quiet(False)
