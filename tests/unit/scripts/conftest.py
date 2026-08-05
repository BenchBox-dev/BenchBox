"""conftest for tests/unit/scripts/ - adds the project scripts/ dir to sys.path."""

import shutil
import sys
from pathlib import Path

import pytest

# Make scripts/ importable so test modules can use plain imports.
_scripts_dir = str(Path(__file__).resolve().parents[3] / "scripts")
if _scripts_dir not in sys.path:
    sys.path.insert(0, _scripts_dir)


@pytest.fixture(autouse=True)
def _todo_db_turso_never_auto_detected(monkeypatch):
    """Keep todo_db tests hermetic against the host machine's real turso CLI.

    `_project/scripts/todo_db.py`'s backend resolution auto-provisions a
    hosted backend by shelling out to `turso` when no explicit backend is
    configured (see `_try_turso_auto_provision`). On a machine where `turso`
    is on PATH and logged in (e.g. a maintainer's workstation), tests that
    exercise the implicit-local-fallback path would otherwise silently start
    making real `turso` subprocess calls -- and possibly real network calls --
    instead of testing the fallback they intend to. Force `shutil.which`
    to report `turso` as absent everywhere by default; tests that want to
    exercise auto-provisioning override `shutil.which` themselves.
    """
    real_which = shutil.which

    def which(cmd, *args, **kwargs):
        if cmd == "turso":
            return None
        return real_which(cmd, *args, **kwargs)

    monkeypatch.setattr(shutil, "which", which)
