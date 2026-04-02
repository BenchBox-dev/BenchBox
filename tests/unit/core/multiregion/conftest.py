"""Shared fixtures for multi-region testing framework tests.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import pytest

from benchbox.experimental.multiregion.config import (
    CloudProvider,
    MultiRegionConfig,
    Region,
    RegionConfig,
)


@pytest.fixture
def us_east_region():
    """US East region fixture."""
    return Region(
        name="US East",
        code="us-east-1",
        provider=CloudProvider.AWS,
        latitude=38.9,
        longitude=-77.0,
    )


@pytest.fixture
def eu_west_region():
    """EU West region fixture."""
    return Region(
        name="EU West",
        code="eu-west-1",
        provider=CloudProvider.AWS,
        latitude=53.3,
        longitude=-6.3,
    )


@pytest.fixture
def ap_region():
    """Asia Pacific region fixture."""
    return Region(
        name="Asia Pacific",
        code="ap-northeast-1",
        provider=CloudProvider.AWS,
        latitude=35.7,
        longitude=139.7,
    )


@pytest.fixture
def us_east_config(us_east_region):
    """US East region config fixture."""
    return RegionConfig(
        region=us_east_region,
        endpoint="us-east.example.com",
        port=5432,
    )


@pytest.fixture
def eu_west_config(eu_west_region):
    """EU West region config fixture."""
    return RegionConfig(
        region=eu_west_region,
        endpoint="eu-west.example.com",
        port=5432,
    )


@pytest.fixture
def multi_region_config(us_east_config, eu_west_config, us_east_region):
    """Multi-region config fixture."""
    return MultiRegionConfig(
        primary_region=us_east_config,
        secondary_regions=[eu_west_config],
        client_region=us_east_region,
    )
