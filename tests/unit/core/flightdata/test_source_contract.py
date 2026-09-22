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
    assert contract["csv_encoding"] == "cp1252"
    assert contract["months"] == [(2024, 12)]
    assert contract["urls"] == [BTS_BASE_URL.format(year=2024, month=12)]


def test_download_stats_record_the_source_window(tmp_path):
    downloader = FlightDataDownloader(scale_factor=0.01, output_dir=tmp_path)
    stats = downloader.get_download_stats()
    assert stats["source"] == "bts-transtats"
    assert stats["months"] == [(2024, 12)]
    assert stats["source_provenance"]["source"] == "unknown"
    assert stats["source_provenance"]["promotion_eligible"] is False


def test_small_scale_records_synthetic_provenance(tmp_path):
    import csv
    import io

    downloader = FlightDataDownloader(scale_factor=0.01, output_dir=tmp_path)
    downloader._process_month(csv.writer(io.StringIO()), 2024, 12, 0)
    assert downloader.source_provenance()["source"] == "synthetic"
    assert downloader.source_provenance()["promotion_eligible"] is False


def test_pinned_checksum_mismatch_fails_instead_of_falling_back(tmp_path, monkeypatch):
    import csv
    import io

    from benchbox.core.data_fetch.errors import ChecksumMismatchError
    from benchbox.core.flightdata import downloader as module

    url = BTS_BASE_URL.format(year=2024, month=12)
    monkeypatch.setitem(module.PINNED_SOURCE_SHA256, url, "0" * 64)

    class _Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return b"provider drift"

    monkeypatch.setattr(module.urllib.request, "urlopen", lambda *_args, **_kwargs: _Response())
    downloader = FlightDataDownloader(scale_factor=0.1, output_dir=tmp_path)
    with pytest.raises(ChecksumMismatchError):
        downloader._process_month(csv.writer(io.StringIO()), 2024, 12, 0)
    assert downloader._stats["months_synthetic"] == 0


def test_checksum_abort_invalidates_outputs_and_manifest(tmp_path, monkeypatch):
    from benchbox.core.data_fetch.errors import ChecksumMismatchError
    from benchbox.utils.datagen_manifest import MANIFEST_FILENAME

    downloader = FlightDataDownloader(scale_factor=0.1, output_dir=tmp_path, force_redownload=True)
    flights_path = tmp_path / downloader.get_compressed_filename("flights.csv")
    flights_path.write_text("old data", encoding="utf-8")
    manifest_path = tmp_path / MANIFEST_FILENAME
    manifest_path.write_text('{"source_contract_id": "stale"}', encoding="utf-8")
    monkeypatch.setattr(
        downloader,
        "_ensure_flights_data",
        lambda _path: (_ for _ in ()).throw(
            ChecksumMismatchError(path="source", expected_sha256="0" * 64, actual_sha256="1" * 64)
        ),
    )

    with pytest.raises(ChecksumMismatchError):
        downloader.download()

    assert not flights_path.exists()
    assert not manifest_path.exists()


def test_unparseable_download_is_not_recorded_as_ingested(tmp_path, monkeypatch):
    import csv
    import io

    from benchbox.core.flightdata import downloader as module

    class _Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return b"not a zip"

    monkeypatch.setattr(module.urllib.request, "urlopen", lambda *_args, **_kwargs: _Response())
    downloader = FlightDataDownloader(scale_factor=0.1, output_dir=tmp_path)
    downloader._process_month(csv.writer(io.StringIO()), 2024, 12, 0)

    assert downloader._content_hashes == {}
    assert downloader.source_provenance()["source"] == "synthetic"


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
    assert manifest["source_provenance"]["promotion_eligible"] is False
    assert downloader._persisted_source_contract_id() == downloader.source_contract_id()
