# Copyright 2026 Joe Harris / BenchBox Project

# Licensed under the MIT License. See LICENSE file in the project root for details.

import hashlib
import json
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Optional


class SkewType(Enum):
    ATTRIBUTE = "attribute"
    JOIN = "join"
    TEMPORAL = "temporal"
    COMBINED = "combined"


class SkewPreset(Enum):
    NONE = "none"
    LIGHT = "light"
    MODERATE = "moderate"
    HEAVY = "heavy"
    EXTREME = "extreme"
    REALISTIC = "realistic"


@dataclass
class AttributeSkewConfig:
    customer_nation_skew: float = 0.0
    customer_segment_skew: float = 0.0

    supplier_nation_skew: float = 0.0
    supplier_region_skew: float = 0.0

    part_brand_skew: float = 0.0
    part_type_skew: float = 0.0
    part_container_skew: float = 0.0

    order_priority_skew: float = 0.0
    order_status_skew: float = 0.0

    shipmode_skew: float = 0.0
    returnflag_skew: float = 0.0

    def get_active_skews(self) -> dict[str, float]:
        return {k: v for k, v in vars(self).items() if isinstance(v, (int, float)) and v > 0}


@dataclass
class JoinSkewConfig:
    customer_order_skew: float = 0.0

    part_popularity_skew: float = 0.0

    supplier_volume_skew: float = 0.0

    partsupp_skew: float = 0.0

    lineitem_per_order_skew: float = 0.0

    def get_active_skews(self) -> dict[str, float]:
        return {k: v for k, v in vars(self).items() if isinstance(v, (int, float)) and v > 0}


@dataclass
class TemporalSkewConfig:
    order_date_skew: float = 0.0
    order_recency_skew: float = 0.0

    ship_date_seasonality: float = 0.0

    enable_hot_periods: bool = False
    hot_period_intensity: float = 0.5

    concentration_start: float = 0.7
    concentration_end: float = 1.0

    def get_active_skews(self) -> dict[str, float]:
        result = {k: v for k, v in vars(self).items() if isinstance(v, (int, float)) and v > 0}
        if self.enable_hot_periods:
            result["enable_hot_periods"] = 1.0
        return result


@dataclass
class SkewConfiguration:
    skew_factor: float = 0.5

    distribution_type: str = "zipfian"

    attribute_skew: AttributeSkewConfig = field(default_factory=AttributeSkewConfig)
    join_skew: JoinSkewConfig = field(default_factory=JoinSkewConfig)
    temporal_skew: TemporalSkewConfig = field(default_factory=TemporalSkewConfig)

    seed: Optional[int] = None

    enable_attribute_skew: bool = True
    enable_join_skew: bool = True
    enable_temporal_skew: bool = False

    def datagen_identity(self) -> dict[str, Any]:
        return asdict(self)

    def datagen_identity_hash(self) -> str:
        encoded = json.dumps(self.datagen_identity(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    def get_skew_summary(self) -> dict:
        return {
            "skew_factor": self.skew_factor,
            "distribution": self.distribution_type,
            "attribute_skew": (self.attribute_skew.get_active_skews() if self.enable_attribute_skew else {}),
            "join_skew": (self.join_skew.get_active_skews() if self.enable_join_skew else {}),
            "temporal_skew": (self.temporal_skew.get_active_skews() if self.enable_temporal_skew else {}),
        }

    def validate(self) -> list[str]:
        warnings = []

        if not 0 <= self.skew_factor <= 1:
            warnings.append(f"skew_factor should be in [0, 1], got {self.skew_factor}")

        if self.distribution_type not in ("zipfian", "normal", "exponential", "uniform"):
            warnings.append(f"Unknown distribution_type: {self.distribution_type}")

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
        return SkewConfiguration(
            skew_factor=0.6,
            distribution_type="zipfian",
            attribute_skew=AttributeSkewConfig(
                customer_nation_skew=0.7,
                customer_segment_skew=0.5,
                part_brand_skew=0.8,
                part_type_skew=0.4,
                shipmode_skew=0.6,
            ),
            join_skew=JoinSkewConfig(
                customer_order_skew=0.7,
                part_popularity_skew=0.8,
                supplier_volume_skew=0.6,
            ),
            temporal_skew=TemporalSkewConfig(
                order_recency_skew=0.6,
                enable_hot_periods=True,
                hot_period_intensity=0.7,
            ),
            enable_temporal_skew=True,
            seed=seed,
        )

    else:
        raise ValueError(f"Unknown preset: {preset}")
