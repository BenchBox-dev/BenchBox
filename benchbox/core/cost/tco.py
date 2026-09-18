"""Total Cost of Ownership (TCO) Calculator for database platforms.

This module provides multi-year TCO projections with:
- 1/3/5-year cost forecasting
- Growth rate modeling (linear, compound)
- Discount modeling (reserved capacity, commitments)
- Budget threshold alerts

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional

from benchbox.core.cost.models import BenchmarkCost, unavailable_cost_warning


class GrowthModel(Enum):
    """Growth models for data/usage projections."""

    NONE = "none"  # No growth - flat usage
    LINEAR = "linear"  # Linear growth (e.g., +10% per year additive)
    COMPOUND = "compound"  # Compound growth (e.g., 1.1x per year multiplicative)


class DiscountType(Enum):
    """Types of pricing discounts."""

    NONE = "none"
    RESERVED = "reserved"  # Reserved capacity commitment
    COMMITTED_USE = "committed_use"  # Committed use discount (GCP)
    ENTERPRISE = "enterprise"  # Enterprise negotiated pricing
    VOLUME = "volume"  # Volume-based discounts


@dataclass
class GrowthConfig:
    """Configuration for usage/data growth projections.

    Attributes:
        model: Growth model to use (none, linear, compound)
        annual_rate: Annual growth rate (0.1 = 10% growth)
        data_growth_rate: Separate growth rate for data volume (if different from usage)
    """

    model: GrowthModel = GrowthModel.NONE
    annual_rate: float = 0.0
    data_growth_rate: Optional[float] = None  # If None, uses annual_rate

    def get_data_growth_rate(self) -> float:
        """Get the data growth rate, defaulting to annual_rate if not set."""
        return self.data_growth_rate if self.data_growth_rate is not None else self.annual_rate

    def calculate_multiplier(self, year: int) -> float:
        """Calculate the growth multiplier for a given year.

        Args:
            year: Year number (1 = first year, 2 = second year, etc.)

        Returns:
            Multiplier to apply to base cost
        """
        if self.model == GrowthModel.NONE or year <= 1:
            return 1.0
        elif self.model == GrowthModel.LINEAR:
            # Linear: base + (year - 1) * rate * base = base * (1 + (year-1) * rate)
            return 1.0 + (year - 1) * self.annual_rate
        elif self.model == GrowthModel.COMPOUND:
            # Compound: base * (1 + rate)^(year - 1)
            return (1.0 + self.annual_rate) ** (year - 1)
        return 1.0


@dataclass
class DiscountConfig:
    """Configuration for pricing discounts.

    Attributes:
        discount_type: Type of discount
        discount_percent: Discount percentage (0.2 = 20% discount)
        commitment_years: Years of commitment (for reserved/committed pricing)
        effective_start_year: Year when discount takes effect (default: 1)
    """

    discount_type: DiscountType = DiscountType.NONE
    discount_percent: float = 0.0
    commitment_years: int = 1
    effective_start_year: int = 1

    def get_discount_multiplier(self, year: int) -> float:
        """Get the discount multiplier for a given year.

        Args:
            year: Year number

        Returns:
            Multiplier to apply (e.g., 0.8 for 20% discount)
        """
        if self.discount_type == DiscountType.NONE:
            return 1.0
        if year < self.effective_start_year:
            return 1.0
        return 1.0 - self.discount_percent


@dataclass
class BudgetThreshold:
    """Budget threshold for cost alerts.

    Attributes:
        name: Name of the threshold (e.g., "warning", "critical")
        amount: Threshold amount in currency
        period: Period for the threshold ("monthly", "annual", "total")
    """

    name: str
    amount: float
    period: str = "annual"  # "monthly", "annual", "total"

    def is_exceeded(self, cost: float, period: str) -> bool:
        """Check if the threshold is exceeded.

        Args:
            cost: Cost amount to check
            period: Period of the cost ("monthly", "annual", "total")

        Returns:
            True if threshold is exceeded
        """
        if period != self.period:
            # Convert to matching period
            if self.period == "annual" and period == "monthly":
                cost = cost * 12
            elif self.period == "monthly" and period == "annual":
                cost = cost / 12
        return cost > self.amount


@dataclass
class BudgetAlert:
    """A budget alert that was triggered.

    Attributes:
        threshold: The threshold that was exceeded
        actual_cost: The actual cost that exceeded the threshold
        year: Year when the alert was triggered
        period: Period of the cost
        message: Human-readable alert message
    """

    threshold: BudgetThreshold
    actual_cost: float
    year: int
    period: str
    message: str


@dataclass
class YearlyProjection:
    """Projected costs for a single year.

    Attributes:
        year: Year number (1, 2, 3, etc.)
        calendar_year: Actual calendar year (e.g., 2025)
        base_cost: Base cost before growth/discounts
        growth_multiplier: Multiplier from growth model
        discount_multiplier: Multiplier from discounts
        projected_cost: Final projected cost
        cumulative_cost: Cumulative cost up to this year
        monthly_cost: Average monthly cost for this year
    """

    year: int
    calendar_year: int
    base_cost: float
    growth_multiplier: float
    discount_multiplier: float
    projected_cost: float
    cumulative_cost: float
    monthly_cost: float

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "year": self.year,
            "calendar_year": self.calendar_year,
            "base_cost": round(self.base_cost, 2),
            "growth_multiplier": round(self.growth_multiplier, 4),
            "discount_multiplier": round(self.discount_multiplier, 4),
            "projected_cost": round(self.projected_cost, 2),
            "cumulative_cost": round(self.cumulative_cost, 2),
            "monthly_cost": round(self.monthly_cost, 2),
        }


@dataclass
class TCOProjection:
    """Complete TCO projection with multi-year forecasts.

    Attributes:
        platform: Platform name
        base_annual_cost: Starting annual cost (from benchmark)
        currency: Currency code
        projection_years: Number of years projected
        start_year: Starting calendar year
        growth_config: Growth configuration used
        discount_config: Discount configuration used
        yearly_projections: List of yearly cost projections
        total_tco: Total cost over all projection years
        average_annual_cost: Average annual cost
        budget_alerts: List of triggered budget alerts
        metadata: Additional metadata about the projection
    """

    platform: str
    base_annual_cost: float
    currency: str = "USD"
    projection_years: int = 5
    start_year: int = field(default_factory=lambda: datetime.now().year)
    growth_config: GrowthConfig = field(default_factory=GrowthConfig)
    discount_config: DiscountConfig = field(default_factory=DiscountConfig)
    yearly_projections: list[YearlyProjection] = field(default_factory=list)
    total_tco: float = 0.0
    average_annual_cost: float = 0.0
    budget_alerts: list[BudgetAlert] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "platform": self.platform,
            "base_annual_cost": round(self.base_annual_cost, 2),
            "currency": self.currency,
            "projection_years": self.projection_years,
            "start_year": self.start_year,
            "growth_config": {
                "model": self.growth_config.model.value,
                "annual_rate": self.growth_config.annual_rate,
                "data_growth_rate": self.growth_config.get_data_growth_rate(),
            },
            "discount_config": {
                "discount_type": self.discount_config.discount_type.value,
                "discount_percent": self.discount_config.discount_percent,
                "commitment_years": self.discount_config.commitment_years,
            },
            "yearly_projections": [yp.to_dict() for yp in self.yearly_projections],
            "total_tco": round(self.total_tco, 2),
            "average_annual_cost": round(self.average_annual_cost, 2),
            "budget_alerts": [
                {
                    "threshold": a.threshold.name,
                    "amount": a.threshold.amount,
                    "actual_cost": round(a.actual_cost, 2),
                    "year": a.year,
                    "message": a.message,
                }
                for a in self.budget_alerts
            ],
            "metadata": self.metadata,
        }


class TCOCalculator:
    """Calculator for multi-year Total Cost of Ownership projections.

    The TCO Calculator extrapolates benchmark costs to annual and multi-year
    projections, accounting for:
    - Usage/data growth over time
    - Pricing discounts (reserved, committed use, enterprise)
    - Budget threshold monitoring

    Example:
        >>> from benchbox.core.cost import CostCalculator
        >>> from benchbox.core.cost.tco import TCOCalculator, GrowthConfig, GrowthModel
        >>>
        >>> # Calculate benchmark cost
        >>> cost_calc = CostCalculator()
        >>> benchmark_cost = cost_calc.calculate_benchmark_cost(phase_costs)
        >>>
        >>> # Project 5-year TCO with 15% annual growth
        >>> tco_calc = TCOCalculator()
        >>> growth = GrowthConfig(model=GrowthModel.COMPOUND, annual_rate=0.15)
        >>> projection = tco_calc.calculate_tco(
        ...     benchmark_cost=benchmark_cost,
        ...     annual_runs=12,  # Monthly runs
        ...     projection_years=5,
        ...     growth_config=growth,
        ... )
        >>> emit(f"5-year TCO: ${projection.total_tco:,.2f}")
    """

    def __init__(self) -> None:
        """Initialize the TCO calculator."""
        self._budget_thresholds: list[BudgetThreshold] = []

    def add_budget_threshold(self, threshold: BudgetThreshold) -> None:
        """Add a budget threshold for alerting.

        Args:
            threshold: Budget threshold to add
        """
        self._budget_thresholds.append(threshold)

    def clear_budget_thresholds(self) -> None:
        """Clear all budget thresholds."""
        self._budget_thresholds.clear()

    def calculate_tco(
        self,
        benchmark_cost: BenchmarkCost,
        annual_runs: int = 1,
        projection_years: int = 5,
        growth_config: Optional[GrowthConfig] = None,
        discount_config: Optional[DiscountConfig] = None,
        platform: Optional[str] = None,
        start_year: Optional[int] = None,
    ) -> TCOProjection:
        """Calculate multi-year TCO projection from benchmark costs.

        Args:
            benchmark_cost: Cost from a single benchmark run
            annual_runs: Number of benchmark runs per year (for workload estimation)
            projection_years: Number of years to project (1, 3, or 5)
            growth_config: Configuration for growth modeling
            discount_config: Configuration for discounts
            platform: Platform name (extracted from benchmark_cost if not provided)
            start_year: Starting calendar year (defaults to current year)

        Returns:
            TCOProjection with yearly breakdowns and total TCO

        Raises:
            ValueError: If the benchmark cost is marked unavailable (fallback
                pricing, defaulted metadata, or stale tables). A cost that is
                not fit to publish is not fit to project.
        """
        unavailable = unavailable_cost_warning(benchmark_cost.warnings)
        if unavailable is not None:
            raise ValueError(f"cannot project TCO from an unavailable benchmark cost: {unavailable}")
        growth = growth_config or GrowthConfig()
        discount = discount_config or DiscountConfig()
        start = start_year or datetime.now().year

        # Calculate base annual cost
        base_annual_cost = benchmark_cost.total_cost * annual_runs

        # Extract platform from benchmark_cost if not provided
        if platform is None:
            platform = benchmark_cost.platform_details.get("platform", "unknown")

        # Generate yearly projections
        yearly_projections: list[YearlyProjection] = []
        cumulative_cost = 0.0

        for year in range(1, projection_years + 1):
            growth_mult = growth.calculate_multiplier(year)
            discount_mult = discount.get_discount_multiplier(year)

            projected_cost = base_annual_cost * growth_mult * discount_mult
            cumulative_cost += projected_cost

            projection = YearlyProjection(
                year=year,
                calendar_year=start + year - 1,
                base_cost=base_annual_cost,
                growth_multiplier=growth_mult,
                discount_multiplier=discount_mult,
                projected_cost=projected_cost,
                cumulative_cost=cumulative_cost,
                monthly_cost=projected_cost / 12,
            )
            yearly_projections.append(projection)

        # Check budget thresholds
        alerts = self._check_budget_thresholds(yearly_projections, cumulative_cost)

        # Create the projection
        tco = TCOProjection(
            platform=platform,
            base_annual_cost=base_annual_cost,
            currency=benchmark_cost.currency,
            projection_years=projection_years,
            start_year=start,
            growth_config=growth,
            discount_config=discount,
            yearly_projections=yearly_projections,
            total_tco=cumulative_cost,
            average_annual_cost=cumulative_cost / projection_years,
            budget_alerts=alerts,
            metadata={
                "benchmark_run_cost": benchmark_cost.total_cost,
                "annual_runs": annual_runs,
                "generated_at": datetime.now().isoformat(),
            },
        )

        return tco

    def calculate_tco_from_annual_cost(
        self,
        annual_cost: float,
        platform: str,
        projection_years: int = 5,
        growth_config: Optional[GrowthConfig] = None,
        discount_config: Optional[DiscountConfig] = None,
        currency: str = "USD",
        start_year: Optional[int] = None,
    ) -> TCOProjection:
        """Calculate TCO projection from a known annual cost.

        This is useful when you already know the annual cost and don't need
        to calculate it from benchmark results.

        Args:
            annual_cost: Known annual cost
            platform: Platform name
            projection_years: Number of years to project
            growth_config: Configuration for growth modeling
            discount_config: Configuration for discounts
            currency: Currency code
            start_year: Starting calendar year

        Returns:
            TCOProjection with yearly breakdowns
        """
        # Create a simple benchmark cost to reuse calculate_tco
        benchmark_cost = BenchmarkCost(
            total_cost=annual_cost,
            currency=currency,
            platform_details={"platform": platform},
        )

        return self.calculate_tco(
            benchmark_cost=benchmark_cost,
            annual_runs=1,  # Already annual
            projection_years=projection_years,
            growth_config=growth_config,
            discount_config=discount_config,
            platform=platform,
            start_year=start_year,
        )

    def compare_platforms(
        self,
        projections: list[TCOProjection],
    ) -> dict[str, Any]:
        """Compare TCO projections across multiple platforms.

        Args:
            projections: List of TCO projections to compare

        Returns:
            Comparison summary with rankings and savings analysis
        """
        if not projections:
            return {"error": "No projections to compare"}

        # Sort by total TCO
        sorted_projections = sorted(projections, key=lambda p: p.total_tco)

        # Calculate savings vs most expensive
        most_expensive = sorted_projections[-1].total_tco

        comparison = {
            "rankings": [
                {
                    "rank": i + 1,
                    "platform": p.platform,
                    "total_tco": round(p.total_tco, 2),
                    "savings_vs_max": round(most_expensive - p.total_tco, 2),
                    "savings_percent": round((most_expensive - p.total_tco) / most_expensive * 100, 1)
                    if most_expensive > 0
                    else 0,
                }
                for i, p in enumerate(sorted_projections)
            ],
            "cheapest_platform": sorted_projections[0].platform,
            "most_expensive_platform": sorted_projections[-1].platform,
            "max_savings": round(most_expensive - sorted_projections[0].total_tco, 2),
            "projection_years": sorted_projections[0].projection_years,
            "currency": sorted_projections[0].currency,
        }

        return comparison

    def _check_budget_thresholds(
        self,
        yearly_projections: list[YearlyProjection],
        total_tco: float,
    ) -> list[BudgetAlert]:
        """Check budget thresholds and generate alerts.

        Args:
            yearly_projections: Yearly cost projections
            total_tco: Total cost over all years

        Returns:
            List of triggered budget alerts
        """
        alerts: list[BudgetAlert] = []

        for threshold in self._budget_thresholds:
            if threshold.period == "total":
                # Check total TCO
                if threshold.is_exceeded(total_tco, "total"):
                    alerts.append(
                        BudgetAlert(
                            threshold=threshold,
                            actual_cost=total_tco,
                            year=len(yearly_projections),
                            period="total",
                            message=f"Total TCO ${total_tco:,.2f} exceeds {threshold.name} "
                            f"threshold of ${threshold.amount:,.2f}",
                        )
                    )
            else:
                # Check each year
                for yp in yearly_projections:
                    cost = yp.monthly_cost if threshold.period == "monthly" else yp.projected_cost

                    if threshold.is_exceeded(cost, threshold.period):
                        alerts.append(
                            BudgetAlert(
                                threshold=threshold,
                                actual_cost=cost,
                                year=yp.year,
                                period=threshold.period,
                                message=f"Year {yp.year} {threshold.period} cost ${cost:,.2f} "
                                f"exceeds {threshold.name} threshold of ${threshold.amount:,.2f}",
                            )
                        )
                        break  # Only alert once per threshold

        return alerts


def create_standard_tco_scenarios(
    benchmark_cost: BenchmarkCost,
    annual_runs: int = 12,
) -> dict[str, TCOProjection]:
    """Create standard TCO scenarios for quick analysis.

    This creates three common scenarios:
    - Conservative: No growth, no discounts
    - Moderate: 10% compound growth, 15% reserved discount
    - Aggressive: 25% compound growth, no discounts

    Args:
        benchmark_cost: Base benchmark cost
        annual_runs: Number of benchmark runs per year

    Returns:
        Dictionary of scenario name to TCO projection
    """
    calculator = TCOCalculator()

    scenarios = {
        "conservative": calculator.calculate_tco(
            benchmark_cost=benchmark_cost,
            annual_runs=annual_runs,
            projection_years=5,
            growth_config=GrowthConfig(model=GrowthModel.NONE),
            discount_config=DiscountConfig(discount_type=DiscountType.NONE),
        ),
        "moderate": calculator.calculate_tco(
            benchmark_cost=benchmark_cost,
            annual_runs=annual_runs,
            projection_years=5,
            growth_config=GrowthConfig(model=GrowthModel.COMPOUND, annual_rate=0.10),
            discount_config=DiscountConfig(
                discount_type=DiscountType.RESERVED,
                discount_percent=0.15,
                commitment_years=3,
            ),
        ),
        "aggressive": calculator.calculate_tco(
            benchmark_cost=benchmark_cost,
            annual_runs=annual_runs,
            projection_years=5,
            growth_config=GrowthConfig(model=GrowthModel.COMPOUND, annual_rate=0.25),
            discount_config=DiscountConfig(discount_type=DiscountType.NONE),
        ),
    }

    return scenarios
