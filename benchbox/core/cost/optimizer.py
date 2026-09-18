"""Cost Optimization Engine with rule-based recommendations.

This module provides automated cost optimization analysis with:
- Rule-based detection of optimization opportunities
- Savings estimates with confidence levels
- Implementation guides with actionable steps
- Priority-ranked recommendations

The engine analyzes benchmark costs across platforms and generates
actionable recommendations to reduce cloud database spending.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional

from benchbox.core.cost.models import BenchmarkCost
from benchbox.core.cost.pricing import (
    resolve_bigquery_price_per_tb,
    resolve_databricks_dbu_price,
    resolve_redshift_node_price,
    resolve_snowflake_credit_price,
)


class OptimizationCategory(Enum):
    """Categories of cost optimization recommendations."""

    PLATFORM_TIER = "platform_tier"  # Tier/edition changes
    REGION = "region"  # Region optimization
    RESOURCE_SIZING = "resource_sizing"  # Warehouse/cluster sizing
    PRICING_MODEL = "pricing_model"  # Reserved vs on-demand
    QUERY = "query"  # Query-level optimizations
    DATA_MANAGEMENT = "data_management"  # Data lifecycle, partitioning


class ConfidenceLevel(Enum):
    """Confidence level for savings estimates."""

    HIGH = "high"  # Based on actual pricing data
    MEDIUM = "medium"  # Based on typical patterns
    LOW = "low"  # Rough estimate, may vary significantly


class ImplementationEffort(Enum):
    """Effort level for implementing a recommendation."""

    TRIVIAL = "trivial"  # Minutes, configuration change only
    LOW = "low"  # Hours, simple changes
    MEDIUM = "medium"  # Days, moderate changes
    HIGH = "high"  # Weeks, significant changes


@dataclass
class SavingsEstimate:
    """Estimated cost savings from implementing a recommendation.

    Attributes:
        amount: Estimated savings amount per period
        currency: Currency code
        period: Time period for savings (e.g., "monthly", "annual")
        confidence: Confidence level of the estimate
        range_low: Low end of savings range (optional)
        range_high: High end of savings range (optional)
        percentage: Savings as percentage of current cost
    """

    amount: float
    currency: str = "USD"
    period: str = "annual"
    confidence: ConfidenceLevel = ConfidenceLevel.MEDIUM
    range_low: Optional[float] = None
    range_high: Optional[float] = None
    percentage: Optional[float] = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation."""
        result = {
            "amount": round(self.amount, 2),
            "currency": self.currency,
            "period": self.period,
            "confidence": self.confidence.value,
        }
        if self.range_low is not None:
            result["range_low"] = round(self.range_low, 2)
        if self.range_high is not None:
            result["range_high"] = round(self.range_high, 2)
        if self.percentage is not None:
            result["percentage"] = round(self.percentage, 1)
        return result


@dataclass
class ImplementationGuide:
    """Step-by-step guide for implementing a recommendation.

    Attributes:
        steps: List of implementation steps
        prerequisites: Requirements before implementation
        risks: Potential risks or considerations
        rollback: How to revert if needed
        estimated_time: Estimated implementation time
    """

    steps: list[str]
    prerequisites: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    rollback: Optional[str] = None
    estimated_time: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation."""
        result = {
            "steps": self.steps,
        }
        if self.prerequisites:
            result["prerequisites"] = self.prerequisites
        if self.risks:
            result["risks"] = self.risks
        if self.rollback:
            result["rollback"] = self.rollback
        if self.estimated_time:
            result["estimated_time"] = self.estimated_time
        return result


@dataclass
class Recommendation:
    """A cost optimization recommendation.

    Attributes:
        id: Unique identifier for the recommendation
        title: Short title describing the recommendation
        description: Detailed description of the optimization
        category: Category of the optimization
        savings: Estimated savings from implementing
        effort: Implementation effort level
        guide: Implementation guide
        priority: Priority score (higher = more important)
        platform: Target platform (if platform-specific)
        current_config: Current configuration being optimized
        recommended_config: Recommended configuration
        metadata: Additional context-specific data
    """

    id: str
    title: str
    description: str
    category: OptimizationCategory
    savings: SavingsEstimate
    effort: ImplementationEffort
    guide: ImplementationGuide
    priority: int = 50  # 1-100, higher = more important
    platform: Optional[str] = None
    current_config: Optional[dict[str, Any]] = None
    recommended_config: Optional[dict[str, Any]] = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation."""
        result = {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "category": self.category.value,
            "savings": self.savings.to_dict(),
            "effort": self.effort.value,
            "guide": self.guide.to_dict(),
            "priority": self.priority,
        }
        if self.platform:
            result["platform"] = self.platform
        if self.current_config:
            result["current_config"] = self.current_config
        if self.recommended_config:
            result["recommended_config"] = self.recommended_config
        if self.metadata:
            result["metadata"] = self.metadata
        return result


@dataclass
class OptimizationReport:
    """Complete cost optimization report.

    Attributes:
        recommendations: List of recommendations sorted by priority
        total_potential_savings: Sum of all recommended savings
        currency: Currency code
        platform: Platform analyzed
        analysis_date: When the analysis was performed
        benchmark_cost: Original benchmark cost analyzed
        metadata: Additional report metadata
    """

    recommendations: list[Recommendation] = field(default_factory=list)
    total_potential_savings: float = 0.0
    currency: str = "USD"
    platform: Optional[str] = None
    analysis_date: str = field(default_factory=lambda: datetime.now().isoformat())
    benchmark_cost: Optional[BenchmarkCost] = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "recommendations": [r.to_dict() for r in self.recommendations],
            "total_potential_savings": round(self.total_potential_savings, 2),
            "currency": self.currency,
            "platform": self.platform,
            "analysis_date": self.analysis_date,
            "recommendation_count": len(self.recommendations),
            "metadata": self.metadata,
        }

    def get_by_category(self, category: OptimizationCategory) -> list[Recommendation]:
        """Get recommendations filtered by category."""
        return [r for r in self.recommendations if r.category == category]

    def get_quick_wins(self, max_effort: ImplementationEffort = ImplementationEffort.LOW) -> list[Recommendation]:
        """Get recommendations that are easy to implement.

        Args:
            max_effort: Maximum effort level to include

        Returns:
            List of low-effort recommendations sorted by savings
        """
        effort_order = [
            ImplementationEffort.TRIVIAL,
            ImplementationEffort.LOW,
            ImplementationEffort.MEDIUM,
            ImplementationEffort.HIGH,
        ]
        max_idx = effort_order.index(max_effort)
        allowed = set(effort_order[: max_idx + 1])

        quick_wins = [r for r in self.recommendations if r.effort in allowed]
        return sorted(quick_wins, key=lambda r: r.savings.amount, reverse=True)


class CostOptimizer:
    """Cost optimization engine with rule-based recommendations.

    The optimizer analyzes benchmark costs and generates actionable
    recommendations for reducing cloud database spending. It uses
    rule-based detection to identify optimization opportunities
    across multiple categories.

    Example:
        >>> from benchbox.core.cost import CostCalculator, BenchmarkCost
        >>> from benchbox.core.cost.optimizer import CostOptimizer
        >>>
        >>> # Analyze benchmark cost
        >>> optimizer = CostOptimizer()
        >>> report = optimizer.analyze(benchmark_cost, platform_config)
        >>>
        >>> # Get prioritized recommendations
        >>> for rec in report.recommendations:
        ...     emit(f"{rec.title}: Save ${rec.savings.amount}/year")
        >>>
        >>> # Get quick wins
        >>> quick_wins = report.get_quick_wins()
    """

    def __init__(self) -> None:
        """Initialize the cost optimizer."""
        self._rules: list[tuple[str, callable]] = []
        self._register_default_rules()

    def _register_default_rules(self) -> None:
        """Register default optimization rules."""
        # Platform tier rules
        self._rules.append(("snowflake_tier", self._check_snowflake_tier))
        self._rules.append(("databricks_tier", self._check_databricks_tier))

        # Region rules
        self._rules.append(("snowflake_region", self._check_snowflake_region))
        self._rules.append(("bigquery_region", self._check_bigquery_region))
        self._rules.append(("redshift_region", self._check_redshift_region))

        # Resource sizing rules
        self._rules.append(("redshift_node_type", self._check_redshift_node_type))
        self._rules.append(("databricks_workload", self._check_databricks_workload))

        # Pricing model rules
        self._rules.append(("reserved_capacity", self._check_reserved_capacity))

        # Query optimization rules
        self._rules.append(("high_cost_queries", self._check_high_cost_queries))
        self._rules.append(("bigquery_bytes", self._check_bigquery_bytes_scanned))

    def analyze(
        self,
        benchmark_cost: BenchmarkCost,
        platform_config: Optional[dict[str, Any]] = None,
        annual_runs: int = 12,
    ) -> OptimizationReport:
        """Analyze benchmark costs and generate optimization recommendations.

        Args:
            benchmark_cost: Benchmark cost to analyze
            platform_config: Platform configuration details
            annual_runs: Expected number of benchmark runs per year

        Returns:
            OptimizationReport with prioritized recommendations
        """
        platform_config = platform_config or {}
        platform = platform_config.get(
            "platform",
            benchmark_cost.platform_details.get("platform", "unknown"),
        )

        recommendations: list[Recommendation] = []

        # Run all applicable rules
        for rule_name, rule_func in self._rules:
            try:
                rec = rule_func(
                    benchmark_cost=benchmark_cost,
                    platform_config=platform_config,
                    platform=platform,
                    annual_runs=annual_runs,
                )
                if rec:
                    if isinstance(rec, list):
                        recommendations.extend(rec)
                    else:
                        recommendations.append(rec)
            except Exception:
                # Skip rules that fail - don't break the entire analysis
                pass

        # Sort by priority (descending)
        recommendations.sort(key=lambda r: r.priority, reverse=True)

        # Calculate total potential savings
        total_savings = sum(r.savings.amount for r in recommendations)

        return OptimizationReport(
            recommendations=recommendations,
            total_potential_savings=total_savings,
            currency=benchmark_cost.currency,
            platform=platform,
            benchmark_cost=benchmark_cost,
            metadata={
                "annual_runs": annual_runs,
                "rules_evaluated": len(self._rules),
                "recommendations_generated": len(recommendations),
            },
        )

    # =========================================================================
    # Platform Tier Rules
    # =========================================================================

    def _check_snowflake_tier(
        self,
        benchmark_cost: BenchmarkCost,
        platform_config: dict[str, Any],
        platform: str,
        annual_runs: int,
    ) -> Optional[Recommendation]:
        """Check if Snowflake edition can be downgraded."""
        if platform.lower() != "snowflake":
            return None

        edition = platform_config.get("edition", "").lower()
        if edition not in ("enterprise", "business_critical"):
            return None  # Already on standard

        cloud = platform_config.get("cloud", "aws")
        region = platform_config.get("region", "us-east-1")

        # Calculate current vs standard pricing
        current_price = resolve_snowflake_credit_price(edition, cloud, region).value
        standard_price = resolve_snowflake_credit_price("standard", cloud, region).value

        if current_price <= standard_price:
            return None

        # Estimate credits from cost
        credits_used = benchmark_cost.total_cost / current_price
        annual_credits = credits_used * annual_runs

        # Calculate savings
        current_annual = annual_credits * current_price
        standard_annual = annual_credits * standard_price
        savings = current_annual - standard_annual
        savings_pct = (savings / current_annual * 100) if current_annual > 0 else 0

        target_edition = "Standard"
        if edition == "business_critical":
            # Check if Enterprise is an option
            enterprise_price = resolve_snowflake_credit_price("enterprise", cloud, region).value
            enterprise_annual = annual_credits * enterprise_price
            enterprise_savings = current_annual - enterprise_annual

            # If Enterprise saves significant money, recommend that instead
            if enterprise_savings > savings * 0.5:
                target_edition = "Enterprise"
                savings = enterprise_savings
                savings_pct = (savings / current_annual * 100) if current_annual > 0 else 0

        return Recommendation(
            id=f"snowflake-tier-{edition}-to-{target_edition.lower()}",
            title=f"Downgrade Snowflake to {target_edition} Edition",
            description=(
                f"Current {edition.replace('_', ' ').title()} edition costs "
                f"${current_price:.2f}/credit vs ${standard_price:.2f}/credit for Standard. "
                f"If {target_edition} features are not required, downgrading saves "
                f"{savings_pct:.0f}% annually."
            ),
            category=OptimizationCategory.PLATFORM_TIER,
            savings=SavingsEstimate(
                amount=savings,
                period="annual",
                confidence=ConfidenceLevel.HIGH,
                percentage=savings_pct,
            ),
            effort=ImplementationEffort.MEDIUM,
            guide=ImplementationGuide(
                steps=[
                    f"Review {target_edition} vs {edition.replace('_', ' ').title()} feature comparison",
                    "Verify no blocked features are in use (e.g., multi-cluster warehouses, failover)",
                    "Contact Snowflake account team to discuss edition change",
                    "Plan migration during low-usage period",
                    "Update Snowflake configuration and validate workloads",
                ],
                prerequisites=[
                    f"Inventory of {edition.replace('_', ' ').title()}-specific features in use",
                    "Stakeholder approval for edition change",
                ],
                risks=[
                    "Some features may not be available in lower edition",
                    "May require contract renegotiation",
                ],
                rollback="Contact Snowflake to upgrade edition if needed",
                estimated_time="2-4 weeks (contract negotiation)",
            ),
            priority=80,
            platform="snowflake",
            current_config={"edition": edition, "price_per_credit": current_price},
            recommended_config={
                "edition": target_edition.lower(),
                "price_per_credit": standard_price
                if target_edition == "Standard"
                else resolve_snowflake_credit_price("enterprise", cloud, region).value,
            },
        )

    def _check_databricks_tier(
        self,
        benchmark_cost: BenchmarkCost,
        platform_config: dict[str, Any],
        platform: str,
        annual_runs: int,
    ) -> Optional[Recommendation]:
        """Check if Databricks tier can be downgraded."""
        if platform.lower() != "databricks":
            return None

        tier = platform_config.get("tier", "").lower()
        if tier not in ("enterprise", "premium"):
            return None

        cloud = platform_config.get("cloud", "aws")
        workload_type = platform_config.get("workload_type", "sql_warehouse")

        # Calculate current vs lower tier pricing
        current_price = resolve_databricks_dbu_price(cloud, tier, workload_type).value

        # Determine target tier
        if tier == "enterprise":
            target_tier = "premium"
        else:
            target_tier = "standard"

        target_price = resolve_databricks_dbu_price(cloud, target_tier, workload_type).value

        if current_price <= target_price:
            return None

        # Estimate DBUs from cost (rough estimate)
        dbu_consumed = benchmark_cost.total_cost / current_price
        annual_dbus = dbu_consumed * annual_runs

        current_annual = annual_dbus * current_price
        target_annual = annual_dbus * target_price
        savings = current_annual - target_annual
        savings_pct = (savings / current_annual * 100) if current_annual > 0 else 0

        return Recommendation(
            id=f"databricks-tier-{tier}-to-{target_tier}",
            title=f"Downgrade Databricks to {target_tier.title()} Tier",
            description=(
                f"Current {tier.title()} tier costs ${current_price:.2f}/DBU vs "
                f"${target_price:.2f}/DBU for {target_tier.title()}. "
                f"Evaluate if {tier.title()}-specific features are required."
            ),
            category=OptimizationCategory.PLATFORM_TIER,
            savings=SavingsEstimate(
                amount=savings,
                period="annual",
                confidence=ConfidenceLevel.MEDIUM,
                percentage=savings_pct,
            ),
            effort=ImplementationEffort.MEDIUM,
            guide=ImplementationGuide(
                steps=[
                    f"Review {tier.title()} vs {target_tier.title()} feature comparison",
                    "Check for Unity Catalog, audit logging, or other premium features in use",
                    "Contact Databricks account team to discuss tier change",
                    "Plan migration and validate workloads",
                ],
                prerequisites=[
                    "Feature inventory for current tier",
                    "Stakeholder approval",
                ],
                risks=[
                    "Some security/governance features may not be available",
                    "May affect compliance requirements",
                ],
                rollback="Upgrade tier through Databricks account settings",
                estimated_time="1-3 weeks",
            ),
            priority=70,
            platform="databricks",
            current_config={"tier": tier, "price_per_dbu": current_price},
            recommended_config={"tier": target_tier, "price_per_dbu": target_price},
        )

    # =========================================================================
    # Region Optimization Rules
    # =========================================================================

    def _check_snowflake_region(
        self,
        benchmark_cost: BenchmarkCost,
        platform_config: dict[str, Any],
        platform: str,
        annual_runs: int,
    ) -> Optional[Recommendation]:
        """Check if a cheaper Snowflake region is available."""
        if platform.lower() != "snowflake":
            return None

        region = platform_config.get("region", "")
        cloud = platform_config.get("cloud", "aws")
        edition = platform_config.get("edition", "standard")

        # Get current price
        current_price = resolve_snowflake_credit_price(edition, cloud, region).value

        # Check US regions (typically cheapest)
        us_price = resolve_snowflake_credit_price(edition, cloud, "us-east-1").value

        if current_price <= us_price:
            return None

        # Calculate potential savings
        credits_used = benchmark_cost.total_cost / current_price
        annual_credits = credits_used * annual_runs

        current_annual = annual_credits * current_price
        us_annual = annual_credits * us_price
        savings = current_annual - us_annual
        savings_pct = (savings / current_annual * 100) if current_annual > 0 else 0

        return Recommendation(
            id="snowflake-region-optimization",
            title="Consider US Region for Lower Snowflake Costs",
            description=(
                f"Current region pricing is ${current_price:.2f}/credit vs "
                f"${us_price:.2f}/credit in US regions. If data residency permits, "
                f"US regions offer {savings_pct:.0f}% lower credit prices."
            ),
            category=OptimizationCategory.REGION,
            savings=SavingsEstimate(
                amount=savings,
                period="annual",
                confidence=ConfidenceLevel.MEDIUM,
                percentage=savings_pct,
            ),
            effort=ImplementationEffort.HIGH,
            guide=ImplementationGuide(
                steps=[
                    "Verify data residency and compliance requirements",
                    "Evaluate latency impact for application users",
                    "Plan data migration strategy",
                    "Create new Snowflake account in target region",
                    "Migrate data and update application connections",
                ],
                prerequisites=[
                    "Data residency compliance review",
                    "Latency requirements analysis",
                    "Application connection update plan",
                ],
                risks=[
                    "Data residency/sovereignty requirements may prohibit this",
                    "Increased latency for non-US users",
                    "Data migration complexity and downtime",
                ],
                rollback="Maintain original region as fallback during transition",
                estimated_time="4-8 weeks",
            ),
            priority=40,  # Lower priority due to high effort
            platform="snowflake",
            current_config={"region": region, "price_per_credit": current_price},
            recommended_config={"region": "us-east-1", "price_per_credit": us_price},
        )

    def _check_bigquery_region(
        self,
        benchmark_cost: BenchmarkCost,
        platform_config: dict[str, Any],
        platform: str,
        annual_runs: int,
    ) -> Optional[Recommendation]:
        """Check if a cheaper BigQuery region is available."""
        if platform.lower() != "bigquery":
            return None

        location = platform_config.get("location", "")
        current_price = resolve_bigquery_price_per_tb(location).value
        us_price = resolve_bigquery_price_per_tb("us").value

        if current_price <= us_price:
            return None

        # Estimate TB processed
        tb_processed = benchmark_cost.total_cost / current_price
        annual_tb = tb_processed * annual_runs

        current_annual = annual_tb * current_price
        us_annual = annual_tb * us_price
        savings = current_annual - us_annual
        savings_pct = (savings / current_annual * 100) if current_annual > 0 else 0

        return Recommendation(
            id="bigquery-region-optimization",
            title="Consider US Multi-Region for Lower BigQuery Costs",
            description=(
                f"Current location pricing is ${current_price:.2f}/TB vs "
                f"${us_price:.2f}/TB in US multi-region. "
                f"US multi-region offers {savings_pct:.0f}% lower processing costs."
            ),
            category=OptimizationCategory.REGION,
            savings=SavingsEstimate(
                amount=savings,
                period="annual",
                confidence=ConfidenceLevel.MEDIUM,
                percentage=savings_pct,
            ),
            effort=ImplementationEffort.HIGH,
            guide=ImplementationGuide(
                steps=[
                    "Verify data residency requirements allow US storage",
                    "Evaluate egress costs for cross-region queries",
                    "Create datasets in US multi-region",
                    "Migrate data using BigQuery Data Transfer Service",
                    "Update application configurations",
                ],
                prerequisites=[
                    "Data residency compliance verification",
                    "Egress cost analysis",
                ],
                risks=[
                    "Data residency requirements may prohibit this",
                    "Cross-region egress costs for some use cases",
                ],
                estimated_time="2-4 weeks",
            ),
            priority=40,
            platform="bigquery",
            current_config={"location": location, "price_per_tb": current_price},
            recommended_config={"location": "us", "price_per_tb": us_price},
        )

    def _check_redshift_region(
        self,
        benchmark_cost: BenchmarkCost,
        platform_config: dict[str, Any],
        platform: str,
        annual_runs: int,
    ) -> Optional[Recommendation]:
        """Check if a cheaper Redshift region is available."""
        if platform.lower() != "redshift":
            return None

        region = platform_config.get("region", "")
        node_type = platform_config.get("node_type", "dc2.large")

        current_price = resolve_redshift_node_price(node_type, region).value
        us_east_price = resolve_redshift_node_price(node_type, "us-east-1").value

        if current_price <= us_east_price:
            return None

        # Estimate node-hours
        node_count = platform_config.get("node_count", 1)
        node_hours = benchmark_cost.total_cost / (current_price * node_count)
        annual_node_hours = node_hours * annual_runs

        current_annual = annual_node_hours * node_count * current_price
        us_annual = annual_node_hours * node_count * us_east_price
        savings = current_annual - us_annual
        savings_pct = (savings / current_annual * 100) if current_annual > 0 else 0

        return Recommendation(
            id="redshift-region-optimization",
            title="Consider US-East Region for Lower Redshift Costs",
            description=(
                f"Current region pricing is ${current_price:.2f}/node-hour vs "
                f"${us_east_price:.2f}/node-hour in us-east-1. "
                f"US-East offers {savings_pct:.0f}% lower compute costs."
            ),
            category=OptimizationCategory.REGION,
            savings=SavingsEstimate(
                amount=savings,
                period="annual",
                confidence=ConfidenceLevel.MEDIUM,
                percentage=savings_pct,
            ),
            effort=ImplementationEffort.HIGH,
            guide=ImplementationGuide(
                steps=[
                    "Verify data residency requirements",
                    "Plan cluster migration using Redshift snapshots",
                    "Create new cluster in target region",
                    "Restore from snapshot and validate",
                    "Update application endpoints",
                ],
                prerequisites=["Compliance review", "Snapshot strategy"],
                risks=[
                    "Data residency constraints",
                    "Increased latency for regional users",
                    "Migration downtime",
                ],
                estimated_time="1-2 weeks",
            ),
            priority=40,
            platform="redshift",
            current_config={"region": region, "price_per_node_hour": current_price},
            recommended_config={"region": "us-east-1", "price_per_node_hour": us_east_price},
        )

    # =========================================================================
    # Resource Sizing Rules
    # =========================================================================

    def _check_redshift_node_type(
        self,
        benchmark_cost: BenchmarkCost,
        platform_config: dict[str, Any],
        platform: str,
        annual_runs: int,
    ) -> Optional[Recommendation]:
        """Check if a different Redshift node type would be more cost-effective."""
        if platform.lower() != "redshift":
            return None

        node_type = platform_config.get("node_type", "").lower()
        region = platform_config.get("region", "us-east-1")
        node_count = platform_config.get("node_count", 1)

        # Check if using legacy DS2 nodes
        if node_type.startswith("ds2"):
            # RA3 nodes with managed storage are often more cost-effective
            current_price = resolve_redshift_node_price(node_type, region).value
            ra3_price = resolve_redshift_node_price("ra3.xlplus", region).value

            # RA3 nodes have different performance characteristics
            # This is a rough comparison
            if ra3_price < current_price:
                savings_per_node_hour = current_price - ra3_price

                # Estimate hours
                hours = benchmark_cost.total_cost / (current_price * node_count)
                annual_hours = hours * annual_runs

                savings = annual_hours * node_count * savings_per_node_hour
                savings_pct = savings / (annual_hours * node_count * current_price) * 100

                return Recommendation(
                    id="redshift-migrate-ds2-to-ra3",
                    title="Migrate from DS2 to RA3 Node Type",
                    description=(
                        f"DS2 nodes are legacy. RA3 nodes offer managed storage, "
                        f"separate compute/storage scaling, and may reduce costs. "
                        f"Current: ${current_price:.2f}/hr vs RA3: ${ra3_price:.2f}/hr."
                    ),
                    category=OptimizationCategory.RESOURCE_SIZING,
                    savings=SavingsEstimate(
                        amount=savings,
                        period="annual",
                        confidence=ConfidenceLevel.LOW,  # Performance varies
                        percentage=savings_pct,
                    ),
                    effort=ImplementationEffort.MEDIUM,
                    guide=ImplementationGuide(
                        steps=[
                            "Analyze current data size and query patterns",
                            "Choose appropriate RA3 node type (xlplus, 4xlarge, 16xlarge)",
                            "Create new RA3 cluster from snapshot",
                            "Run performance validation benchmarks",
                            "Migrate production traffic",
                        ],
                        prerequisites=[
                            "Data size analysis",
                            "Query pattern analysis",
                        ],
                        risks=[
                            "Performance may differ - validate with benchmarks",
                            "RA3 requires VPC (not EC2-Classic)",
                        ],
                        estimated_time="1-2 weeks",
                    ),
                    priority=60,
                    platform="redshift",
                    current_config={"node_type": node_type},
                    recommended_config={"node_type": "ra3.xlplus"},
                )

        return None

    def _check_databricks_workload(
        self,
        benchmark_cost: BenchmarkCost,
        platform_config: dict[str, Any],
        platform: str,
        annual_runs: int,
    ) -> Optional[Recommendation]:
        """Check if a more cost-effective Databricks workload type is available."""
        if platform.lower() != "databricks":
            return None

        workload_type = platform_config.get("workload_type", "").lower()
        if workload_type != "all_purpose":
            return None  # Only recommend switching FROM all_purpose

        cloud = platform_config.get("cloud", "aws")
        tier = platform_config.get("tier", "premium")

        current_price = resolve_databricks_dbu_price(cloud, tier, "all_purpose").value
        jobs_price = resolve_databricks_dbu_price(cloud, tier, "jobs").value

        if jobs_price >= current_price:
            return None

        # Estimate DBUs
        dbus = benchmark_cost.total_cost / current_price
        annual_dbus = dbus * annual_runs

        current_annual = annual_dbus * current_price
        jobs_annual = annual_dbus * jobs_price
        savings = current_annual - jobs_annual
        savings_pct = (savings / current_annual * 100) if current_annual > 0 else 0

        return Recommendation(
            id="databricks-workload-optimization",
            title="Use Jobs Compute for Batch Workloads",
            description=(
                f"All-Purpose compute costs ${current_price:.2f}/DBU vs "
                f"${jobs_price:.2f}/DBU for Jobs compute. "
                f"For batch/scheduled workloads, Jobs compute saves {savings_pct:.0f}%."
            ),
            category=OptimizationCategory.RESOURCE_SIZING,
            savings=SavingsEstimate(
                amount=savings,
                period="annual",
                confidence=ConfidenceLevel.HIGH,
                percentage=savings_pct,
            ),
            effort=ImplementationEffort.LOW,
            guide=ImplementationGuide(
                steps=[
                    "Identify batch/scheduled workloads currently on All-Purpose clusters",
                    "Convert notebooks/scripts to Databricks Jobs",
                    "Configure Jobs clusters with appropriate sizing",
                    "Set up scheduling and monitoring",
                ],
                prerequisites=[
                    "Workload categorization (interactive vs batch)",
                ],
                risks=[
                    "Jobs clusters don't support interactive development",
                    "Cluster startup time for each job run",
                ],
                estimated_time="1-3 days",
            ),
            priority=75,
            platform="databricks",
            current_config={"workload_type": "all_purpose", "price_per_dbu": current_price},
            recommended_config={"workload_type": "jobs", "price_per_dbu": jobs_price},
        )

    # =========================================================================
    # Pricing Model Rules
    # =========================================================================

    def _check_reserved_capacity(
        self,
        benchmark_cost: BenchmarkCost,
        platform_config: dict[str, Any],
        platform: str,
        annual_runs: int,
    ) -> Optional[Recommendation]:
        """Check if reserved capacity would be beneficial."""
        platform_lower = platform.lower()

        # Reserved capacity typically saves 20-40% for committed usage
        annual_cost = benchmark_cost.total_cost * annual_runs

        # Only recommend for significant annual spend
        if annual_cost < 10000:  # $10K minimum for reserved capacity consideration
            return None

        # Define savings by platform
        savings_pct_map = {
            "snowflake": 30,  # Capacity commitments
            "redshift": 35,  # Reserved instances
            "databricks": 25,  # Committed use
            "bigquery": 20,  # Flat-rate pricing
        }

        if platform_lower not in savings_pct_map:
            return None

        savings_pct = savings_pct_map[platform_lower]
        savings = annual_cost * (savings_pct / 100)

        commitment_terms = {
            "snowflake": "1-3 year capacity commitment",
            "redshift": "1-3 year reserved instance",
            "databricks": "1-3 year committed use",
            "bigquery": "Flat-rate pricing (slots)",
        }

        return Recommendation(
            id=f"{platform_lower}-reserved-capacity",
            title=f"Consider {platform.title()} Reserved Capacity",
            description=(
                f"With ${annual_cost:,.0f}/year in spend, reserved capacity "
                f"({commitment_terms.get(platform_lower, 'commitment')}) "
                f"could save approximately {savings_pct}% (${savings:,.0f}/year)."
            ),
            category=OptimizationCategory.PRICING_MODEL,
            savings=SavingsEstimate(
                amount=savings,
                period="annual",
                confidence=ConfidenceLevel.MEDIUM,
                percentage=savings_pct,
                range_low=savings * 0.8,  # Conservative estimate
                range_high=savings * 1.2,  # Optimistic estimate
            ),
            effort=ImplementationEffort.MEDIUM,
            guide=ImplementationGuide(
                steps=[
                    "Analyze historical usage patterns for consistency",
                    "Forecast future usage growth",
                    "Contact account team for commitment options",
                    "Negotiate terms and commitment level",
                    "Monitor usage vs commitment to optimize",
                ],
                prerequisites=[
                    "12+ months of usage history",
                    "Usage forecasting",
                    "Budget approval for commitment",
                ],
                risks=[
                    "Locked into commitment if usage decreases",
                    "May not benefit if workloads are variable",
                    "Contract changes require negotiation",
                ],
                estimated_time="2-4 weeks (negotiation)",
            ),
            priority=65,
            platform=platform_lower,
            current_config={"pricing_model": "on_demand", "annual_cost": annual_cost},
            recommended_config={"pricing_model": "reserved", "savings_percent": savings_pct},
        )

    # =========================================================================
    # Query Optimization Rules
    # =========================================================================

    def _check_high_cost_queries(
        self,
        benchmark_cost: BenchmarkCost,
        platform_config: dict[str, Any],
        platform: str,
        annual_runs: int,
    ) -> Optional[Recommendation]:
        """Identify high-cost queries that could be optimized."""
        if not benchmark_cost.phase_costs:
            return None

        # Collect all query costs
        query_costs: list[tuple[str, float]] = []
        for phase in benchmark_cost.phase_costs:
            if phase.query_costs:
                for i, qc in enumerate(phase.query_costs):
                    query_costs.append((f"{phase.phase_name}_q{i + 1}", qc.compute_cost))

        if not query_costs:
            return None

        # Find queries that account for disproportionate cost
        total_cost = sum(c for _, c in query_costs)
        if total_cost == 0:
            return None

        # Sort by cost descending
        query_costs.sort(key=lambda x: x[1], reverse=True)

        # Find queries that account for >20% of cost each
        high_cost_queries = [
            (name, cost, cost / total_cost * 100) for name, cost in query_costs if cost / total_cost > 0.20
        ]

        if not high_cost_queries:
            return None

        # Estimate 30% optimization potential for high-cost queries
        optimization_potential = 0.30
        potential_savings = sum(cost for _, cost, _ in high_cost_queries) * optimization_potential
        annual_savings = potential_savings * annual_runs

        query_list = ", ".join(f"{name} ({pct:.0f}%)" for name, _, pct in high_cost_queries[:3])

        return Recommendation(
            id="high-cost-query-optimization",
            title="Optimize High-Cost Queries",
            description=(
                f"Queries {query_list} account for disproportionate cost. "
                f"Query optimization (indexing, partitioning, query rewriting) "
                f"could reduce costs by 20-40%."
            ),
            category=OptimizationCategory.QUERY,
            savings=SavingsEstimate(
                amount=annual_savings,
                period="annual",
                confidence=ConfidenceLevel.LOW,
                range_low=annual_savings * 0.5,
                range_high=annual_savings * 1.5,
            ),
            effort=ImplementationEffort.MEDIUM,
            guide=ImplementationGuide(
                steps=[
                    "Profile high-cost queries using EXPLAIN/ANALYZE",
                    "Identify missing indexes or suboptimal joins",
                    "Consider partitioning for large table scans",
                    "Rewrite queries for better performance",
                    "Test optimizations in non-production environment",
                    "Deploy and monitor improvements",
                ],
                prerequisites=[
                    "Query profiling tools",
                    "Development environment for testing",
                ],
                risks=[
                    "Query changes may affect application behavior",
                    "Index additions increase storage and write costs",
                ],
                estimated_time="1-2 weeks per query",
            ),
            priority=55,
            platform=platform,
            metadata={
                "high_cost_queries": [
                    {"name": name, "cost": cost, "percentage": pct} for name, cost, pct in high_cost_queries
                ]
            },
        )

    def _check_bigquery_bytes_scanned(
        self,
        benchmark_cost: BenchmarkCost,
        platform_config: dict[str, Any],
        platform: str,
        annual_runs: int,
    ) -> Optional[Recommendation]:
        """Check if BigQuery bytes scanned can be reduced through partitioning/clustering."""
        if platform.lower() != "bigquery":
            return None

        # Check for high bytes scanned in pricing details
        pricing_details = benchmark_cost.platform_details.get("pricing_details", {})
        bytes_processed = pricing_details.get("total_bytes_processed", 0)

        if bytes_processed == 0:
            # Try to estimate from cost
            location = platform_config.get("location", "us")
            price_per_tb = resolve_bigquery_price_per_tb(location).value
            tb_processed = benchmark_cost.total_cost / price_per_tb
            bytes_processed = tb_processed * (1024**4)

        if bytes_processed < 100 * (1024**3):  # Less than 100GB, skip
            return None

        # Estimate 50% reduction potential through partitioning/clustering
        reduction_potential = 0.50
        annual_cost = benchmark_cost.total_cost * annual_runs
        potential_savings = annual_cost * reduction_potential

        tb_processed = bytes_processed / (1024**4)

        return Recommendation(
            id="bigquery-partition-cluster",
            title="Reduce BigQuery Bytes Scanned with Partitioning",
            description=(
                f"Current queries scan {tb_processed:.2f} TB. "
                f"Implementing partitioning (by date) and clustering (by frequently filtered columns) "
                f"can reduce bytes scanned by 50-90%."
            ),
            category=OptimizationCategory.DATA_MANAGEMENT,
            savings=SavingsEstimate(
                amount=potential_savings,
                period="annual",
                confidence=ConfidenceLevel.MEDIUM,
                range_low=potential_savings * 0.5,  # 25% reduction
                range_high=potential_savings * 1.8,  # 90% reduction
            ),
            effort=ImplementationEffort.MEDIUM,
            guide=ImplementationGuide(
                steps=[
                    "Identify tables with high scan volumes",
                    "Analyze query patterns for partition key selection (often date)",
                    "Select clustering columns (frequently filtered columns)",
                    "Create new partitioned/clustered tables",
                    "Migrate data using BigQuery's CREATE TABLE AS SELECT",
                    "Update queries to use partition filters",
                    "Validate cost reduction in query metadata",
                ],
                prerequisites=[
                    "Query pattern analysis",
                    "Table usage statistics",
                ],
                risks=[
                    "Queries without partition filters won't benefit",
                    "Initial data migration has one-time cost",
                ],
                estimated_time="1-2 weeks",
            ),
            priority=70,
            platform="bigquery",
            metadata={"bytes_processed": bytes_processed, "tb_processed": tb_processed},
        )
