"""Tests for skill-sync lock review/audit helper."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.fast]

REPO_ROOT = Path(__file__).resolve().parents[3]


def _load_script(name: str):
    path = REPO_ROOT / "_project" / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


skill_sync_lock_audit = _load_script("skill_sync_lock_audit")


def _lock(*, code_sha: str = "aaa", todo_sha: str = "bbb", fetched_at: str = "old") -> dict:
    return {
        "version": 1,
        "lockedAt": fetched_at,
        "skills": {
            "code": {
                "source": {"fetchedAt": fetched_at},
                "files": {"references/five-axis-review.md": {"sha256": code_sha, "size": len(code_sha)}},
            },
            "todo": {
                "source": {"fetchedAt": fetched_at},
                "files": {"SKILL.md": {"sha256": todo_sha, "size": len(todo_sha)}},
            },
        },
    }


def test_diff_skill_files_ignores_timestamp_churn() -> None:
    changes = skill_sync_lock_audit.diff_skill_files(_lock(fetched_at="old"), _lock(fetched_at="new"))

    assert changes == []


def test_diff_skill_files_reports_content_hash_changes() -> None:
    changes = skill_sync_lock_audit.diff_skill_files(_lock(), _lock(code_sha="changed"))

    assert [change.path for change in changes] == ["code/references/five-axis-review.md"]
    assert changes[0].old_sha == "aaa"
    assert changes[0].new_sha == "changed"


def test_allowed_patterns_from_todo_maps_skill_scope(tmp_path: Path) -> None:
    todo = tmp_path / "todo.yaml"
    todo.write_text(
        """
        id: example
        scope_limit:
          only_modify:
            - ".claude/skills/code/references/five-axis-review.md"
            - ".claude/skills/todo/"
            - "benchbox/not-a-skill.py"
        """,
        encoding="utf-8",
    )

    assert skill_sync_lock_audit.allowed_patterns_from_todo(todo) == [
        "code/references/five-axis-review.md",
        "todo/",
    ]


def test_allowed_patterns_gate_changed_lock_paths() -> None:
    assert skill_sync_lock_audit._is_allowed("todo/SKILL.md", ["todo/"])
    assert skill_sync_lock_audit._is_allowed(
        "code/references/five-axis-review.md", ["code/references/five-axis-review.md"]
    )
    assert not skill_sync_lock_audit._is_allowed("blog/references/critique.md", ["code/"])
