from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from _project.scripts.oracle_reviewers.evidence import Trace, codex_errors, relative, trace

pytestmark = [pytest.mark.unit, pytest.mark.fast]


def _events(*events: dict) -> str:
    return "\n".join(json.dumps(event) for event in events) + "\n"


def test_codex_trace_keeps_only_successful_command_text() -> None:
    ok = {"type": "command_execution", "command": "cat a.py", "aggregated_output": "b.py c.py", "exit_code": 0}
    failed = {**ok, "command": "cat b.py", "exit_code": 1}
    started = {"type": "item.started", "item": {**ok, "command": "cat c.py"}}
    message = {"type": "item.completed", "item": {"type": "agent_message", "text": "cat d.py"}}
    stdout = _events(
        {"type": "item.completed", "item": ok}, {"type": "item.completed", "item": failed}, started, message
    )
    assert trace("codex", "not json\n" + stdout) == Trace(("cat a.py",))


def _claude_stream(*uses: tuple[str, str, dict, bool]) -> str:
    events = []
    for use_id, name, tool_input, error in uses:
        block = {"type": "tool_use", "id": use_id, "name": name, "input": tool_input}
        events.append({"type": "assistant", "message": {"content": [block]}})
        result = {"type": "tool_result", "tool_use_id": use_id, "is_error": error, "content": "x"}
        events.append({"type": "user", "message": {"content": [result]}})
    events.append({"type": "result", "num_turns": len(uses) + 1})
    return _events(*events)


def test_claude_trace_keeps_successful_reads_and_greps_only() -> None:
    stdout = _claude_stream(
        ("1", "Read", {"file_path": "/ws/a.py"}, False),
        ("2", "Grep", {"pattern": "x", "path": "b.py"}, False),
        ("3", "Read", {"file_path": "/ws/c.py"}, True),
        ("4", "Glob", {"pattern": "*.py", "path": "/ws/d.py"}, False),
        ("5", "StructuredOutput", {"status": "complete"}, False),
    )
    assert trace("claude", stdout) == Trace(("/ws/a.py", "b.py"))
    assert trace("claude", json.dumps({"num_turns": 4})) == Trace()
    assert trace("muse", stdout) == Trace()


@pytest.mark.parametrize(
    ("command", "named"),
    [
        ("cat -n pkg/a.py", True),
        ("/bin/zsh -lc 'cat -n pkg/a.py'", True),
        ("/bin/zsh -lc 'pwd; ls; head -n 40 pkg/a.py'", True),
        ("grep -n compare pkg/a.py", True),
        ("rg -e pkg/a.py -n x pkg/a.py", True),
        ("git diff HEAD~1 -- pkg/a.py", True),
        ("sed -n '1,80p' ./pkg/a.py", True),
        ("git show HEAD:pkg/a.py", True),
        ("rg -n compare pkg/a.py", True),
        ("cat {root}/pkg/a.py", True),
        ("cat pkg/data.py", False),
        ("ls pkg/a.py", False),
        ("test -f pkg/a.py", False),
        ("wc -l pkg/a.py", False),
        ("echo pkg/a.py", False),
        ("find pkg/a.py", False),
        ("grep -n pkg/a.py .oracle-pull-request.diff", False),
        ("grep -n -e pkg/a.py .oracle-pull-request.diff", False),
        ("rg pkg/a.py", False),
        ("/bin/zsh -lc 'echo pkg/a.py; ls'", False),
        ("cat pkg/a.pyc", False),
        ("ls -R pkg", False),
        ("cat .oracle-pull-request.diff", False),
        ("cat otherpkg/a.py", False),
    ],
)
def test_a_codex_read_names_the_required_file_exactly(tmp_path: Path, command: str, named: bool) -> None:
    from _project.scripts.oracle_reviewers.evidence import unread

    workspace = tmp_path / "ws"
    workspace.mkdir()
    text = command.format(root=os.path.realpath(workspace))
    assert (unread("codex", ["pkg/a.py"], Trace((text,)), workspace) == []) is named


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
