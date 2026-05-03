"""Unit tests for the explorer read-model contract additions.

Covers:
  (a) _platform_id strips known trust suffixes correctly
  (b) _platform_id is idempotent on clean names
  (c) _query_display_ms returns median of passing runs, not first
  (d) _query_display_ms returns None when all runs failed
  (e) _query_display_ms uses measurement-only rows when run_type present
  (f) display_geomean_ms differs from geomean_ms when samples vary
  (g) is_ranking_eligible returns False for community-submission trust
  (h) select_canonical_row picks ranking-eligible over non-eligible
  (i) select_canonical_row picks newest when both are ranking-eligible
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from benchbox.core.explorer_pipeline.models import (
    RANKING_ELIGIBLE_TRUST_LABELS,
    RANKING_ELIGIBLE_VISIBILITIES,
    ManifestEntry,
    QueryDisplayTiming,
    QueryTiming,
    _platform_id,
    is_ranking_eligible,
    select_canonical_row,
)
from benchbox.core.explorer_pipeline.transformer import (
    BundleTransformer,
    _query_display_ms,
)
from tests.unit.core.explorer_pipeline.conftest import MINIMAL_BUNDLE

pytestmark = [pytest.mark.unit, pytest.mark.fast]


# ---------------------------------------------------------------------------
# (a) _platform_id strips known trust suffixes correctly
# ---------------------------------------------------------------------------


class TestPlatformId:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("DuckDB-trust-ci", "duckdb"),
            ("DuckDB-trust-community", "duckdb"),
            ("DuckDB-trust-local", "duckdb"),
            ("DuckDB-trust-unknown", "duckdb"),
            ("DuckDB", "duckdb"),
        ],
    )
    def test_strips_trust_suffixes(self, raw: str, expected: str) -> None:
        assert _platform_id(raw) == expected

    # (b) idempotent on clean names
    @pytest.mark.parametrize(
        "name",
        [
            "polars-df",
            "clickhouse-cloud",
            "clickhouse-local",  # must not be stripped - ends in "local" but no "-trust-"
            "clickhouse-server",  # must not be stripped - ends in word that could false-match
            "motherduck",
            "duckdb",
        ],
    )
    def test_idempotent_on_clean_names(self, name: str) -> None:
        assert _platform_id(name) == name

    def test_spaces_replaced_with_dashes(self) -> None:
        assert _platform_id("ClickHouse Cloud") == "clickhouse-cloud"

    def test_lowercased(self) -> None:
        assert _platform_id("DuckDB") == "duckdb"

    def test_platform_id_written_to_manifest_entry(self, bundle_file: Path) -> None:
        transformer = BundleTransformer()
        entry = transformer.to_manifest_entry(bundle_file)
        assert entry.platform_id == "duckdb"
        # raw platform field must remain unchanged
        assert entry.platform == "duckdb"

    def test_platform_id_written_to_detail_result(self, bundle_file: Path) -> None:
        transformer = BundleTransformer()
        result = transformer.to_detail_result(bundle_file, result_id="test-id-001")
        assert result.platform_id == "duckdb"
        assert result.platform == "duckdb"

    def test_platform_id_strips_provenance_on_bundle(self, tmp_path: Path) -> None:
        bundle = copy.deepcopy(MINIMAL_BUNDLE)
        bundle["platform"]["name"] = "DuckDB-trust-ci"
        bundle_path = tmp_path / "b.json"
        bundle_path.write_text(json.dumps(bundle))
        transformer = BundleTransformer()
        entry = transformer.to_manifest_entry(bundle_path)
        assert entry.platform_id == "duckdb"
        assert entry.platform == "DuckDB-trust-ci"


# ---------------------------------------------------------------------------
# (c) _query_display_ms returns median of passing runs, not first
# ---------------------------------------------------------------------------


class TestQueryDisplayMs:
    def _make_timing(
        self,
        query_id: str,
        duration_ms: float,
        status: str = "pass",
        run_type: str | None = "measurement",
        iter_: int | None = None,
    ) -> QueryTiming:
        return QueryTiming(
            query_id=query_id,
            duration_ms=duration_ms,
            status=status,
            run_type=run_type,
            iter=iter_,
        )

    def test_returns_median_not_first(self) -> None:
        timings = [
            self._make_timing("Q1", 16.0),  # cold-cache outlier
            self._make_timing("Q1", 11.0),
            self._make_timing("Q1", 11.0),
            self._make_timing("Q1", 11.0),
        ]
        # median of [11, 11, 11, 16] = (11+11)/2 = 11.0
        display_ms, sample_count = _query_display_ms(timings)
        assert display_ms == pytest.approx(11.0)
        assert sample_count == 4

    # (d) returns None when all runs failed
    def test_returns_none_when_all_failed(self) -> None:
        timings = [
            self._make_timing("Q1", 100.0, status="fail"),
            self._make_timing("Q1", 200.0, status="fail"),
        ]
        display_ms, sample_count = _query_display_ms(timings)
        assert display_ms is None
        assert sample_count == 0

    def test_returns_none_for_missing_query_id(self) -> None:
        # Caller is responsible for pre-filtering; empty list → (None, 0)
        display_ms, sample_count = _query_display_ms([])
        assert display_ms is None
        assert sample_count == 0

    # (e) uses measurement-only rows when run_type present
    def test_uses_measurement_rows_over_throughput(self) -> None:
        timings = [
            self._make_timing("Q1", 10.0, run_type="measurement"),
            self._make_timing("Q1", 50.0, run_type="throughput"),
            self._make_timing("Q1", 60.0, run_type="throughput"),
        ]
        # Only the measurement row should contribute; median of [10] = 10
        display_ms, sample_count = _query_display_ms(timings)
        assert display_ms == pytest.approx(10.0)
        assert sample_count == 1

    def test_falls_back_to_all_passing_when_no_run_type(self) -> None:
        timings = [
            QueryTiming(query_id="Q1", duration_ms=20.0, status="pass"),
            QueryTiming(query_id="Q1", duration_ms=30.0, status="pass"),
        ]
        # no run_type → median of [20, 30] = 25
        display_ms, sample_count = _query_display_ms(timings)
        assert display_ms == pytest.approx(25.0)
        assert sample_count == 2

    def test_odd_count_median(self) -> None:
        timings = [
            self._make_timing("Q1", 10.0),
            self._make_timing("Q1", 20.0),
            self._make_timing("Q1", 30.0),
        ]
        display_ms, _ = _query_display_ms(timings)
        assert display_ms == pytest.approx(20.0)


# ---------------------------------------------------------------------------
# (f) display_geomean_ms differs from geomean_ms when samples vary
# ---------------------------------------------------------------------------


class TestDisplayGeomean:
    def test_display_geomean_differs_from_raw_geomean(self, tmp_path: Path) -> None:
        """When a query has a cold-cache outlier, display_geomean_ms (median-per-query)
        should be lower than geomean_ms (mean-of-all-raw-samples).

        Q1: [16ms outlier, 11ms, 11ms, 11ms warm-cache]
          geomean_ms     = geomean([16, 11, 11, 11]) ≈ 12.25ms  (all raw samples)
          display_ms(Q1) = median([16, 11, 11, 11]) = 11.0ms
          display_geomean_ms = geomean([11.0]) = 11.0ms
        """
        bundle = copy.deepcopy(MINIMAL_BUNDLE)
        # Only Q1 so the geomean/display_geomean comparison is unambiguous
        bundle["queries"] = [
            {"id": "Q1", "ms": 16.0, "run_type": "measurement", "status": "SUCCESS", "iter": 1},
            {"id": "Q1", "ms": 11.0, "run_type": "measurement", "status": "SUCCESS", "iter": 2},
            {"id": "Q1", "ms": 11.0, "run_type": "measurement", "status": "SUCCESS", "iter": 3},
            {"id": "Q1", "ms": 11.0, "run_type": "measurement", "status": "SUCCESS", "iter": 4},
        ]
        bundle["summary"]["queries"] = {"total": 1, "passed": 1, "failed": 0}
        bundle_path = tmp_path / "b.json"
        bundle_path.write_text(json.dumps(bundle))
        transformer = BundleTransformer()
        entry = transformer.to_manifest_entry(bundle_path)

        assert entry.geomean_ms is not None
        assert entry.display_geomean_ms is not None
        # display uses median (11.0); raw geomean includes the 16ms outlier (≈12.25)
        assert entry.display_geomean_ms < entry.geomean_ms
        assert entry.display_geomean_ms == pytest.approx(11.0)

    def test_display_timings_populated_on_detail_result(self, bundle_file: Path) -> None:
        transformer = BundleTransformer()
        result = transformer.to_detail_result(bundle_file, result_id="test-id")
        assert len(result.display_timings) == 2
        query_ids = {dt.query_id for dt in result.display_timings}
        assert query_ids == {"Q1", "Q6"}
        for dt in result.display_timings:
            assert dt.display_ms is not None
            assert dt.sample_count >= 1


# ---------------------------------------------------------------------------
# (g) is_ranking_eligible returns False for community-submission trust
# ---------------------------------------------------------------------------


class TestRankingEligibility:
    def _make_entry(
        self,
        trust_label: str,
        visibility: str,
        *,
        validation_status: str | None = None,
        failed_query_count: int = 0,
    ) -> ManifestEntry:
        return ManifestEntry(
            result_id="x",
            benchmark="tpch",
            scale_factor=0.1,
            platform="duckdb",
            driver_version=None,
            run_date="2026-01-01",
            power_score=None,
            total_duration_s=10.0,
            query_count=22,
            trust_label=trust_label,
            visibility=visibility,
            validation_status=validation_status,
            failed_query_count=failed_query_count,
        )

    def test_maintainer_run_public_curated_is_eligible(self) -> None:
        entry = self._make_entry("maintainer-run", "public-curated")
        assert is_ranking_eligible(entry) is True

    def test_ci_verified_public_verified_is_eligible(self) -> None:
        entry = self._make_entry("ci-verified", "public-verified")
        assert is_ranking_eligible(entry) is True

    def test_community_submission_self_reported_is_not_eligible(self) -> None:
        entry = self._make_entry("community-submission", "public-self-reported")
        assert is_ranking_eligible(entry) is False

    def test_community_submission_public_curated_is_not_eligible(self) -> None:
        """Trust label alone fails even with good visibility."""
        entry = self._make_entry("community-submission", "public-curated")
        assert is_ranking_eligible(entry) is False

    def test_maintainer_run_self_reported_is_not_eligible(self) -> None:
        """Visibility alone fails even with good trust label."""
        entry = self._make_entry("maintainer-run", "public-self-reported")
        assert is_ranking_eligible(entry) is False

    def test_partial_query_failure_count_is_not_ranking_eligible(self) -> None:
        entry = self._make_entry("maintainer-run", "public-curated", failed_query_count=1)
        assert is_ranking_eligible(entry) is False

    def test_partial_validation_status_is_not_ranking_eligible(self) -> None:
        entry = self._make_entry("maintainer-run", "public-curated", validation_status="partial")
        assert is_ranking_eligible(entry) is False

    def test_ranking_eligible_visibilities_constant(self) -> None:
        assert "public-curated" in RANKING_ELIGIBLE_VISIBILITIES
        assert "public-verified" in RANKING_ELIGIBLE_VISIBILITIES

    def test_ranking_eligible_trust_labels_constant(self) -> None:
        assert "maintainer-run" in RANKING_ELIGIBLE_TRUST_LABELS
        assert "ci-verified" in RANKING_ELIGIBLE_TRUST_LABELS


# ---------------------------------------------------------------------------
# (h) select_canonical_row picks ranking-eligible over non-eligible
# ---------------------------------------------------------------------------


class TestSelectCanonicalRow:
    def _make_entry(
        self,
        run_date: str,
        trust_label: str = "maintainer-run",
        visibility: str = "public-curated",
        failed_query_count: int = 0,
        validation_status: str | None = None,
    ) -> ManifestEntry:
        return ManifestEntry(
            result_id=f"x-{run_date}",
            benchmark="tpch",
            scale_factor=0.1,
            platform="duckdb",
            driver_version=None,
            run_date=run_date,
            power_score=None,
            total_duration_s=10.0,
            query_count=22,
            trust_label=trust_label,
            visibility=visibility,
            failed_query_count=failed_query_count,
            validation_status=validation_status,
        )

    def test_returns_none_for_empty_list(self) -> None:
        assert select_canonical_row([]) is None

    def test_returns_single_entry(self) -> None:
        entry = self._make_entry("2026-01-01")
        assert select_canonical_row([entry]) is entry

    # (h) eligible beats non-eligible
    def test_eligible_beats_non_eligible(self) -> None:
        eligible = self._make_entry("2026-01-01", "maintainer-run", "public-curated")
        non_eligible = self._make_entry("2026-06-01", "community-submission", "public-self-reported")
        # non_eligible is newer but not eligible - eligible should win
        result = select_canonical_row([non_eligible, eligible])
        assert result is eligible

    # (i) newest wins when both are eligible
    def test_newest_wins_when_both_eligible(self) -> None:
        older = self._make_entry("2026-01-01")
        newer = self._make_entry("2026-06-01")
        result = select_canonical_row([older, newer])
        assert result is newer

    def test_newest_wins_when_both_non_eligible(self) -> None:
        older = self._make_entry("2026-01-01", "community-submission", "public-self-reported")
        newer = self._make_entry("2026-06-01", "community-submission", "public-self-reported")
        result = select_canonical_row([older, newer])
        assert result is newer

    def test_three_entries_eligible_older_wins_non_eligible_newer(self) -> None:
        eligible_older = self._make_entry("2026-01-01", "maintainer-run", "public-curated")
        eligible_newer = self._make_entry("2026-06-01", "maintainer-run", "public-curated")
        non_eligible_newest = self._make_entry("2026-12-01", "community-submission", "public-self-reported")
        result = select_canonical_row([eligible_older, eligible_newer, non_eligible_newest])
        assert result is eligible_newer  # newest eligible, not newest overall

    def test_clean_row_wins_over_newer_partial_query_failure(self) -> None:
        clean_older = self._make_entry("2026-01-01")
        partial_newer = self._make_entry(
            "2026-12-01",
            failed_query_count=1,
            validation_status="partial",
        )
        result = select_canonical_row([partial_newer, clean_older])
        assert result is clean_older

    def test_deterministic_when_date_and_eligibility_tied(self) -> None:
        """Result must not depend on input order when all keys except result_id tie."""
        e1 = self._make_entry("2026-01-01")
        e2 = self._make_entry("2026-01-01")
        # result_ids are "x-2026-01-01" for both - force distinct IDs
        e1 = e1.model_copy(update={"result_id": "aaa-hash"})
        e2 = e2.model_copy(update={"result_id": "zzz-hash"})
        result_ab = select_canonical_row([e1, e2])
        result_ba = select_canonical_row([e2, e1])
        assert result_ab is result_ba
