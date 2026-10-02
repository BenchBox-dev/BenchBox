"""Own the stdio output state installed by in-process MCP servers."""

import pytest


@pytest.fixture(autouse=True)
def _mcp_stdio_state(_hermetic_state, monkeypatch: pytest.MonkeyPatch) -> None:
    """Restore the output mode when the test's MCP server lifetime ends."""
    import benchbox.utils.printing as printing

    monkeypatch.setattr(printing, "_QUIET", printing._QUIET)
