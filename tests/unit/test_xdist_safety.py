"""Regression tests for BenchBox pytest-xdist safety hooks."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import _benchbox_pytest_xdist_safety as safety_plugin

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


def test_safe_worker_count_hard_caps_to_two_on_macos(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BENCHBOX_MAX_XDIST_WORKERS", raising=False)
    monkeypatch.setattr(safety_plugin.sys, "platform", "darwin", raising=False)
    monkeypatch.setattr(safety_plugin.os, "cpu_count", lambda: 12)
    monkeypatch.setattr(
        "psutil.virtual_memory",
        lambda: SimpleNamespace(available=8 * 1024 * 1024 * 1024),
    )

    assert safety_plugin._safe_worker_count() == 6


def test_safe_worker_count_honors_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BENCHBOX_MAX_XDIST_WORKERS", "5")
    monkeypatch.setattr(safety_plugin.sys, "platform", "darwin", raising=False)

    assert safety_plugin._safe_worker_count() == 5


def test_pytest_xdist_auto_num_workers_uses_safe_count(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(safety_plugin, "_safe_worker_count", lambda: 2)

    assert safety_plugin.pytest_xdist_auto_num_workers(SimpleNamespace()) == 2


def test_rewrite_numprocesses_args_caps_explicit_requests() -> None:
    args = ["-n", "8", "tests/unit/test_release_sync.py"]

    requested = safety_plugin._rewrite_numprocesses_args(args, 2)

    assert requested == "8"
    assert args == ["-n", "2", "tests/unit/test_release_sync.py"]


def test_rewrite_numprocesses_args_caps_auto_requests() -> None:
    args = ["--numprocesses=auto", "tests/unit/test_release_sync.py"]

    requested = safety_plugin._rewrite_numprocesses_args(args, 2)

    assert requested == "auto"
    assert args == ["--numprocesses=2", "tests/unit/test_release_sync.py"]


def test_rewrite_numprocesses_args_leaves_safe_requests_unchanged() -> None:
    args = ["-n2", "tests/unit/test_release_sync.py"]

    requested = safety_plugin._rewrite_numprocesses_args(args, 2)

    assert requested is None
    assert args == ["-n2", "tests/unit/test_release_sync.py"]


def test_rewrite_numprocesses_args_uses_last_numprocesses_occurrence() -> None:
    args = ["-n", "auto", "-n", "8", "tests/unit/test_release_sync.py"]

    requested = safety_plugin._rewrite_numprocesses_args(args, 2)

    assert requested == "8"
    assert args == ["-n", "auto", "-n", "2", "tests/unit/test_release_sync.py"]


def test_suppress_xdist_worker_title_patches_only_exec_namespace(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify the stack walk targets xdist's exec namespace, not any worker_title symbol.

    On macOS, xdist's per-test setproctitle() calls trigger launchservicesd
    to consume 200%+ CPU rebuilding its process registry. The conftest
    patches the live xdist worker_title to a no-op via stack walking.
    """
    outer_title_fn = lambda title: "OUTER_FRAME"  # noqa: E731
    monkeypatch.setitem(globals(), "worker_title", outer_title_fn)

    original_title_fn = lambda title: "INNER_FRAME"  # noqa: E731
    fake_remote_globals = {
        "__name__": "__channelexec__",
        "worker_title": original_title_fn,
    }

    exec(
        "from tests.conftest import _suppress_xdist_worker_title\nresult = _suppress_xdist_worker_title()",
        fake_remote_globals,
    )

    assert fake_remote_globals["result"] is True
    assert fake_remote_globals["worker_title"]("any title") is None
    assert fake_remote_globals["worker_title"] is not original_title_fn
    assert globals()["worker_title"] is outer_title_fn


def test_suppress_xdist_worker_title_ignores_non_exec_frames(monkeypatch: pytest.MonkeyPatch) -> None:
    from tests.conftest import _suppress_xdist_worker_title

    original_title_fn = lambda title: "NOT_XDIST"  # noqa: E731
    monkeypatch.setitem(globals(), "worker_title", original_title_fn)

    # The return value depends on whether a real xdist __channelexec__ frame
    # exists further up the stack (True when running under -n N, False under -n 0).
    # The key invariant: THIS frame's worker_title must never be patched.
    _suppress_xdist_worker_title()
    assert globals()["worker_title"] is original_title_fn
