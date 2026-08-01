"""Fixtures shared by DataFrame platform mixin tests."""

from __future__ import annotations

import pytest

from benchbox.core.dataframe import MemoryCheckResult


@pytest.fixture
def sufficient_dataframe_memory(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep mocked mixin execution independent of ambient host memory.

    This fixture is intentionally not autouse. Test modules must opt in so
    dedicated memory-policy tests continue to exercise the real capacity
    check and its insufficient-memory behavior.
    """

    def _sufficient_memory(_benchmark: str, scale_factor: float, platform: str) -> MemoryCheckResult:
        return MemoryCheckResult(
            is_safe=True,
            message="sufficient memory supplied by test fixture",
            estimated_memory_gb=0.0,
            available_memory_gb=float("inf"),
            scale_factor=scale_factor,
            platform=platform,
        )

    monkeypatch.setattr(
        "benchbox.platforms.dataframe.benchmark_mixin.check_sufficient_memory",
        _sufficient_memory,
    )
