"""Coverage for the Makefile's `require_data_dir_if_mounted` guard.

`require_data_dir_if_mounted` (Makefile) is the ONLY validation on the
`make test-docker-up-lakesail` / `make test-docker-velox` entry points --
the behaviour documented in `docker/velox/README.md`,
`docs/platforms/lakesail.md`, and `docs/platforms/velox_docker_dev.md` --
yet had zero test coverage before this module: mutation testing (deleting
the `$(call require_data_dir_if_mounted,$*)` line from `test-docker-up-%`
alone) survived the full suite. These tests shell out to the REAL `make`
binary against the real Makefile so they pin what developers actually run,
but never touch a real container engine: `CONTAINER_ENGINE` is pointed at a
fake stub executable that only logs its argv and exits 0, so the guard is
exercised (and, on rejection, its ABSENCE of any compose call is proven)
without creating or destroying any real container/volume.

This module also pins the regression the guard's original placement caused
(F2 in the 2026-08-06 adversarial review): `require_data_dir_if_mounted`
used to sit AFTER `status=1` and AFTER `trap cleanup EXIT INT TERM` in
`test-docker-up-%`, so a guard rejection's own `exit 1` fired the
failure-cleanup trap -- which runs `compose down -v` against whatever
project name was already on record and deletes the tracking file. A second
shell re-running `make test-docker-up-lakesail` without exporting
BENCHBOX_DATA_DIR against an ALREADY-RUNNING stack from a first shell would
tear that live stack down and orphan it from tracking, even though the
guard's job is only to refuse a bad export, not to touch any existing
stack. `test_guard_rejection_leaves_a_tracked_stack_untouched` below pins
the fix: the guard must reject before the trap is even installed.
"""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.medium]

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

_FAKE_ENGINE_SCRIPT = """#!/usr/bin/env bash
# Fake CONTAINER_ENGINE for Makefile docker-guard tests. Never touches a
# real container engine: logs every invocation it receives and exits 0
# unconditionally, as if `compose up -d --wait` / `compose down -v` always
# succeeded.
printf '%s\\n' "$*" >> "$FAKE_ENGINE_LOG"
exit 0
"""


def _write_fake_engine(tmp_path: Path) -> Path:
    engine = tmp_path / "fake-container-engine"
    engine.write_text(_FAKE_ENGINE_SCRIPT)
    mode = engine.stat().st_mode
    engine.chmod(mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return engine


def _run_make(
    target: str,
    tmp_path: Path,
    *,
    state_dir: Path,
    engine: Path,
    log_file: Path,
    data_dir: str | None,
) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env.pop("BENCHBOX_DATA_DIR", None)
    if data_dir is not None:
        env["BENCHBOX_DATA_DIR"] = data_dir
    env["FAKE_ENGINE_LOG"] = str(log_file)

    return subprocess.run(
        [
            "make",
            "-C",
            str(REPO_ROOT),
            target,
            f"CONTAINER_ENGINE={engine}",
            f"DOCKER_TEST_STATE_DIR={state_dir}",
        ],
        capture_output=True,
        text=True,
        timeout=60,
        env=env,
    )


@pytest.mark.parametrize(
    ("target", "platform"),
    [
        ("test-docker-up-lakesail", "lakesail"),
        ("test-docker-up-velox", "velox"),
    ],
)
def test_guard_rejects_missing_data_dir_without_touching_compose(tmp_path, target, platform):
    state_dir = tmp_path / "docker-projects"
    state_dir.mkdir()
    log_file = tmp_path / "engine.log"
    engine = _write_fake_engine(tmp_path)

    result = _run_make(target, tmp_path, state_dir=state_dir, engine=engine, log_file=log_file, data_dir=None)

    assert result.returncode != 0, result.stderr
    assert "BENCHBOX_DATA_DIR must be exported" in result.stderr
    assert f"docker/{platform}" in result.stderr
    assert not log_file.exists(), (
        "guard rejection must never reach the container engine -- "
        f"fake engine log unexpectedly created: {log_file.read_text() if log_file.exists() else ''}"
    )


@pytest.mark.parametrize(
    ("target", "platform"),
    [
        ("test-docker-up-lakesail", "lakesail"),
        ("test-docker-up-velox", "velox"),
    ],
)
def test_guard_rejects_relative_data_dir_without_touching_compose(tmp_path, target, platform):
    state_dir = tmp_path / "docker-projects"
    state_dir.mkdir()
    log_file = tmp_path / "engine.log"
    engine = _write_fake_engine(tmp_path)

    result = _run_make(
        target, tmp_path, state_dir=state_dir, engine=engine, log_file=log_file, data_dir="relative/data-dir"
    )

    assert result.returncode != 0, result.stderr
    assert "must be an ABSOLUTE path" in result.stderr
    assert f"docker/{platform}" in result.stderr
    assert not log_file.exists()


@pytest.mark.parametrize("data_dir", [None, "relative/data-dir"], ids=["missing", "relative"])
def test_docker_velox_guard_rejects_and_never_calls_compose_up(tmp_path, data_dir):
    """`test-docker-%` (unlike `test-docker-up-%`) installs an unconditional
    cleanup trap that always runs `compose down -v` on exit, guard rejection
    included -- but its project name is a fresh, never-persisted
    `$$(date +%s)-$$RANDOM` value each invocation (no `project_file`
    tracking, unlike test-docker-up-%), so that `down -v` targets a project
    that was never created rather than tearing down an existing tracked
    stack (the F2 scenario). This pins that the guard still rejects before
    `compose up` and that the engine, if invoked at all by the unconditional
    trap, only ever sees `down`, never `up`."""
    state_dir = tmp_path / "docker-projects"
    state_dir.mkdir()
    log_file = tmp_path / "engine.log"
    engine = _write_fake_engine(tmp_path)

    result = _run_make(
        "test-docker-velox", tmp_path, state_dir=state_dir, engine=engine, log_file=log_file, data_dir=data_dir
    )

    assert result.returncode != 0, result.stderr
    assert "docker/velox" in result.stderr
    if log_file.exists():
        log_text = log_file.read_text()
        assert "up" not in log_text.split(), f"guard rejection must never reach `compose up`: {log_text!r}"


def test_up_questdb_is_not_guarded(tmp_path):
    """questdb does not mirror host paths into the container -- the guard
    must be a no-op for it, and `make test-docker-up-questdb` must proceed
    to compose even with BENCHBOX_DATA_DIR unset."""
    state_dir = tmp_path / "docker-projects"
    state_dir.mkdir()
    log_file = tmp_path / "engine.log"
    engine = _write_fake_engine(tmp_path)

    result = _run_make(
        "test-docker-up-questdb", tmp_path, state_dir=state_dir, engine=engine, log_file=log_file, data_dir=None
    )

    assert result.returncode == 0, result.stderr
    assert log_file.exists(), "expected the (fake) container engine to be invoked for a non-mirroring platform"
    assert "up" in log_file.read_text()
    assert (state_dir / "questdb.project").exists()


def test_guard_rejection_leaves_a_tracked_stack_untouched(tmp_path):
    """F2 regression pin: a guard rejection in shell B must not tear down
    (or orphan the tracking of) a healthy stack already brought up in shell
    A. Simulates shell A's tracked project, then runs the guarded bring-up
    a second time without exporting BENCHBOX_DATA_DIR, as shell B would."""
    state_dir = tmp_path / "docker-projects"
    state_dir.mkdir()
    project_file = state_dir / "lakesail.project"
    live_project_name = "benchbox-lakesail-test-LIVE-FROM-SHELL-A"
    project_file.write_text(live_project_name + "\n")
    log_file = tmp_path / "engine.log"
    engine = _write_fake_engine(tmp_path)

    result = _run_make(
        "test-docker-up-lakesail", tmp_path, state_dir=state_dir, engine=engine, log_file=log_file, data_dir=None
    )

    assert result.returncode != 0, result.stderr
    assert "BENCHBOX_DATA_DIR must be exported" in result.stderr
    assert project_file.exists(), "guard rejection must not delete the tracking file for an already-running stack"
    assert project_file.read_text() == live_project_name + "\n", (
        "guard rejection must not rewrite the tracking file for an already-running stack"
    )
    assert not log_file.exists(), (
        "guard rejection must never invoke `compose down -v` against an already-running stack -- "
        f"fake engine log unexpectedly created: {log_file.read_text() if log_file.exists() else ''}"
    )
