"""Pinned reproducible external-source contracts for FlightData.

Scale-factor month windows always end at the pinned BTS month: newly published
months must never silently shift a scale factor's dataset. All tests are
offline (no downloads).
"""

from __future__ import annotations

import pytest

from benchbox.core.flightdata.downloader import (
    BTS_BASE_URL,
    PINNED_END_MONTH,
    PINNED_END_YEAR,
    FlightDataDownloader,
    _months_sequence,
    _scale_to_months,
)

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


def test_pin_matches_expected_snapshot():
    assert (PINNED_END_YEAR, PINNED_END_MONTH) == (2024, 12)


def test_window_ends_at_the_pin_not_latest_available():
    assert _months_sequence(1) == [(2024, 12)]
    months = _months_sequence(13)
    assert months[0] == (2024, 12)
    assert months[-1] == (2023, 12)


def test_explicit_end_still_overridable():
    assert _months_sequence(1, end_year=2020, end_month=6) == [(2020, 6)]


def test_scale_to_months_mapping_is_stable():
    assert _scale_to_months(0.01) == 1
    assert _scale_to_months(1.0) == 41


def test_downloader_window_is_pinned(tmp_path):
    downloader = FlightDataDownloader(scale_factor=0.01, output_dir=tmp_path)
    assert downloader._months == [(2024, 12)]
    assert downloader.num_months == 1


def test_source_contract_lists_exact_remote_files(tmp_path):
    downloader = FlightDataDownloader(scale_factor=0.01, output_dir=tmp_path)
    contract = downloader.source_contract()
    assert contract["source"] == "bts-transtats"
    assert contract["base_url"] == BTS_BASE_URL
    assert contract["months"] == [(2024, 12)]
    assert contract["urls"] == [BTS_BASE_URL.format(year=2024, month=12)]


def test_download_stats_record_the_source_window(tmp_path):
    downloader = FlightDataDownloader(scale_factor=0.01, output_dir=tmp_path)
    stats = downloader.get_download_stats()
    assert stats["source"] == "bts-transtats"
    assert stats["months"] == [(2024, 12)]


def test_contract_id_stable_and_pin_sensitive(tmp_path):
    first = FlightDataDownloader(scale_factor=0.01, output_dir=tmp_path)
    second = FlightDataDownloader(scale_factor=0.01, output_dir=tmp_path)
    assert first.source_contract_id() == second.source_contract_id()
    other = FlightDataDownloader(scale_factor=1.0, output_dir=tmp_path)
    assert first.source_contract_id() != other.source_contract_id()


def test_missing_manifest_has_no_persisted_contract(tmp_path):
    downloader = FlightDataDownloader(scale_factor=0.01, output_dir=tmp_path)
    assert downloader._persisted_source_contract_id() is None


def test_manifest_persists_contract_and_hashes(tmp_path):
    from benchbox.utils.datagen_manifest import MANIFEST_FILENAME, load_manifest

    downloader = FlightDataDownloader(scale_factor=0.01, output_dir=tmp_path)
    flights = tmp_path / "flights.csv"
    flights.write_text("x", encoding="utf-8")
    downloader._table_file_row_counts = {flights: 0}
    downloader._content_hashes = {"https://example/x.zip": "abc123"}
    downloader._write_manifest({"flights": flights})
    manifest = load_manifest(tmp_path / MANIFEST_FILENAME)
    assert manifest["source_contract_id"] == downloader.source_contract_id()
    assert manifest["source_contract"]["source"] == "bts-transtats"
    assert manifest["content_hashes"] == {"https://example/x.zip": "abc123"}
    assert downloader._persisted_source_contract_id() == downloader.source_contract_id()
