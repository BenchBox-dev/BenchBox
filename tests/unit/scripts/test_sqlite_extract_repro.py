"""Check the standalone extraction reproducer's result and error reporting."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.fast]


@pytest.mark.parametrize(
    ("translated", "expected", "exit_code", "has_error"),
    [
        ("SELECT 2020", [(2020,)], 0, False),
        ("SELECT 2019", [(2020,)], 1, False),
        ("SELECT NULL", [(0,)], 1, False),
        ("SELECT ' x'", [("x",)], 1, False),
        ("SELECT 1 UNION ALL SELECT 1", [(1,)], 1, False),
        ("SELECT 2 UNION ALL SELECT 1", [(1,), (2,)], 1, False),
        ("SELECT missing_function()", [(2020,)], 1, True),
    ],
)
def test_execution_report(monkeypatch, capsys, translated, expected, exit_code, has_error):
    path = Path(__file__).resolve().parents[3] / "_project/sqlglot-upstream/repros/sqlite_extract.py"
    spec = importlib.util.spec_from_file_location("sqlite_extract_repro", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "cases", lambda: [("witness", "postgres", "SELECT source", expected)])

    def transpile(sql, *, read, write):
        assert (sql, read, write) == ("SELECT source", "postgres", "sqlite")
        return [translated]

    monkeypatch.setattr(module.sqlglot, "transpile", transpile)
    assert module.main() == exit_code
    report = json.loads(capsys.readouterr().out)
    assert report["total"] == 1
    assert report["passed"] == int(exit_code == 0)
    assert ("error" in report["cases"][0]) == has_error
    assert len(report["naive_lowering_counterexamples"]) == 2
