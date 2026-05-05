"""Tests for TODO/DONE YAML validation."""

from __future__ import annotations

import importlib.util
import sys
import textwrap
from pathlib import Path

import pytest

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]

REPO_ROOT = Path(__file__).resolve().parents[3]
_BLIND_SPOT_COMMAND_PREFIX = (
    "uv run --project _project/scripts -- python _project/scripts/sweep_blind_spots.py list --status open | grep -E"
)
_BLIND_SPOT_PATTERN = "'081920|081921|081922' || echo 'all triaged'"


def _load_script():
    name = "validate_todo"
    path = REPO_ROOT / "_project" / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


validate_todo = _load_script()


def _validator():
    return validate_todo.TodoValidator(REPO_ROOT / "_project" / "TODO_SCHEMA.yaml")


def _write_todo(tmp_path: Path, body: str, relative_path: str = "example.yaml") -> Path:
    path = tmp_path / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(body).lstrip(), encoding="utf-8")
    return path


def test_non_completed_todo_rejects_wrapped_quoted_verification_command(tmp_path: Path) -> None:
    path = _write_todo(
        tmp_path,
        f"""
        id: example-todo
        title: "Example TODO"
        worktree: main
        priority: "Medium"
        status: "In Progress"
        description: |
          This TODO exercises command validation.
        verification:
        - description: "Blind-spot triage check"
          command: "{_BLIND_SPOT_COMMAND_PREFIX}
            {_BLIND_SPOT_PATTERN}"
          expected_output: "all triaged"
        """,
    )

    is_valid, errors = _validator().validate_file(path)

    assert not is_valid
    assert "verification command at line" in "\n".join(errors)
    assert "spans multiple physical lines" in "\n".join(errors)


def test_non_completed_todo_accepts_single_line_verification_command(tmp_path: Path) -> None:
    path = _write_todo(
        tmp_path,
        f"""
        id: example-todo
        title: "Example TODO"
        worktree: main
        priority: "Medium"
        status: "In Progress"
        description: |
          This TODO exercises command validation.
        verification:
        - description: "Blind-spot triage check"
          command: "{_BLIND_SPOT_COMMAND_PREFIX} {_BLIND_SPOT_PATTERN}"
          expected_output: "all triaged"
        """,
    )

    is_valid, errors = _validator().validate_file(path)

    assert is_valid, errors


def test_done_tree_keeps_legacy_wrapped_verification_commands_valid(tmp_path: Path) -> None:
    path = _write_todo(
        tmp_path,
        """
        id: example-done
        title: "Example DONE"
        worktree: main
        priority: "Medium"
        status: "Not Started"
        description: |
          This DONE item represents a historical record.
        verification:
        - description: "Legacy wrapped command"
          command: "uv run -- python -m pytest tests/unit/example.py
            -q"
          expected_output: "all tests pass"
        """,
        "_project/DONE/main/active/example-done.yaml",
    )

    is_valid, errors = _validator().validate_file(path)

    assert is_valid, errors


def test_non_completed_todo_accepts_literal_block_for_intentional_multiline_command(tmp_path: Path) -> None:
    path = _write_todo(
        tmp_path,
        """
        id: example-todo
        title: "Example TODO"
        worktree: main
        priority: "Medium"
        status: "In Progress"
        description: |
          This TODO exercises command validation.
        verification:
        - description: "Intentional multi-line shell script"
          command: |
            set -e
            echo ok
          expected_output: "ok"
        """,
    )

    is_valid, errors = _validator().validate_file(path)

    assert is_valid, errors
