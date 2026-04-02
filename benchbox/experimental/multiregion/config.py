"""Region configuration for multi-region testing.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class CloudProvider(str, Enum):
    """Supported cloud providers."""

    AWS = "aws"
    GCP = "gcp"
    AZURE = "azure"
    SNOWFLAKE = "snowflake"
    DATABRICKS = "databricks"
    CUSTOM = "custom"


@dataclass
class Region:
    """A geographic region for database deployment.

    Attributes:
        name: Human-readable region name (e.g., "US East")
        code: Region code (e.g., "us-east-1", "eastus", "us-east1")
        provider: Cloud provider for this region
        latitude: Approximate latitude for distance calculation
        longitude: Approximate longitude for distance calculation
    """

    name: str
    code: str
    provider: CloudProvider
    latitude: float | None = None
    longitude: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __hash__(self) -> int:
        return hash((self.code, self.provider))

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Region):
            return False
        return self.code == other.code and self.provider == other.provider


@dataclass
class RegionConfig:
    """Configuration for a single region's database endpoint.

    Attributes:
        region: The geographic region
        endpoint: Database connection endpoint/URL
        port: Database port
        connection_params: Additional connection parameters
    """

    region: Region
    endpoint: str
    port: int = 5432
    connection_params: dict[str, Any] = field(default_factory=dict)

    @property
    def connection_string(self) -> str:
        """Build connection string for this region."""
        return f"{self.endpoint}:{self.port}"


@dataclass
class MultiRegionConfig:
    """Configuration for multi-region benchmark testing.

    Attributes:
        primary_region: The primary/source region
        secondary_regions: List of secondary/target regions
        client_region: Region where benchmark client runs (for latency)
        enable_latency_measurement: Whether to measure cross-region latency
        enable_transfer_tracking: Whether to track data transfer
    """

    primary_region: RegionConfig
    secondary_regions: list[RegionConfig] = field(default_factory=list)
    client_region: Region | None = None
    enable_latency_measurement: bool = True
    enable_transfer_tracking: bool = True

    @property
    def all_regions(self) -> list[RegionConfig]:
        """Get all configured regions."""
        return [self.primary_region] + self.secondary_regions

    def get_region_by_code(self, code: str) -> RegionConfig | None:
        """Find region configuration by code."""
        for region_config in self.all_regions:
            if region_config.region.code == code:
                return region_config
        return None


# Pre-defined regions for major cloud providers
AWS_REGIONS: dict[str, Region] = {
    "us-east-1": Region("US East (N. Virginia)", "us-east-1", CloudProvider.AWS, 38.9, -77.0),
    "us-east-2": Region("US East (Ohio)", "us-east-2", CloudProvider.AWS, 40.4, -82.9),
    "us-west-1": Region("US West (N. California)", "us-west-1", CloudProvider.AWS, 37.8, -122.4),
    "us-west-2": Region("US West (Oregon)", "us-west-2", CloudProvider.AWS, 45.5, -122.7),
    "eu-west-1": Region("EU (Ireland)", "eu-west-1", CloudProvider.AWS, 53.3, -6.3),
    "eu-west-2": Region("EU (London)", "eu-west-2", CloudProvider.AWS, 51.5, -0.1),
    "eu-central-1": Region("EU (Frankfurt)", "eu-central-1", CloudProvider.AWS, 50.1, 8.7),
    "ap-northeast-1": Region("Asia Pacific (Tokyo)", "ap-northeast-1", CloudProvider.AWS, 35.7, 139.7),
    "ap-southeast-1": Region("Asia Pacific (Singapore)", "ap-southeast-1", CloudProvider.AWS, 1.4, 103.8),
    "ap-southeast-2": Region("Asia Pacific (Sydney)", "ap-southeast-2", CloudProvider.AWS, -33.9, 151.2),
}

GCP_REGIONS: dict[str, Region] = {
    "us-east1": Region("US East (S. Carolina)", "us-east1", CloudProvider.GCP, 33.8, -81.2),
    "us-east4": Region("US East (N. Virginia)", "us-east4", CloudProvider.GCP, 38.9, -77.0),
    "us-central1": Region("US Central (Iowa)", "us-central1", CloudProvider.GCP, 41.3, -93.1),
    "us-west1": Region("US West (Oregon)", "us-west1", CloudProvider.GCP, 45.5, -122.7),
    "europe-west1": Region("EU (Belgium)", "europe-west1", CloudProvider.GCP, 50.8, 4.4),
    "europe-west2": Region("EU (London)", "europe-west2", CloudProvider.GCP, 51.5, -0.1),
    "europe-west3": Region("EU (Frankfurt)", "europe-west3", CloudProvider.GCP, 50.1, 8.7),
    "asia-east1": Region("Asia (Taiwan)", "asia-east1", CloudProvider.GCP, 25.0, 121.5),
    "asia-northeast1": Region("Asia (Tokyo)", "asia-northeast1", CloudProvider.GCP, 35.7, 139.7),
    "australia-southeast1": Region("Australia (Sydney)", "australia-southeast1", CloudProvider.GCP, -33.9, 151.2),
}

AZURE_REGIONS: dict[str, Region] = {
    "eastus": Region("US East", "eastus", CloudProvider.AZURE, 37.4, -79.0),
    "eastus2": Region("US East 2", "eastus2", CloudProvider.AZURE, 36.7, -78.9),
    "westus": Region("US West", "westus", CloudProvider.AZURE, 37.8, -122.4),
    "westus2": Region("US West 2", "westus2", CloudProvider.AZURE, 47.6, -122.3),
    "northeurope": Region("EU North (Ireland)", "northeurope", CloudProvider.AZURE, 53.3, -6.3),
    "westeurope": Region("EU West (Netherlands)", "westeurope", CloudProvider.AZURE, 52.4, 4.9),
    "germanywestcentral": Region("Germany West Central", "germanywestcentral", CloudProvider.AZURE, 50.1, 8.7),
    "japaneast": Region("Japan East", "japaneast", CloudProvider.AZURE, 35.7, 139.7),
    "southeastasia": Region("Southeast Asia", "southeastasia", CloudProvider.AZURE, 1.4, 103.8),
    "australiaeast": Region("Australia East", "australiaeast", CloudProvider.AZURE, -33.9, 151.2),
}


def get_region(provider: CloudProvider, code: str) -> Region | None:
    """Get a pre-defined region by provider and code.

    Args:
        provider: Cloud provider
        code: Region code

    Returns:
        Region if found, None otherwise
    """
    region_maps = {
        CloudProvider.AWS: AWS_REGIONS,
        CloudProvider.GCP: GCP_REGIONS,
        CloudProvider.AZURE: AZURE_REGIONS,
    }

    regions = region_maps.get(provider, {})
    return regions.get(code)


def calculate_distance_km(region1: Region, region2: Region) -> float | None:
    """Calculate approximate distance between two regions.

    Uses Haversine formula for great-circle distance.

    Args:
        region1: First region
        region2: Second region

    Returns:
        Distance in kilometers, or None if coordinates unavailable
    """
    import math

    if region1.latitude is None or region1.longitude is None or region2.latitude is None or region2.longitude is None:
        return None

    R = 6371  # Earth's radius in km

    lat1 = math.radians(region1.latitude)
    lat2 = math.radians(region2.latitude)
    dlat = math.radians(region2.latitude - region1.latitude)
    dlon = math.radians(region2.longitude - region1.longitude)

    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    c = 2 * math.asin(math.sqrt(a))

    return R * c
