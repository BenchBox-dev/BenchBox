"""w7 regression: cost.total_usd must survive a load → re-export round trip.

Pre-w7, ``_extract_cost_summary`` only returned ``total_cost`` and
``cost_model`` (no ``normalized_cost``), and the schema-side guard
``_normalized_cost_allows_direct_total`` rejected any non-dict
``normalized_cost``. The combination silently dropped ``cost.total_usd``
for every legacy bundle on every re-export.

These tests cover both halves:
  - ``_extract_cost_summary`` preserves the normalized_cost block.
  - ``_normalized_cost_allows_direct_total`` distinguishes "missing"
    (legacy → allow) from "rejected" (e.g. cost_status=unavailable → block).
"""

from __future__ import annotations

import pytest

from benchbox.core.results.loader import _extract_cost_summary
from benchbox.core.results.schema import _normalized_cost_allows_direct_total

pytestmark = [pytest.mark.unit, pytest.mark.fast]


class TestExtractCostSummaryPreservesNormalizedCost:
    def test_returns_normalized_cost_when_present(self) -> None:
        normalized = {
            "cost_status": "normalized",
            "normalized_cost_usd": 0.42,
            "cost_model_version": "2026.05.0",
        }
        summary = _extract_cost_summary(
            {"total_usd": 0.42, "model": "estimated"},
            normalized,
        )
        assert summary == {
            "total_cost": 0.42,
            "cost_model": "estimated",
            "normalized_cost": normalized,
        }

    def test_omits_normalized_cost_when_legacy_bundle_has_none(self) -> None:
        summary = _extract_cost_summary({"total_usd": 0.99, "model": "estimated"}, None)
        assert summary == {"total_cost": 0.99, "cost_model": "estimated"}
        assert "normalized_cost" not in summary

    def test_returns_none_for_empty_cost_section(self) -> None:
        assert _extract_cost_summary({}, None) is None
        assert _extract_cost_summary({}, {"cost_status": "normalized"}) is None


class TestNormalizedCostAllowsDirectTotal:
    def test_missing_block_allows_direct_total_for_legacy_bundles(self) -> None:
        """Legacy bundles produced before normalized_cost existed have no
        block at all — the direct ``cost.total_usd`` is the only signal,
        and re-exports must preserve it. Pre-w7 the schema rejected this."""
        assert _normalized_cost_allows_direct_total(None) is True

    def test_normalized_status_allows_direct_total(self) -> None:
        assert _normalized_cost_allows_direct_total({"cost_status": "normalized", "normalized_cost_usd": 1.23}) is True

    def test_not_applicable_local_status_allows_direct_total(self) -> None:
        assert (
            _normalized_cost_allows_direct_total({"cost_status": "not_applicable_local", "normalized_cost_usd": 0.0})
            is True
        )

    def test_unavailable_status_blocks_direct_total(self) -> None:
        assert (
            _normalized_cost_allows_direct_total({"cost_status": "unavailable", "normalized_cost_usd": None}) is False
        )

    def test_normalized_without_amount_blocks_direct_total(self) -> None:
        assert _normalized_cost_allows_direct_total({"cost_status": "normalized", "normalized_cost_usd": None}) is False

    def test_non_dict_non_none_value_blocks_direct_total(self) -> None:
        # Defensive: anything other than None or a dict shape is suspect.
        assert _normalized_cost_allows_direct_total("normalized") is False
        assert _normalized_cost_allows_direct_total(42) is False
