"""Tests for the canonical result-provenance vocabulary."""

from __future__ import annotations

import pytest

from benchbox.core.publishing.bundle_publisher import VALID_LABELS
from benchbox.core.results import provenance as p

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


class TestSourceToTrustLabel:
    def test_all_sources_map_to_a_label(self) -> None:
        assert set(p.SOURCE_TO_TRUST_LABEL) == set(p.RESULT_SOURCES)

    @pytest.mark.parametrize(
        ("source", "label"),
        [
            ("internal", "maintainer-run"),
            ("community", "community-submission"),
            ("vendor", "vendor-supplied"),
        ],
    )
    def test_expected_mapping(self, source: str, label: str) -> None:
        assert p.trust_label_for_source(source) == label

    def test_unknown_source_defaults_to_internal_label(self) -> None:
        assert p.normalize_source("nonsense") == "internal"
        assert p.trust_label_for_source("nonsense") == "maintainer-run"

    def test_source_normalization_is_case_insensitive_and_trims(self) -> None:
        assert p.normalize_source("  VENDOR ") == "vendor"
        assert p.is_valid_source("Community") is True
        assert p.is_valid_source("partner") is False


class TestVisibilityAndRanking:
    @pytest.mark.parametrize(
        ("label", "visibility"),
        [
            ("maintainer-run", "public-curated"),
            ("community-submission", "public-self-reported"),
            ("vendor-supplied", "public-vendor-reported"),
            ("verified", "public-verified"),
        ],
    )
    def test_label_to_visibility(self, label: str, visibility: str) -> None:
        assert p.visibility_for_label(label) == visibility

    def test_vendor_is_ranking_eligible(self) -> None:
        # Decision D2: vendor-supplied is ranked (with a distinct badge).
        assert p.is_ranking_eligible_visibility("public-vendor-reported") is True

    def test_curated_and_verified_are_ranking_eligible(self) -> None:
        assert p.is_ranking_eligible_visibility("public-curated") is True
        assert p.is_ranking_eligible_visibility("public-verified") is True

    def test_self_reported_and_hidden_states_are_not_ranking_eligible(self) -> None:
        for state in ("public-self-reported", "unlisted", "private", ""):
            assert p.is_ranking_eligible_visibility(state) is False

    def test_every_trust_label_has_a_visibility_and_display(self) -> None:
        for label in p.TRUST_LABELS:
            assert label in p.TRUST_LABEL_TO_VISIBILITY
            assert label in p.TRUST_LABEL_DISPLAY

    def test_display_text_matches_contract(self) -> None:
        assert p.display_for_label("vendor-supplied") == "Vendor Supplied"
        assert p.display_for_label("maintainer-run") == "Maintainer Run"

    def test_unknown_label_fails_safe_to_non_ranked_visibility(self) -> None:
        # A corrupt/typo/future label must NOT be promoted to the ranked
        # public-curated tier; it falls back to a visible-but-unranked state.
        vis = p.visibility_for_label("vendor-suppplied")  # deliberate typo
        assert vis == "public-self-reported"
        assert p.is_ranking_eligible_visibility(vis) is False


class TestFunding:
    def test_expected_vocabulary(self) -> None:
        assert p.FUNDING_SOURCES == (
            "employer",
            "personal",
            "free-trial",
            "vendor-sponsored",
            "grant",
            "unspecified",
        )

    def test_default_is_unspecified(self) -> None:
        assert p.DEFAULT_FUNDING == "unspecified"
        assert p.normalize_funding(None) == "unspecified"
        assert p.normalize_funding("") == "unspecified"
        assert p.normalize_funding("mystery-grant") == "unspecified"

    def test_valid_values_round_trip(self) -> None:
        for value in p.FUNDING_SOURCES:
            assert p.is_valid_funding(value) is True
            assert p.normalize_funding(value.upper()) == value

    def test_unknown_is_invalid_but_normalizes(self) -> None:
        assert p.is_valid_funding("crowdfunded") is False


class TestPublishLabelIntegration:
    def test_vendor_supplied_is_a_valid_publish_label(self) -> None:
        assert "vendor-supplied" in VALID_LABELS

    def test_provenance_labels_lead_the_publish_vocabulary(self) -> None:
        # The three source-derived labels must come FIRST, in source order, so
        # the publish vocabulary stays derived from provenance.py rather than
        # re-listing literals. Assert position, not mere membership (membership
        # is guaranteed by construction and would be a tautology).
        source_labels = tuple(p.SOURCE_TO_TRUST_LABEL.values())
        assert VALID_LABELS[: len(source_labels)] == source_labels

    def test_workflow_only_labels_remain(self) -> None:
        for label in ("ci", "local", "unofficial-research"):
            assert label in VALID_LABELS
