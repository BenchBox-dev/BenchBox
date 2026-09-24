"""Skew configuration for TPC-H Skew benchmark.

Defines configuration structures for different types of data skew:
- Attribute skew: Non-uniform distribution of attribute values
- Join skew: Non-uniform distribution of foreign key relationships
- Temporal skew: Non-uniform distribution of dates (hot periods)

Based on the research: "Introducing Skew into the TPC-H Benchmark"

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import hashlib
import json
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Optional


class SkewType(Enum):
    """Types of data skew supported."""

    ATTRIBUTE = "attribute"  # Skew in attribute value distributions
    JOIN = "join"  # Skew in foreign key relationships
    TEMPORAL = "temporal"  # Skew in date/time distributions
    COMBINED = "combined"  # All types combined


class SkewPreset(Enum):
    """Pre-defined skew configurations."""

    NONE = "none"  # Uniform distribution (standard TPC-H)
    LIGHT = "light"  # Light skew (z=0.2)
    MODERATE = "moderate"  # Moderate skew (z=0.5)
    HEAVY = "heavy"  # Heavy skew (z=0.8)
    EXTREME = "extreme"  # Extreme skew (z=1.0, Zipf's law)
    REALISTIC = "realistic"  # Realistic e-commerce pattern


@dataclass
class AttributeSkewConfig:
    """Configuration for attribute-level skew.

    Attribute skew affects the distribution of values within a column,
    causing some values to appear much more frequently than others.
    """

    # Customer attributes
    customer_nation_skew: float = 0.0  # Skew in customer nationality distribution
    customer_segment_skew: float = 0.0  # Skew in market segments

    # Supplier attributes
    supplier_nation_skew: float = 0.0  # Skew in supplier nationality
    supplier_region_skew: float = 0.0  # Skew in supplier regions

    # Part attributes
    part_brand_skew: float = 0.0  # Skew in part brands (80/20 rule)
    part_type_skew: float = 0.0  # Skew in part types
    part_container_skew: float = 0.0  # Skew in container types

    # Order attributes
    order_priority_skew: float = 0.0  # Skew in order priorities
    order_status_skew: float = 0.0  # Skew in order statuses

    # Line item attributes
    shipmode_skew: float = 0.0  # Skew in shipping modes
    returnflag_skew: float = 0.0  # Skew in return flags

    def get_active_skews(self) -> dict[str, float]:
        """Get all non-zero skew configurations."""
        return {k: v for k, v in vars(self).items() if isinstance(v, (int, float)) and v > 0}


@dataclass
class JoinSkewConfig:
    """Configuration for join relationship skew.

    Join skew affects foreign key distributions, causing some
    parent records to have many more children than others.
    This significantly impacts join performance.
    """

    # Customer -> Orders relationship
    customer_order_skew: float = 0.0  # Some customers order much more

    # Part -> LineItem relationship
    part_popularity_skew: float = 0.0  # Some parts are very popular

    # Supplier -> LineItem relationship
    supplier_volume_skew: float = 0.0  # Some suppliers have more sales

    # Part/Supplier -> PartSupp relationship
    partsupp_skew: float = 0.0  # Skew in part-supplier relationships

    # Order -> LineItem relationship
    lineitem_per_order_skew: float = 0.0  # Variance in items per order

    def get_active_skews(self) -> dict[str, float]:
        """Get all non-zero skew configurations."""
        return {k: v for k, v in vars(self).items() if isinstance(v, (int, float)) and v > 0}


@dataclass
class TemporalSkewConfig:
    """Configuration for temporal (date) skew.

    Temporal skew introduces non-uniform distributions in dates,
    modeling real-world patterns like:
    - Holiday shopping spikes
    - Seasonal trends
    - Recent activity being more common
    """

    # Order date skew
    order_date_skew: float = 0.0  # Concentration in certain periods
    order_recency_skew: float = 0.0  # Recent orders more common

    # Ship date patterns
    ship_date_seasonality: float = 0.0  # Seasonal shipping patterns

    # Hot periods (holiday seasons)
    enable_hot_periods: bool = False
    hot_period_intensity: float = 0.5  # How much traffic spikes in hot periods

    # Date range concentration
    concentration_start: float = 0.7  # Start of concentrated period (0-1)
    concentration_end: float = 1.0  # End of concentrated period (0-1)

    def get_active_skews(self) -> dict[str, float]:
        """Get all non-zero skew configurations."""
        result = {k: v for k, v in vars(self).items() if isinstance(v, (int, float)) and v > 0}
        if self.enable_hot_periods:
            result["enable_hot_periods"] = 1.0
        return result


@dataclass
class SkewConfiguration:
    """Complete skew configuration for TPC-H Skew benchmark.

    Combines attribute, join, and temporal skew settings into
    a unified configuration that can be applied to data generation.
    """

    # Overall skew factor (0.0 = uniform, 1.0 = maximum)
    skew_factor: float = 0.5

    # Distribution type for generating skewed values
    distribution_type: str = "zipfian"  # zipfian, normal, exponential

    # Component configurations
    attribute_skew: AttributeSkewConfig = field(default_factory=AttributeSkewConfig)
    join_skew: JoinSkewConfig = field(default_factory=JoinSkewConfig)
    temporal_skew: TemporalSkewConfig = field(default_factory=TemporalSkewConfig)

    # Seed for reproducibility
    seed: Optional[int] = None

    # Enable specific skew types
    enable_attribute_skew: bool = True
    enable_join_skew: bool = True
    enable_temporal_skew: bool = False

    def datagen_identity(self) -> dict[str, Any]:
        """Return the complete effective configuration that shapes generated data.

        Presets are resolved before constructing this object, so a preset and a
        custom configuration with the same effective values deliberately share
        one identity. Keeping the seed and every per-column knob here prevents
        cache reuse and result comparison across differently generated data.
        """
        return asdict(self)

    def datagen_identity_hash(self) -> str:
        """Return a stable hash of :meth:`datagen_identity`."""
        encoded = json.dumps(self.datagen_identity(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    def get_skew_summary(self) -> dict:
        """Get summary of active skew settings.

        Returns:
            Dictionary with skew type summaries
        """
        return {
            "skew_factor": self.skew_factor,
            "distribution": self.distribution_type,
            "attribute_skew": (self.attribute_skew.get_active_skews() if self.enable_attribute_skew else {}),
            "join_skew": (self.join_skew.get_active_skews() if self.enable_join_skew else {}),
            "temporal_skew": (self.temporal_skew.get_active_skews() if self.enable_temporal_skew else {}),
        }

    def validate(self) -> list[str]:
        """Validate configuration and return any warnings.

        Returns:
            List of warning messages (empty if valid)
        """
        warnings = []

        if not 0 <= self.skew_factor <= 1:
            warnings.append(f"skew_factor should be in [0, 1], got {self.skew_factor}")

        if self.distribution_type not in ("zipfian", "normal", "exponential", "uniform"):
            warnings.append(f"Unknown distribution_type: {self.distribution_type}")

        # Check for very high skew values
        high_skew_attrs = []
        if self.enable_attribute_skew:
            for k, v in self.attribute_skew.get_active_skews().items():
                if v > 0.9:
                    high_skew_attrs.append(k)
        if self.enable_join_skew:
            for k, v in self.join_skew.get_active_skews().items():
                if v > 0.9:
                    high_skew_attrs.append(k)

        if high_skew_attrs:
            warnings.append(
                f"Very high skew (>0.9) on: {', '.join(high_skew_attrs)}. This may cause extreme data imbalance."
            )

        return warnings


def get_preset_config(preset: SkewPreset, seed: Optional[int] = None) -> SkewConfiguration:
    """Get a pre-configured skew configuration.

    Args:
        preset: Preset name from SkewPreset enum
        seed: Optional seed for reproducibility

    Returns:
        SkewConfiguration with preset values
    """
    if preset == SkewPreset.NONE:
        return SkewConfiguration(
            skew_factor=0.0,
            distribution_type="uniform",
            enable_attribute_skew=False,
            enable_join_skew=False,
            enable_temporal_skew=False,
            seed=seed,
        )

    elif preset == SkewPreset.LIGHT:
        return SkewConfiguration(
            skew_factor=0.2,
            distribution_type="zipfian",
            attribute_skew=AttributeSkewConfig(
                customer_nation_skew=0.2,
                part_brand_skew=0.2,
                shipmode_skew=0.15,
            ),
            join_skew=JoinSkewConfig(
                customer_order_skew=0.2,
                part_popularity_skew=0.2,
            ),
            seed=seed,
        )

    elif preset == SkewPreset.MODERATE:
        return SkewConfiguration(
            skew_factor=0.5,
            distribution_type="zipfian",
            attribute_skew=AttributeSkewConfig(
                customer_nation_skew=0.5,
                customer_segment_skew=0.4,
                part_brand_skew=0.5,
                part_type_skew=0.3,
                shipmode_skew=0.4,
                order_priority_skew=0.3,
            ),
            join_skew=JoinSkewConfig(
                customer_order_skew=0.5,
                part_popularity_skew=0.5,
                supplier_volume_skew=0.4,
            ),
            seed=seed,
        )

    elif preset == SkewPreset.HEAVY:
        return SkewConfiguration(
            skew_factor=0.8,
            distribution_type="zipfian",
            attribute_skew=AttributeSkewConfig(
                customer_nation_skew=0.8,
                customer_segment_skew=0.7,
                supplier_nation_skew=0.6,
                part_brand_skew=0.8,
                part_type_skew=0.6,
                shipmode_skew=0.7,
                order_priority_skew=0.5,
            ),
            join_skew=JoinSkewConfig(
                customer_order_skew=0.8,
                part_popularity_skew=0.8,
                supplier_volume_skew=0.7,
                lineitem_per_order_skew=0.5,
            ),
            temporal_skew=TemporalSkewConfig(
                order_date_skew=0.6,
                order_recency_skew=0.5,
            ),
            enable_temporal_skew=True,
            seed=seed,
        )

    elif preset == SkewPreset.EXTREME:
        return SkewConfiguration(
            skew_factor=1.0,
            distribution_type="zipfian",
            attribute_skew=AttributeSkewConfig(
                customer_nation_skew=1.0,
                customer_segment_skew=0.9,
                supplier_nation_skew=0.9,
                supplier_region_skew=0.8,
                part_brand_skew=1.0,
                part_type_skew=0.8,
                part_container_skew=0.7,
                shipmode_skew=0.9,
                order_priority_skew=0.7,
            ),
            join_skew=JoinSkewConfig(
                customer_order_skew=1.0,
                part_popularity_skew=1.0,
                supplier_volume_skew=0.9,
                lineitem_per_order_skew=0.7,
            ),
            temporal_skew=TemporalSkewConfig(
                order_date_skew=0.8,
                order_recency_skew=0.7,
                enable_hot_periods=True,
                hot_period_intensity=0.8,
            ),
            enable_temporal_skew=True,
            seed=seed,
        )

    elif preset == SkewPreset.REALISTIC:
        # Based on real-world e-commerce patterns
        return SkewConfiguration(
            skew_factor=0.6,
            distribution_type="zipfian",
            attribute_skew=AttributeSkewConfig(
                customer_nation_skew=0.7,  # Most customers from few countries
                customer_segment_skew=0.5,  # Some segments larger
                part_brand_skew=0.8,  # 80/20 rule for brands
                part_type_skew=0.4,
                shipmode_skew=0.6,  # Most use standard shipping
            ),
            join_skew=JoinSkewConfig(
                customer_order_skew=0.7,  # Power users order a lot
                part_popularity_skew=0.8,  # Popular products dominate
                supplier_volume_skew=0.6,  # Large suppliers
            ),
            temporal_skew=TemporalSkewConfig(
                order_recency_skew=0.6,  # Recent orders more common
                enable_hot_periods=True,  # Holiday spikes
                hot_period_intensity=0.7,
            ),
            enable_temporal_skew=True,
            seed=seed,
        )

    else:
        raise ValueError(f"Unknown preset: {preset}")
