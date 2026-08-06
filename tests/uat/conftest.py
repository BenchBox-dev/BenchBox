"""Shared UAT test isolation fixtures."""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import patch

import pytest

from tests.uat import docker_assets, matrix
from tests.uat.preflight_budget import MemorySnapshot

# Ample headroom relative to the 2.0 GiB default free_memory_min_gib, so the
# default never gates. Deliberately a fixed number, not a reading.
HERMETIC_FREE_MEMORY_GIB = 64.0


@contextmanager
def platform_reachability(value: bool = True, *, probe=None):
    """Pin BOTH reachability entry points the execute phase uses.

    `execute.py` deliberately calls two different primitives:
    `platform_is_reachable` (cached, once per platform, the skip_unreachable
    check) and `probe_platform_reachability` (no-cache, used by the
    post-start readiness check and the per-cell liveness probe). A test that
    patches only the first leaves the other two doing REAL TCP connects
    against whatever happens to be listening on the developer's machine.

    `probe` overrides just the no-cache probe -- pass a side-effect callable
    to model a stack that is up when the platform starts and dies partway
    through its cells.
    """
    with patch("tests.uat.phases.execute.platform_is_reachable", return_value=value):
        if probe is None:
            with patch("tests.uat.phases.execute.probe_platform_reachability", return_value=value):
                yield
        else:
            with patch("tests.uat.phases.execute.probe_platform_reachability", side_effect=probe):
                yield


def docker_verb(argv) -> str:
    """Classify a compose argv into "up"/"ps"/"down" for fake docker_runner fixtures.

    Lives here, shared, because the obvious local spelling is a trap. Several
    fixtures independently wrote `action = "up" if "up" in argv else "down"`,
    which silently classified the readiness check's `compose ps -a` as a
    "down" the moment that call was added -- producing a plausible-looking
    `['up', 'down', 'cell', 'down']` sequence and a red test in a file the
    change never touched. Any new compose verb must be added HERE, once, or
    the same failure repeats.

    `compose_up_command`, `compose_ps_command` and `compose_down_command`
    argvs each contain exactly one of these three literal verb tokens (see
    docker_assets.py), so match order does not matter.
    """
    if "up" in argv:
        return "up"
    if "ps" in argv:
        return "ps"
    return "down"


def healthy_ps_stdout(service: str = "svc") -> str:
    """A `compose ps -a` table with one running service -- readiness passes.

    Deliberately a real table rather than "": empty output now means "this
    project has no containers at all", which the readiness check treats as
    NOT ready (see `_check_docker_platform_readiness`). A fixture returning
    "" would be asserting the failure path while looking like the happy one.
    """
    return f"NAME      IMAGE     COMMAND   STATUS\n{service}   img       cmd       Up 5 seconds\n"


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
