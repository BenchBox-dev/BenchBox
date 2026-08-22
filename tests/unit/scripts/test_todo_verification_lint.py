"""Semantic verification-command lint regressions."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.fast]

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "_project/scripts/todo_verification_lint.py"
SPEC = importlib.util.spec_from_file_location("todo_verification_lint", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
lint = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = lint
SPEC.loader.exec_module(lint)


@pytest.mark.parametrize(
    ("command", "rule"),
    [
        ("uv run _project/scripts/todo_db.py list", "retired-entrypoint"),
        ("benchbox run --queries sketch_*", "wildcard-queries"),
        ("find out -newer start end", "find-newer-extra-operand"),
        ("duckdb results-*.duckdb 'select 1'", "wildcard-duckdb"),
        ("test -d runs/$(date +%F)", "runtime-date"),
    ],
)
def test_falsifiability_rules_reject_known_semantic_antipatterns(command: str, rule: str) -> None:
    assert rule in lint.lint_command(command)


@pytest.mark.parametrize(
    "command",
    [
        "! test -e _project/scripts/todo_db.py",
        "! test -e _project/scripts/validate_todo.py && ! test -e _project/scripts/todo_cli.py",
        "rg -n 'todo_db.py' _project/scripts",
        "benchbox run --queries q1,q2",
        "find out -newer start -print",
        "duckdb results.duckdb 'select 1'",
        "test -d runs/2026-08-20",
        "printf 'first\nsecond'",
    ],
)
def test_post_rule_advisory_near_misses_remain_valid(command: str) -> None:
    assert lint.lint_command(command) == []


def test_lint_items_reports_item_and_sequence() -> None:
    findings = lint.lint_items(
        [{"id": "example", "verifications": [{"seq": 7, "command": "benchbox run --queries '*'"}]}]
    )

    assert findings == [lint.Finding("example", 7, "wildcard-queries")]


def test_filter_items_uses_done_state_and_inclusive_creation_window() -> None:
    items = [
        {"id": "before", "state": "done", "created_at": "2026-05-28T23:59:59Z"},
        {"id": "inside", "state": "done", "created_at": "2026-05-29T00:00:00Z"},
        {"id": "active", "state": "active", "created_at": "2026-06-01T00:00:00Z"},
    ]

    assert lint.filter_items(items, since="2026-05-29", until="2026-08-20") == [items[1]]
