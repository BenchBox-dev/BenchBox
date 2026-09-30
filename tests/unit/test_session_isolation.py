"""Prove HOME isolation covers collection without bypassing the shared lock."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import click
import pytest
from click.testing import CliRunner

from scripts.local_validation import _close_lock, wait_for_lock, write_holder
from tests.utilities.paths import REPO_ROOT

pytestmark = [pytest.mark.unit, pytest.mark.fast]


def test_unit_home_is_owned_and_empty(_unit_home: Path) -> None:
    assert Path.home() == _unit_home
    assert os.environ["USERPROFILE"] == str(_unit_home)
    assert not (_unit_home / ".benchbox").exists()


def test_cli_invocation_owns_quiet_and_provider_state() -> None:
    import benchbox.utils.config_interface as ci
    import benchbox.utils.printing as printing

    before = (printing._QUIET, ci._config_provider)
    installed = object()

    @click.command()
    def command():
        printing.set_quiet(True)
        ci._config_provider = installed  # type: ignore[assignment]
        assert printing.is_quiet()
        assert ci._config_provider is installed
        raise click.ClickException("intentional failure")

    result = CliRunner().invoke(command)
    assert result.exit_code == 1
    assert (printing._QUIET, ci._config_provider) == before


@pytest.mark.parametrize("collect_only", [False, True])
def test_home_is_isolated_before_conftest_and_collection(tmp_path: Path, collect_only: bool) -> None:
    real_home = tmp_path / "caller-home"
    real_config = real_home / ".benchbox" / "config.yaml"
    real_config.parent.mkdir(parents=True)
    poison = "poisoned-real-home-config\n"
    real_config.write_text(poison, encoding="utf-8")
    (tmp_path / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    (tmp_path / "conftest.py").write_text(
        "import os\nfrom pathlib import Path\n"
        'assert str(Path.home()) != os.environ["PROBE_CALLER_HOME"]\n'
        'assert not (Path.home() / ".benchbox" / "config.yaml").exists()\n'
        'assert os.environ["USERPROFILE"] == str(Path.home())\n',
        encoding="utf-8",
    )
    (tmp_path / "test_probe.py").write_text(
        "from pathlib import Path\n"
        'assert not (Path.home() / ".benchbox").exists()\n'
        "def test_home():\n"
        '    (Path.home() / ".benchbox").mkdir()\n'
        '    (Path.home() / ".benchbox" / "config.yaml").write_text("owned")\n',
        encoding="utf-8",
    )
    env = dict(
        os.environ,
        HOME=str(real_home),
        USERPROFILE=str(real_home),
        PROBE_CALLER_HOME=str(real_home),
        PYTHONPATH=str(REPO_ROOT),
    )
    command = [
        sys.executable,
        "-m",
        "pytest",
        "-c",
        str(tmp_path / "pytest.ini"),
        "--confcutdir",
        str(tmp_path),
        "-p",
        "_benchbox_pytest_xdist_safety",
        "-n",
        "0",
        "-q",
        "test_probe.py",
    ]
    if collect_only:
        command.append("--collect-only")
    result = subprocess.run(command, cwd=tmp_path, env=env, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    assert real_config.read_text(encoding="utf-8") == poison


def test_contended_lock_prevents_home_setup(tmp_path: Path) -> None:
    lock_path = tmp_path / "lock" / "test.lock"
    fd = wait_for_lock(lock_path, 0)
    write_holder(fd, lock_path, phase="test", gate="isolation-negative")
    env = dict(
        os.environ,
        PYTHONPATH=str(REPO_ROOT),
        BENCHBOX_TEST_LOCK_DIR=str(lock_path.parent),
        BENCHBOX_TEST_LOCK_WAIT_SECONDS="0",
    )
    env.pop("BENCHBOX_TEST_SESSION_OWNER", None)
    script = (
        "import os\nfrom tests.utilities import session_isolation as isolation\n"
        "before = dict(os.environ)\n"
        'def forbidden(*a, **k):\n    raise AssertionError("HOME created before lock")\n'
        "isolation.tempfile.TemporaryDirectory = forbidden\n"
        "try:\n    isolation.start()\n"
        "except TimeoutError:\n    assert dict(os.environ) == before\n"
        'else:\n    raise AssertionError("contended lock bypassed")\n'
    )
    try:
        result = subprocess.run([sys.executable, "-c", script], env=env, capture_output=True, text=True, timeout=30)
        assert result.returncode == 0, result.stdout + result.stderr
        assert f"pid:{os.getpid()} " in lock_path.read_text(encoding="utf-8")
    finally:
        _close_lock(fd)


def test_session_finish_restores_caller_environment(tmp_path: Path) -> None:
    env = dict(os.environ, PYTHONPATH=str(REPO_ROOT))
    script = (
        "import os\nfrom pathlib import Path\nfrom tests.utilities import session_isolation as isolation\n"
        "before = dict(os.environ)\n"
        "isolation.start()\nowned_home = Path.home()\n"
        'assert owned_home.is_dir()\nassert str(owned_home) != before["HOME"]\n'
        "isolation.finish()\nisolation.finish()\n"
        "assert dict(os.environ) == before\nassert not owned_home.exists()\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script], cwd=tmp_path, env=env, capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 0, result.stdout + result.stderr
