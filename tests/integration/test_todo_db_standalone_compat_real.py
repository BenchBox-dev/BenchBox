"""Real-subprocess smoke coverage for the standalone compatibility boundary."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.medium]


def test_real_standalone_binary_accepts_pinned_database_and_identity(tmp_path: Path) -> None:
    executable = shutil.which("todo-db")
    if executable is None:
        pytest.skip("released todo-db binary is not installed")

    repo_root = Path(__file__).resolve().parents[2]
    database = tmp_path / "standalone.sqlite"
    environment = os.environ.copy()
    environment.update(
        {
            "BENCHBOX_REPO_ROOT": str(repo_root),
            "BENCHBOX_TODO_DB_COMMAND": executable,
            "TODO_DB_PATH": str(tmp_path / "must-not-win.sqlite"),
        }
    )
    result = subprocess.run(
        [
            "uv",
            "run",
            "--",
            "python",
            str(repo_root / "_project" / "scripts" / "todo_db_standalone_compat.py"),
            "--db",
            str(database),
            "init",
        ],
        cwd=repo_root,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert database.is_file()
    assert not (tmp_path / "must-not-win.sqlite").exists()
