"""Post-deploy probes compare served bytes with the receipt through verify_live."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.site_deploy import probe as p, receipt as r
from tests.unit.scripts.site_deploy.test_receipt import MOUNTS, candidate_receipt, write_site

pytestmark = [pytest.mark.unit, pytest.mark.fast]


@pytest.fixture
def served(tmp_path: Path) -> tuple[Path, Path]:
    site = write_site(tmp_path / "site")
    receipt = candidate_receipt(site, tmp_path / "a.tar")
    path = tmp_path / "receipt.json"
    path.write_text(r.dumps(receipt), encoding="utf-8")
    return site, path


def test_matching_bytes_pass_every_probe(served: tuple[Path, Path]) -> None:
    site, receipt_path = served
    with p.serve_directory(site) as base_url:
        summary = p.probe_once(base_url, receipt_path, MOUNTS)
    assert summary["ok"], summary["errors"]
    expected = json.loads(receipt_path.read_text())["checksums"]
    assert summary["matched"] == len(expected)
    assert {probe["path"] for probe in summary["probes"]} >= set(MOUNTS)


def test_altered_bytes_fail_with_the_offending_path(served: tuple[Path, Path]) -> None:
    site, receipt_path = served
    (site / "docs" / "index.html").write_text("stale or tampered", encoding="utf-8")
    with p.serve_directory(site) as base_url:
        summary = p.probe_once(base_url, receipt_path, MOUNTS)
    assert not summary["ok"]
    assert "/docs/" in summary["mismatched"]
    assert any("/docs/" in error for error in summary["errors"])


def test_missing_route_fails(served: tuple[Path, Path]) -> None:
    site, receipt_path = served
    (site / "blog" / "index.html").unlink()
    with p.serve_directory(site) as base_url:
        summary = p.probe_once(base_url, receipt_path, MOUNTS)
    assert not summary["ok"]
    assert any("404" in error or "/blog/" in error for error in summary["errors"])


def test_unreachable_origin_fails(served: tuple[Path, Path]) -> None:
    _, receipt_path = served
    summary = p.probe_once("http://127.0.0.1:9", receipt_path, MOUNTS, timeout=1.0)
    assert not summary["ok"]


def test_retries_until_the_new_site_is_served(served: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch) -> None:
    _, receipt_path = served
    outcomes = iter(
        [{"ok": False, "errors": ["old site"]}, {"ok": False, "errors": ["old site"]}, {"ok": True, "errors": []}]
    )
    sleeps: list[float] = []
    monkeypatch.setattr(p, "probe_once", lambda *a, **k: dict(next(outcomes)))
    summary = p.probe_with_retries("http://x", receipt_path, MOUNTS, attempts=5, delay_seconds=7, sleep=sleeps.append)
    assert summary["ok"] and summary["attempt"] == 3
    assert sleeps == [7, 7]


def test_gives_up_after_the_last_attempt(served: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch) -> None:
    _, receipt_path = served
    monkeypatch.setattr(p, "probe_once", lambda *a, **k: {"ok": False, "errors": ["old site"]})
    sleeps: list[float] = []
    summary = p.probe_with_retries("http://x", receipt_path, MOUNTS, attempts=3, delay_seconds=1, sleep=sleeps.append)
    assert not summary["ok"] and summary["attempt"] == 3
    assert len(sleeps) == 2


def test_attempts_must_be_positive(served: tuple[Path, Path]) -> None:
    with pytest.raises(ValueError):
        p.probe_with_retries("http://x", served[1], MOUNTS, attempts=0)
