import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.fast]

ROOT = Path(__file__).resolve().parents[2]

_KEYS = (
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_INDEX_FILE",
    "GIT_COMMON_DIR",
    "GIT_OBJECT_DIRECTORY",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_PREFIX",
)


def test_session_drops_inherited_repository_location() -> None:
    for key in _KEYS:
        assert key not in os.environ


def test_a_hook_environment_cannot_redirect_scratch_git_commands(tmp_path: Path) -> None:
    outer = tmp_path / "outer"
    subprocess.run(["git", "init", "-q", str(outer)], check=True)
    probe = tmp_path / "probe.py"
    probe.write_text(
        "import os, subprocess, sys\n"
        "sys.path.insert(0, sys.argv[1])\n"
        "import tests.conftest  # noqa: F401\n"
        "scratch = sys.argv[2]\n"
        "os.makedirs(scratch)\n"
        "subprocess.run(['git', 'init', '-q', '.'], cwd=scratch, check=True)\n"
        "subprocess.run(['git', 'config', 'user.name', 'Scratch'], cwd=scratch, check=True)\n",
        encoding="utf-8",
    )
    env = dict(os.environ, GIT_DIR=str(outer / ".git"), GIT_WORK_TREE=str(outer))
    subprocess.run(
        [sys.executable, str(probe), str(ROOT), str(tmp_path / "scratch")],
        check=True,
        env=env,
        cwd=tmp_path,
    )
    outer_name = subprocess.run(
        ["git", "config", "-f", str(outer / ".git" / "config"), "--get", "user.name"],
        capture_output=True,
        text=True,
    )
    assert outer_name.stdout.strip() == ""
    assert (tmp_path / "scratch" / ".git").is_dir()
