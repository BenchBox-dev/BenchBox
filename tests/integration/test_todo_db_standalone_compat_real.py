"""Real-subprocess smoke coverage for the standalone compatibility boundary."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.medium]


def _run_wrapper(
    repo_root: Path, database: Path, *args: str, todo_db_path: Path | None = None
) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment.update({"BENCHBOX_REPO_ROOT": str(repo_root), "TODO_DB_PATH": str(todo_db_path or database)})
    return subprocess.run(
        [str(repo_root / "_project" / "scripts" / "todo"), "--db", str(database), *args],
        cwd=repo_root,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )


def test_real_locked_wrapper_accepts_pinned_database_and_identity(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    database = tmp_path / "standalone.sqlite"
    result = _run_wrapper(repo_root, database, "init", todo_db_path=tmp_path / "must-not-win.sqlite")
    assert result.returncode == 0, result.stderr
    assert database.is_file()
    assert not (tmp_path / "must-not-win.sqlite").exists()


@pytest.mark.parametrize("command", ["init-project", "restore", "restore-legacy"])
def test_real_locked_wrapper_rejects_standalone_only_destructive_commands(tmp_path: Path, command: str) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    result = _run_wrapper(repo_root, tmp_path / "standalone.sqlite", command)

    assert result.returncode == 2
    assert "does not expose standalone-only" in result.stderr


def test_real_locked_wrapper_preserves_package_export_bytes(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    database = tmp_path / "standalone.sqlite"
    assert _run_wrapper(repo_root, database, "init").returncode == 0
    compatibility_dir = tmp_path / "compatibility"
    lossless_dir = tmp_path / "lossless"
    wrapper_export = _run_wrapper(
        repo_root,
        database,
        "export",
        "--out",
        str(compatibility_dir),
        "--lossless-out",
        str(lossless_dir),
    )
    assert wrapper_export.returncode == 0, wrapper_export.stderr

    direct_export = tmp_path / "direct.json"
    direct = subprocess.run(
        [
            "uv",
            "run",
            "--project",
            str(repo_root / "_project" / "scripts"),
            "--locked",
            "--",
            "todo-db",
            "--db",
            str(database),
            "--project-id",
            "benchbox",
            "--repository",
            "https://github.com/joeharris76/BenchBox",
            "export",
            "--output",
            str(direct_export),
        ],
        cwd=repo_root,
        text=True,
        capture_output=True,
        check=False,
    )
    assert direct.returncode == 0, direct.stderr
    assert (lossless_dir / "todo-db.json").read_bytes() == direct_export.read_bytes()
