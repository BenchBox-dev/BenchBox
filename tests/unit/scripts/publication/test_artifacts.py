from __future__ import annotations

from pathlib import Path

import pytest

from scripts.publication.check_artifact_privacy import (
    main as privacy_main,
    scan_directory_for_privacy,
    scan_file_for_privacy,
)
from scripts.publication.check_corpus_bijection import check_bijection
from scripts.publication.verify_shadow_site import main as shadow_main, verify_site_directory

pytestmark = [pytest.mark.unit, pytest.mark.fast]


def test_corpus_bijection_exact_match():
    accepted = [
        "results-data/bundles/b1.json",
        "results-data/bundles/b2.json",
        "results-data/bundles/b3.json",
    ]
    published = [
        "results-data/bundles/b1.json",
        "results-data/bundles/b2.json",
        "results-data/bundles/b3.json",
    ]
    valid, errors = check_bijection(accepted, published)
    assert valid is True
    assert errors == []


def test_corpus_bijection_unexplained_skip_rejection():
    accepted = [
        "results-data/bundles/b1.json",
        "results-data/bundles/b2.json",
    ]
    published = [
        "results-data/bundles/b1.json",
    ]
    valid, errors = check_bijection(accepted, published)
    assert valid is False
    assert any("Zero-skip bijection violation" in e for e in errors)


def test_corpus_bijection_with_approved_disposition():
    accepted = [
        "results-data/bundles/b1.json",
        "results-data/bundles/b2_omitted.json",
    ]
    published = [
        "results-data/bundles/b1.json",
    ]
    dispositions = {
        "results-data/bundles/b2_omitted.json": "withdrawn_under_adr_2026_08_23",
    }
    valid, errors = check_bijection(accepted, published, dispositions=dispositions)
    assert valid is True
    assert errors == []


def test_privacy_scanner_clean_and_dirty(tmp_path: Path):
    clean_file = tmp_path / "clean.json"
    clean_file.write_text('{"public_key": "valid_public_data"}', encoding="utf-8")
    assert scan_file_for_privacy(clean_file) == []

    dirty_file = tmp_path / "dirty.json"
    dirty_file.write_text('{"token": "ghp_123456789012345678901234567890123456"}', encoding="utf-8")
    findings = scan_file_for_privacy(dirty_file)
    assert len(findings) > 0
    assert "GitHub Personal Access Token" in findings[0]


def test_shadow_site_verifier(tmp_path: Path):
    site = tmp_path / "site"
    site.mkdir()
    (site / "index.html").write_text('<a href="about.html">About</a>', encoding="utf-8")
    (site / "about.html").write_text('<a href="index.html">Home</a>', encoding="utf-8")

    errors = verify_site_directory(site)
    assert errors == []

    # Inject broken link
    (site / "broken.html").write_text('<a href="missing.html">Link</a>', encoding="utf-8")
    errors = verify_site_directory(site)
    assert any("missing.html" in e for e in errors)


def test_shadow_site_missing_directory_fails_closed(tmp_path: Path) -> None:
    missing = tmp_path / "no-such-site"
    errors = verify_site_directory(missing)
    assert errors
    assert any("does not exist" in e for e in errors)
    assert shadow_main([str(missing)]) != 0


def test_privacy_scan_missing_directory_fails_closed(tmp_path: Path) -> None:
    missing = tmp_path / "no-such-site"
    findings = scan_directory_for_privacy(missing)
    assert findings
    assert any("does not exist" in f for f in findings)
    assert privacy_main([str(missing)]) != 0
