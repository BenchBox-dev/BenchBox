"""Pinned reproducible external-source contracts for NYC Taxi.

The default benchmark dataset is exactly the pinned TLC file set: bumping the
pin is an explicit, reviewed change, never a silent slide with newly published
TLC data. All tests are offline (no downloads).
"""

from __future__ import annotations

import pytest

from benchbox.core.nyctaxi.downloader import (
    PINNED_SOURCE_MONTHS,
    PINNED_SOURCE_YEAR,
    TLC_BASE_URL,
    NYCTaxiDataDownloader,
)

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


def test_pin_matches_expected_snapshot():
    assert PINNED_SOURCE_YEAR == 2019
    assert list(range(1, 13)) == PINNED_SOURCE_MONTHS


def test_defaults_resolve_to_the_pin(tmp_path):
    downloader = NYCTaxiDataDownloader(output_dir=tmp_path)
    assert downloader.year == PINNED_SOURCE_YEAR
    assert downloader.months == PINNED_SOURCE_MONTHS


def test_source_contract_lists_exact_remote_files(tmp_path):
    downloader = NYCTaxiDataDownloader(months=[1], output_dir=tmp_path)
    contract = downloader.source_contract()
    assert contract["source"] == "nyc-tlc"
    assert contract["base_url"] == TLC_BASE_URL
    assert contract["year"] == 2019
    assert contract["months"] == [1]
    assert contract["urls"] == [f"{TLC_BASE_URL}/yellow_tripdata_2019-01.parquet"]
    assert contract["taxi_zones_url"].endswith("taxi_zone_lookup.csv")


def test_full_default_contract_covers_twelve_pinned_files(tmp_path):
    downloader = NYCTaxiDataDownloader(output_dir=tmp_path)
    assert len(downloader.source_contract()["urls"]) == 12


def test_explicit_year_and_months_still_override(tmp_path):
    downloader = NYCTaxiDataDownloader(year=2020, months=[1, 2, 3], output_dir=tmp_path)
    assert downloader.year == 2020
    assert downloader.months == [1, 2, 3]
    assert downloader.source_contract()["year"] == 2020


def test_download_stats_record_the_source(tmp_path):
    downloader = NYCTaxiDataDownloader(months=[6, 7], output_dir=tmp_path)
    stats = downloader.get_download_stats()
    assert stats["source"] == "nyc-tlc"
    assert stats["year"] == 2019
    assert stats["months"] == [6, 7]
