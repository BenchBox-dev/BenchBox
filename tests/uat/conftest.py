"""Shared UAT test isolation fixtures."""

from __future__ import annotations

import pytest

from tests.uat import docker_assets, matrix


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
