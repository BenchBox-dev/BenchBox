"""Tests for data transfer tracking module.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import time

import pytest

from benchbox.experimental.multiregion.config import CloudProvider
from benchbox.experimental.multiregion.transfer import (
    TRANSFER_PRICING,
    DataTransfer,
    TransferCostEstimate,
    TransferCostEstimator,
    TransferDirection,
    TransferSummary,
    TransferTracker,
)

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


class TestTransferDirection:
    """Tests for TransferDirection enum."""

    def test_all_directions(self):
        """Should have expected directions."""
        directions = list(TransferDirection)
        assert TransferDirection.INTRA_REGION in directions
        assert TransferDirection.INTER_REGION in directions
        assert TransferDirection.INTERNET_EGRESS in directions
        assert TransferDirection.INTERNET_INGRESS in directions


class TestDataTransfer:
    """Tests for DataTransfer dataclass."""

    def test_basic_creation(self, us_east_region, eu_west_region):
        """Should create transfer record."""
        transfer = DataTransfer(
            source_region=us_east_region,
            destination_region=eu_west_region,
            bytes_transferred=1024 * 1024 * 100,  # 100 MB
            direction=TransferDirection.INTER_REGION,
            timestamp=time.time(),
        )
        assert transfer.bytes_transferred == 104857600

    def test_gb_transferred(self, us_east_region, eu_west_region):
        """Should calculate GB transferred."""
        transfer = DataTransfer(
            source_region=us_east_region,
            destination_region=eu_west_region,
            bytes_transferred=1024**3,  # 1 GB
            direction=TransferDirection.INTER_REGION,
            timestamp=time.time(),
        )
        assert transfer.gb_transferred == 1.0

    def test_mb_transferred(self, us_east_region, eu_west_region):
        """Should calculate MB transferred."""
        transfer = DataTransfer(
            source_region=us_east_region,
            destination_region=eu_west_region,
            bytes_transferred=1024**2 * 50,  # 50 MB
            direction=TransferDirection.INTER_REGION,
            timestamp=time.time(),
        )
        assert transfer.mb_transferred == 50.0


class TestTransferTracker:
    """Tests for TransferTracker class."""

    def test_record_transfer(self, us_east_region, eu_west_region):
        """Should record a transfer."""
        tracker = TransferTracker(client_region=us_east_region)
        transfer = tracker.record_transfer(
            source_region=us_east_region,
            destination_region=eu_west_region,
            bytes_transferred=1000,
        )
        assert transfer.bytes_transferred == 1000
        assert len(tracker.transfers) == 1

    def test_intra_region_direction(self, us_east_region):
        """Should detect intra-region transfer."""
        tracker = TransferTracker()
        transfer = tracker.record_transfer(
            source_region=us_east_region,
            destination_region=us_east_region,
            bytes_transferred=1000,
        )
        assert transfer.direction == TransferDirection.INTRA_REGION

    def test_inter_region_direction(self, us_east_region, eu_west_region):
        """Should detect inter-region transfer."""
        tracker = TransferTracker()
        transfer = tracker.record_transfer(
            source_region=us_east_region,
            destination_region=eu_west_region,
            bytes_transferred=1000,
        )
        assert transfer.direction == TransferDirection.INTER_REGION

    def test_internet_egress_direction(self, us_east_region):
        """Should detect internet egress."""
        tracker = TransferTracker()
        transfer = tracker.record_transfer(
            source_region=us_east_region,
            destination_region=None,
            bytes_transferred=1000,
        )
        assert transfer.direction == TransferDirection.INTERNET_EGRESS

    def test_record_query_result(self, us_east_region):
        """Should record query result transfer."""
        tracker = TransferTracker(client_region=us_east_region)
        transfer = tracker.record_query_result(
            source_region=us_east_region,
            result_bytes=50000,
            query_id="q1",
        )
        assert transfer.operation == "query"
        assert transfer.metadata.get("query_id") == "q1"

    def test_get_summary(self, us_east_region, eu_west_region):
        """Should generate transfer summary."""
        tracker = TransferTracker()
        tracker.record_transfer(us_east_region, eu_west_region, 1000)
        tracker.record_transfer(us_east_region, us_east_region, 500)
        tracker.record_transfer(us_east_region, None, 2000)

        summary = tracker.get_summary()
        assert summary.total_bytes == 3500
        assert summary.total_transfers == 3
        assert len(summary.by_direction) == 3

    def test_clear(self, us_east_region):
        """Should clear recorded transfers."""
        tracker = TransferTracker()
        tracker.record_transfer(us_east_region, None, 1000)
        assert len(tracker.transfers) == 1
        tracker.clear()
        assert len(tracker.transfers) == 0


class TestTransferSummary:
    """Tests for TransferSummary dataclass."""

    def test_total_gb(self):
        """Should calculate total GB."""
        summary = TransferSummary(
            total_bytes=1024**3 * 5,  # 5 GB
            total_transfers=10,
        )
        assert summary.total_gb == 5.0


class TestTransferPricing:
    """Tests for transfer pricing constants."""

    def test_aws_pricing(self):
        """Should have AWS pricing."""
        assert CloudProvider.AWS in TRANSFER_PRICING
        pricing = TRANSFER_PRICING[CloudProvider.AWS]
        assert TransferDirection.INTERNET_EGRESS in pricing
        assert pricing[TransferDirection.INTERNET_EGRESS] > 0

    def test_gcp_pricing(self):
        """Should have GCP pricing."""
        assert CloudProvider.GCP in TRANSFER_PRICING

    def test_azure_pricing(self):
        """Should have Azure pricing."""
        assert CloudProvider.AZURE in TRANSFER_PRICING

    def test_ingress_free(self):
        """Internet ingress should be free."""
        for provider in [CloudProvider.AWS, CloudProvider.GCP, CloudProvider.AZURE]:
            pricing = TRANSFER_PRICING[provider]
            assert pricing[TransferDirection.INTERNET_INGRESS] == 0.0


class TestTransferCostEstimator:
    """Tests for TransferCostEstimator class."""

    def test_estimate_cost(self, us_east_region, eu_west_region):
        """Should estimate transfer costs."""
        estimator = TransferCostEstimator(CloudProvider.AWS)
        summary = TransferSummary(
            total_bytes=1024**3,  # 1 GB
            total_transfers=1,
            by_direction={TransferDirection.INTERNET_EGRESS: 1024**3},
        )
        estimate = estimator.estimate_cost(summary)
        assert estimate.total_cost_usd > 0

    def test_estimate_transfer_cost(self):
        """Should estimate single transfer cost."""
        estimator = TransferCostEstimator(CloudProvider.AWS)
        cost = estimator.estimate_transfer_cost(
            direction=TransferDirection.INTERNET_EGRESS,
            bytes_count=1024**3,  # 1 GB
        )
        # AWS egress is ~$0.09/GB
        assert 0.05 < cost < 0.15

    def test_intra_region_cheaper(self):
        """Intra-region should be cheaper than inter-region."""
        estimator = TransferCostEstimator(CloudProvider.AWS)
        intra = estimator.estimate_transfer_cost(TransferDirection.INTRA_REGION, 1024**3)
        inter = estimator.estimate_transfer_cost(TransferDirection.INTER_REGION, 1024**3)
        assert intra < inter

    def test_cost_estimate_has_notes(self, us_east_region):
        """Should include pricing notes."""
        estimator = TransferCostEstimator(CloudProvider.AWS)
        summary = TransferSummary(total_bytes=1000, total_transfers=1)
        estimate = estimator.estimate_cost(summary)
        assert len(estimate.pricing_notes) > 0

    def test_volume_discount_note(self):
        """Should note volume discounts for large transfers."""
        estimator = TransferCostEstimator(CloudProvider.AWS)
        summary = TransferSummary(
            total_bytes=1024**3 * 150,  # 150 GB
            total_transfers=1,
        )
        estimate = estimator.estimate_cost(summary)
        discount_note = any("Volume" in note for note in estimate.pricing_notes)
        assert discount_note


class TestTransferCostEstimate:
    """Tests for TransferCostEstimate dataclass."""

    def test_basic_creation(self):
        """Should create cost estimate."""
        estimate = TransferCostEstimate(
            total_cost_usd=15.50,
            by_direction={TransferDirection.INTERNET_EGRESS: 15.50},
        )
        assert estimate.total_cost_usd == 15.50
