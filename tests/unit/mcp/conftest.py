import pytest


@pytest.fixture(autouse=True)
def _mcp_stdio_state(_hermetic_state, monkeypatch: pytest.MonkeyPatch) -> None:

    import benchbox.utils.printing as printing

    monkeypatch.setattr(printing, "_QUIET", printing._QUIET)
