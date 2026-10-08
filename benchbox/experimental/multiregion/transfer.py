# Copyright 2026 Joe Harris / BenchBox Project

# Licensed under the MIT License. See LICENSE file in the project root for details.

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from benchbox.experimental.multiregion.config import CloudProvider, Region

logger = logging.getLogger(__name__)


class TransferDirection(str, Enum):
    INTRA_REGION = "intra_region"
    INTER_REGION = "inter_region"
    INTERNET_EGRESS = "internet_egress"
    INTERNET_INGRESS = "internet_ingress"


@dataclass
class DataTransfer:
    source_region: Region
    destination_region: Region | None
    bytes_transferred: int
    direction: TransferDirection
    timestamp: float
    operation: str = "query"
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def gb_transferred(self) -> float:
        return self.bytes_transferred / (1024**3)

    @property
    def mb_transferred(self) -> float:
        return self.bytes_transferred / (1024**2)


@dataclass
class TransferSummary:
    total_bytes: int
    total_transfers: int
    by_direction: dict[TransferDirection, int] = field(default_factory=dict)
    by_operation: dict[str, int] = field(default_factory=dict)
    by_region_pair: dict[tuple[str, str], int] = field(default_factory=dict)

    @property
    def total_gb(self) -> float:
        return self.total_bytes / (1024**3)


class TransferTracker:
    def __init__(self, client_region: Region | None = None):
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
        import time

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
        return self.record_transfer(
            source_region=source_region,
            destination_region=self._client_region,
            bytes_transferred=result_bytes,
            operation="query",
            metadata={"query_id": query_id} if query_id else None,
        )

    def get_summary(self) -> TransferSummary:
        by_direction: dict[TransferDirection, int] = {}
        by_operation: dict[str, int] = {}
        by_region_pair: dict[tuple[str, str], int] = {}

        total_bytes = 0
        for transfer in self._transfers:
            total_bytes += transfer.bytes_transferred

            by_direction[transfer.direction] = by_direction.get(transfer.direction, 0) + transfer.bytes_transferred

            by_operation[transfer.operation] = by_operation.get(transfer.operation, 0) + transfer.bytes_transferred

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
        return self._transfers.copy()

    def clear(self) -> None:
        self._transfers.clear()


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
        TransferDirection.INTERNET_EGRESS: 0.00,
        TransferDirection.INTERNET_INGRESS: 0.00,
    },
    CloudProvider.DATABRICKS: {
        TransferDirection.INTRA_REGION: 0.00,
        TransferDirection.INTER_REGION: 0.02,
        TransferDirection.INTERNET_EGRESS: 0.00,
        TransferDirection.INTERNET_INGRESS: 0.00,
    },
}


@dataclass
class TransferCostEstimate:
    total_cost_usd: float
    by_direction: dict[TransferDirection, float] = field(default_factory=dict)
    by_region_pair: dict[tuple[str, str], float] = field(default_factory=dict)
    pricing_notes: list[str] = field(default_factory=list)


class TransferCostEstimator:
    def __init__(self, provider: CloudProvider):
        self._provider = provider
        self._pricing = TRANSFER_PRICING.get(
            provider,
            TRANSFER_PRICING[CloudProvider.AWS],
        )

    def estimate_cost(self, summary: TransferSummary) -> TransferCostEstimate:
        by_direction: dict[TransferDirection, float] = {}
        by_region_pair: dict[tuple[str, str], float] = {}
        total_cost = 0.0
        notes: list[str] = []

        for direction, bytes_count in summary.by_direction.items():
            gb = bytes_count / (1024**3)
            price_per_gb = self._pricing.get(direction, 0.0)
            cost = gb * price_per_gb
            by_direction[direction] = cost
            total_cost += cost

        for pair, bytes_count in summary.by_region_pair.items():
            gb = bytes_count / (1024**3)
            if pair[0] == pair[1]:
                price_per_gb = self._pricing.get(TransferDirection.INTRA_REGION, 0.01)
            elif pair[1] == "internet":
                price_per_gb = self._pricing.get(TransferDirection.INTERNET_EGRESS, 0.09)
            else:
                price_per_gb = self._pricing.get(TransferDirection.INTER_REGION, 0.02)
            by_region_pair[pair] = gb * price_per_gb

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
        gb = bytes_count / (1024**3)
        price_per_gb = self._pricing.get(direction, 0.0)
        return gb * price_per_gb
