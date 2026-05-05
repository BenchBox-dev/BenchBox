"""Fast-test coverage for tests/uat/_cli.py main dispatch."""

from __future__ import annotations

import pytest

from tests.uat import _cli

pytestmark = pytest.mark.fast


def test_main_routes_subcommand(monkeypatch):
    calls: list[tuple[str, list[str]]] = []

    def fake_execute_main(argv):
        calls.append(("execute", argv))
        return 0

    monkeypatch.setitem(_cli.SUBCOMMANDS, "execute", fake_execute_main)
    rc = _cli.main(["execute", "--config", "x.yaml"])
    assert rc == 0
    assert calls == [("execute", ["--config", "x.yaml"])]


def test_main_no_args_routes_to_cell(monkeypatch):
    calls: list[list[str]] = []

    def fake_cell_main(argv):
        calls.append(argv)
        return 0

    monkeypatch.setitem(_cli.SUBCOMMANDS, "cell", fake_cell_main)
    monkeypatch.setattr(_cli, "cell_main", fake_cell_main)
    rc = _cli.main([])
    assert rc == 0
    assert calls == [[]]


def test_main_bare_flags_route_to_cell(monkeypatch):
    """Backward-compat: `python -m tests.uat._cli --platform=...` is the uat-cell make target."""
    calls: list[list[str]] = []

    def fake_cell_main(argv):
        calls.append(argv)
        return 0

    monkeypatch.setattr(_cli, "cell_main", fake_cell_main)
    rc = _cli.main(["--platform", "duckdb", "--benchmark", "tpch", "--scale", "0.01"])
    assert rc == 0
    assert calls == [["--platform", "duckdb", "--benchmark", "tpch", "--scale", "0.01"]]


def test_main_unknown_subcommand_returns_2(capsys):
    rc = _cli.main(["nonsense"])
    assert rc == 2
    err = capsys.readouterr().err
    assert "unknown subcommand" in err


def test_main_help_returns_0(capsys):
    rc = _cli.main(["--help"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "subcommands" in out


def test_subcommands_table_covers_all_make_targets():
    """The dispatch table must cover every make uat-* target's subcommand."""
    expected = {
        "cell",
        "execute",
        "validate",
        "package",
        "explorer-smoke",
        "report",
        "sweep",
        "stress",
    }
    assert set(_cli.SUBCOMMANDS) == expected
