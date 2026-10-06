from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import patch

import pytest

from tests.uat import docker_assets, matrix
from tests.uat.preflight_budget import MemorySnapshot

HERMETIC_FREE_MEMORY_GIB = 64.0

# Ample headroom relative to the 5.0 GiB default free_space_min_gib (and any
# checked-in budget-table estimate for the tiny fake matrices used here), so
# the default never gates. Deliberately a fixed number, not a reading.
HERMETIC_FREE_SPACE_GIB = 500.0


@contextmanager
def platform_reachability(value: bool = True, *, probe=None):
    with patch("tests.uat.phases.execute.platform_is_reachable", return_value=value):
        if probe is None:
            with patch("tests.uat.phases.execute.probe_platform_reachability", return_value=value):
                yield
        else:
            with patch("tests.uat.phases.execute.probe_platform_reachability", side_effect=probe):
                yield


def docker_verb(argv) -> str:
    if "up" in argv:
        return "up"
    if "ps" in argv:
        return "ps"
    if "stats" in argv:
        return "stats"
    return "down"


def healthy_ps_stdout(service: str = "svc") -> str:
    return f"NAME      IMAGE     COMMAND   STATUS\n{service}   img       cmd       Up 5 seconds\n"


@pytest.fixture(autouse=True)
def isolate_reachability_cache():
    matrix._REACHABILITY_CACHE.clear()
    yield
    matrix._REACHABILITY_CACHE.clear()


@pytest.fixture(autouse=True)
def isolate_container_cli_resolution(monkeypatch):
    docker_assets.resolve_container_cli.cache_clear()
    monkeypatch.setenv(docker_assets.CONTAINER_CLI_ENV_VAR, "docker")
    monkeypatch.setattr(docker_assets, "_which_container_cli", lambda cli: f"/usr/bin/{cli}")
    yield
    docker_assets.resolve_container_cli.cache_clear()


@pytest.fixture(autouse=True)
def isolate_free_memory_reading(monkeypatch):
    monkeypatch.setattr(
        "tests.uat.phases.execute.default_free_memory_reader",
        lambda: MemorySnapshot(free_gib=HERMETIC_FREE_MEMORY_GIB, swap_used_percent=0.0),
    )


@pytest.fixture(autouse=True)
def isolate_free_space_reading(monkeypatch):
    """Stop ambient host disk deciding whether this suite passes.

    Two production fallbacks read the developer's real free disk when no
    reader is injected: `run_execute` falls back to
    `execute.default_free_space_reader`, and the orchestrator's per-cell
    disk-floor runner falls back to `preflight_budget.free_space_gib`.
    Without this, every test that drives the execute phase or a full sweep
    without an explicit reader -- notably the run_sweep e2e tests in
    test_e2e_integration.py -- aborts with abort_kind="disk_floor" on a
    nearly-full host and passes after scratch is freed. Verified: forcing
    the default to 0.07 GiB turns those otherwise-passing tests red.
    Pin both defaults to a healthy fixed reading.

    This patches only the DEFAULTs. Tests that exercise the gate pass
    `free_space_reader=` explicitly, which bypasses these fallbacks
    entirely -- so the fixture cannot mask a gate regression (see the
    disk-floor tests in test_phases.py and test_orchestrator.py, which fail
    if the gate stops aborting). No test asserts on a real disk reading, so
    nothing else can observe the pinned default.
    """
    monkeypatch.setattr(
        "tests.uat.phases.execute.default_free_space_reader",
        lambda _path: HERMETIC_FREE_SPACE_GIB,
    )
    monkeypatch.setattr(
        "tests.uat.preflight_budget.free_space_gib",
        lambda _path: HERMETIC_FREE_SPACE_GIB,
    )
