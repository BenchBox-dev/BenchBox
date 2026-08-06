"""Shared UAT test isolation fixtures."""

from __future__ import annotations

import pytest

from tests.uat import docker_assets, matrix
from tests.uat.preflight_budget import MemorySnapshot

# Ample headroom relative to the 2.0 GiB default free_memory_min_gib, so the
# default never gates. Deliberately a fixed number, not a reading.
HERMETIC_FREE_MEMORY_GIB = 64.0


@pytest.fixture(autouse=True)
def isolate_reachability_cache():
    """Keep matrix reachability cache state from leaking across tests."""
    matrix._REACHABILITY_CACHE.clear()
    yield
    matrix._REACHABILITY_CACHE.clear()


@pytest.fixture(autouse=True)
def isolate_container_cli_resolution(monkeypatch):
    """Default the resolved container engine to `docker` for every test.

    This suite runs on both docker-only CI (Linux) and macOS-with-mocker dev
    machines; without this, tests asserting on literal `docker` argv would
    resolve to `mocker` on a dev machine and fail nondeterministically.
    Starts from a clean `resolve_container_cli()` cache (the resolver's own
    tests in test_docker_assets.py override env/PATH within their own body
    and clear the cache again -- see uat-container-engine-routing w1).
    """
    docker_assets.resolve_container_cli.cache_clear()
    monkeypatch.setenv(docker_assets.CONTAINER_CLI_ENV_VAR, "docker")
    monkeypatch.setattr(docker_assets, "_which_container_cli", lambda cli: f"/usr/bin/{cli}")
    yield
    docker_assets.resolve_container_cli.cache_clear()


@pytest.fixture(autouse=True)
def isolate_free_memory_reading(monkeypatch):
    """Stop ambient host memory deciding whether this suite passes.

    `run_execute` falls back to `preflight_budget.read_memory_snapshot` when
    no `memory_reader` is injected, so without this every test that drives
    the execute phase reads the developer's real free memory and the
    free-memory gate fires or not depending on what else is running on the
    machine. Verified: simulating a 0.07 GiB host turns 18 otherwise-passing
    tests red. Pin the default to a healthy fixed reading.

    This patches only the DEFAULT. Tests that exercise the gate pass
    `memory_reader=` to `run_execute` explicitly, which bypasses this
    fallback entirely -- so the fixture cannot mask a gate regression (see
    the memory-floor tests in test_phases.py, which fail if the gate stops
    aborting). Tests of the reader itself call
    `preflight_budget.read_memory_snapshot` directly and are likewise
    unaffected.
    """
    monkeypatch.setattr(
        "tests.uat.phases.execute.default_free_memory_reader",
        lambda: MemorySnapshot(free_gib=HERMETIC_FREE_MEMORY_GIB, swap_used_percent=0.0),
    )
