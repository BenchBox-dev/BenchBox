"""Fast coverage tests for ClickHouse tuning helpers.

Pins the behavior of `ClickHouseTuningMixin.apply_platform_optimizations`
after removing the dead `platform_config.clickhouse_optimizations` branch
(the attribute was never defined by `PlatformOptimizationConfiguration`,
so any real, truthy config instance raised `AttributeError` before this
fix -- see tuning-residual-cleanups-20260716 w2).
"""

from __future__ import annotations

import logging
from unittest.mock import Mock

import pytest

from benchbox.core.tuning.interface import PlatformOptimizationConfiguration
from benchbox.platforms.clickhouse.tuning import ClickHouseTuningMixin

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


class _ClickHouseTuningHarness(ClickHouseTuningMixin):
    def __init__(self) -> None:
        self.logger = Mock(spec=logging.Logger)


def test_apply_platform_optimizations_is_noop_for_real_config() -> None:
    """A real (default) PlatformOptimizationConfiguration must not raise.

    Before the fix, this raised AttributeError because the mixin read
    `platform_config.clickhouse_optimizations`, an attribute that
    `PlatformOptimizationConfiguration` never defines.
    """
    adapter = _ClickHouseTuningHarness()
    connection = Mock()

    adapter.apply_platform_optimizations(PlatformOptimizationConfiguration(), connection)

    connection.execute.assert_not_called()


def test_apply_platform_optimizations_noop_with_nondefault_fields_set() -> None:
    """Even with Databricks/BigQuery-style fields populated, ClickHouse has
    no mapping for them and must remain a no-op rather than erroring."""
    adapter = _ClickHouseTuningHarness()
    connection = Mock()
    platform_config = PlatformOptimizationConfiguration(
        z_ordering_enabled=True,
        bloom_filters_enabled=True,
    )

    adapter.apply_platform_optimizations(platform_config, connection)

    connection.execute.assert_not_called()


def test_apply_platform_optimizations_returns_early_for_falsy_config() -> None:
    adapter = _ClickHouseTuningHarness()
    connection = Mock()

    adapter.apply_platform_optimizations(None, connection)

    connection.execute.assert_not_called()
