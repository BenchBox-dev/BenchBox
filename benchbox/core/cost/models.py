"""Cost data models for benchmark results.

This module defines the data structures for representing costs at different
levels of granularity: individual queries, benchmark phases, and complete benchmarks.
"""

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Literal, Optional

CostScope = Literal["compute_only", "compute_plus_storage"]
CostStatus = Literal["normalized", "not_applicable_local", "unavailable"]


@dataclass(frozen=True)
class DeploymentMetadata:
    """Deployment context used to normalize and audit benchmark cost."""

    cloud_provider: str | None = None
    cloud_region: str | None = None
    instance_type: str | None = None
    warehouse_size: str | None = None
    node_count: int | None = None
    cluster_size: str | None = None
    storage_format: str | None = None
    storage_tier: str | None = None

    def to_dict(self) -> dict[str, str | int | None]:
        """Convert to a stable dictionary shape for result serialization."""
        return {
            "cloud_provider": self.cloud_provider,
            "cloud_region": self.cloud_region,
            "instance_type": self.instance_type,
            "warehouse_size": self.warehouse_size,
            "node_count": self.node_count,
            "cluster_size": self.cluster_size,
            "storage_format": self.storage_format,
            "storage_tier": self.storage_tier,
        }


@dataclass(frozen=True)
class NormalizedCost:
    """BenchBox-normalized cost with explicit provenance and availability status.

    `normalized_cost_usd` is `None` when `cost_status == "unavailable"` so
    missing cloud pricing metadata cannot be misread as zero cost. Local or
    self-hosted runs may use `cost_status == "not_applicable_local"` with
    `normalized_cost_usd == Decimal("0")`, but consumers must still treat the
    status as non-comparable with normalized cloud cost.
    """

    normalized_cost_usd: Decimal | None
    cost_model_version: str
    cost_model_source: str
    cost_scope: CostScope
    cost_status: CostStatus
    billing_unit: str
    pricing_region: str
    deployment: DeploymentMetadata = field(default_factory=DeploymentMetadata)

    def __post_init__(self) -> None:
        if self.normalized_cost_usd is not None and not isinstance(self.normalized_cost_usd, Decimal):
            object.__setattr__(self, "normalized_cost_usd", Decimal(str(self.normalized_cost_usd)))
        if self.normalized_cost_usd is not None and self.normalized_cost_usd < 0:
            raise ValueError("normalized cost cannot be negative")
        if self.cost_status == "normalized" and self.normalized_cost_usd is None:
            raise ValueError("normalized cost requires normalized_cost_usd")
        if self.cost_status == "not_applicable_local" and self.normalized_cost_usd != Decimal("0"):
            raise ValueError("local not-applicable cost must carry explicit zero normalized_cost_usd")
        if self.cost_status == "unavailable" and self.normalized_cost_usd is not None:
            raise ValueError("unavailable cost must not carry normalized_cost_usd")

    def to_dict(self) -> dict[str, Any]:
        """Convert to a serialization-ready dictionary without losing Decimal precision."""
        return {
            "normalized_cost_usd": str(self.normalized_cost_usd) if self.normalized_cost_usd is not None else None,
            "cost_model_version": self.cost_model_version,
            "cost_model_source": self.cost_model_source,
            "cost_scope": self.cost_scope,
            "cost_status": self.cost_status,
            "billing_unit": self.billing_unit,
            "pricing_region": self.pricing_region,
            "deployment": self.deployment.to_dict(),
        }


@dataclass
class QueryCost:
    """Cost information for a single query execution.

    Attributes:
        compute_cost: The compute cost in the specified currency
        currency: Currency code (e.g., "USD")
        pricing_details: Additional details about how the cost was calculated,
                        platform-specific metrics, pricing tier, etc.
    """

    compute_cost: float
    currency: str = "USD"
    pricing_details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "compute_cost": self.compute_cost,
            "currency": self.currency,
            "pricing_details": self.pricing_details,
        }


@dataclass
class PhaseCost:
    """Aggregated cost information for a benchmark phase.

    Attributes:
        phase_name: Name of the phase (e.g., "power_test", "throughput_test")
        total_cost: Total cost for all queries in this phase
        query_count: Number of queries in this phase
        currency: Currency code
        query_costs: Individual query costs (optional, for detailed breakdowns)
        wall_clock_duration_seconds: Actual wall clock time for the phase (optional)
        concurrent_streams: Number of concurrent query streams (optional)
    """

    phase_name: str
    total_cost: float
    query_count: int
    currency: str = "USD"
    query_costs: Optional[list[QueryCost]] = None
    wall_clock_duration_seconds: Optional[float] = None
    concurrent_streams: Optional[int] = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation."""
        result: dict[str, Any] = {
            "phase_name": self.phase_name,
            "total_cost": self.total_cost,
            "query_count": self.query_count,
            "currency": self.currency,
        }
        if self.wall_clock_duration_seconds is not None:
            result["wall_clock_duration_seconds"] = self.wall_clock_duration_seconds
            # Calculate effective cost per hour
            if self.wall_clock_duration_seconds > 0:
                result["effective_cost_per_hour"] = self.total_cost / (self.wall_clock_duration_seconds / 3600.0)
        if self.concurrent_streams is not None:
            result["concurrent_streams"] = self.concurrent_streams
        if self.query_costs is not None:
            result["query_costs"] = [qc.to_dict() for qc in self.query_costs]
        return result


@dataclass
class BenchmarkCost:
    """Complete cost information for an entire benchmark run.

    Attributes:
        total_cost: Total cost across all phases
        currency: Currency code
        phase_costs: List of costs broken down by phase
        platform_details: Platform-specific pricing context (region, tier, warehouse size, etc.)
        cost_model: Type of cost calculation ("marginal", "actual", "estimated")
        warnings: List of user-facing warnings about cost calculation limitations
        storage_cost: Estimated storage cost (optional)
    """

    total_cost: float
    currency: str = "USD"
    phase_costs: list[PhaseCost] = field(default_factory=list)
    platform_details: dict[str, Any] = field(default_factory=dict)
    cost_model: Optional[str] = None
    warnings: list[str] = field(default_factory=list)
    storage_cost: Optional[float] = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation."""
        result = {
            "total_cost": self.total_cost,
            "currency": self.currency,
            "phase_costs": [pc.to_dict() for pc in self.phase_costs],
            "platform_details": self.platform_details,
        }
        if self.cost_model:
            result["cost_model"] = self.cost_model
        if self.warnings:
            result["warnings"] = self.warnings
        if self.storage_cost is not None:
            result["storage_cost"] = self.storage_cost
        return result

    @classmethod
    def from_phase_costs(
        cls,
        phase_costs: list[PhaseCost],
        platform_details: Optional[dict[str, Any]] = None,
        currency: str = "USD",
    ) -> "BenchmarkCost":
        """Create a BenchmarkCost by aggregating phase costs.

        Args:
            phase_costs: List of phase costs to aggregate
            platform_details: Platform-specific context information
            currency: Currency code (all phase costs should use the same currency)

        Returns:
            BenchmarkCost with total calculated from phases
        """
        total = sum(pc.total_cost for pc in phase_costs)
        return cls(
            total_cost=total,
            currency=currency,
            phase_costs=phase_costs,
            platform_details=platform_details or {},
        )
