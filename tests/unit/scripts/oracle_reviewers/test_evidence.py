from __future__ import annotations

import json
from pathlib import Path

import pytest

from _project.scripts.oracle_reviewers.evidence import Trace, codex_errors, relative, trace

pytestmark = [pytest.mark.unit, pytest.mark.fast]


def _events(*events: dict) -> str:
    return "\n".join(json.dumps(event) for event in events) + "\n"


def test_codex_trace_keeps_only_successful_command_executions() -> None:
    ok = {"type": "command_execution", "command": "cat a.py", "aggregated_output": "x = 1", "exit_code": 0}
    failed = {**ok, "command": "cat b.py", "exit_code": 1}
    started = {"type": "item.started", "item": {**ok, "command": "cat c.py"}}
    message = {"type": "item.completed", "item": {"type": "agent_message", "text": "cat d.py"}}
    stdout = _events(
        {"type": "item.completed", "item": ok}, {"type": "item.completed", "item": failed}, started, message
    )
    assert trace("codex", "not json\n" + stdout) == Trace(reads=("cat a.py\nx = 1",))


def test_claude_trace_reads_the_turn_count_from_the_envelope() -> None:
    assert trace("claude", json.dumps({"num_turns": 4})) == Trace(turns=4)
    assert trace("claude", json.dumps({"num_turns": True})) == Trace()
    assert trace("claude", "not json") == Trace()
    assert trace("muse", json.dumps({"num_turns": 4})) == Trace()


def test_codex_errors_become_error_lines_for_the_absence_patterns() -> None:
    stdout = _events(
        {"type": "error", "message": "unexpected status 401 Unauthorized"},
        {"type": "turn.failed", "error": {"message": "You've hit your usage limit"}},
        {"type": "item.completed", "item": {"type": "agent_message", "message": "ignored"}},
    )
    assert codex_errors(stdout) == "ERROR: unexpected status 401 Unauthorized\nERROR: You've hit your usage limit"


def test_relative_maps_workspace_paths_and_leaves_outside_paths_absolute(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    (workspace / "pkg").mkdir(parents=True)
    assert relative("pkg/a.py", workspace) == "pkg/a.py"
    assert relative("./pkg/a.py", workspace) == "pkg/a.py"
    assert relative(str(workspace.resolve() / "pkg" / "a.py"), workspace) == "pkg/a.py"
    assert relative("/etc/passwd", workspace) == "/etc/passwd"
    assert relative("pkg/a.py:12", workspace) == "pkg/a.py"
    assert relative("pkg/a.py:12-40", workspace) == "pkg/a.py"
    assert relative(str(workspace.resolve() / "pkg" / "a.py") + ":3", workspace) == "pkg/a.py"
    assert relative("../ws2/a.py", workspace).endswith("ws2/a.py")
    assert not relative("../ws2/a.py", workspace).startswith("ws2")
