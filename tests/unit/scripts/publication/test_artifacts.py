from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from scripts.publication import check_corpus_bijection as bijection_mod
from scripts.publication.check_artifact_privacy import (
    main as privacy_main,
    scan_directory_for_privacy,
    scan_file_for_privacy,
)
from scripts.publication.check_corpus_bijection import check as check_corpus, check_bijection, main as bijection_main
from scripts.publication.verify_shadow_site import main as shadow_main, verify_site_directory

pytestmark = [pytest.mark.unit, pytest.mark.fast]


def _minimal_bundle(*, benchmark: str = "tpch", platform: str = "duckdb", stamp: str = "a") -> dict:
    return {
        "version": "2.2",
        "benchmark": {"id": benchmark, "scale_factor": 0.01},
        "platform": {"name": platform},
        "run": {"timestamp": "2026-01-15T12:00:00+00:00", "total_duration_ms": 1.0},
        "queries": [],
        "summary": {},
        "_stamp": stamp,
    }


def _write_bundle(path: Path, *, stamp: str = "a", **kwargs: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_minimal_bundle(stamp=stamp, **kwargs), sort_keys=True), encoding="utf-8")
    return path


def _write_sqlite_artifact(path: Path, result_ids: list[str]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(path))
    try:
        con.execute("CREATE TABLE results (result_id TEXT)")
        con.executemany("INSERT INTO results (result_id) VALUES (?)", [(rid,) for rid in result_ids])
        con.commit()
    finally:
        con.close()
    return path


def _seed(path: Path, dispositions: dict[str, str]) -> Path:
    path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "dispositions": dispositions,
                "union": sorted(dispositions),
                "digests": dict.fromkeys(dispositions, "0" * 64),
            }
        ),
        encoding="utf-8",
    )
    return path


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


def test_check_published_only_missing_from_dir_is_ok(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """published_only accepted paths may be absent from --bundles-dir."""
    bundles = tmp_path / "bundles"
    present = _write_bundle(bundles / "present.json", stamp="present")
    accepted = [
        "results-data/bundles/present.json",
        "results-data/bundles/published_only.json",
    ]
    seed = _seed(
        tmp_path / "ledger-seed.json",
        {
            "results-data/bundles/present.json": "accepted",
            "results-data/bundles/published_only.json": "published_only",
        },
    )
    monkeypatch.setattr(bijection_mod, "accepted_paths_from_ref", lambda ref: accepted)
    monkeypatch.setattr(
        bijection_mod,
        "recompute_result_id",
        lambda path: f"rid-{path.stem}",
    )
    errors = check_corpus(
        accepted_ref="HEAD",
        bundles_dir=bundles,
        artifact=None,
        ledger_seed=seed,
    )
    assert errors == []
    assert present.is_file()


def test_check_extra_artifact_id_without_overlay_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """An artifact result_id with no accepted path and no legacy_overlay disposition fails."""
    bundles = tmp_path / "bundles"
    _write_bundle(bundles / "b1.json", stamp="b1")
    accepted = ["results-data/bundles/b1.json"]
    seed = _seed(tmp_path / "ledger-seed.json", {"results-data/bundles/b1.json": "accepted"})
    artifact = _write_sqlite_artifact(tmp_path / "results.duckdb", ["rid-b1", "rid-ghost"])

    monkeypatch.setattr(bijection_mod, "accepted_paths_from_ref", lambda ref: accepted)
    monkeypatch.setattr(bijection_mod, "recompute_result_id", lambda path: f"rid-{path.stem}")
    errors = check_corpus(
        accepted_ref="HEAD",
        bundles_dir=bundles,
        artifact=artifact,
        ledger_seed=seed,
    )
    assert errors
    assert any("untraceable publication" in e for e in errors)


def test_check_legacy_overlay_extra_matched_by_recomputed_rid(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """legacy_overlay extras are allowed when their recomputed result_id matches the artifact."""
    bundles = tmp_path / "bundles"
    _write_bundle(bundles / "accepted.json", stamp="acc")
    overlay = _write_bundle(bundles / "overlay.json", stamp="ovl", platform="clickhouse")
    accepted = ["results-data/bundles/accepted.json"]
    seed = _seed(
        tmp_path / "ledger-seed.json",
        {
            "results-data/bundles/accepted.json": "accepted",
            "results-data/bundles/overlay.json": "legacy_overlay",
        },
    )
    overlay_rid = bijection_mod.recompute_result_id_from_bytes(overlay.read_bytes(), hint_path=str(overlay))
    artifact = _write_sqlite_artifact(tmp_path / "results.sqlite", ["rid-accepted", overlay_rid])

    monkeypatch.setattr(bijection_mod, "accepted_paths_from_ref", lambda ref: accepted)
    monkeypatch.setattr(bijection_mod, "recompute_result_id", lambda path: f"rid-{path.stem}")
    errors = check_corpus(
        accepted_ref="HEAD",
        bundles_dir=bundles,
        artifact=artifact,
        ledger_seed=seed,
    )
    assert errors == []


def test_main_require_artifact_missing_exits_nonzero(tmp_path: Path) -> None:
    missing = tmp_path / "no-such.duckdb"
    rc = bijection_main(
        [
            "--accepted-ref",
            "HEAD",
            "--bundles-dir",
            str(tmp_path / "bundles"),
            "--artifact",
            str(missing),
            "--require-artifact",
        ]
    )
    assert rc != 0
