"""Data transfer tracking for multi-region testing.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from benchbox.experimental.multiregion.config import CloudProvider, Region

logger = logging.getLogger(__name__)


class TransferDirection(str, Enum):
    """Direction of data transfer."""

    INTRA_REGION = "intra_region"
    INTER_REGION = "inter_region"
    INTERNET_EGRESS = "internet_egress"
    INTERNET_INGRESS = "internet_ingress"


@dataclass
class DataTransfer:
    """Record of a data transfer operation."""

    source_region: Region
    destination_region: Region | None
    bytes_transferred: int
    direction: TransferDirection
    timestamp: float
    operation: str = "query"  # query, load, export, replication
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def gb_transferred(self) -> float:
        """Transfer size in gigabytes."""
        return self.bytes_transferred / (1024**3)

    @property
    def mb_transferred(self) -> float:
        """Transfer size in megabytes."""
        return self.bytes_transferred / (1024**2)


@dataclass
class TransferSummary:
    """Summary of data transfers."""

    total_bytes: int
    total_transfers: int
    by_direction: dict[TransferDirection, int] = field(default_factory=dict)
    by_operation: dict[str, int] = field(default_factory=dict)
    by_region_pair: dict[tuple[str, str], int] = field(default_factory=dict)

    @property
    def total_gb(self) -> float:
        """Total transfer in gigabytes."""
        return self.total_bytes / (1024**3)


class TransferTracker:
    """Tracks data transfers during benchmark execution.

    Monitors:
    - Query result data returned
    - Data loading operations
    - Cross-region data movement
    - Internet egress
    """

    def __init__(self, client_region: Region | None = None):
        """Initialize transfer tracker.

        Args:
            client_region: Region where client is running
        """
        self._client_region = client_region
        self._transfers: list[DataTransfer] = []

    def record_transfer(
        self,
        source_region: Region,
        destination_region: Region | None,
        bytes_transferred: int,
        operation: str = "query",
        metadata: dict[str, Any] | None = None,
    ) -> DataTransfer:
        """Record a data transfer.

        Args:
            source_region: Region where data originated
            destination_region: Region where data was sent (None for internet)
            bytes_transferred: Number of bytes transferred
            operation: Type of operation
            metadata: Additional metadata

        Returns:
            The recorded transfer
        """
        import time

        # Determine direction
        if destination_region is None:
            direction = TransferDirection.INTERNET_EGRESS
        elif source_region == destination_region:
            direction = TransferDirection.INTRA_REGION
        else:
            direction = TransferDirection.INTER_REGION

        transfer = DataTransfer(
            source_region=source_region,
            destination_region=destination_region,
            bytes_transferred=bytes_transferred,
            direction=direction,
            timestamp=time.time(),
            operation=operation,
            metadata=metadata or {},
        )

        self._transfers.append(transfer)
        return transfer

    def record_query_result(
        self,
        source_region: Region,
        result_bytes: int,
        query_id: str | None = None,
    ) -> DataTransfer:
        """Record data transfer from a query result.

        Args:
            source_region: Region where query was executed
            result_bytes: Size of query result in bytes
            query_id: Optional query identifier

        Returns:
            The recorded transfer
        """
        return self.record_transfer(
            source_region=source_region,
            destination_region=self._client_region,
            bytes_transferred=result_bytes,
            operation="query",
            metadata={"query_id": query_id} if query_id else None,
        )

    def get_summary(self) -> TransferSummary:
        """Get summary of all recorded transfers.

        Returns:
            Transfer summary with aggregated statistics
        """
        by_direction: dict[TransferDirection, int] = {}
        by_operation: dict[str, int] = {}
        by_region_pair: dict[tuple[str, str], int] = {}

        total_bytes = 0
        for transfer in self._transfers:
            total_bytes += transfer.bytes_transferred

            # By direction
            by_direction[transfer.direction] = by_direction.get(transfer.direction, 0) + transfer.bytes_transferred

            # By operation
            by_operation[transfer.operation] = by_operation.get(transfer.operation, 0) + transfer.bytes_transferred

            # By region pair
            src = transfer.source_region.code
            dst = transfer.destination_region.code if transfer.destination_region else "internet"
            pair = (src, dst)
            by_region_pair[pair] = by_region_pair.get(pair, 0) + transfer.bytes_transferred

        return TransferSummary(
            total_bytes=total_bytes,
            total_transfers=len(self._transfers),
            by_direction=by_direction,
            by_operation=by_operation,
            by_region_pair=by_region_pair,
        )

    @property
    def transfers(self) -> list[DataTransfer]:
        """Get all recorded transfers."""
        return self._transfers.copy()

    def clear(self) -> None:
        """Clear all recorded transfers."""
        self._transfers.clear()


# Cloud provider pricing (per GB) - approximate as of 2024
# Actual pricing varies by volume, commitment, etc.
TRANSFER_PRICING: dict[CloudProvider, dict[TransferDirection, float]] = {
    CloudProvider.AWS: {
        TransferDirection.INTRA_REGION: 0.01,
        TransferDirection.INTER_REGION: 0.02,
        TransferDirection.INTERNET_EGRESS: 0.09,
        TransferDirection.INTERNET_INGRESS: 0.00,
    },
    CloudProvider.GCP: {
        TransferDirection.INTRA_REGION: 0.01,
        TransferDirection.INTER_REGION: 0.02,
        TransferDirection.INTERNET_EGRESS: 0.12,
        TransferDirection.INTERNET_INGRESS: 0.00,
    },
    CloudProvider.AZURE: {
        TransferDirection.INTRA_REGION: 0.01,
        TransferDirection.INTER_REGION: 0.02,
        TransferDirection.INTERNET_EGRESS: 0.087,
        TransferDirection.INTERNET_INGRESS: 0.00,
    },
    CloudProvider.SNOWFLAKE: {
        TransferDirection.INTRA_REGION: 0.00,
        TransferDirection.INTER_REGION: 0.02,
        TransferDirection.INTERNET_EGRESS: 0.00,  # Included in compute
        TransferDirection.INTERNET_INGRESS: 0.00,
    },
    CloudProvider.DATABRICKS: {
        TransferDirection.INTRA_REGION: 0.00,
        TransferDirection.INTER_REGION: 0.02,
        TransferDirection.INTERNET_EGRESS: 0.00,  # Varies by underlying cloud
        TransferDirection.INTERNET_INGRESS: 0.00,
    },
}


@dataclass
class TransferCostEstimate:
    """Estimated cost for data transfers."""

    total_cost_usd: float
    by_direction: dict[TransferDirection, float] = field(default_factory=dict)
    by_region_pair: dict[tuple[str, str], float] = field(default_factory=dict)
    pricing_notes: list[str] = field(default_factory=list)


class TransferCostEstimator:
    """Estimates data transfer costs based on cloud provider pricing.

    Note: Estimates are approximate and may not reflect actual charges.
    Actual costs depend on volume discounts, committed use, etc.
    """

    def __init__(self, provider: CloudProvider):
        """Initialize cost estimator.

        Args:
            provider: Cloud provider for pricing
        """
        self._provider = provider
        self._pricing = TRANSFER_PRICING.get(
            provider,
            TRANSFER_PRICING[CloudProvider.AWS],  # Default fallback
        )

    def estimate_cost(self, summary: TransferSummary) -> TransferCostEstimate:
        """Estimate transfer costs from summary.

        Args:
            summary: Transfer summary

        Returns:
            Cost estimate
        """
        by_direction: dict[TransferDirection, float] = {}
        by_region_pair: dict[tuple[str, str], float] = {}
        total_cost = 0.0
        notes: list[str] = []

        # Calculate by direction
        for direction, bytes_count in summary.by_direction.items():
            gb = bytes_count / (1024**3)
            price_per_gb = self._pricing.get(direction, 0.0)
            cost = gb * price_per_gb
            by_direction[direction] = cost
            total_cost += cost

        # Calculate by region pair
        for pair, bytes_count in summary.by_region_pair.items():
            gb = bytes_count / (1024**3)
            # Use inter-region pricing for cross-region, intra for same
            if pair[0] == pair[1]:
                price_per_gb = self._pricing.get(TransferDirection.INTRA_REGION, 0.01)
            elif pair[1] == "internet":
                price_per_gb = self._pricing.get(TransferDirection.INTERNET_EGRESS, 0.09)
            else:
                price_per_gb = self._pricing.get(TransferDirection.INTER_REGION, 0.02)
            by_region_pair[pair] = gb * price_per_gb

        # Add pricing notes
        notes.append(f"Pricing based on {self._provider.value} standard rates")
        notes.append("Actual costs may vary based on volume discounts and commitments")
        if summary.total_gb > 100:
            notes.append("Volume discounts may apply for large transfers")

        return TransferCostEstimate(
            total_cost_usd=round(total_cost, 4),
            by_direction=by_direction,
            by_region_pair=by_region_pair,
            pricing_notes=notes,
        )

    def estimate_transfer_cost(
        self,
        direction: TransferDirection,
        bytes_count: int,
    ) -> float:
        """Estimate cost for a single transfer.

        Args:
            direction: Transfer direction
            bytes_count: Transfer size in bytes

        Returns:
            Estimated cost in USD
        """
        gb = bytes_count / (1024**3)
        price_per_gb = self._pricing.get(direction, 0.0)
        return gb * price_per_gb
