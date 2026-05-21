"""Shared UAT test isolation fixtures."""

from __future__ import annotations

import pytest

from tests.uat import matrix


@pytest.fixture(autouse=True)
def isolate_reachability_cache():
    """Keep matrix reachability cache state from leaking across tests."""
    matrix._REACHABILITY_CACHE.clear()
    yield
    matrix._REACHABILITY_CACHE.clear()
