"""Cost estimation and tracking for AI Primitives benchmark.

Provides utilities for estimating AI function costs before execution
and tracking actual costs during benchmark runs.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)


def _load_specs() -> dict[str, Any]:
    with (Path(__file__).with_name("specs.yaml")).open(encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


_SPECS = _load_specs()


# Platform-specific pricing (USD per 1000 tokens)
# These are approximate and should be updated as pricing changes
PLATFORM_PRICING: dict[str, dict[str, float]] = _SPECS["platform_pricing"]

# Default pricing for unknown platforms
DEFAULT_PRICING = _SPECS["default_pricing"]


@dataclass
class CostEstimate:
    """Estimated cost for an AI query or batch of queries.

    Attributes:
        query_id: Query identifier
        estimated_tokens: Total estimated tokens
        estimated_cost_usd: Estimated cost in USD
        model: Model used for estimation
        platform: Target platform
        num_rows: Number of rows processed
        notes: Additional notes or warnings
    """

    query_id: str
    estimated_tokens: int
    estimated_cost_usd: float
    model: str = ""
    platform: str = ""
    num_rows: int = 1
    notes: list[str] = field(default_factory=list)

    def __str__(self) -> str:
        return f"CostEstimate({self.query_id}: ~{self.estimated_tokens} tokens, ${self.estimated_cost_usd:.6f})"


@dataclass
class CostTracker:
    """Tracks actual costs during benchmark execution.

    Attributes:
        platform: Target platform
        budget_usd: Maximum budget allowed (0 = unlimited)
        queries_executed: Number of queries executed
        total_tokens: Total tokens consumed
        total_cost_usd: Total cost incurred
        estimates: List of cost estimates
        actuals: List of actual costs per query
    """

    platform: str = ""
    budget_usd: float = 0.0
    queries_executed: int = 0
    total_tokens: int = 0
    total_cost_usd: float = 0.0
    estimates: list[CostEstimate] = field(default_factory=list)
    actuals: list[dict[str, Any]] = field(default_factory=list)

    def add_estimate(self, estimate: CostEstimate) -> None:
        """Add a cost estimate to tracking."""
        self.estimates.append(estimate)

    def record_execution(
        self,
        query_id: str,
        tokens_used: int,
        cost_usd: float,
        success: bool = True,
    ) -> None:
        """Record an actual query execution.

        Args:
            query_id: Query identifier
            tokens_used: Actual tokens consumed
            cost_usd: Actual cost incurred
            success: Whether execution succeeded
        """
        self.queries_executed += 1
        self.total_tokens += tokens_used
        self.total_cost_usd += cost_usd
        self.actuals.append(
            {
                "query_id": query_id,
                "tokens_used": tokens_used,
                "cost_usd": cost_usd,
                "success": success,
            }
        )

    def check_budget(self, additional_cost: float = 0.0) -> bool:
        """Check if budget allows additional spending.

        Args:
            additional_cost: Additional cost to check

        Returns:
            True if within budget, False otherwise
        """
        if self.budget_usd <= 0:
            return True  # No budget limit
        return (self.total_cost_usd + additional_cost) <= self.budget_usd

    def get_budget_remaining(self) -> float:
        """Get remaining budget.

        Returns:
            Remaining budget in USD, or -1 if unlimited
        """
        if self.budget_usd <= 0:
            return -1.0
        return max(0.0, self.budget_usd - self.total_cost_usd)

    def get_summary(self) -> dict[str, Any]:
        """Get cost tracking summary.

        Returns:
            Dictionary with cost tracking summary
        """
        estimated_total = sum(e.estimated_cost_usd for e in self.estimates)

        return {
            "platform": self.platform,
            "queries_executed": self.queries_executed,
            "total_tokens": self.total_tokens,
            "total_cost_usd": self.total_cost_usd,
            "estimated_cost_usd": estimated_total,
            "budget_usd": self.budget_usd if self.budget_usd > 0 else "unlimited",
            "budget_remaining_usd": self.get_budget_remaining(),
            "accuracy": (f"{(estimated_total / self.total_cost_usd * 100):.1f}%" if self.total_cost_usd > 0 else "N/A"),
        }


def get_platform_pricing(platform: str) -> dict[str, float]:
    """Get pricing table for a platform.

    Args:
        platform: Platform name (snowflake, bigquery, databricks)

    Returns:
        Dictionary mapping model names to cost per 1000 tokens
    """
    return PLATFORM_PRICING.get(platform.lower(), DEFAULT_PRICING)


def estimate_query_cost(
    query_id: str,
    platform: str,
    model: str | None = None,
    estimated_tokens: int = 100,
    num_rows: int = 1,
    cost_per_1k_tokens: float | None = None,
) -> CostEstimate:
    """Estimate the cost of running an AI query.

    Args:
        query_id: Query identifier
        platform: Target platform
        model: Model name (uses default if not specified)
        estimated_tokens: Estimated tokens per row
        num_rows: Number of rows to process
        cost_per_1k_tokens: Override cost per 1000 tokens

    Returns:
        CostEstimate with estimated costs
    """
    pricing = get_platform_pricing(platform)

    # Determine cost per 1k tokens
    if cost_per_1k_tokens is not None:
        rate = cost_per_1k_tokens
    elif model and model.lower() in pricing:
        rate = pricing[model.lower()]
    else:
        rate = pricing.get("default", 0.001)

    total_tokens = estimated_tokens * num_rows
    total_cost = (total_tokens / 1000) * rate

    notes = []
    if platform.lower() not in PLATFORM_PRICING:
        notes.append(f"Using default pricing for unknown platform '{platform}'")
    if model and model.lower() not in pricing:
        notes.append(f"Using default rate for unknown model '{model}'")

    return CostEstimate(
        query_id=query_id,
        estimated_tokens=total_tokens,
        estimated_cost_usd=total_cost,
        model=model or "default",
        platform=platform,
        num_rows=num_rows,
        notes=notes,
    )


def estimate_benchmark_cost(
    queries: list[dict[str, Any]],
    platform: str,
    default_rows: int = 10,
) -> tuple[float, list[CostEstimate]]:
    """Estimate total cost for running multiple AI queries.

    Args:
        queries: List of query metadata dicts with 'id', 'estimated_tokens', etc.
        platform: Target platform
        default_rows: Default number of rows per query

    Returns:
        Tuple of (total_estimated_cost, list_of_estimates)
    """
    estimates = []
    total_cost = 0.0

    for query in queries:
        estimate = estimate_query_cost(
            query_id=query.get("id", "unknown"),
            platform=platform,
            model=query.get("model"),
            estimated_tokens=query.get("estimated_tokens", 100),
            num_rows=query.get("num_rows", default_rows),
            cost_per_1k_tokens=query.get("cost_per_1k_tokens"),
        )
        estimates.append(estimate)
        total_cost += estimate.estimated_cost_usd

    return total_cost, estimates


def format_cost_warning(
    estimated_cost: float,
    budget: float | None = None,
    platform: str = "",
) -> str:
    """Format a cost warning message.

    Args:
        estimated_cost: Estimated total cost in USD
        budget: Budget limit (None = unlimited)
        platform: Platform name

    Returns:
        Formatted warning message
    """
    msg = f"Estimated AI function cost: ${estimated_cost:.4f}"
    if platform:
        msg += f" on {platform}"

    if budget is not None:
        if estimated_cost > budget:
            msg += f"\n  WARNING: Exceeds budget of ${budget:.4f}!"
            msg += f"\n  Over budget by: ${estimated_cost - budget:.4f}"
        else:
            msg += f"\n  Within budget (${budget:.4f})"
            msg += f"\n  Remaining after execution: ${budget - estimated_cost:.4f}"

    return msg


__all__ = [
    "CostEstimate",
    "CostTracker",
    "estimate_query_cost",
    "estimate_benchmark_cost",
    "format_cost_warning",
    "get_platform_pricing",
    "PLATFORM_PRICING",
]
